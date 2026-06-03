---
title: Cycle de vie des devoirs et soumissions
summary: Statuts et transitions pour Assignment, AssignmentDeployment, AssignmentSubmission et GradingRun — flux complet du côté enseignant et du côté étudiant.
read_when: |
  - Tu travailles sur le système de classes/devoirs (routers/classrooms.py, routers/student.py)
  - Tu veux comprendre comment les soumissions et les corrections s'articulent
  - Tu implémentes ou débogues le déploiement en masse (deploy-all) ou la correction automatique
---

# Cycle de vie des devoirs et soumissions

Ce document décrit le cycle de vie complet du système pédagogique de LabOnDemand : depuis la création d'un devoir jusqu'à la correction et la notation de la soumission d'un étudiant.

---

## Vue d'ensemble

```
Teacher crée Assignment
      │
      ├──► Bulk-spawn : AssignmentDeployment par étudiant inscrit
      │         └── Lab K8s créé dans le namespace de l'étudiant
      │
Student consulte son devoir, travaille dans son lab
      │
      └──► Student soumet : AssignmentSubmission (texte + liens)
                │
                ├── Correction manuelle : Teacher POST /grade
                │         └── submission.status = graded, grade, feedback
                │
                └── Correction automatique : GradingSpec + GradingRun
                          └── score_suggestion + résultats par sonde
```

---

## Statuts des entités

### Assignment

| Statut | Signification |
|--------|---------------|
| `active` | Devoir visible et acceptant des soumissions |
| `archived` | Devoir archivé — plus de soumissions acceptées, visible en lecture seule |

### AssignmentDeployment (lab de l'étudiant)

| spawn_status | Signification |
|---|---|
| `ok` | Lab déployé avec succès dans le namespace de l'étudiant |
| `skipped` | Étudiant avait déjà un lab pour ce devoir |
| `error` | Échec du déploiement (message dans `spawn_error`) |

### AssignmentSubmission

| Statut | Signification |
|--------|---------------|
| `submitted` | Soumission reçue, en attente de correction |
| `graded` | Soumission corrigée (manuellement ou automatiquement) |

### GradingRun

| Statut | Signification |
|--------|---------------|
| `queued` | En file d'attente de correction automatique |
| `running` | Correction en cours d'exécution |
| `done` | Correction terminée — `score_suggestion`, `results` disponibles |
| `error` | Correction échouée — message dans `error` |

---

## Flux côté enseignant

### 1. Créer une classe et inscrire des étudiants

```http
POST /api/v1/classrooms
{ "name": "INF101", "description": "Programmation orientée objet" }

POST /api/v1/classrooms/{classroom_id}/students
{ "user_ids": [2, 3, 4] }
```

### 2. Créer un devoir

```http
POST /api/v1/classrooms/{classroom_id}/assignments
{
  "title": "TP : structures de données",
  "instructions": "## Consignes\n\nImplémentez une liste chaînée...",
  "deliverables": "Un fichier `main.py` avec les fonctions demandées.",
  "template_key": "vscode",
  "cpu_preset": "low",
  "ram_preset": "medium",
  "due_at": "2026-06-30T23:59:00",
  "grading_mode": "graded"
}
```

