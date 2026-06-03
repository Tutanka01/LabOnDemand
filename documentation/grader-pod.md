---
title: Grader Pod — exécution isolée des tests boîte noire
summary: Architecture, sécurité et contrat du Grader Pod (MVP-2) — le Job Kubernetes éphémère et isolé qui exécute les probes d'un devoir contre le lab d'un étudiant, et dont l'API récupère le verdict en lisant les logs (modèle pull).
read_when: |
  - Tu travailles sur la correction automatique (backend/grader_service.py, dockerfiles/grader/)
  - Tu veux comprendre comment les tests sont exécutés en sécurité contre un lab
  - Tu débogues un GradingRun bloqué, une probe qui échoue, ou l'image grader
  - Tu prépares le déploiement (publier l'image, ouvrir les NetworkPolicy)
---

# Grader Pod — exécution isolée des tests boîte noire

Le **Grader Pod** est le moteur d'exécution des tests automatiques (MVP-2). C'est un
**Job Kubernetes éphémère, isolé et sans aucun droit cluster**, lancé par l'API pour
exécuter les *probes* d'un devoir contre le lab d'un étudiant, « vu de l'extérieur ».

Philosophie produit : **la preuve d'abord, la note ensuite.** Le grader *trie* (verdict
par probe, score suggéré), l'enseignant *juge*. Voir aussi [`assignment-lifecycle.md`](assignment-lifecycle.md)
pour le cycle de vie complet et [`security.md`](security.md) pour le modèle de sécurité global.

---

## Décision d'architecture : modèle *pull* (lecture des logs)

> L'API crée le Job, **surveille son statut** via l'API Kubernetes, puis **lit le stdout
> du pod** pour récupérer le verdict. Le grader ne rappelle **jamais** l'API.

Pourquoi pull et pas un callback HTTP (push) ?

L'API tourne dans Docker Compose et parle à un cluster **distant** via `kubeconfig.yaml`.
Un pod du cluster n'a donc **pas d'adresse fiable** pour joindre l'API. Le modèle pull
évite d'exposer un endpoint public, supprime tout besoin d'egress du grader vers l'API, et
réutilise l'accès cluster que l'API possède déjà.

Les champs `result_token_hash` / `token_used_at` de `grading_runs` et le schéma
`GradingRunCallbackRequest` restent en place pour un **futur mode push** (à activer si l'API
est un jour exposée dans le cluster), mais ne sont **pas utilisés** aujourd'hui.

```
  API (Docker Compose)                    Cluster distant (kubeconfig)
  ┌────────────────────┐  create Job      ┌──────────────────────────────────┐
  │ run-tests          │ ───────────────► │ Job grader (ns labondemand-grader)│
  │  → GradingRun queued│                  │  SA sans token · NetworkPolicy    │
  │                    │   poll status    │  grader.py :                      │
  │ watcher async      │ ◄──────────────► │   lit GRADER_SPEC + URL cible     │
  │  (run_in_executor) │   read pod logs  │   exécute http / tcp / sql / script│
  │ parse + score      │ ◄─────────────── │   imprime le verdict JSON sur stdout│
  │  → GradingRun done │                  │        │ egress: lab + DNS only    │
  └────────────────────┘                  │        ▼                          │
                                          │   Lab étudiant ({name}-service)   │
                                          └──────────────────────────────────┘
```

Implémentation : `backend/grader_service.py` (orchestration) et `dockerfiles/grader/`
(image + entrypoint `grader.py`).

---

## Garanties de sécurité du Job

Le manifeste produit par `build_job_manifest()` applique :

