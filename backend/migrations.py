"""
Migrations SQL souples pour LabOnDemand.
Chaque migration est idempotente (ALTER/CREATE IF NOT EXISTS) et exécutée avec
rollback propre en cas d'échec.
"""
import logging
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("labondemand.migrations")

# Liste ordonnée de migrations. Chaque entrée est un tuple (nom, requête SQL).
# Les ALTER TABLE échouent silencieusement si la colonne existe déjà (MySQL/MariaDB).
MIGRATIONS: list[tuple[str, str]] = [
    (
        "add_templates_tags",
        "ALTER TABLE templates ADD COLUMN tags VARCHAR(255) NULL",
    ),
    (
        "add_users_auth_provider",
        "ALTER TABLE users ADD COLUMN auth_provider VARCHAR(20) NOT NULL DEFAULT 'local'",
    ),
    (
        "add_users_external_id",
        "ALTER TABLE users ADD COLUMN external_id VARCHAR(255) NULL",
    ),
    (
        "create_runtime_configs",
        "CREATE TABLE IF NOT EXISTS runtime_configs ("
        "id INTEGER PRIMARY KEY AUTO_INCREMENT,"
        "key VARCHAR(50) UNIQUE NOT NULL,"
        "default_image VARCHAR(200),"
        "target_port INTEGER,"
        "default_service_type VARCHAR(30) NOT NULL DEFAULT 'NodePort',"
        "allowed_for_students BOOLEAN DEFAULT TRUE,"
        "min_cpu_request VARCHAR(20),"
        "min_memory_request VARCHAR(20),"
        "min_cpu_limit VARCHAR(20),"
        "min_memory_limit VARCHAR(20),"
        "active BOOLEAN DEFAULT TRUE,"
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "updated_at DATETIME NULL"
        ")",
    ),
    (
        "add_runtime_configs_allowed_for_students",
        "ALTER TABLE runtime_configs ADD COLUMN allowed_for_students BOOLEAN DEFAULT TRUE",
    ),
    (
        "add_users_role_override",
        "ALTER TABLE users ADD COLUMN role_override BOOLEAN NOT NULL DEFAULT FALSE",
    ),
    # IMP-1 — table de suivi des déploiements
    (
        "create_deployments",
        "CREATE TABLE IF NOT EXISTS deployments ("
        "id INTEGER PRIMARY KEY AUTO_INCREMENT,"
        "user_id INTEGER NOT NULL,"
        "name VARCHAR(100) NOT NULL,"
        "deployment_type VARCHAR(50) NOT NULL DEFAULT 'custom',"
        "namespace VARCHAR(100) NOT NULL,"
        "stack_name VARCHAR(100) NULL,"
        "status VARCHAR(30) NOT NULL DEFAULT 'active',"
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "deleted_at DATETIME NULL,"
        "last_seen_at DATETIME NULL,"
        "expires_at DATETIME NULL,"
        "cpu_requested VARCHAR(20) NULL,"
        "mem_requested VARCHAR(20) NULL,"
        "INDEX idx_dep_user (user_id),"
        "INDEX idx_dep_status (status),"
        "INDEX idx_dep_expires (expires_at),"
        "CONSTRAINT fk_dep_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
        ")",
    ),
    # IMP-3 — dérogations de quota par utilisateur
    (
        "create_user_quota_overrides",
        "CREATE TABLE IF NOT EXISTS user_quota_overrides ("
        "id INTEGER PRIMARY KEY AUTO_INCREMENT,"
        "user_id INTEGER NOT NULL UNIQUE,"
        "max_apps INTEGER NULL,"
        "max_cpu_m INTEGER NULL,"
        "max_mem_mi INTEGER NULL,"
        "max_storage_gi INTEGER NULL,"
        "expires_at DATETIME NULL,"
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "updated_at DATETIME NULL,"
        "created_by INTEGER NULL,"
        "INDEX idx_qo_user (user_id),"
        "CONSTRAINT fk_qo_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
        ")",
    ),
]


def run_migrations(db: Session) -> None:
    """Exécute toutes les migrations de manière idempotente."""
    for name, sql in MIGRATIONS:
        try:
            db.execute(text(sql))
            db.commit()
            logger.debug("Migration '%s' applied (or already present)", name)
        except Exception:
            db.rollback()
            logger.debug("Migration '%s' skipped (already applied)", name)
