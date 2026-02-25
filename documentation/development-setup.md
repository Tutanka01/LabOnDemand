# Setup de développement

## Prérequis

- Docker + Docker Compose v2
- Un cluster Kubernetes accessible (kubeconfig valide)
- Python 3.11+ (pour l'exécution locale sans Docker)

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

## Variables d'environnement (.env)

```bash
# === API ===
DEBUG_MODE=false
LOG_LEVEL=INFO

# === Kubernetes ===
# Laisser vide pour utiliser le kubeconfig du pod (in-cluster)
# ou monter ~/.kube/config dans le conteneur (développement local)
CLUSTER_EXTERNAL_IP=192.168.1.100   # IP externe du cluster pour les NodePorts
USER_NAMESPACE_PREFIX=labondemand-user

# === Sessions ===
REDIS_URL=redis://redis:6379/0
SESSION_EXPIRY_HOURS=24
SECURE_COOKIES=false   # false en HTTP local, true en HTTPS production

# === Admin par défaut ===
ADMIN_DEFAULT_PASSWORD=ChangeMe123!

# === Ingress (optionnel) ===
INGRESS_ENABLED=false
INGRESS_BASE_DOMAIN=labs.example.com
INGRESS_CLASS_NAME=traefik
# INGRESS_TLS_SECRET=letsencrypt-prod

# === SSO / OIDC (optionnel) ===
SSO_ENABLED=false
# OIDC_ISSUER=https://sso.example.com/oidc
# OIDC_CLIENT_ID=labondemand
# OIDC_CLIENT_SECRET=secret
# OIDC_REDIRECT_URI=https://labs.example.com/api/v1/auth/sso/callback
# FRONTEND_BASE_URL=https://labs.example.com
```

## Exécution locale (sans Docker)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Exporter les variables d'environnement
export REDIS_URL=redis://localhost:6379/0
export ADMIN_DEFAULT_PASSWORD=ChangeMe123!

uvicorn main:app --reload --port 8000
```

Le frontend peut être servi directement avec n'importe quel serveur HTTP statique:

```bash
cd frontend
python -m http.server 3000
```

## Structure des logs

Les logs sont en JSON structuré. Exemple:

```json
{"timestamp": "2025-01-01T12:00:00", "level": "INFO", "logger": "labondemand.deployment",
 "message": "deployment_created", "extra_fields": {"user_id": 1, "name": "my-lab", "type": "jupyter"}}
```

Les fichiers de log sont écrits dans `logs/` (configurable via `LOG_DIR`).

## Migrations

Les migrations SQL sont définies dans `backend/migrations.py`. Elles sont
exécutées automatiquement au démarrage via `run_migrations()`. Chaque migration
est idempotente (échoue silencieusement si la colonne/table existe déjà).

Pour ajouter une migration:

```python
# backend/migrations.py
MIGRATIONS: list[tuple[str, str]] = [
    ...
    ("add_users_new_column", "ALTER TABLE users ADD COLUMN new_col VARCHAR(255) NULL"),
]
```

## Accès Kubernetes en développement

Monter le kubeconfig local dans le conteneur API:

```yaml
# compose.yaml — service api
volumes:
  - ~/.kube:/root/.kube:ro
```

L'application détecte automatiquement le kubeconfig via `config.load_kube_config()`.
En production (in-cluster), `config.load_incluster_config()` est utilisé.
