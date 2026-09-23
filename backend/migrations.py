"""
Mise à niveau des bases « legacy » de LabOnDemand (antérieures à Alembic).

Avant Alembic, le schéma était créé par ``Base.metadata.create_all`` puis complété
à chaque démarrage par une liste de requêtes ALTER dont toutes les erreurs étaient
ignorées. Ce module amène une telle base à l'état exact des modèles actuels :

  1. ``create_all`` : crée uniquement les tables manquantes (jamais d'ALTER) ;
  2. ``LEGACY_MIGRATIONS`` : ajoute les colonnes apparues après la création des
     tables sur les anciennes installations ;
  3. index de ``users.external_id`` : converge vers l'index unique du modèle.

Seules les erreurs « objet déjà présent / déjà absent » sont ignorées : toute autre
erreur (verrou, doublons bloquant un index UNIQUE, faute de frappe…) est propagée.

Ne plus ajouter d'entrée ici : toute évolution du schéma passe par une révision
Alembic (voir documentation/database-migrations.md).
"""

import logging
import re

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from .database import Base
from . import models  # noqa: F401  (enregistre les tables dans Base.metadata)

logger = logging.getLogger("labondemand.migrations")

_MYSQL_DIALECTS = frozenset({"mysql", "mariadb"})

# Codes MariaDB/MySQL signifiant « déjà appliqué » : seuls ceux-ci sont ignorés.
_MYSQL_ALREADY_APPLIED_CODES = frozenset(
    {
        1050,  # ER_TABLE_EXISTS_ERROR : table déjà existante
        1060,  # ER_DUP_FIELDNAME : colonne déjà existante
        1061,  # ER_DUP_KEYNAME : index déjà existant
        1091,  # ER_CANT_DROP_FIELD_OR_KEY : colonne/index déjà supprimé
    }
)

# Équivalents SQLite (pas de code d'erreur : on filtre sur le message exact).
_SQLITE_ALREADY_APPLIED_PATTERNS = (
    re.compile(r"^duplicate column name: "),
    re.compile(r"^(table|index) \S+ already exists$"),
    re.compile(r"^no such index: "),
)

# Colonnes ajoutées aux modèles après la création des tables. Sur une base
# récente, create_all les a déjà créées : l'ALTER échoue en « colonne déjà
# existante », ce qui est attendu. Types et défauts identiques aux ALTER
# historiquement exécutés en production (ne pas les modifier).
LEGACY_MIGRATIONS: list[tuple[str, str]] = [
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
        "add_runtime_configs_allowed_for_students",
        "ALTER TABLE runtime_configs ADD COLUMN allowed_for_students BOOLEAN DEFAULT TRUE",
    ),
    (
        "add_users_role_override",
        "ALTER TABLE users ADD COLUMN role_override BOOLEAN NOT NULL DEFAULT FALSE",
    ),
    # MVP devoirs — énoncé "livrables attendus" sur les devoirs
    (
        "add_assignments_deliverables",
        "ALTER TABLE assignments ADD COLUMN deliverables TEXT NULL",
    ),
    # MVP-2 — grading_mode sur les devoirs (none|self_check|graded)
    (
        "add_assignments_grading_mode",
        "ALTER TABLE assignments ADD COLUMN grading_mode VARCHAR(20) NOT NULL DEFAULT 'none'",
    ),
]

# Index unique attendu par le modèle (User.external_id : unique=True, index=True).
_EXTERNAL_ID_INDEX = "ix_users_external_id"
# Doublon historique créé par l'ancienne migration add_users_external_id_unique.
_LEGACY_EXTERNAL_ID_INDEX = "idx_users_external_id_unique"


class LegacyMigrationError(RuntimeError):
    """Échec d'une étape de mise à niveau legacy (erreur réelle, non ignorable)."""


def is_already_applied_error(exc: DBAPIError, dialect_name: str) -> bool:
    """Indique si l'erreur signifie seulement que l'étape est déjà appliquée."""
    orig = getattr(exc, "orig", None)
    if dialect_name in _MYSQL_DIALECTS:
        args = getattr(orig, "args", ())
        code = args[0] if args and isinstance(args[0], int) else None
        return code in _MYSQL_ALREADY_APPLIED_CODES
    if dialect_name == "sqlite":
        message = str(orig) if orig is not None else ""
        return any(p.match(message) for p in _SQLITE_ALREADY_APPLIED_PATTERNS)
    return False


