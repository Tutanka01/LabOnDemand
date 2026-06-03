---
title: Setup de développement
summary: Procédure pour lancer LabOnDemand en local via Docker Compose, configuration des variables d'environnement, migrations et accès aux services.
read_when: |
  - Tu installes le projet pour la première fois sur ta machine de dev
  - Tu cherches quelles variables d'environnement configurer dans .env
  - Tu veux lancer les tests ou vérifier les migrations
---

# Setup de développement

## Prérequis

- Docker + Docker Compose v2
- Un cluster Kubernetes accessible (kubeconfig valide : k3s, kind, Minikube ou cluster distant)

> **Note** : le projet tourne sous Python 3.13. N'installe pas de dépendances directement sur l'hôte — utilise toujours Docker Compose pour que les versions correspondent aux conteneurs.

---

## Démarrage rapide avec Docker Compose

```bash
# Cloner le dépôt
git clone <repo>
cd LabOnDemand

# Copier et adapter la configuration
cp .env.exemple .env    # puis éditer selon ton environnement

# Lancer l'application
docker compose up --build

# L'API est disponible sur http://localhost:8000
# Le frontend est disponible sur http://localhost
```

Attendre que FastAPI affiche `Application startup complete` dans les logs. Un compte `admin` est automatiquement créé avec le mot de passe défini par `ADMIN_DEFAULT_PASSWORD`.

---

## Variables d'environnement (.env)

### API

```env
API_PORT=8000
DEBUG_MODE=False
FRONTEND_PORT=80
CORS_ORIGINS=http://localhost,http://localhost:8000
```

> `DEBUG_MODE=True` active Swagger UI (`/docs`) et l'endpoint de diagnostic `/api/v1/diagnostic/test-auth`.
> **Ne jamais utiliser en production.**

### Base de données

```env
DB_HOST=db
DB_PORT=3306
DB_NAME=labondemand
DB_USER=labondemand
DB_PASSWORD=secure_password_secret
DB_ROOT_PASSWORD=root_password_secret
```

### Sessions Redis

```env
REDIS_PASSWORD=change-me
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
REDIS_NAMESPACE=session:
SESSION_EXPIRY_HOURS=24
SECURE_COOKIES=False      # false en HTTP local, true en HTTPS production
SESSION_SAMESITE=Lax
COOKIE_DOMAIN=            # Laisser vide en local
```

Dans Docker Compose, Redis reste sur le réseau interne et n'est pas publié sur l'hôte.

### Admin par défaut

```env
ADMIN_DEFAULT_PASSWORD=changez-moi-en-dev
```

### Domaine de base

```env
BASE_DOMAIN=labondemand.local
SECRET_KEY="une_super_cle_secrete_tres_longue_et_aleatoire_a_changer"
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

### Ingress (optionnel)

```env
INGRESS_ENABLED=true
INGRESS_BASE_DOMAIN=apps.labondemand.makhal
INGRESS_CLASS_NAME=nginx
INGRESS_TLS_SECRET=
INGRESS_DEFAULT_PATH=/
INGRESS_PATH_TYPE=Prefix
INGRESS_FORCE_TLS_REDIRECT=false
INGRESS_AUTO_TYPES=custom,jupyter,vscode,wordpress,mysql,lamp
INGRESS_EXCLUDED_TYPES=netbeans
```

### SSO / OIDC (optionnel)

```env
SSO_ENABLED=True
OIDC_ISSUER=https://sso.univ-pau.fr/cas/oidc
OIDC_CLIENT_ID=votre_client_id
OIDC_CLIENT_SECRET=votre_client_secret
OIDC_REDIRECT_URI=https://votre-app.fr/api/v1/auth/sso/callback
# OIDC_DISCOVERY_TTL_SECONDS=3600   # TTL du cache de découverte OIDC (défaut: 1h)
```

### Kubernetes

```env
CLUSTER_EXTERNAL_IP=           # IP externe du cluster pour les NodePorts
```

### TTL et nettoyage automatique

```env
LAB_TTL_STUDENT_DAYS=7         # Expiration des labs étudiants (défaut: 7 jours)
LAB_TTL_TEACHER_DAYS=30        # Expiration des labs enseignants (défaut: 30 jours)
LAB_GRACE_PERIOD_DAYS=3        # Délai avant suppression définitive après mise en pause
CLEANUP_INTERVAL_MINUTES=60    # Fréquence de la tâche de nettoyage (défaut: 60 min)
ORPHAN_NS_GRACE_DAYS=7         # Délai avant suppression d'un namespace orphelin
```

> Les labs admin n'expirent jamais (`expires_at = NULL`).
> Voir `documentation/lifecycle.md` pour les détails du TTL.

### Logging

```env
LOG_LEVEL=INFO
LOG_MAX_BYTES=5242880           # 5 Mo par fichier
LOG_BACKUP_COUNT=10             # 10 fichiers de rotation
AUDIT_LOG_MAX_BYTES=10485760   # 10 Mo par fichier d'audit
AUDIT_LOG_BACKUP_COUNT=30      # 30 fichiers de rotation d'audit
```

---

## Commandes Docker Compose utiles

```bash
# Voir les logs de l'API
docker compose logs -f api

