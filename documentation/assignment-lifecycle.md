---
title: Cycle de vie des devoirs et soumissions
summary: Statuts et transitions pour Assignment, AssignmentDeployment, AssignmentSubmission et GradingRun — flux complet du côté enseignant et du côté étudiant.
read_when: |
  - Tu travailles sur le système de classes/devoirs (routers/classrooms.py, routers/student.py)
  - Tu veux comprendre comment les soumissions et les corrections s'articulent
  - Tu implémentes ou débogues le bulk-spawn ou la correction automatique
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

POST /api/v1/classrooms/{classroom_id}/enroll
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
- `grading_mode` : `none` (pas de note), `self_check` (étudiant déclenche la correction), `graded` (correction à l'initiative de l'enseignant)
- `cpu_preset` / `ram_preset` : parmi les presets définis par rôle dans `backend/templates.py`

### 3. Déployer les labs en masse (bulk-spawn)

```http
POST /api/v1/assignments/{assignment_id}/bulk-spawn
```

Déploie automatiquement un lab pour chaque étudiant inscrit dans la classe. Les labs sont créés dans le namespace de chaque étudiant (`labondemand-user-{id}`), avec les ressources définies dans le devoir.

La réponse contient un `BulkSpawnReport` : `{ total, ok, skipped, error, details }`.

### 4. Consulter les soumissions

```http
GET /api/v1/classrooms/{classroom_id}/submissions
```

Retourne toutes les soumissions de tous les devoirs de la classe, avec le statut de chaque étudiant (`submitted`, `graded`, ou `null` si pas encore soumis).

### 5. Noter une soumission

```http
POST /api/v1/assignments/{assignment_id}/grade
{
  "user_id": 3,
  "grade": "15/20",
  "feedback": "Bonne implémentation, mais la complexité de la recherche pourrait être améliorée."
}
```

Met `submission.status = "graded"`, enregistre `grade`, `feedback`, `graded_by` et `graded_at`.

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

Inclut le Markdown des instructions, les livrables attendus, et le lien vers le lab de l'étudiant.

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

### 4. Consulter le résultat de correction

```http
GET /api/v1/student/assignments/{assignment_id}/grading-status
```

Retourne le `GradingRun` le plus récent, filtré selon `Probe.visibility` :
- Sondes `student` : résultat complet visible
- Sondes `summary` : seulement le résumé agrégé
- Sondes `teacher_only` : masquées

---

## Correction automatique (GradingSpec / GradingRun)

### Configurer la correction automatique

Un enseignant ou admin peut créer une `GradingSpec` pour un devoir. Elle définit une liste de sondes (`checks`) qui seront exécutées sur le lab de l'étudiant.

```json
{
  "grader_image": "registry.example.com/grader:latest",
  "timeout_seconds": 120,
  "checks": [
    {
      "id": "http-check",
      "name": "L'application répond sur le port 8080",
      "kind": "http",
      "vantage": "outside",
      "config": { "path": "/", "port": 8080 },
      "expect": { "status": 200 },
      "weight": 30,
      "visibility": "student"
    },
    {
      "id": "file-check",
      "name": "Le fichier main.py est présent",
      "kind": "file",
      "vantage": "inside",
      "config": { "path": "/workspace/main.py" },
      "expect": { "exists": true },
      "weight": 20,
      "visibility": "student"
    }
  ]
}
```

Types de sondes disponibles :

| `kind` | Description | `vantage` |
|--------|-------------|-----------|
| `http` | Requête HTTP vers le lab | `outside` |
| `tcp` | Connexion TCP (port ouvert ?) | `outside` |
| `sql` | Requête SQL dans le lab | `inside` |
| `file` | Vérification de présence/contenu fichier | `inside` |
| `command` | Exécution d'une commande dans le pod | `inside` |
| `script` | Script personnalisé via `custom_script` | `inside` |

### Déclenchement

Selon `grading_mode` de l'Assignment :
- `self_check` : l'étudiant peut déclencher manuellement un `GradingRun`
- `graded` : l'enseignant ou une soumission déclenche le `GradingRun`

### Résultat

Un `GradingRun` terminé (`status = done`) contient :
- `score_suggestion` : score calculé (0–100) pondéré par `weight` de chaque sonde
- `results` : liste de `ProbeResult` avec le détail de chaque sonde
- `passed_checks` / `total_checks` : compteurs de sondes passées

Le score est une **suggestion** — l'enseignant conserve toujours la main sur la note finale via le champ `grade` de la soumission.

---

## Points d'attention

- Une soumission est unique par `(assignment_id, user_id)`. La réexécuter met à jour la soumission existante, pas en crée une nouvelle.
- `is_late` est calculé et fixé au moment de la soumission (`due_at_snapshot` est copié pour éviter la dérive si `due_at` est modifié a posteriori).
- Le `bulk-spawn` ignore les étudiants ayant déjà un lab pour ce devoir (`spawn_status = "skipped"`).
- Les `GradingRun` sont archivés en base, ce qui permet d'observer l'évolution de la correction si l'étudiant rerend.
- `result_token_hash` + `token_used_at` sur `GradingRun` permettent une validation à usage unique du résultat (anti-rejeu).