def _execute_step(connection: Connection, name: str, sql: str) -> bool:
    """Exécute une étape idempotente. Retourne False si elle était déjà appliquée."""
    try:
        connection.execute(text(sql))
        connection.commit()
    except DBAPIError as exc:
        connection.rollback()
        if is_already_applied_error(exc, connection.dialect.name):
            logger.debug(
                "legacy_migration_already_applied",
                extra={"extra_fields": {"migration": name}},
            )
            return False
        logger.error(
            "legacy_migration_failed",
            extra={"extra_fields": {"migration": name, "error": str(exc.orig)}},
        )
        raise LegacyMigrationError(
            f"Migration legacy '{name}' en échec : {exc.orig}"
        ) from exc
    logger.info(
        "legacy_migration_applied", extra={"extra_fields": {"migration": name}}
    )
    return True


def _drop_index(connection: Connection, table: str, name: str) -> None:
    quote = connection.dialect.identifier_preparer.quote
    if connection.dialect.name in _MYSQL_DIALECTS:
        sql = f"ALTER TABLE {quote(table)} DROP INDEX {quote(name)}"
    else:
        sql = f"DROP INDEX {quote(name)}"
    _execute_step(connection, f"drop_index_{name}", sql)


def _reconcile_users_external_id_index(connection: Connection) -> None:
    """Amène l'indexation de ``users.external_id`` à l'état du modèle.

    Selon la date de création de la table ``users``, une base legacy possède :
      - l'index unique ``idx_users_external_id_unique`` seul (colonne ajoutée par
        ALTER, donc sans l'index du modèle) ;
      - ``ix_users_external_id`` NON unique (modèle de février 2026) + le précédent ;
      - ``ix_users_external_id`` unique + le précédent, redondant.
    Cible : ``ix_users_external_id`` unique, sans doublon d'index.
    """
    indexes = {ix["name"]: ix for ix in inspect(connection).get_indexes("users")}
    current = indexes.get(_EXTERNAL_ID_INDEX)
    is_model_index = (
        current is not None
        and bool(current.get("unique"))
        and list(current.get("column_names") or []) == ["external_id"]
    )

    if not is_model_index:
        # Contrôle préalable : un index unique ne peut pas être créé sur des
        # doublons. On échoue avant de toucher au moindre index existant.
        duplicates = connection.execute(
            text(
                "SELECT COUNT(*) FROM (SELECT external_id FROM users "
                "WHERE external_id IS NOT NULL GROUP BY external_id "
                "HAVING COUNT(*) > 1) AS dup"
            )
        ).scalar()
        connection.commit()
        if duplicates:
            raise LegacyMigrationError(
                f"{duplicates} valeur(s) de users.external_id sont partagées par "
                "plusieurs comptes : impossible de créer l'index unique "
                f"{_EXTERNAL_ID_INDEX}. Dédoublonnez ces comptes SSO (SELECT "
                "external_id, COUNT(*) FROM users WHERE external_id IS NOT NULL "
                "GROUP BY external_id HAVING COUNT(*) > 1) puis redémarrez."
            )
        if current is not None:
            _drop_index(connection, "users", _EXTERNAL_ID_INDEX)
        model_index = next(
            ix
            for ix in Base.metadata.tables["users"].indexes
            if ix.name == _EXTERNAL_ID_INDEX
        )
        model_index.create(connection)
        connection.commit()
        logger.info(
            "legacy_migration_applied",
            extra={"extra_fields": {"migration": f"create_index_{_EXTERNAL_ID_INDEX}"}},
        )

    if _LEGACY_EXTERNAL_ID_INDEX in indexes:
        # Redondant avec l'index unique du modèle, désormais garanti ci-dessus.
        _drop_index(connection, "users", _LEGACY_EXTERNAL_ID_INDEX)


def apply_legacy_migrations(connection: Connection) -> None:
    """Amène une base legacy à l'état des modèles. Idempotent.

    Toute erreur autre que « déjà appliqué » lève ``LegacyMigrationError``.
    """
    # 1. Tables manquantes (checkfirst : les tables existantes ne sont pas touchées)
    Base.metadata.create_all(bind=connection)
    connection.commit()
    # 2. Colonnes ajoutées après coup
    for name, sql in LEGACY_MIGRATIONS:
        _execute_step(connection, name, sql)
    # 3. Index de users.external_id
    _reconcile_users_external_id_index(connection)
