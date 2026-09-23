"""
Environnement Alembic de LabOnDemand.

Chargé par Alembic (pas importé comme module). Ne pas l'appeler directement :
passer par ``python -m backend.db_migrate`` (voir documentation/database-migrations.md).

- Moteur : celui de l'application (``backend.database.engine``, lu au moment de
  l'exécution) ou la connexion transmise par ``db_migrate`` via
  ``config.attributes["connection"]`` (déjà protégée par le verrou de schéma).
- Métadonnées : ``Base.metadata`` des modèles (``backend.models``).
"""

from alembic import context

from backend import database
from backend import models  # noqa: F401  (enregistre les tables dans Base.metadata)
from backend.db_migrate import include_object

config = context.config
target_metadata = database.Base.metadata


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        # Détecte aussi les changements de type (longueur de String, Enum…).
        compare_type=True,
        # Opérations « batch » systématiques : les révisions s'exécutent telles
        # quelles sur MariaDB (ALTER directs) ET sur SQLite (tests), qui ne sait
        # modifier une colonne qu'en recréant la table.
        render_as_batch=True,
        include_object=include_object,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """Génère le SQL sans se connecter (``db_migrate upgrade --sql``)."""
    _configure(
        dialect_name=database.engine.dialect.name,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        return

    with database.engine.connect() as connection:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
