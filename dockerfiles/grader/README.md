# Image Grader LabOnDemand

Image jetable et **sans aucun accès au cluster** qui exécute les probes « boîte noire »
d'un devoir contre le lab d'un étudiant, puis imprime son verdict en JSON sur stdout.
L'API LabOnDemand crée un `Job` Kubernetes isolé à partir de cette image, surveille sa
fin, puis **lit son stdout** pour récupérer les résultats (modèle *pull* — le grader ne
rappelle jamais l'API).

## Build

```bash
docker build -t labondemand/grader:latest dockerfiles/grader/
```

Publier l'image sur le registre du cluster, puis renseigner son nom via la variable
d'environnement `GRADER_IMAGE` de l'API (défaut : `labondemand/grader:latest`). Un devoir
peut surcharger l'image via `GradingSpec.grader_image`.

## Entrées (variables d'environnement injectées par le Job)

| Variable | Rôle |
|---|---|
| `GRADER_SPEC` | JSON `{"checks": [<probe>, ...]}` — les probes de l'enseignant |
| `GRADER_TARGET_URL` | URL HTTP de base du lab cible (`http://svc.ns.svc.cluster.local:80`) |
| `GRADER_TARGET_HOST` | hostname du lab (probes `tcp` / `sql`) |
| `GRADER_TARGET_PORT` | port par défaut du lab |
| `GRADER_TIMEOUT` | timeout par probe en secondes |
| `GRADER_SCRIPT` | (optionnel) script bash de l'enseignant |

## Probes supportées (périmètre MVP-2 : *outside*)

- **http** — `config: {url|path, method, headers, body}` ; `expect: {status, body_contains, regex}`
- **tcp** — `config: {host?, port}` ; `expect: {open: true|false}`
- **sql** — `config: {engine: mysql|postgres, host?, port, user, password, database, query}` ; `expect: {min_rows, contains}`
- **script** — exécute `GRADER_SCRIPT` (voir contrat ci-dessous)

Les probes `inside` (`file` / `command`, exec dans le pod étudiant) ne sont **pas**
supportées par le grader isolé : elles produisent un statut `skip`.

## Contrat de sortie

Le grader imprime, entre deux marqueurs, une ligne JSON :

```
===GRADER_RESULT_BEGIN===
{"checks": [{"id": "...", "name": "...", "status": "pass", "message": "...", "output": "...", "weight": 1, "visibility": "student"}]}
===GRADER_RESULT_END===
```

`status` ∈ `pass | fail | error | skip`. Le grader **ne plante jamais** : une probe en
échec produit un résultat `fail`/`error`, jamais un exit non nul qui masquerait les autres.

## Contrat des scripts enseignant (`kind: script`)

Le script reçoit `GRADER_TARGET_URL` / `GRADER_TARGET_HOST` dans son environnement, et :

1. **soit** imprime sur stdout un objet `{"checks": [...]}` (mêmes champs que ci-dessus) —
   plusieurs checks possibles ;
2. **soit** renvoie un exit code (`0` = succès, non-zéro = échec) et le grader en déduit un
   verdict binaire.

## Sécurité

Le `Job` qui exécute cette image est créé par l'API avec : ServiceAccount sans token monté,
aucun droit RBAC, `NetworkPolicy` egress restreinte (lab cible + DNS), limites CPU/RAM,
`activeDeadlineSeconds` et `ttlSecondsAfterFinished` courts. Voir `backend/grader_service.py`.
