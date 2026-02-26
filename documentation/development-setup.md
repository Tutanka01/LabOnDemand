---
title: Setup de développement
summary: Procédure pour lancer LabOnDemand en local via Docker Compose ou Python natif, configuration des variables d'environnement et accès aux services.
read_when: |
  - Tu installes le projet pour la première fois sur ta machine de dev
  - Tu veux lancer l'API ou le frontend en dehors de Docker
  - Tu cherches quelles variables d'environnement configurer dans .env
---

# Setup de développement

## Prérequis

- Docker + Docker Compose v2
- Un cluster Kubernetes accessible (kubeconfig valide : k3s, kind, Minikube ou cluster distant)
- Python 3.11+ (pour l'exécution locale sans Docker)

---

## Démarrage rapide avec Docker Compose

```bash
# Cloner le dépôt
git clone <repo>
cd LabOnDemand

# Copier et adapter la configuration
cp .env.example .env    # ou créer .env manuellement (voir ci-dessous)

# Lancer l'application
docker compose up --build

# L'API est disponible sur http://localhost:8000
# Le frontend est disponible sur http://localhost:80
```

Attendre que FastAPI affiche `Application startup complete` dans les logs.
Un compte `admin` est automatiquement créé avec le mot de passe défini par
`ADMIN_DEFAULT_PASSWORD`.

---

## Variables d'environnement (.env)

### API

```env
DEBUG_MODE=false
LOG_LEVEL=INFO
```

> `DEBUG_MODE=true` active Swagger UI (`/docs`) et l'endpoint de diagnostic.
> **Ne jamais utiliser en production.**

### Base de données

```env
DB_URL=mysql+pymysql://labondemand:password@db/labondemand
DB_PASSWORD=password
DB_ROOT_PASSWORD=rootpassword
```

### Kubernetes

```env
CLUSTER_EXTERNAL_IP=192.168.1.100    # IP externe du cluster pour les NodePorts
USER_NAMESPACE_PREFIX=labondemand-user
```

### Sessions Redis

```env
REDIS_URL=redis://redis:6379/0
SESSION_EXPIRY_HOURS=24
SECURE_COOKIES=false      # false en HTTP local, true en HTTPS production
SESSION_SAMESITE=Strict
COOKIE_DOMAIN=            # Laisser vide en local
```

### Admin par défaut

```env
ADMIN_DEFAULT_PASSWORD=ChangeMe123!
```

### Ingress (optionnel)

```env
INGRESS_ENABLED=false
INGRESS_BASE_DOMAIN=labs.example.com
INGRESS_CLASS_NAME=traefik
# INGRESS_TLS_SECRET=letsencrypt-prod
```

### SSO / OIDC (optionnel)

```env
SSO_ENABLED=false
# OIDC_ISSUER=https://sso.example.com/oidc
# OIDC_CLIENT_ID=labondemand
# OIDC_CLIENT_SECRET=secret
# OIDC_REDIRECT_URI=https://labs.example.com/api/v1/auth/sso/callback
# FRONTEND_BASE_URL=https://labs.example.com
# OIDC_DISCOVERY_TTL_SECONDS=3600   # TTL du cache de découverte OIDC (défaut: 1h)
```

### TTL et nettoyage automatique

```env
LAB_TTL_STUDENT_DAYS=7        # Expiration des labs étudiants en jours (défaut: 7)
LAB_TTL_TEACHER_DAYS=30       # Expiration des labs enseignants en jours (défaut: 30)
CLEANUP_INTERVAL_MINUTES=60   # Fréquence de la tâche de nettoyage (défaut: 60 min)
```

> Les labs admin n'expirent jamais (`expires_at = NULL`).
> Voir `documentation/lifecycle.md` pour les détails du TTL.

---

## Exécution locale (sans Docker)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r ../requirements.txt

# Variables d'environnement minimales
export REDIS_URL=redis://localhost:6379/0
export ADMIN_DEFAULT_PASSWORD=ChangeMe123!
export DB_URL=mysql+pymysql://labondemand:password@localhost/labondemand

uvicorn main:app --reload --port 8000
```

Le frontend peut être servi avec n'importe quel serveur HTTP statique :

```bash
cd frontend
python -m http.server 3000
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
| `logs/audit.log` | Actions sensibles (login, création/suppression user, import CSV, quotas) |

Variables de configuration :

```env
LOG_DIR=./logs
LOG_MAX_BYTES=5242880    # 5 Mo par fichier
LOG_BACKUP_COUNT=10      # 10 fichiers de rotation
LOG_ENABLE_CONSOLE=True  # Aussi en sortie console (utile en dev)
```

---

## Migrations

Les migrations SQL sont définies dans `backend/migrations.py`. Elles sont
exécutées **automatiquement au démarrage** via `run_migrations()`. Chaque
migration est idempotente (échoue silencieusement si la colonne/table existe déjà).

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

### Tables gérées par migrations

| Migration | Table/Colonne |
|-----------|---------------|
| `add_templates_tags` | `templates.tags` |
| `add_users_auth_provider` | `users.auth_provider` |
| `add_users_external_id` | `users.external_id` |
| `create_runtime_configs` | Table `runtime_configs` |
| `add_users_role_override` | `users.role_override` |
| `create_deployments` | Table `deployments` (TTL, historique) |
| `create_user_quota_overrides` | Table `user_quota_overrides` (dérogations quotas) |

---

## Tâche de fond (cleanup)

La tâche `backend/tasks/cleanup.py` est démarrée automatiquement lors du
bootstrap de l'application. Elle :
- Expire et met en pause les labs dont `expires_at ≤ now()`
- Supprime les namespaces Kubernetes orphelins

Elle ne nécessite pas de service externe. Pour vérifier son bon fonctionnement :

```bash
grep cleanup_task_started logs/app.log
grep deployment_auto_paused_expired logs/app.log
```

---

## Accès Kubernetes en développement

Monter le kubeconfig local dans le conteneur API :

```yaml
# compose.yaml — service api
volumes:
  - ~/.kube:/root/.kube:ro
```

L'application détecte automatiquement le kubeconfig via `config.load_kube_config()`.
En production (in-cluster), utiliser `config.load_incluster_config()`.

---

## Lancer les tests

```bash
# Depuis la racine du projet
python backend/tests/run_tests.py --all       # tous les tests
python backend/tests/run_tests.py --backend   # tests FastAPI uniquement
python backend/tests/run_tests.py --ui        # Selenium (front)
```

Voir `documentation/testing.md` pour la configuration détaillée.
