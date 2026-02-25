# Architecture LabOnDemand

## Vue d'ensemble

LabOnDemand est une plateforme web permettant aux enseignants et étudiants de déployer des environnements de laboratoire (Jupyter, VS Code, LAMP, WordPress, MySQL/phpMyAdmin…) directement sur un cluster Kubernetes, sans connaissances Kubernetes.

```
Browser
  │
  ├─ Static files (Nginx)   frontend/
  │
  └─ REST API (FastAPI)     backend/
       │
       ├─ Auth + sessions   security.py  ←→  Redis
       ├─ CRUD déploiements routers/     ←→  Kubernetes API
       ├─ BDD               database.py  ←→  MariaDB
       └─ OIDC / SSO        auth_router.py
```

## Structure du dépôt

```
LabOnDemand/
├── backend/
│   ├── main.py                  # Point d'entrée FastAPI, bootstrap, montage des routers
│   ├── config.py                # Tous les paramètres (env vars)
│   ├── models.py                # ORM SQLAlchemy (User, UserRole, Template, RuntimeConfig)
│   ├── schemas.py               # Pydantic schemas (validation entrée/sortie)
│   ├── database.py              # Création du moteur SQLAlchemy
│   ├── security.py              # Sessions, hachage, dépendances FastAPI (get_current_user)
│   ├── migrations.py            # Migrations SQL idempotentes (ALTER TABLE)
│   ├── seed.py                  # Données initiales (admin, templates, runtime configs)
│   ├── k8s_utils.py             # Utilitaires Kubernetes (labels, namespaces, quotas)
│   ├── templates.py             # DeploymentConfig: lecture templates depuis la BDD
│   ├── deployment_service.py    # DeploymentService: orchestration des déploiements K8s
│   ├── session_store.py         # Abstraction Redis / mémoire pour les sessions
│   ├── logging_config.py        # Configuration du logging structuré (JSON)
│   ├── diagnostic.py            # Endpoint /diagnostic (DEBUG seulement)
│   ├── routers/                 # Endpoints K8s découpés par domaine
│   │   ├── k8s_deployments.py   # CRUD déploiements (liste, détails, create, delete, pause)
│   │   ├── k8s_storage.py       # PersistentVolumeClaims
│   │   ├── k8s_terminal.py      # WebSocket exec (terminal pod)
│   │   ├── k8s_templates.py     # Templates + resource-presets
│   │   ├── k8s_runtime_configs.py  # Runtime configs CRUD
│   │   ├── k8s_monitoring.py    # Stats cluster, namespaces, pods, usage
│   │   └── quotas.py            # Résumé de quota utilisateur
│   └── services/                # Mixins de déploiement (stacks multi-conteneurs)
│       ├── wordpress_deploy.py  # Stack WordPress + MariaDB
│       ├── mysql_deploy.py      # Stack MySQL + phpMyAdmin
│       └── lamp_deploy.py       # Stack LAMP (Apache + PHP + MySQL + phpMyAdmin)
├── frontend/
│   ├── index.html / script.js   # Dashboard principal (déploiements)
│   ├── admin.html / js/admin.js # Gestion des utilisateurs (admin)
│   ├── login.html / js/login.js
│   ├── register.html / js/register.js
│   ├── js/api.js                # Fonction api() partagée + checkSsoStatus()
│   ├── js/auth.js               # AuthManager (vérification session)
│   ├── js/templates.js          # CRUD templates (admin)
│   ├── js/runtime-configs.js    # CRUD runtime configs (admin)
│   ├── js/dashboard/            # Modules du dashboard principal
│   │   ├── deployments.js       # Affichage et actions sur les déploiements
│   │   ├── resources.js         # PVCs + quotas
│   │   ├── state.js             # État global de l'application
│   │   ├── statusView.js        # Vue statut des pods
│   │   └── utils.js             # Utilitaires UI
│   └── style.css                # Styles globaux
├── documentation/               # Documentation détaillée
├── dockerfiles/                 # Dockerfiles pour les images de déploiement
└── compose.yaml                 # Docker Compose (dev/local)
```

## Flux d'une requête de déploiement

```
1. Browser      POST /api/v1/k8s/deployments
                  body: { name, deployment_type, namespace, ... }

2. FastAPI       routers/k8s_deployments.py
                  • Authentification via get_current_user() (cookie session_id)
                  • Validation Pydantic du body
                  • Résolution du namespace (user namespace ou namespace fourni)

3. DeploymentService.create_deployment()
                  • Vérifie quotas utilisateur (max_deployments_per_user)
                  • Sélectionne la stratégie selon deployment_type:
                    - simple (vscode, jupyter, custom, netbeans) → manifests inline
                    - wordpress → WordPressDeployMixin._create_wordpress_stack()
                    - mysql    → MySQLDeployMixin._create_mysql_pma_stack()
                    - lamp     → LAMPDeployMixin._create_lamp_stack()

4. Kubernetes API  Création des objets K8s:
                  Secret → PVC → Service(s) → Deployment(s) → [Ingress]

5. Réponse JSON  { message, deployment_type, namespace, service_info,
                   created_objects, credentials }
```

## Modèle de données

```
users
  id, username, email, hashed_password, role (student|teacher|admin)
  is_active, auth_provider (local|oidc), external_id, created_at

templates
  id, key, name, runtime_type, docker_image, default_port
  access_mode, tags, is_active, description

runtime_configs
  id, name, key, value, description, is_active, allowed_for_students
```

## RBAC

| Rôle    | Déploiements | Quotas CPU/RAM | Templates | Utilisateurs |
|---------|-------------|---------------|-----------|--------------|
| student | ses propres  | faibles        | lecture   | —            |
| teacher | ses propres  | moyens         | lecture   | —            |
| admin   | tous         | élevés         | CRUD      | CRUD         |

Les quotas sont définis dans `k8s_utils.py:get_role_limits()` et clampés par
`clamp_resources_for_role()` avant création des manifests K8s.

## Sessions

- Token opaque (32 octets URL-safe) stocké dans le cookie `session_id`
- Payload (user_id, username, role) stocké côté serveur dans Redis
- Fallback en mémoire si Redis n'est pas configuré
- Expiration configurable via `SESSION_EXPIRY_HOURS` (défaut: 24h)

## Ingress (optionnel)

Lorsque `INGRESS_ENABLED=true`, les déploiements reçoivent automatiquement
une ressource Ingress avec un sous-domaine de la forme:

```
{deployment-name}-{user-id}.{INGRESS_BASE_DOMAIN}
```

Compatible Traefik et Nginx Ingress Controller. TLS via cert-manager si
`INGRESS_TLS_SECRET` est défini.
