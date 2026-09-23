"""
Migrations versionnées du schéma de base de données (Alembic).

Au démarrage de l'API, ``upgrade_schema()`` (appelé par ``main.bootstrap``) :
  1. sérialise les démarrages concurrents (workers, réplicas) par un verrou
     ``GET_LOCK`` sur MariaDB/MySQL ;
  2. selon l'état de la base :
       - base vierge                    → ``alembic upgrade head`` ;
       - base legacy (tables présentes, aucune révision Alembic : toute
         installation antérieure à Alembic) → mise à niveau legacy
         (``migrations.py``), vérification, ``stamp`` de la baseline, puis
         ``upgrade head`` ;
       - base versionnée                → ``alembic upgrade head`` ;
  3. vérifie que la base est bien à la révision head.
Toute erreur est remontée : l'API ne démarre pas sur un schéma incertain.

En ligne de commande (conteneur api) :

    python -m backend.db_migrate upgrade           # comme au démarrage
    python -m backend.db_migrate upgrade --sql     # affiche le SQL sans l'exécuter
    python -m backend.db_migrate current           # état de la base
    python -m backend.db_migrate check             # modèles == révisions ?
    python -m backend.db_migrate revision --autogenerate -m "add foo"
    python -m backend.db_migrate history | heads | stamp REV | downgrade REV
"""

import argparse
import logging
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from . import database
from . import models  # noqa: F401  (enregistre les tables dans Base.metadata)
from .migrations import LegacyMigrationError, apply_legacy_migrations

logger = logging.getLogger("labondemand.db_migrate")

ALEMBIC_DIR = Path(__file__).resolve().parent / "alembic"
# Révision décrivant le schéma complet au moment de l'introduction d'Alembic.
BASELINE_REVISION = "0001_baseline"
SCHEMA_LOCK_PREFIX = "labondemand_schema"
DEFAULT_LOCK_TIMEOUT_SECONDS = 300
LOCK_TIMEOUT_ENV = "DB_SCHEMA_LOCK_TIMEOUT"

_MYSQL_DIALECTS = frozenset({"mysql", "mariadb"})
_VERSION_TABLE = "alembic_version"
# Différences bloquantes après une mise à niveau legacy : il manque des tables
# ou colonnes, l'application ne peut pas fonctionner et « stamper » la baseline
# mentirait sur l'état réel de la base. Les autres écarts sont journalisés.
_BLOCKING_LEGACY_DIFFS = frozenset({"add_table", "add_column"})


class SchemaMigrationError(RuntimeError):
    """Le schéma n'a pas pu être amené à la révision attendue (fatal au démarrage)."""


class SchemaLockTimeout(SchemaMigrationError):
    """Le verrou de schéma n'a pas été obtenu dans le délai imparti."""


# ============= CONFIGURATION ALEMBIC =============


def include_object(obj: Any, name: str, type_: str, reflected: bool, compare_to: Any) -> bool:
    """Ignore les tables présentes en base mais inconnues des modèles.

    Une base legacy peut contenir des tables abandonnées (ex. ``labs``, 2025) :
    l'autogénération ne doit jamais proposer de les supprimer. Une suppression
    de table reste possible, mais écrite à la main dans une révision.
    """
    return not (type_ == "table" and reflected and compare_to is None)


def get_alembic_config(connection: Connection | None = None) -> Config:
    """Configuration Alembic programmatique (pas d'alembic.ini : l'image ne
    contient que backend/). La connexion fournie est réutilisée par env.py."""
    # stdout lu à l'appel (et non à l'import d'Alembic) : sortie redirigeable.
    config = Config(stdout=sys.stdout)
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    config.set_main_option("path_separator", "os")
    # Fichiers de révision triés par date : 20260923_<rev>_<slug>.py
    config.set_main_option(
        "file_template", "%%(year)d%%(month).2d%%(day).2d_%%(rev)s_%%(slug)s"
    )
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def get_head_revision() -> str:
    """Révision head du code. Plusieurs têtes = révisions à fusionner (erreur)."""
    heads = ScriptDirectory.from_config(get_alembic_config()).get_heads()
    if len(heads) != 1:
        raise SchemaMigrationError(
            f"Les révisions Alembic doivent avoir une seule tête, trouvé : {heads}. "
            "Fusionnez-les avec une révision de merge."
        )
    return heads[0]


