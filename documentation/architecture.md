# Architecture LabOnDemand

## Présentation

LabOnDemand est une plateforme multi-tenant permettant aux **enseignants et étudiants** de déployer des environnements de laboratoire Kubernetes (Jupyter, VS Code, LAMP, WordPress, MySQL/phpMyAdmin…) sans connaissance de Kubernetes. L'accès est contrôlé par un RBAC à trois rôles, les ressources sont isolées par namespace utilisateur, et la plateforme peut être connectée à un IdP universitaire via OIDC/SSO.

---

## Vue d'ensemble des composants

```
┌─────────────────────────────────────────────────────────────────┐
│  Navigateur                                                      │
│  ├── Static files (Nginx)   frontend/                            │
│  └── REST API (FastAPI 0.115) backend/                           │
│         │                                                        │
│         ├── Auth + sessions  security.py  ◄──► Redis             │
│         ├── Auth OIDC/SSO    sso.py + auth_router.py             │
│         ├── CRUD déploiements routers/    ◄──► Kubernetes API    │
│         ├── BDD               database.py ◄──► MariaDB           │
│         └── Tâches de fond    tasks/cleanup.py (asyncio)         │
└─────────────────────────────────────────────────────────────────┘
```

**Technologies** : Python 3.11, FastAPI, SQLAlchemy 2, MariaDB, Redis, kubernetes-client, Nginx, Docker Compose.

---

## Structure du dépôt

```
LabOnDemand/
├── backend/
│   ├── main.py                  # Point d'entrée FastAPI, bootstrap, tâche de nettoyage
│   ├── config.py                # Tous les paramètres (env vars, valeurs par défaut)
│   ├── models.py                # ORM SQLAlchemy (User, Deployment, UserQuotaOverride, Template, RuntimeConfig)
│   ├── schemas.py               # Pydantic schemas (validation entrée/sortie)
│   ├── database.py              # Moteur SQLAlchemy + SessionLocal
│   ├── security.py              # Sessions, hachage bcrypt, dépendances FastAPI, delete_user_sessions()
│   ├── migrations.py            # Migrations SQL idempotentes (CREATE TABLE IF NOT EXISTS / ALTER TABLE)
│   ├── seed.py                  # Données initiales (admin, templates, runtime configs)
│   ├── k8s_utils.py             # Labels, namespaces, quotas (get_role_limits + UserQuotaOverride)
│   ├── templates.py             # DeploymentConfig : lecture templates depuis la BDD
│   ├── deployment_service.py    # DeploymentService : orchestration K8s + cleanup_user_namespace()
│   ├── session_store.py         # Redis store (TTL par clé, scan par user_id)
│   ├── sso.py                   # OIDC : discovery (TTL configurable), exchange, userinfo, map_role
│   ├── logging_config.py        # Logging structuré JSON (app.log, access.log, audit.log)
│   ├── error_handlers.py        # Gestionnaire d'exception global
│   ├── auth_router.py           # Endpoints /auth/* (login, SSO, users, quota-override, CSV import)
│   ├── routers/                 # Endpoints K8s découpés par domaine
│   │   ├── k8s_deployments.py   # CRUD déploiements (liste, détails, create*, delete, pause, resume)
│   │   ├── k8s_storage.py       # PersistentVolumeClaims
│   │   ├── k8s_terminal.py      # WebSocket exec (terminal pod)
│   │   ├── k8s_templates.py     # Templates CRUD + resource-presets
│   │   ├── k8s_runtime_configs.py  # Runtime configs CRUD
│   │   ├── k8s_monitoring.py    # Stats cluster, namespaces, pods, usage
│   │   ├── quotas.py            # Résumé de quota utilisateur
│   │   └── _helpers.py          # Utilitaires partagés (raise_k8s_http, audit_logger)
│   ├── services/                # Mixins de déploiement (stacks multi-conteneurs)
│   │   ├── wordpress_deploy.py  # Stack WordPress + MariaDB
│   │   ├── mysql_deploy.py      # Stack MySQL + phpMyAdmin
│   │   └── lamp_deploy.py       # Stack LAMP (Apache + PHP + MySQL + phpMyAdmin)
│   └── tasks/                   # Tâches de fond asyncio
│       └── cleanup.py           # Nettoyage labs expirés + namespaces orphelins
├── frontend/
│   ├── index.html / script.js   # Dashboard principal (déploiements, quotas)
│   ├── admin.html / js/admin.js # Gestion des utilisateurs et quotas (admin)
│   ├── admin-stats.html         # Statistiques cluster (admin)
│   ├── login.html / js/login.js
│   ├── register.html / js/register.js
│   ├── js/api.js                # window.api() partagé + checkSsoStatus()
│   ├── js/auth.js               # AuthManager (vérification session + redirection)
│   ├── js/darkmode.js           # Toggle mode sombre/clair (localStorage + prefers-color-scheme)
│   ├── js/templates.js          # CRUD templates (admin)
│   ├── js/runtime-configs.js    # CRUD runtime configs (admin)
│   ├── js/dashboard/            # Modules du dashboard
│   │   ├── deployments.js       # Affichage et actions (pause, resume, delete)
│   │   ├── resources.js         # PVCs + quotas
│   │   ├── state.js             # État global
│   │   ├── statusView.js        # Vue statut des pods
│   │   └── utils.js             # Utilitaires UI
│   ├── css/admin.css / quotas.css / …
│   └── style.css                # Styles globaux (variables, dark mode, utilitaires)
├── documentation/               # Documentation détaillée (ce dossier)
├── dockerfiles/                 # Dockerfiles images de déploiement
└── compose.yaml                 # Docker Compose (dev/local)
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

## Modèle de données

```
users
  id, username, email, hashed_password
  role (student|teacher|admin), role_override (bool)
  is_active, auth_provider (local|oidc), external_id  ← UNIQUE (identifiant SSO)
  created_at, updated_at

