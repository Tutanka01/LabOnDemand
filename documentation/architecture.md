---
title: Architecture LabOnDemand
summary: Vue d'ensemble des composants techniques — FastAPI, MariaDB, Redis, Kubernetes, Nginx, React — structure du dépôt, modèle de données complet et flux de données entre les couches.
read_when: |
  - Tu découvres le projet et veux comprendre comment les composants s'articulent
  - Tu travailles sur une nouvelle fonctionnalité et dois situer où coder
  - Tu debugges un problème qui traverse plusieurs couches (API, BDD, K8s)
---

# Architecture LabOnDemand

## Présentation

LabOnDemand est une plateforme multi-tenant permettant aux **enseignants et étudiants** de déployer des environnements de laboratoire Kubernetes (Jupyter, VS Code, LAMP, WordPress, MySQL/phpMyAdmin…) sans connaissance de Kubernetes. L'accès est contrôlé par un RBAC à trois rôles, les ressources sont isolées par namespace utilisateur, et la plateforme peut être connectée à un IdP universitaire via OIDC/SSO.

En plus des labs individuels, la plateforme propose un **système pédagogique complet** : classes, devoirs avec déploiement en masse, soumissions, et correction automatisée par sondes.

---

## Vue d'ensemble des composants

```
┌─────────────────────────────────────────────────────────────────┐
│  Navigateur                                                      │
│  ├── React/Vite SPA (Nginx)  frontend-app/                       │
│  └── REST API (FastAPI 0.115) backend/                           │
│         │                                                        │
│         ├── Auth + sessions  security.py  ◄──► Redis             │
│         ├── Auth OIDC/SSO    sso.py + auth_router.py             │
│         ├── Labs K8s         routers/k8s_*  ◄──► Kubernetes API  │
│         ├── Classes/Devoirs  routers/classrooms.py               │
│         ├── Étudiant         routers/student.py                  │
│         ├── Audit logs       routers/audit_logs.py               │
│         ├── BDD              database.py  ◄──► MariaDB            │
│         └── Tâches de fond   tasks/cleanup.py (asyncio)          │
└─────────────────────────────────────────────────────────────────┘
```

**Technologies** : Python 3.13, FastAPI 0.115, SQLAlchemy 2, MariaDB, Redis, kubernetes-client 32, Nginx, React 18, TypeScript, Vite, Tailwind CSS, Radix UI, Docker Compose.

Redis est utilisé comme store de sessions authentifié et reste sur le réseau interne. Les origines CORS sont autorisées explicitement côté application ; le proxy Nginx ne reflète pas dynamiquement l'en-tête `Origin` reçu.

---

## Structure du dépôt