# Voir les logs du frontend
docker compose logs -f frontend

# Ouvrir un shell dans le conteneur API
docker compose exec api bash

# Reconstruire uniquement le backend
docker compose build api

# Valider le build de production du frontend
docker compose build frontend

# Arrêter les conteneurs sans perdre les volumes
docker compose down
```

---

## Structure des logs

Les logs sont en JSON structuré avec rotation automatique.

```json
{
  "timestamp": "2026-01-01T12:00:00",
  "level": "INFO",
  "logger": "labondemand.deployment",
  "message": "deployment_created",
  "extra_fields": {
    "user_id": 1,
    "name": "my-lab",
    "type": "jupyter",
    "namespace": "labondemand-user-1"
  }
}
```

| Fichier | Contenu |
|---------|---------|
| `logs/app.log` | Logs applicatifs généraux |
| `logs/access.log` | Toutes les requêtes HTTP (méthode, path, status, durée, user_id) |
| `logs/audit.log` | Actions sensibles (login, création/suppression user, import CSV, quotas, devoirs) |

---

## Migrations

Les migrations SQL sont définies dans `backend/migrations.py`. Elles sont exécutées **automatiquement au démarrage** via `run_migrations()`. Chaque migration est idempotente (échoue silencieusement si la colonne/table existe déjà).

Pour ajouter une migration :

```python
# backend/migrations.py
MIGRATIONS: list[tuple[str, str]] = [
    # ... migrations existantes ...
    (
        "add_deployments_custom_field",
        "ALTER TABLE deployments ADD COLUMN custom_field VARCHAR(255) NULL",
    ),
]
```

La migration sera appliquée au prochain démarrage.

### Toutes les migrations actuelles

| Migration | Effet |
|-----------|-------|
| `add_templates_tags` | `templates.tags VARCHAR(255)` |
| `add_users_auth_provider` | `users.auth_provider VARCHAR(20) DEFAULT 'local'` |
| `add_users_external_id` | `users.external_id VARCHAR(255)` |
| `create_runtime_configs` | Table `runtime_configs` complète |
| `add_runtime_configs_allowed_for_students` | `runtime_configs.allowed_for_students BOOLEAN` |
| `add_users_role_override` | `users.role_override BOOLEAN DEFAULT FALSE` |
| `create_deployments` | Table `deployments` (TTL, historique) |
| `add_users_external_id_unique` | Contrainte UNIQUE sur `external_id` |
| `create_classrooms` | Table `classrooms` |
| `create_enrollments` | Table `enrollments` (UNIQUE classroom+user) |
| `create_assignments` | Table `assignments` |
| `create_assignment_deployments` | Table `assignment_deployments` |
| `create_user_quota_overrides` | Table `user_quota_overrides` (dérogations quotas) |
| `add_assignments_deliverables` | `assignments.deliverables TEXT NULL` |
| `create_assignment_submissions` | Table `assignment_submissions` |
| `add_assignments_grading_mode` | `assignments.grading_mode VARCHAR(20) DEFAULT 'none'` |
| `create_grading_specs` | Table `grading_specs` (correction automatique) |
| `create_grading_runs` | Table `grading_runs` (historique des corrections) |

---

## Tâche de fond (cleanup)

La tâche `backend/tasks/cleanup.py` est démarrée automatiquement lors du bootstrap de l'application. Elle :
- Expire et met en pause les labs dont `expires_at ≤ now()`
- Supprime les labs en pause après la période de grâce
- Supprime les namespaces Kubernetes orphelins

Pour vérifier son bon fonctionnement :

```bash
docker compose exec api grep cleanup_task_started /app/logs/app.log
docker compose exec api grep deployment_auto_paused_expired /app/logs/app.log
```

---

## Accès Kubernetes en développement

Le fichier `kubeconfig.yaml` à la racine du projet est monté en lecture seule dans le conteneur API :

```yaml
# compose.yaml — service api
volumes:
  - ./kubeconfig.yaml:/root/.kube/config:ro
```

L'application détecte automatiquement le kubeconfig via `config.load_kube_config()`. En production (in-cluster), utiliser `config.load_incluster_config()`.

> Le kubeconfig est un secret opérationnel. Ne le versionnez jamais.

---

## Lancer les tests

```bash
# Suite complète (recommandé — même environnement que la CI)
docker compose exec api python -m pytest backend/tests/ -q

# Un seul fichier
docker compose exec api python -m pytest backend/tests/test_classrooms.py -q

# Un seul test, avec affichage des logs
docker compose exec api python -m pytest backend/tests/test_auth.py::test_login_success -v -s

# Alternative hors Docker (nécessite un virtualenv configuré)
PYTHONPATH=. pytest backend/tests/ -q
```

Voir `documentation/testing.md` pour la configuration détaillée et la liste des fixtures.
