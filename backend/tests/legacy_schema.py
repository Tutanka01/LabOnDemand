"""
Fabrique de bases « legacy » (créées avant Alembic) pour les tests de migration.

Reproduit les états réellement rencontrés en production, d'après l'historique git
de backend/models.py et backend/migrations.py :

- ``latest``   : dernière version pré-Alembic (create_all + ALTER legacy), avec
                 l'index doublon ``idx_users_external_id_unique`` créé sur MariaDB
                 par l'ancienne migration ``add_users_external_id_unique`` ;
- ``sso_2026`` : table ``users`` créée entre b8f2f3a et bd840b5, quand
                 ``ix_users_external_id`` n'était pas encore unique ;
- ``oct_2025`` : installation d'octobre 2025 (8727411) : ni SSO, ni classes, ni
                 devoirs, avec la table ``labs`` abandonnée depuis mai 2025 ;
- ``pre_alter``: tables actuelles privées des 7 colonnes ajoutées par la liste
                 ALTER legacy : chaque ALTER s'exécute réellement.

Fonctionne sur SQLite et MariaDB (DDL générée par SQLAlchemy).
``schema_snapshot`` décrit un schéma réel pour comparer deux bases.
"""

import enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
    inspect,
    text,
)
from sqlalchemy.engine import Connection

from backend.database import Base

LEGACY_VARIANTS = ("latest", "sso_2026", "oct_2025", "pre_alter")

# Colonnes ajoutées par backend/migrations.py:LEGACY_MIGRATIONS.
_ALTER_ADDED_COLUMNS = (
    ("templates", "tags"),
    ("users", "auth_provider"),
    ("users", "external_id"),
    ("runtime_configs", "allowed_for_students"),
    ("users", "role_override"),
    ("assignments", "deliverables"),
    ("assignments", "grading_mode"),
)


class _Role(enum.Enum):
    student = "student"
    teacher = "teacher"
    admin = "admin"


def _oct_2025_metadata() -> MetaData:
    """Modèles tels qu'au commit 8727411 (+ table labs de mai 2025)."""
    md = MetaData()
    Table(
        "users",
        md,
        Column("id", Integer, primary_key=True, index=True),
        Column("username", String(50), unique=True, index=True, nullable=False),
        Column("email", String(100), unique=True, index=True, nullable=False),
        Column("full_name", String(100), nullable=True),
        Column("hashed_password", String(255), nullable=False),
        Column("role", Enum(_Role, name="userrole"), nullable=False),
        Column("is_active", Boolean),
        Column("created_at", DateTime(timezone=True), server_default=func.now()),
        Column("updated_at", DateTime(timezone=True)),
    )
    Table(
        "labs",
        md,
        Column("id", Integer, primary_key=True, index=True),
        Column("name", String(100), index=True),
        Column("description", Text, nullable=True),
        Column("lab_type", String(50)),
        Column("k8s_namespace", String(100)),
        Column("deployment_name", String(100)),
        Column("service_name", String(100)),
        Column("created_at", DateTime(timezone=True), server_default=func.now()),
        Column("updated_at", DateTime(timezone=True)),
        Column("owner_id", Integer, ForeignKey("users.id")),
    )
    Table(
        "templates",
        md,
        Column("id", Integer, primary_key=True, index=True),
        Column("key", String(50), unique=True, index=True, nullable=False),
        Column("name", String(100), nullable=False),
        Column("description", String(255), nullable=True),
        Column("icon", String(100), nullable=True),
        Column("deployment_type", String(30), nullable=False),
        Column("default_image", String(200), nullable=True),
        Column("default_port", Integer, nullable=True),
        Column("default_service_type", String(30), nullable=False),
        Column("tags", String(255), nullable=True),
        Column("active", Boolean),
        Column("created_at", DateTime(timezone=True), server_default=func.now()),
        Column("updated_at", DateTime(timezone=True)),
    )
    Table(
        "runtime_configs",
        md,
        Column("id", Integer, primary_key=True, index=True),
        Column("key", String(50), unique=True, index=True, nullable=False),
        Column("default_image", String(200), nullable=True),
        Column("target_port", Integer, nullable=True),
        Column("default_service_type", String(30), nullable=False),
        Column("allowed_for_students", Boolean),
        Column("min_cpu_request", String(20), nullable=True),
        Column("min_memory_request", String(20), nullable=True),
        Column("min_cpu_limit", String(20), nullable=True),
        Column("min_memory_limit", String(20), nullable=True),
        Column("active", Boolean),
        Column("created_at", DateTime(timezone=True), server_default=func.now()),
        Column("updated_at", DateTime(timezone=True)),
    )
    return md