Champs clés :
- `grading_mode` : `none` (pas de tests), `self_check` (l'étudiant peut lancer les tests), `graded` (tests activés, à l'initiative de l'enseignant)
- `cpu_preset` / `ram_preset` : parmi les presets définis par rôle dans `backend/routers/classrooms.py`

### 3. Déployer les labs en masse (deploy-all)

```http
POST /api/v1/classrooms/{classroom_id}/assignments/{assignment_id}/deploy-all
```

Déploie automatiquement un lab pour chaque étudiant inscrit dans la classe. Les labs sont créés dans le namespace de chaque étudiant (`labondemand-user-{id}`), avec les ressources définies dans le devoir.

La réponse contient un `BulkSpawnReport` : `{ total, ok, skipped, errors, results }`.

### 4. Consulter les soumissions

```http
GET /api/v1/classrooms/{classroom_id}/assignments/{assignment_id}/submissions
```

Retourne une ligne par étudiant inscrit (statut `not_started` / `submitted` / `graded`),
avec le **verdict du dernier Grading Run** (`grading_status`, `grading_passed`,
`grading_total`, `score_suggestion`) pour la colonne de triage.

### 5. Noter une soumission

```http
POST /api/v1/classrooms/{classroom_id}/assignments/{assignment_id}/submissions/{submission_id}/grade
{
  "grade": "15/20",
  "feedback": "Bonne implémentation, mais la complexité de la recherche pourrait être améliorée."
}
```

Met `submission.status = "graded"`, enregistre `grade`, `feedback`, `graded_by` et `graded_at`.
Le détail d'une soumission (`GET …/submissions/{submission_id}`) inclut aussi `grading_run`
(résultats détaillés non filtrés) pour corriger en s'appuyant sur les preuves.

### 6. Lancer / relancer les tests

```http
POST /api/v1/classrooms/{cid}/assignments/{aid}/test-now        # contre le lab de démo du prof
POST /api/v1/classrooms/{cid}/assignments/{aid}/run-tests-all   # un GradingRun par étudiant ayant un lab
GET  /api/v1/classrooms/{cid}/assignments/{aid}/grading-runs/{run_id}  # suivi (vue prof, non filtrée)
```

---

## Flux côté étudiant

### 1. Voir ses devoirs

```http
GET /api/v1/student/assignments
```

Liste tous les devoirs des classes où l'étudiant est inscrit, avec :
- `status` du devoir (`active` / `archived`)
- `is_late` (si la date limite est dépassée)
- `submission_status` (null / submitted / graded)
- `deployment_url` (URL vers son lab si déployé)

### 2. Voir le détail d'un devoir

```http
GET /api/v1/student/assignments/{assignment_id}
```

Inclut le Markdown des instructions, les livrables attendus, le lien vers le lab, et —
si des tests sont configurés — `grading_mode`, `visible_probes` (probes visibles, **sans**
la config/expect interne qui révélerait la réponse) et `latest_run` (dernier résultat, filtré).

### 3. Soumettre

```http
POST /api/v1/student/assignments/{assignment_id}/submit
{
  "text": "J'ai implémenté la liste chaînée avec insertion en O(1)...",
  "links": [
    { "label": "Dépôt Git", "url": "https://github.com/..." },
    { "label": "Démonstration", "url": "https://..." }
  ]
}
```

- Si une soumission existe déjà, elle est mise à jour (upsert sur `(assignment_id, user_id)`).
- `is_late` est calculé automatiquement en comparant `submitted_at` avec `due_at`.
- Un snapshot de l'état du lab (`lab_snapshot`) peut être inclus automatiquement.

### 4. Lancer les tests (self-check) et suivre le résultat

```http
POST /api/v1/student/assignments/{assignment_id}/run-tests
GET  /api/v1/student/assignments/{assignment_id}/grading-runs/{run_id}
```

`run-tests` crée un `GradingRun` (`status = queued`, `trigger = student_self`) et renvoie
immédiatement ; le front **poll** ensuite `grading-runs/{run_id}` jusqu'à `done`/`error` pour
afficher la progression check par check. Pré-requis : `grading_mode ≠ none`, une `GradingSpec`
avec au moins une probe (ou un script), et un lab ouvert.

Le résultat est **filtré selon `Probe.visibility`** :
- Sondes `student` : résultat complet visible
- Sondes `summary` : seulement pass/fail (sans message ni sortie)
- Sondes `teacher_only` : masquées

---

## Correction automatique (GradingSpec / GradingRun)

L'exécution réelle des tests est assurée par le **Grader Pod** — un Job Kubernetes isolé
dont l'API récupère le verdict en lisant les logs (modèle *pull*). Architecture, sécurité et
contrat détaillés dans [`grader-pod.md`](grader-pod.md). Cette section couvre la
configuration et le cycle de vie applicatifs.

### Configurer la correction automatique

Un enseignant ou admin crée une `GradingSpec` pour un devoir
(`POST /api/v1/classrooms/{cid}/assignments/{aid}/grading-spec`). Elle définit une liste de
sondes (`checks`) exécutées contre le lab de l'étudiant.

```json
{
  "grader_image": null,
  "timeout_seconds": 120,
  "checks": [
    {
      "id": "http-check",
      "name": "L'application répond 200 sur /health",
      "kind": "http",
      "vantage": "outside",
      "config": { "url": "/health" },
      "expect": { "status": 200, "body_contains": "ok" },
      "weight": 3,
      "visibility": "student"
    },
    {
      "id": "db-port",
      "name": "Le port MySQL est ouvert",
      "kind": "tcp",
      "vantage": "outside",
      "config": { "port": 3306 },
      "expect": { "open": true },
      "weight": 1,
      "visibility": "summary"
    }
  ]
}
```

`grader_image: null` → image plateforme par défaut (`GRADER_IMAGE`).

Types de sondes :

| `kind` | Description | MVP-2 |
|--------|-------------|-------|
| `http` | Requête HTTP vers le lab (`status`, `body_contains`, `regex`) | ✅ exécutée |
| `tcp` | Port ouvert ? | ✅ exécutée |
| `sql` | Requête SQL (mysql/postgres) contre le lab | ✅ exécutée |
| `script` | Script bash de l'enseignant (`custom_script`) | ✅ exécutée |
| `file` | Présence/contenu d'un fichier (`vantage: inside`) | ⏳ `skip` (différé) |
| `command` | Commande dans le pod (`vantage: inside`) | ⏳ `skip` (différé) |

> Les probes `inside` exigeraient un `exec` dans le pod étudiant, ce qui casserait
> l'isolation du grader : elles sont **marquées `skip`** en MVP-2. Voir [`grader-pod.md`](grader-pod.md).

### Déclenchement

Selon `grading_mode` de l'Assignment :
- `self_check` / `graded` : l'étudiant lance ses tests via `POST …/run-tests` (formatif).
- L'enseignant lance `POST …/test-now` (lab de démo) ou `POST …/run-tests-all` (toute la classe).

### Résultat

Un `GradingRun` terminé (`status = done`) contient :
- `score_suggestion` : somme pondérée des probes passées **ramenée sur 20** (ex. `"15/20"`), `skip` exclues
- `results` : liste de `ProbeResult` avec le détail de chaque sonde
- `passed_checks` / `total_checks` : compteurs de sondes passées

Le score est une **suggestion** — l'enseignant conserve toujours la main sur la note finale
via le champ `grade` de la soumission (pré-rempli avec la suggestion, modifiable).

---

## Points d'attention

- Une soumission est unique par `(assignment_id, user_id)`. La réexécuter met à jour la soumission existante, pas en crée une nouvelle.
- `is_late` est calculé et fixé au moment de la soumission (`due_at_snapshot` est copié pour éviter la dérive si `due_at` est modifié a posteriori).
- Le `deploy-all` (rapport `BulkSpawnReport`) ignore les étudiants ayant déjà un lab pour ce devoir (`spawn_status = "skipped"`).
- Les `GradingRun` sont archivés en base, ce qui permet d'observer l'évolution de la correction si l'étudiant rerend.
- En MVP-2 le verdict est récupéré en **lisant les logs du Job** (modèle *pull*). Les champs `result_token_hash` + `token_used_at` sur `GradingRun` sont **réservés à un futur mode push** (callback HTTP token à usage unique) et ne sont pas utilisés aujourd'hui. Voir [`grader-pod.md`](grader-pod.md).
- Un run resté bloqué (`queued`/`running`) au-delà de `GRADING_RUN_STUCK_MINUTES` est réconcilié en `error` par la tâche de nettoyage (`backend/tasks/cleanup.py`).