| Garantie | Détail |
|---|---|
| **Aucun accès cluster** | `serviceAccountName: grader-sa` **sans RoleBinding** + `automountServiceAccountToken: false`. Pas de kubeconfig monté. |
| **NetworkPolicy egress** | Ingress refusé ; egress autorisé **uniquement** vers les namespaces de labs (`namespaceSelector: managed-by=labondemand`) et le DNS du cluster (port 53). Internet, API et infra sont bloqués. |
| **Time-box** | `activeDeadlineSeconds = GradingSpec.timeout_seconds`. |
| **Pas de retry** | `backoffLimit: 0`, `restartPolicy: Never`. |
| **Auto-suppression** | `ttlSecondsAfterFinished` (≈ `GRADER_JOB_TTL_SECONDS`). |
| **Ressources plafonnées** | `requests` 100m / 128Mi, `limits` 500m / 256Mi. |
| **Conteneur durci** | `runAsNonRoot`, `runAsUser: 10001`, `seccompProfile: RuntimeDefault`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`. |

> **L'enforcement de la NetworkPolicy dépend du CNI** du cluster (Calico, Cilium…). Sur un
> CNI sans support NetworkPolicy, la politique est ignorée silencieusement — mais tous les
> autres garde-fous (SA sans droits, pas de kubeconfig, quotas, time-box, TTL) restent actifs.

Le namespace `labondemand-grader` est créé à la demande, labellisé
`managed-by=labondemand`, avec une `ResourceQuota` + `LimitRange` strictes (baseline
« student »). Provisionnement idempotent via `ensure_grader_infra()`.

---

## Périmètre des probes (MVP-2)

Le grader isolé attaque le lab **de l'extérieur**. Les probes supportées :

| `kind` | Description | `config` | `expect` |
|--------|-------------|----------|----------|
| `http` | Requête HTTP vers le lab | `url`/`path`, `method`, `headers`, `body` | `status`, `body_contains`, `regex` |
| `tcp` | Port ouvert ? | `host?`, `port` | `open` (true/false) |
| `sql` | Requête SQL (mysql/postgres) | `engine`, `host?`, `port`, `user`, `password`, `database`, `query` | `min_rows`, `contains` |
| `script` | Script bash de l'enseignant | — (`GradingSpec.custom_script`) | contrat JSON (voir plus bas) |

> Les probes **`inside`** (`file` / `command`, qui exigeraient un `exec` dans le pod
> étudiant) **casseraient l'isolation** du grader (il n'a aucun droit cluster). Elles sont
> donc **marquées `skip`** par le grader en MVP-2 et différées à une itération ultérieure
> (exécution côté API). L'éditeur de probes les accepte encore mais elles ne sont pas
> exécutées.

Résolution de la cible : à partir de `AssignmentDeployment`, l'API construit
`http://{deployment.name}-service.{namespace}.svc.cluster.local:{port}` (port issu du
`Template`/`RuntimeConfig` du devoir). Voir `resolve_target()`.

---

## Contrat de sortie

`grader.py` n'utilise **que la bibliothèque standard** (urllib, socket, subprocess) — aucune
dépendance pip. Il imprime son verdict entre deux marqueurs :

```
===GRADER_RESULT_BEGIN===
{"checks": [
  {"id": "h1", "name": "/health répond 200", "status": "pass",
   "message": "HTTP 200 conforme", "output": "…", "weight": 2, "visibility": "student"}
]}
===GRADER_RESULT_END===
```

`status` ∈ `pass | fail | error | skip`. Le grader **ne plante jamais** : une probe en
échec produit un résultat `fail`/`error`, jamais un exit non nul qui masquerait les autres.

### Contrat des scripts enseignant (`kind: script`)

Le script reçoit `GRADER_TARGET_URL` et `GRADER_TARGET_HOST` dans son environnement, et :

1. **soit** imprime sur stdout `{"checks": [...]}` (mêmes champs, plusieurs checks possibles) ;
2. **soit** renvoie un exit code (`0` = succès, non-zéro = échec) → verdict binaire.

---

## Du verdict à la note

À la fin d'un run (`status = done`), `summarize()` calcule (probes `skip` exclues) :

- `total_checks`, `passed_checks` ;
- `score_suggestion` = somme pondérée des probes passées ramenée sur 20, ex. `"15/20"`.

