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
    # Contrainte UNIQUE sur external_id pour empêcher les doublons SSO
    # (idempotente : MySQL ignore silencieusement si la contrainte existe déjà)
    (
        "add_users_external_id_unique",
        "ALTER TABLE users ADD UNIQUE INDEX idx_users_external_id_unique (external_id)",
    ),
    # Classroom system (P0)
    (
        "create_classrooms",
        "CREATE TABLE IF NOT EXISTS classrooms ("
        "id INTEGER PRIMARY KEY AUTO_INCREMENT,"
        "name VARCHAR(100) NOT NULL,"
        "description VARCHAR(500) NULL,"
        "owner_id INTEGER NOT NULL,"
        "archived BOOLEAN NOT NULL DEFAULT FALSE,"
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "updated_at DATETIME NULL,"
        "INDEX idx_cl_owner (owner_id),"
        "INDEX idx_cl_archived (archived),"
        "INDEX idx_cl_name (name),"
        "CONSTRAINT fk_cl_owner FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE"
        ")",
    ),
    (
        "create_enrollments",
        "CREATE TABLE IF NOT EXISTS enrollments ("
        "id INTEGER PRIMARY KEY AUTO_INCREMENT,"
        "classroom_id INTEGER NOT NULL,"
        "user_id INTEGER NOT NULL,"
        "enrolled_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "removed_at DATETIME NULL,"
        "INDEX idx_enr_classroom (classroom_id),"
        "INDEX idx_enr_user (user_id),"
        "UNIQUE KEY uq_enrollment_classroom_user (classroom_id, user_id),"
        "CONSTRAINT fk_enr_classroom FOREIGN KEY (classroom_id) REFERENCES classrooms(id) ON DELETE CASCADE,"
        "CONSTRAINT fk_enr_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
        ")",
    ),
    (
        "create_assignments",
        "CREATE TABLE IF NOT EXISTS assignments ("
        "id INTEGER PRIMARY KEY AUTO_INCREMENT,"
        "classroom_id INTEGER NOT NULL,"
        "title VARCHAR(200) NOT NULL,"
        "instructions TEXT NULL,"
        "template_key VARCHAR(50) NULL,"
        "cpu_preset VARCHAR(20) NULL,"
        "ram_preset VARCHAR(20) NULL,"
        "due_at DATETIME NULL,"
        "status VARCHAR(20) NOT NULL DEFAULT 'active',"
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "updated_at DATETIME NULL,"
        "INDEX idx_asgn_classroom (classroom_id),"
        "CONSTRAINT fk_asgn_classroom FOREIGN KEY (classroom_id) REFERENCES classrooms(id) ON DELETE CASCADE"
        ")",
    ),
    (
        "create_assignment_deployments",
        "CREATE TABLE IF NOT EXISTS assignment_deployments ("
        "id INTEGER PRIMARY KEY AUTO_INCREMENT,"
        "assignment_id INTEGER NOT NULL,"
        "user_id INTEGER NOT NULL,"
        "deployment_id INTEGER NULL,"
        "spawn_status VARCHAR(20) NOT NULL,"
        "spawn_error VARCHAR(500) NULL,"
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "INDEX idx_ad_assignment (assignment_id),"
        "INDEX idx_ad_user (user_id),"
        "INDEX idx_ad_deployment (deployment_id),"
        "CONSTRAINT fk_ad_assignment FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE,"
        "CONSTRAINT fk_ad_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,"
        "CONSTRAINT fk_ad_deployment FOREIGN KEY (deployment_id) REFERENCES deployments(id) ON DELETE SET NULL"
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
    # MVP devoirs — énoncé "livrables attendus" sur les devoirs
    (
        "add_assignments_deliverables",
        "ALTER TABLE assignments ADD COLUMN deliverables TEXT NULL",
    ),
    # MVP devoirs — table des soumissions étudiantes
    (
        "create_assignment_submissions",
        "CREATE TABLE IF NOT EXISTS assignment_submissions ("
        "id INTEGER PRIMARY KEY AUTO_INCREMENT,"
        "assignment_id INTEGER NOT NULL,"
        "user_id INTEGER NOT NULL,"
        "attempt_no INTEGER NOT NULL DEFAULT 1,"
        "status VARCHAR(20) NOT NULL DEFAULT 'submitted',"
        "text TEXT NULL,"
        "links TEXT NULL,"
        "deployment_id INTEGER NULL,"
        "lab_snapshot TEXT NULL,"
        "submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "is_late BOOLEAN NOT NULL DEFAULT FALSE,"
        "due_at_snapshot DATETIME NULL,"
        "grade VARCHAR(20) NULL,"
        "feedback TEXT NULL,"
        "graded_by INTEGER NULL,"
        "graded_at DATETIME NULL,"
        "updated_at DATETIME NULL,"
        "CONSTRAINT uq_submission_assignment_user UNIQUE (assignment_id, user_id),"
        "INDEX idx_sub_assignment (assignment_id),"
        "INDEX idx_sub_user (user_id),"
        "INDEX idx_sub_deployment (deployment_id),"
        "CONSTRAINT fk_sub_assignment FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE,"
        "CONSTRAINT fk_sub_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,"
        "CONSTRAINT fk_sub_deployment FOREIGN KEY (deployment_id) REFERENCES deployments(id) ON DELETE SET NULL"
        ")",
    ),
    # MVP-2 — grading_mode sur les devoirs (none|self_check|graded)
    (
        "add_assignments_grading_mode",
        "ALTER TABLE assignments ADD COLUMN grading_mode VARCHAR(20) NOT NULL DEFAULT 'none'",
    ),
    # MVP-2 — batterie de tests (probes) d'un devoir
    (
        "create_grading_specs",
        "CREATE TABLE IF NOT EXISTS grading_specs ("
        "id INTEGER PRIMARY KEY AUTO_INCREMENT,"
        "assignment_id INTEGER NOT NULL UNIQUE,"
        "grader_image VARCHAR(300) NULL,"
        "timeout_seconds INTEGER NOT NULL DEFAULT 120,"
        "checks TEXT NULL,"
        "custom_script TEXT NULL,"
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "updated_at DATETIME NULL,"
        "INDEX idx_gs_assignment (assignment_id),"
        "CONSTRAINT fk_gs_assignment FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE"
        ")",
    ),
    # MVP-2 — exécutions du Grader Pod
    (
        "create_grading_runs",
        "CREATE TABLE IF NOT EXISTS grading_runs ("
        "id INTEGER PRIMARY KEY AUTO_INCREMENT,"
        "assignment_id INTEGER NOT NULL,"
        "user_id INTEGER NOT NULL,"
        "submission_id INTEGER NULL,"
        "deployment_id INTEGER NULL,"
        "trigger VARCHAR(20) NOT NULL,"
        "status VARCHAR(20) NOT NULL DEFAULT 'queued',"
        "started_at DATETIME NULL,"
        "finished_at DATETIME NULL,"
        "total_checks INTEGER NULL,"
        "passed_checks INTEGER NULL,"
        "score_suggestion VARCHAR(20) NULL,"
        "results TEXT NULL,"
        "error VARCHAR(500) NULL,"
        "result_token_hash VARCHAR(64) NULL,"
        "token_used_at DATETIME NULL,"
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "INDEX idx_gr_assignment (assignment_id),"
        "INDEX idx_gr_user (user_id),"
        "INDEX idx_gr_submission (submission_id),"
        "INDEX idx_gr_status (status),"
        "CONSTRAINT fk_gr_assignment FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE,"
        "CONSTRAINT fk_gr_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,"
        "CONSTRAINT fk_gr_submission FOREIGN KEY (submission_id) REFERENCES assignment_submissions(id) ON DELETE SET NULL,"
        "CONSTRAINT fk_gr_deployment FOREIGN KEY (deployment_id) REFERENCES deployments(id) ON DELETE SET NULL"
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