```
LabOnDemand/
├── backend/
│   ├── main.py                     # Point d'entrée FastAPI, bootstrap, tâche de nettoyage
│   ├── config.py                   # Tous les paramètres (env vars, valeurs par défaut)
│   ├── models.py                   # ORM SQLAlchemy (voir section Modèle de données)
│   ├── schemas.py                  # Pydantic schemas (validation entrée/sortie)
│   ├── database.py                 # Moteur SQLAlchemy + SessionLocal
│   ├── security.py                 # Sessions, hachage bcrypt, dépendances FastAPI
│   ├── migrations.py               # Migrations SQL idempotentes (18 migrations)
│   ├── seed.py                     # Données initiales (admin, templates, runtime configs)
│   ├── k8s_utils.py                # Labels, namespaces, quotas (get_role_limits + UserQuotaOverride)
│   ├── templates.py                # DeploymentConfig : lecture templates depuis la BDD
│   ├── deployment_service.py       # DeploymentService : orchestration K8s + cleanup
│   ├── grader_service.py           # Grader Pod : Job isolé, NetworkPolicy, watcher pull (voir grader-pod.md)
│   ├── session_store.py            # Redis store (TTL par clé, scan par user_id)
│   ├── sso.py                      # OIDC : discovery (TTL configurable), exchange, userinfo, map_role
│   ├── logging_config.py           # Logging structuré JSON (app.log, access.log, audit.log)
│   ├── error_handlers.py           # Gestionnaire d'exception global
│   ├── auth_router.py              # /auth/* (login, SSO, users, quota-override, CSV import)
│   ├── routers/                    # Endpoints découpés par domaine
│   │   ├── k8s_deployments.py      # CRUD déploiements (liste, create*, pause, resume, delete)
│   │   ├── k8s_storage.py          # PersistentVolumeClaims
│   │   ├── k8s_terminal.py         # WebSocket exec (terminal pod)
│   │   ├── k8s_templates.py        # Templates CRUD + resource-presets
│   │   ├── k8s_runtime_configs.py  # Runtime configs CRUD
│   │   ├── k8s_monitoring.py       # Stats cluster, namespaces, pods, usage
│   │   ├── quotas.py               # Résumé de quota utilisateur
│   │   ├── classrooms.py           # Classes, inscriptions, devoirs, soumissions, correction
│   │   ├── student.py              # Vue étudiant : devoirs, soumissions, statut de correction
│   │   ├── audit_logs.py           # Journal d'audit (admin)
│   │   └── _helpers.py             # Utilitaires partagés (raise_k8s_http, audit_logger)
│   ├── services/                   # Mixins de déploiement (stacks multi-conteneurs)
│   │   ├── wordpress_deploy.py     # Stack WordPress + MariaDB
│   │   ├── mysql_deploy.py         # Stack MySQL + phpMyAdmin
│   │   └── lamp_deploy.py          # Stack LAMP (Apache + PHP + MySQL + phpMyAdmin)
│   ├── tasks/                      # Tâches de fond asyncio
│   │   └── cleanup.py              # Nettoyage labs expirés + namespaces orphelins + runs grader bloqués
│   └── tests/                      # Suite pytest (18 fichiers, SQLite in-memory)
├── frontend-app/                   # SPA React/TypeScript/Vite (frontend principal)
│   ├── src/
│   │   ├── components/
│   │   │   ├── admin/              # Gestion utilisateurs, templates, runtime configs
│   │   │   ├── dashboard/          # Déploiements, quotas, terminal, détails lab
│   │   │   └── teacher/            # Classes, devoirs, soumissions, correction
│   │   ├── lib/
│   │   │   ├── api.ts              # Client HTTP (fetch wrappé, gestion erreurs)
│   │   │   └── format.ts           # Formatage dates, tailles, statuts
│   │   ├── hooks/                  # React Query hooks (TanStack Query)
│   │   ├── types/api.ts            # Types TypeScript des réponses API
│   │   ├── locales/                # Traductions i18n
│   │   │   ├── fr.json             # Français
│   │   │   └── en.json             # Anglais
│   │   └── styles/main.css         # Tailwind + variables CSS
│   ├── Dockerfile                  # Build Node.js 20 → runtime Nginx:alpine
│   └── package.json
├── frontend/                       # Ancien frontend HTML/Vanilla JS (legacy, non utilisé)
├── documentation/                  # Documentation détaillée (ce dossier)
├── dockerfiles/                    # Dockerfiles images de déploiement (vscode, etc.)
│   └── grader/                     # Image Grader Pod (Dockerfile + grader.py + contrat, voir grader-pod.md)
├── nginx/                          # Configuration Nginx
├── tests/                          # Tests d'intégration / charge
└── compose.yaml                    # Docker Compose (dev/local)
```

> `*` = endpoint rate-limité (10 créations / 5 min par IP)

---

## Flux d'une requête de déploiement

```
1. Navigateur   POST /api/v1/k8s/deployments
                  body: { name, deployment_type, image, cpu_request, … }

2. FastAPI middleware
                  • Logging structuré + request_id
                  • Rate limiting (slowapi) ← @limiter.limit("10/5minute")

3. k8s_deployments.create_deployment()
                  • get_current_user() → session Redis → User ORM
                  • Validation Pydantic du body

4. DeploymentService.create_deployment()
                  • ensure_namespace_exists(user_namespace)
                  • ensure_namespace_baseline(namespace, role) → ResourceQuota + LimitRange
                  • _assert_user_quota() → get_role_limits(role, user_id) ← UserQuotaOverride
                  • clamp_resources_for_role() → plafonnement CPU/RAM
                  • _preflight_k8s_quota() → vérification K8s ResourceQuota
                  • Stratégie selon deployment_type:
                    - simple    → manifests inline (vscode, jupyter, custom)
                    - wordpress → WordPressDeployMixin._create_wordpress_stack()
                    - mysql     → MySQLDeployMixin._create_mysql_pma_stack()
                    - lamp      → LAMPDeployMixin._create_lamp_stack()

5. Kubernetes API  Secret → PVC → Service(s) → Deployment(s) → [Ingress]

6. Réponse JSON  { message, deployment_type, namespace, service_info, created_objects }
```

---

## Flux d'un devoir (Classroom → Assignment → Submission)