def _end_transaction(connection: Connection) -> None:
    """Termine la transaction implicite (autobegin) ouverte par une lecture."""
    if connection.in_transaction():
        connection.commit()


def get_current_revision(connection: Connection) -> str | None:
    """Révision enregistrée dans alembic_version (None si absente ou vide)."""
    current = MigrationContext.configure(connection).get_current_revision()
    _end_transaction(connection)
    return current


def _run_alembic(connection: Connection, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Exécute une commande Alembic sur ``connection`` (hors transaction, pour
    qu'Alembic gère lui-même ses transactions et valide la table de version)."""
    _end_transaction(connection)
    fn(get_alembic_config(connection), *args, **kwargs)
    _end_transaction(connection)


# ============= VERROU DE SCHÉMA =============


def _lock_timeout_from_env() -> int:
    raw = os.getenv(LOCK_TIMEOUT_ENV, str(DEFAULT_LOCK_TIMEOUT_SECONDS))
    try:
        value = int(raw)
    except ValueError:
        value = -1
    if value < 0:
        raise SchemaMigrationError(
            f"{LOCK_TIMEOUT_ENV} invalide : {raw!r} (entier positif en secondes attendu)"
        )
    return value


def schema_lock_name(connection: Connection) -> str:
    """Nom du verrou. GET_LOCK est global au serveur : le nom de la base en fait
    partie pour que deux instances partageant un serveur ne se bloquent pas."""
    return f"{SCHEMA_LOCK_PREFIX}:{connection.engine.url.database or ''}"[:64]


def _release_schema_lock(connection: Connection, name: str) -> None:
    try:
        if connection.in_transaction():
            connection.rollback()
        connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": name})
        _end_transaction(connection)
    except Exception as exc:
        # Fermer la connexion physique libère le verrou côté serveur : surtout
        # ne pas la rendre au pool en détenant encore le verrou.
        logger.exception(
            "schema_lock_release_failed",
            extra={"extra_fields": {"lock": name, "error": str(exc)}},
        )
        connection.invalidate()


@contextmanager
def schema_lock(connection: Connection, timeout: int) -> Iterator[None]:
    """Verrou exclusif des opérations de schéma, tenu par ``connection``.

    MariaDB/MySQL : ``GET_LOCK`` (libéré par ``RELEASE_LOCK`` ou à la fermeture
    de la connexion, y compris si le processus meurt). SQLite : sans objet.
    """
    if connection.dialect.name not in _MYSQL_DIALECTS:
        yield
        return

    name = schema_lock_name(connection)
    started = time.monotonic()
    acquired = connection.execute(
        text("SELECT GET_LOCK(:name, :timeout)"), {"name": name, "timeout": timeout}
    ).scalar()
    _end_transaction(connection)
    if acquired != 1:
        raise SchemaLockTimeout(
            f"Verrou de schéma '{name}' non obtenu en {timeout} s : une autre "
            "instance migre probablement la base. Relancez une fois cette migration "
            f"terminée, ou augmentez {LOCK_TIMEOUT_ENV}."
        )
    logger.info(
        "schema_lock_acquired",
        extra={
            "extra_fields": {
                "lock": name,
                "waited_s": round(time.monotonic() - started, 3),
            }
        },
    )
    try:
        yield
    finally:
        _release_schema_lock(connection, name)


# ============= ÉTAT ET VÉRIFICATION DU SCHÉMA =============


def inspect_schema_state(connection: Connection) -> tuple[str, str | None]:
    """Retourne (état, révision) avec état ∈ {"fresh", "legacy", "versioned"}."""
    tables = set(inspect(connection).get_table_names())
    _end_transaction(connection)
    current = get_current_revision(connection) if _VERSION_TABLE in tables else None
    if current is not None:
        return "versioned", current
    if tables & set(database.Base.metadata.tables):
        # Aucune révision mais des tables applicatives : installation antérieure
        # à Alembic, ou premier démarrage interrompu avant le stamp.
        return "legacy", None
    return "fresh", None


def _diff_kind(diff: Any) -> str:
    # compare_metadata : tuple (op, ...) ou liste de tuples modify_* par colonne.
    return diff[0][0] if isinstance(diff, list) else diff[0]


def describe_diff(diff: Any) -> str:
    """Représentation courte et lisible d'une différence compare_metadata."""
    if isinstance(diff, list):
        return "; ".join(describe_diff(d) for d in diff)
    kind = diff[0]
    if kind in ("add_table", "remove_table"):
        return f"{kind} {diff[1].name}"
    if kind in ("add_column", "remove_column"):
        return f"{kind} {diff[2]}.{diff[3].name}"
    if kind in ("add_index", "remove_index", "add_constraint", "remove_constraint"):
        return f"{kind} {diff[1].name} ({diff[1].table.name})"
    if kind in ("add_fk", "remove_fk"):
        fk = diff[1]
        columns = ",".join(c.name for c in fk.columns)
        return f"{kind} {fk.parent.name}({columns}) -> {fk.referred_table.name}"
    if kind.startswith("modify_"):
        return f"{kind} {diff[2]}.{diff[3]}: {diff[5]!r} -> {diff[6]!r}"
    return repr(diff)


def schema_differences(connection: Connection) -> list[Any]:
    """Écarts entre la base et ``Base.metadata`` (mêmes règles que l'autogénération)."""
    context = MigrationContext.configure(
        connection,
        opts={"compare_type": True, "include_object": include_object},
    )
    diffs = compare_metadata(context, database.Base.metadata)
    _end_transaction(connection)
    return diffs


def verify_legacy_schema(connection: Connection) -> list[str]:
    """Contrôle une base legacy mise à niveau avant de la déclarer baseline.

    Tables ou colonnes manquantes : erreur. Autres écarts : avertissement.
    """
    diffs = schema_differences(connection)
    blocking = [describe_diff(d) for d in diffs if _diff_kind(d) in _BLOCKING_LEGACY_DIFFS]
    if blocking:
        raise SchemaMigrationError(
            "Base legacy incomplète après mise à niveau, stamp de la baseline refusé : "
            + ", ".join(blocking)
        )
    described = [describe_diff(d) for d in diffs]
    if described:
        logger.warning(
            "legacy_schema_drift",
            extra={"extra_fields": {"differences": described}},
        )
    return described


def _ensure_known_revision(current: str) -> None:
    script = ScriptDirectory.from_config(get_alembic_config())
    try:
        script.get_revision(current)
    except CommandError as exc:
        raise SchemaMigrationError(
            f"La base est à la révision '{current}', inconnue de cette version de "
            "l'application (retour à une image plus ancienne ?). Redéployez la "
            "version qui a migré la base ou restaurez une sauvegarde."
        ) from exc


# ============= MISE À JOUR DU SCHÉMA =============


def upgrade_schema(engine: Engine | None = None, *, lock_timeout: int | None = None) -> str:
    """Amène la base à la révision head (voir docstring du module).

    ``engine`` : par défaut ``backend.database.engine``, lu à l'appel (les tests
    le remplacent). Retourne la révision finale ; lève ``SchemaMigrationError``
    ou ``LegacyMigrationError`` en cas d'échec.
    """
    engine = engine if engine is not None else database.engine
    timeout = _lock_timeout_from_env() if lock_timeout is None else lock_timeout
    head = get_head_revision()
    started = time.monotonic()

    with engine.connect() as connection:
        with schema_lock(connection, timeout):
            state, current = inspect_schema_state(connection)
            logger.info(
                "schema_state",
                extra={"extra_fields": {"state": state, "revision": current, "head": head}},
            )
            if state == "legacy":
                logger.warning(
                    "legacy_schema_upgrade_started",
                    extra={"extra_fields": {"baseline": BASELINE_REVISION}},
                )
                apply_legacy_migrations(connection)
                verify_legacy_schema(connection)
                _run_alembic(connection, command.stamp, BASELINE_REVISION)
                current = BASELINE_REVISION
                logger.warning(
                    "legacy_schema_stamped",
                    extra={"extra_fields": {"baseline": BASELINE_REVISION}},
                )
            elif state == "versioned":
                _ensure_known_revision(current)

            if current != head:
                _run_alembic(connection, command.upgrade, "head")
            final = get_current_revision(connection)

    if final != head:
        raise SchemaMigrationError(
            f"Schéma à la révision {final!r} après migration, {head!r} attendue."
        )
    logger.info(
        "schema_up_to_date",
        extra={
            "extra_fields": {
                "revision": final,
                "duration_s": round(time.monotonic() - started, 3),
            }
        },
    )
    return final


# ============= LIGNE DE COMMANDE =============


class _CliFormatter(logging.Formatter):
    """Affiche aussi les champs structurés (extra_fields) des logs applicatifs."""

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        fields = getattr(record, "extra_fields", None)
        if fields:
            message += " " + " ".join(f"{k}={v}" for k, v in fields.items())
        return message


@contextmanager
def _locked_connection() -> Iterator[Connection]:
    with database.engine.connect() as connection:
        with schema_lock(connection, _lock_timeout_from_env()):
            yield connection


def _print_status(connection: Connection) -> None:
    state, current = inspect_schema_state(connection)
    head = get_head_revision()
    labels = {
        "fresh": "vierge (aucune table applicative)",
        "legacy": "legacy : antérieure à Alembic, sera mise à niveau au démarrage",
        "versioned": "à jour" if current == head else "en retard sur head",
    }
    print(f"Base     : {database.engine.url.render_as_string(hide_password=True)}")
    print(f"État     : {labels[state]}")
    print(f"Révision : {current or '-'}")
    print(f"Head     : {head}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.db_migrate",
        description="Migrations du schéma LabOnDemand (Alembic).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    upgrade = sub.add_parser(
        "upgrade", help="amène la base à head (mêmes étapes et verrou qu'au démarrage)"
    )
    upgrade.add_argument(
        "--sql",
        nargs="?",
        const="head",
        metavar="PLAGE",
        help="n'exécute rien, affiche le SQL (ex. '0001_baseline:head')",
    )
    sub.add_parser("current", help="affiche l'état et la révision de la base")
    sub.add_parser("heads", help="affiche la ou les révisions head du code")
    sub.add_parser("history", help="liste les révisions")
    sub.add_parser("check", help="échoue si les modèles divergent de la dernière révision")

    stamp = sub.add_parser("stamp", help="enregistre une révision SANS rien exécuter")
    stamp.add_argument("revision")

    downgrade = sub.add_parser(
        "downgrade", help="annule des révisions (préférer une restauration en production)"
    )
    downgrade.add_argument("revision")

    revision = sub.add_parser("revision", help="crée un nouveau fichier de révision")
    revision.add_argument("-m", "--message", required=True)
    revision.add_argument(
        "--autogenerate",
        action="store_true",
        help="pré-remplit la révision en comparant les modèles à la base (à relire !)",
    )
    revision.add_argument("--rev-id", help="identifiant imposé (sinon aléatoire)")
    return parser


def setup_cli_logging() -> None:
    """Journalisation lisible sur la console pour la ligne de commande."""
    handler = logging.StreamHandler()
    handler.setFormatter(_CliFormatter("%(levelname)s [%(name)s] %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée CLI ; retourne le code de sortie (0 succès, 1 échec)."""
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "upgrade":
            if args.sql:
                command.upgrade(get_alembic_config(), args.sql, sql=True)
            else:
                upgrade_schema()
        elif args.command == "current":
            with database.engine.connect() as connection:
                _print_status(connection)
        elif args.command == "heads":
            command.heads(get_alembic_config(), verbose=True)
        elif args.command == "history":
            command.history(get_alembic_config(), verbose=True)
        elif args.command == "check":
            with database.engine.connect() as connection:
                command.check(get_alembic_config(connection))
            print("Aucune différence entre les modèles et la base.")
        elif args.command == "stamp":
            with _locked_connection() as connection:
                _run_alembic(connection, command.stamp, args.revision)
        elif args.command == "downgrade":
            with _locked_connection() as connection:
                _run_alembic(connection, command.downgrade, args.revision)
        elif args.command == "revision":
            with database.engine.connect() as connection:
                command.revision(
                    get_alembic_config(connection),
                    message=args.message,
                    autogenerate=args.autogenerate,
                    rev_id=args.rev_id,
                )
    except (SchemaMigrationError, LegacyMigrationError, CommandError, NotImplementedError) as exc:
        # NotImplementedError : downgrade de la baseline, refusé volontairement.
        logger.error("db_migrate_failed", extra={"extra_fields": {"error": str(exc)}})
        return 1
    return 0


if __name__ == "__main__":
    setup_cli_logging()
    sys.exit(main())