deployments                        ← IMP-1 (traçabilité)
  id, user_id (FK→users)
  name, deployment_type, namespace, stack_name
  status (active|paused|expired|deleted)
  created_at, deleted_at, last_seen_at, expires_at
  cpu_requested, mem_requested

user_quota_overrides               ← IMP-3 (dérogations admin)
  id, user_id (FK→users, UNIQUE)
  max_apps, max_cpu_m, max_mem_mi, max_storage_gi
  expires_at (NULL = permanent), created_at, created_by

templates
  id, key, name, deployment_type, default_image, default_port
  default_service_type, tags, active, created_at

runtime_configs
  id, key, default_image, target_port, default_service_type
  allowed_for_students, min_cpu_request, min_memory_request
  min_cpu_limit, min_memory_limit, active, created_at
```

---

## RBAC (contrôle d'accès par rôle)

| Rôle    | Déploiements | Quotas CPU/RAM | Templates | Utilisateurs | Quota override |
|---------|-------------|----------------|-----------|--------------|----------------|
| student | ses propres  | faibles         | lecture   | —            | —              |
| teacher | ses propres  | moyens          | lecture   | —            | —              |
| admin   | tous         | élevés          | CRUD      | CRUD         | CRUD           |

Les quotas par défaut (définis dans `k8s_utils.get_role_limits()`) peuvent être
surchargés individuellement via `UserQuotaOverride`. Voir `documentation/resource-limits.md`.

---

## Sessions

- Token opaque 32 octets (URL-safe) stocké dans le cookie HttpOnly `session_id`
- Payload `{user_id, username, role}` conservé côté serveur dans Redis (TTL = `SESSION_EXPIRY_HOURS`)
- À la **suppression d'un utilisateur** : toutes ses sessions Redis sont invalidées immédiatement
  via `security.delete_user_sessions(user_id)` (scan par pattern `session:*`)
- Au **logout** : seule la session active est supprimée

---

## Cycle de vie des labs (TTL)

Chaque déploiement peut avoir une date d'expiration `expires_at` calculée lors de
la création selon le rôle (configurable via env, voir `documentation/lifecycle.md`).

La tâche de fond `backend/tasks/cleanup.py` tourne toutes les `CLEANUP_INTERVAL_MINUTES`
minutes et :
1. Met en pause les déploiements dont `expires_at ≤ now`
2. Supprime définitivement (de K8s) les labs en pause depuis plus de `LAB_GRACE_PERIOD_DAYS` jours
3. Supprime les namespaces Kubernetes orphelins (user supprimé mais namespace présent),
   avec deux garde-fous pour protéger les namespaces SSO :
   - déploiements actifs encore rattachés en DB → skip
   - namespace créé depuis moins de `ORPHAN_NS_GRACE_DAYS` jours → skip

---

## Nettoyage à la suppression d'utilisateur

```
DELETE /api/v1/auth/users/{id}
  │
  ├─ 1. delete_user_sessions(user_id)     → invalide toutes les sessions Redis
  ├─ 2. cleanup_user_namespace(user_id)   → supprime le namespace K8s (labondemand-user-N)
  └─ 3. db.delete(user)                   → supprime la ligne en base (CASCADE → deployments, overrides)
```

Les étapes 1 et 2 sont non-bloquantes : une erreur K8s ou Redis n'empêche pas la
suppression en base. Tout est tracé dans `logs/audit.log`.

---

## Health check

`GET /api/v1/health` retourne :

```json
{
  "status": "healthy",   // ou "degraded" si un composant est en erreur
  "db":    "ok",
  "redis": "ok",
  "k8s":   "ok",
  "timestamp": "2026-01-01T00:00:00"
}
```

Utilisé par Docker Compose (`healthcheck`), le monitoring externe, et les outils
de déploiement CI/CD.

---

## Ingress (optionnel)

Lorsque `INGRESS_ENABLED=true`, chaque déploiement reçoit automatiquement
un objet Ingress avec un sous-domaine de la forme :

```
{name}-u{user_id}.{INGRESS_BASE_DOMAIN}
```

Compatible Traefik et Nginx Ingress Controller. TLS via `INGRESS_TLS_SECRET`.

---

## Mode sombre (dark mode)

Le frontend gère un mode sombre natif CSS via :
- La propriété `data-theme="dark"` sur `<html>` (toggle via bouton 🌙 dans le header)
- La `@media (prefers-color-scheme: dark)` comme valeur par défaut système
- La persistance dans `localStorage` (clé `labondemand-theme`)
- Le script `frontend/js/darkmode.js` initialisé **avant** le chargement du DOM
  pour éviter tout flash de contenu blanc