```
Teacher  POST /api/v1/classrooms                                  → crée une classe
Teacher  POST /api/v1/classrooms/{cid}/students                   → inscrit des étudiants
Teacher  POST /api/v1/classrooms/{cid}/assignments                → crée un devoir (template, CPU/RAM, due_at)
Teacher  POST /api/v1/classrooms/{cid}/assignments/{aid}/deploy-all → déploie le lab sur tous les étudiants

Student  GET  /api/v1/student/assignments                         → liste les devoirs de ses classes
Student  GET  /api/v1/student/assignments/{aid}                   → détail + lab + probes visibles + dernier run
Student  POST /api/v1/student/assignments/{aid}/submit            → soumet (texte + liens)
Student  POST /api/v1/student/assignments/{aid}/run-tests         → lance les tests (self-check)
Student  GET  /api/v1/student/assignments/{aid}/grading-runs/{id} → suivi (filtré par visibilité)

Teacher  GET  /api/v1/classrooms/{cid}/assignments/{aid}/submissions          → tableau de triage (+ verdict)
Teacher  POST /api/v1/classrooms/{cid}/assignments/{aid}/submissions/{sid}/grade → note (grade + feedback)
Teacher  POST /api/v1/classrooms/{cid}/assignments/{aid}/test-now             → tests sur le lab de démo
Teacher  POST /api/v1/classrooms/{cid}/assignments/{aid}/run-tests-all        → tests sur toute la classe

[Grader] GradingSpec → GradingRun : Job K8s isolé, verdict lu dans les logs (pull). Voir grader-pod.md
```

---

## Modèle de données

### Utilisateurs et accès

```
users
  id, username, email, hashed_password
  role (student|teacher|admin), role_override (bool)
  is_active, auth_provider (local|oidc), external_id  ← UNIQUE (identifiant SSO)
  created_at, updated_at

user_quota_overrides               ← dérogations admin (IMP-3)
  id, user_id (FK→users, UNIQUE)
  max_apps, max_cpu_m, max_mem_mi, max_storage_gi
  expires_at (NULL = permanent), created_at, created_by
```

### Labs Kubernetes

```
templates
  id, key, name, deployment_type, default_image, default_port
  default_service_type, tags, active, created_at

runtime_configs
  id, key, default_image, target_port, default_service_type
  allowed_for_students, min_cpu/memory_request, min_cpu/memory_limit, active

deployments                        ← traçabilité TTL (IMP-1)
  id, user_id (FK→users)
  name, deployment_type, namespace, stack_name
  status (active|paused|expired|deleted)
  created_at, deleted_at, last_seen_at, expires_at
  cpu_requested, mem_requested
```

### Système pédagogique

```
classrooms
  id, name, description, owner_id (FK→users), archived, created_at, updated_at

enrollments
  id, classroom_id (FK CASCADE), user_id (FK CASCADE)
  enrolled_at, removed_at
  UNIQUE (classroom_id, user_id)

assignments
  id, classroom_id (FK CASCADE), title, instructions (Text MD), deliverables (Text MD)
  template_key, cpu_preset, ram_preset
  due_at, status (active|archived)
  grading_mode (none|self_check|graded)
  created_at, updated_at

assignment_deployments             ← lien devoir ↔ lab étudiant
  id, assignment_id (FK CASCADE), user_id (FK CASCADE)
  deployment_id (FK SET NULL)
  spawn_status (ok|skipped|error), spawn_error
  created_at

assignment_submissions             ← soumissions étudiants (MVP-1)
  id, assignment_id (FK CASCADE), user_id (FK CASCADE)
  attempt_no, status (submitted|graded)
  text (Text), links (JSON), deployment_id (FK SET NULL), lab_snapshot (JSON)
  submitted_at, is_late, due_at_snapshot
  grade (ex. "15/20"), feedback (Text), graded_by (FK→users), graded_at
  UNIQUE (assignment_id, user_id)
```

### Correction automatique (MVP-2)

```
grading_specs                      ← configuration de la correction par sondes
  id, assignment_id (FK CASCADE, UNIQUE)
  grader_image, timeout_seconds (10–600, défaut 120)
  checks (JSON: liste de Probe), custom_script (Text)
  created_at, updated_at

  Probe: { id, name, kind (http|tcp|sql|file|command|script),
           vantage (outside|inside), config (Dict), expect (Dict),
           weight (0–100), visibility (student|summary|teacher_only) }
  MVP-2 : kinds outside http/tcp/sql + script exécutés ; file/command (inside) → skip.

grading_runs                       ← historique des exécutions de correction
  id, assignment_id, user_id, submission_id, deployment_id
  trigger (student_self|on_submit|teacher)
  status (queued|running|done|error)
  started_at, finished_at
  total_checks, passed_checks, score_suggestion (ex. "15/20")
  results (JSON: liste de ProbeResult), error
  result_token_hash (SHA-256), token_used_at   ← réservés à un futur mode push (non utilisés en MVP-2)
  created_at
```

> Exécution = **Grader Pod** : Job K8s éphémère et isolé, verdict récupéré via les logs
> (modèle *pull*). Orchestration dans `backend/grader_service.py` + image `dockerfiles/grader/`.
> Détails : [`grader-pod.md`](grader-pod.md).