Le score est une **suggestion**. L'enseignant garde la main sur la note finale (`grade` de
la soumission), pré-remplie avec la suggestion mais librement modifiable.

**Visibilité** appliquée à la vue étudiant (`filter_results_for_student()`) :
`student` = détail complet · `summary` = pass/fail sans message ni sortie · `teacher_only` =
masquée. Le prof voit tout, sans filtre.

---

## Variables d'environnement

| Variable | Défaut | Rôle |
|----------|--------|------|
| `GRADER_IMAGE` | `labondemand/grader:latest` | Image du grader (publiée sur le registre du cluster). Surchargée par devoir via `GradingSpec.grader_image`. |
| `GRADER_NAMESPACE` | `labondemand-grader` | Namespace dédié et verrouillé des Jobs grader. |
| `GRADER_JOB_TTL_SECONDS` | `180` | `ttlSecondsAfterFinished` du Job (auto-suppression). |
| `GRADER_POLL_INTERVAL_SECONDS` | `3` | Intervalle de polling du statut du Job. |
| `GRADER_WATCH_GRACE_SECONDS` | `30` | Marge ajoutée au timeout avant de déclarer un run en erreur. |
| `GRADING_RUN_STUCK_MINUTES` | `15` | (cleanup) délai au-delà duquel un run `queued`/`running` est réconcilié en `error`. |

---

## Construire et publier l'image

```bash
docker build -t labondemand/grader:latest dockerfiles/grader/
# Puis pousser sur le registre accessible par le cluster, ou taguer pour celui-ci :
# docker tag labondemand/grader:latest <registry>/labondemand/grader:latest
# docker push <registry>/labondemand/grader:latest
```

Renseigner ensuite `GRADER_IMAGE` (et le `imagePullSecrets` du namespace si le registre est
privé). Sans publication, les Jobs resteront en `ImagePullBackOff` et les runs finiront en
`error` après le timeout.

Test fonctionnel rapide de l'entrypoint (hors cluster) :

```bash
docker run --rm \
  -e GRADER_TARGET_URL=http://127.0.0.1:9 -e GRADER_TARGET_HOST=127.0.0.1 \
  -e GRADER_TARGET_PORT=9 -e GRADER_TIMEOUT=2 \
  -e GRADER_SPEC='{"checks":[{"id":"web","name":"Health","kind":"http","config":{"url":"/health"},"expect":{"status":200},"weight":1,"visibility":"student"}]}' \
  labondemand/grader:latest
```

---

## Cycle de vie d'un run

```
queued ──(watcher)──► running ──(logs OK)──► done
   │                     │
   │                     └──(timeout / logs illisibles)──► error
   └──(run bloqué > GRADING_RUN_STUCK_MINUTES, réconciliation cleanup)──► error
```

La réconciliation (dans `backend/tasks/cleanup.py`) repasse en `error` les runs restés
bloqués (Job disparu, API redémarrée pendant un run) et supprime le Job grader résiduel —
filet de sécurité en plus du `ttlSecondsAfterFinished`.

---

## Dépannage

| Symptôme | Piste |
|----------|-------|
| Run reste `queued`/`running` puis `error` « Timeout » | Image grader absente du registre (`ImagePullBackOff`), ou lab cible injoignable. `kubectl -n labondemand-grader get pods,jobs`. |
| « Verdict illisible » | Le pod n'a pas imprimé les marqueurs `GRADER_RESULT_*` (crash avant l'émission, script enseignant trop verbeux). Voir `kubectl -n labondemand-grader logs job/grader-r<run_id>`. |
| Probes `http`/`sql` toutes en `fail` connexion | NetworkPolicy bloquante (CNI), mauvais port résolu, ou service du lab absent. |
| Probe `sql` en `error` | Client `mysql`/`psql` invoqué ; vérifier `engine`, `host`, identifiants dans `config`. |
| Probe `inside` jamais exécutée | Comportement attendu en MVP-2 (`skip`). |

Endpoints associés : voir [`assignment-lifecycle.md`](assignment-lifecycle.md) §Correction automatique.