def _drop_index_sql(connection: Connection, name: str) -> str:
    if connection.dialect.name == "sqlite":
        return f"DROP INDEX {name}"
    return f"ALTER TABLE users DROP INDEX {name}"


def build_legacy_database(connection: Connection, variant: str) -> None:
    """Crée sur ``connection`` (base vide) le schéma legacy ``variant``, sans alembic_version."""
    if variant == "oct_2025":
        _oct_2025_metadata().create_all(bind=connection)
    elif variant in ("latest", "sso_2026"):
        Base.metadata.create_all(bind=connection)
        if variant == "sso_2026":
            connection.execute(text(_drop_index_sql(connection, "ix_users_external_id")))
            connection.execute(
                text("CREATE INDEX ix_users_external_id ON users (external_id)")
            )
        # Équivalent portable de l'ancienne migration MySQL
        # « ALTER TABLE users ADD UNIQUE INDEX idx_users_external_id_unique ».
        connection.execute(
            text(
                "CREATE UNIQUE INDEX idx_users_external_id_unique "
                "ON users (external_id)"
            )
        )
    elif variant == "pre_alter":
        Base.metadata.create_all(bind=connection)
        # SQLite refuse de supprimer une colonne indexée : l'index d'abord.
        connection.execute(text(_drop_index_sql(connection, "ix_users_external_id")))
        for table, column in _ALTER_ADDED_COLUMNS:
            connection.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
    else:
        raise ValueError(f"variante legacy inconnue : {variant}")
    connection.commit()


def insert_legacy_rows(connection: Connection) -> None:
    """Insère deux comptes et un template, comme l'ORM de chaque époque l'aurait fait."""
    user_columns = {c["name"] for c in inspect(connection).get_columns("users")}
    extra_cols, extra_vals = "", ""
    if "auth_provider" in user_columns:
        # NOT NULL sans défaut SQL quand create_all a créé la colonne : l'ORM la renseignait.
        extra_cols, extra_vals = ", auth_provider, role_override", ", 'local', 0"
    for username, email, role in (
        ("legacy_student", "legacy@test.lab", "student"),
        ("legacy_admin", "legacy-admin@test.lab", "admin"),
    ):
        connection.execute(
            text(
                "INSERT INTO users (username, email, hashed_password, role, is_active"
                f"{extra_cols}) VALUES (:username, :email, 'x', :role, 1{extra_vals})"
            ),
            {"username": username, "email": email, "role": role},
        )
    connection.execute(
        text(
            "INSERT INTO templates (`key`, name, deployment_type, default_service_type, active) "
            "VALUES ('legacy-tpl', 'Legacy', 'custom', 'NodePort', 1)"
        )
    )
    connection.commit()


def schema_snapshot(connection: Connection) -> dict:
    """Description comparable du schéma réel (hors alembic_version).

    Sert à vérifier que la baseline Alembic produit exactement le même schéma
    que ``Base.metadata.create_all``. Les noms de clés étrangères sont ignorés
    (générés par le serveur sur MariaDB), leur structure et ON DELETE non.
    """
    insp = inspect(connection)
    snapshot: dict = {}
    for table in sorted(insp.get_table_names()):
        if table == "alembic_version":
            continue
        snapshot[table] = {
            "columns": [
                (
                    col["name"],
                    str(col["type"]),
                    col["nullable"],
                    str(col.get("default")),
                    col.get("autoincrement"),
                )
                for col in insp.get_columns(table)
            ],
            "pk": insp.get_pk_constraint(table)["constrained_columns"],
            "indexes": sorted(
                (ix["name"], tuple(ix["column_names"]), bool(ix["unique"]))
                for ix in insp.get_indexes(table)
            ),
            "uniques": sorted(
                (uc["name"], tuple(uc["column_names"]))
                for uc in insp.get_unique_constraints(table)
            ),
            "fks": sorted(
                (
                    tuple(fk["constrained_columns"]),
                    fk["referred_table"],
                    tuple(fk["referred_columns"]),
                    (fk.get("options") or {}).get("ondelete"),
                )
                for fk in insp.get_foreign_keys(table)
            ),
        }
    if connection.in_transaction():
        connection.commit()
    return snapshot