---

## RBAC (contrôle d'accès par rôle)

| Rôle    | Labs K8s     | Quotas CPU/RAM | Templates | Utilisateurs | Classes / Devoirs         | Quota override |
|---------|-------------|----------------|-----------|--------------|---------------------------|----------------|
| student | ses propres  | faibles         | lecture   | —            | lecture (inscrits)         | —              |
| teacher | ses propres  | moyens          | lecture   | —            | CRUD (ses classes)         | —              |
| admin   | tous         | élevés          | CRUD      | CRUD         | accès complet              | CRUD           |

Règles complémentaires :
- Un teacher ne voit que les classes dont il est `owner_id`.
- Un student ne voit que les devoirs des classes où il est inscrit (`enrolled_at IS NOT NULL, removed_at IS NULL`).
- Les opérations sensibles sur un lab (détails, identifiants, pause, terminal, suppression) : propriétaire **ou** admin uniquement — un teacher n'a pas d'accès transverse aux labs d'autres utilisateurs.
- `role_override = true` sur un utilisateur indique que son rôle ne peut pas être modifié par synchronisation SSO.

Les quotas par défaut (définis dans `k8s_utils.get_role_limits()`) peuvent être surchargés individuellement via `UserQuotaOverride`. Voir `documentation/resource-limits.md`.

---

## Sessions

- Token opaque 32 octets (URL-safe) stocké dans le cookie HttpOnly `session_id`
- Payload `{user_id, username, role}` conservé côté serveur dans Redis (TTL = `SESSION_EXPIRY_HOURS`)
- À la **suppression d'un utilisateur** : toutes ses sessions Redis sont invalidées immédiatement via `security.delete_user_sessions(user_id)` (scan par pattern `session:*`)
- Au **logout** : seule la session active est supprimée

---

## Cycle de vie des labs (TTL)

Chaque déploiement peut avoir une date d'expiration `expires_at` calculée lors de la création selon le rôle (configurable via env, voir `documentation/lifecycle.md`).

La tâche de fond `backend/tasks/cleanup.py` tourne toutes les `CLEANUP_INTERVAL_MINUTES` minutes et :
1. Met en pause les déploiements dont `expires_at ≤ now` et synchronise la DB
2. Supprime définitivement les labs en pause après `LAB_GRACE_PERIOD_DAYS`
3. Supprime les namespaces Kubernetes orphelins avec deux garde-fous SSO

---

## Nettoyage à la suppression d'utilisateur

```
DELETE /api/v1/auth/users/{id}
  │
  ├─ 1. delete_user_sessions(user_id)     → invalide toutes les sessions Redis
  ├─ 2. cleanup_user_namespace(user_id)   → supprime le namespace K8s (labondemand-user-N)
  └─ 3. db.delete(user)                   → supprime la ligne en base (CASCADE → deployments, overrides, classes…)
```

Les étapes 1 et 2 sont non-bloquantes : une erreur K8s ou Redis n'empêche pas la suppression en base. Tout est tracé dans `logs/audit.log`.

---

## Health check

`GET /api/v1/health` retourne :

```json
{
  "status": "healthy",
  "db":    "ok",
  "redis": "ok",
  "k8s":   "ok",
  "timestamp": "2026-01-01T00:00:00"
}
```

Utilisé par Docker Compose (`healthcheck`), le monitoring externe, et les outils de déploiement CI/CD.

---

## Ingress (optionnel)

Lorsque `INGRESS_ENABLED=true`, chaque déploiement reçoit automatiquement un objet Ingress avec un sous-domaine de la forme :

```
{name}-u{user_id}.{INGRESS_BASE_DOMAIN}
```

Compatible Traefik et Nginx Ingress Controller. TLS via `INGRESS_TLS_SECRET`. Les types de déploiement concernés sont configurables via `INGRESS_AUTO_TYPES`.

---

## Frontend (frontend-app/)

L'interface est une SPA React 18 / TypeScript / Vite compilée dans une image Nginx. Elle n'est **jamais servie directement par Node.js en production** — uniquement via le conteneur `frontend`.

Bibliothèques clés :
- **Radix UI** : composants accessibles (dialog, dropdown, tabs, tooltip…)
- **TanStack Query** : fetching et cache des données serveur
- **TanStack Table** : tableaux triables/filtrables (liste des déploiements, soumissions…)
- **Xterm.js** : terminal WebSocket intégré dans le dashboard
- **lucide-react** : icônes

L'UI est bilingue (français / anglais). Les chaînes de traduction sont dans `frontend-app/src/locales/fr.json` et `en.json`. Toute nouvelle chaîne visible doit être ajoutée dans les deux fichiers.
