"""Tests des migrations Alembic et du bootstrap du schéma (backend/db_migrate.py).

Bases SQLite en mémoire dédiées : la base partagée des tests n'est pas touchée.
La vérification sur un vrai MariaDB est dans test_alembic_mariadb.py (opt-in).
"""
import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

import backend.database as database
import backend.db_migrate as db_migrate
import backend.main as main_module
import backend.migrations as legacy
from backend.db_migrate import (
    BASELINE_REVISION,
    SchemaMigrationError,
    get_alembic_config,
    get_current_revision,
    get_head_revision,
    upgrade_schema,
)
from backend.migrations import LegacyMigrationError
from backend.tests.legacy_schema import (
    LEGACY_VARIANTS,
    build_legacy_database,
    insert_legacy_rows,
    schema_snapshot,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _sqlite_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture()
def scratch_engine():
    engine = _sqlite_engine()
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def app_engine(monkeypatch, scratch_engine):
    """Remplace ``backend.database.engine`` comme le ferait un autre déploiement."""
    monkeypatch.setattr(database, "engine", scratch_engine)
    return scratch_engine


def _revision(engine) -> str | None:
    with engine.connect() as conn:
        return get_current_revision(conn)


def _tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def _diffs(engine, *, ignore_unknown_tables: bool = False) -> list:
    with engine.connect() as conn:
        opts = {"compare_type": True}
        if ignore_unknown_tables:
            opts["include_object"] = db_migrate.include_object
        context = MigrationContext.configure(conn, opts=opts)
        return compare_metadata(context, database.Base.metadata)


# ---------- Révisions ----------

def test_revisions_have_a_single_head_rooted_at_baseline():
    script = ScriptDirectory.from_config(get_alembic_config())
    assert len(script.get_heads()) == 1
    assert get_head_revision() == script.get_current_head()
    baseline = script.get_revision(BASELINE_REVISION)
    assert baseline.down_revision is None
    assert list(script.get_bases()) == [BASELINE_REVISION]


def test_multiple_heads_are_refused(monkeypatch):
    monkeypatch.setattr(ScriptDirectory, "get_heads", lambda self: ["aaa", "bbb"])
    with pytest.raises(SchemaMigrationError, match="une seule tête"):
        get_head_revision()


# ---------- Base vierge ----------

def test_fresh_database_upgrades_to_head(scratch_engine):
    assert upgrade_schema(scratch_engine) == get_head_revision()
    assert _revision(scratch_engine) == get_head_revision()
    assert set(database.Base.metadata.tables) <= _tables(scratch_engine)


def test_models_have_no_pending_changes(scratch_engine):
    """Toute modification de models.py doit s'accompagner d'une révision.

    Si ce test échoue : ``python -m backend.db_migrate revision --autogenerate
    -m "..."``, relire le fichier généré, puis le committer avec le modèle.
    """
    upgrade_schema(scratch_engine)
    assert _diffs(scratch_engine) == []


def test_baseline_schema_is_identical_to_create_all(scratch_engine):
    upgrade_schema(scratch_engine)
    reference = _sqlite_engine()
    try:
        database.Base.metadata.create_all(bind=reference)
        with scratch_engine.connect() as migrated, reference.connect() as created:
            assert schema_snapshot(migrated) == schema_snapshot(created)
    finally:
        reference.dispose()


def test_upgrade_is_idempotent(scratch_engine):
    head = upgrade_schema(scratch_engine)
    assert upgrade_schema(scratch_engine) == head
    assert _revision(scratch_engine) == head


def test_bootstrap_uses_database_engine_at_call_time(app_engine):
    """main.bootstrap appelle upgrade_schema() sans argument."""
    assert upgrade_schema() == get_head_revision()
    assert _revision(app_engine) == get_head_revision()


def test_offline_sql_is_generated_without_touching_the_database(app_engine, capfd):
    assert db_migrate.main(["upgrade", "--sql"]) == 0
    out = capfd.readouterr().out
    assert "CREATE TABLE users" in out
    assert f"'{BASELINE_REVISION}'" in out
    assert _tables(app_engine) == set()


# ---------- Bases legacy (antérieures à Alembic) ----------

@pytest.mark.parametrize("variant", LEGACY_VARIANTS)
def test_legacy_database_is_upgraded_stamped_and_idempotent(scratch_engine, variant):
    with scratch_engine.connect() as conn:
        build_legacy_database(conn, variant)
        insert_legacy_rows(conn)
    assert "alembic_version" not in _tables(scratch_engine)

    head = get_head_revision()
    assert upgrade_schema(scratch_engine) == head
    assert _revision(scratch_engine) == head
    with scratch_engine.connect() as conn:
        snapshot_after_first = schema_snapshot(conn)

    assert upgrade_schema(scratch_engine) == head  # second démarrage : rien à faire
    with scratch_engine.connect() as conn:
        assert schema_snapshot(conn) == snapshot_after_first

    # Seules les tables inconnues des modèles (labs) subsistent comme écart.
    assert _diffs(scratch_engine, ignore_unknown_tables=True) == []
    if variant == "oct_2025":
        assert "labs" in _tables(scratch_engine)

    with scratch_engine.connect() as conn:
        users = conn.execute(text("SELECT username FROM users ORDER BY username")).scalars()
        assert list(users) == ["legacy_admin", "legacy_student"]
        assert conn.execute(text("SELECT name FROM templates")).scalar() == "Legacy"


def test_interrupted_first_start_is_resumed(scratch_engine):
    """Tables créées mais aucune révision enregistrée (arrêt avant le stamp,
    ou baseline partiellement appliquée sur MariaDB) : traité comme legacy."""
    database.Base.metadata.create_all(bind=scratch_engine)
    with scratch_engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
    assert upgrade_schema(scratch_engine) == get_head_revision()


def test_genuine_legacy_error_propagates_and_nothing_is_stamped(scratch_engine, monkeypatch):
    with scratch_engine.connect() as conn:
        build_legacy_database(conn, "latest")
    monkeypatch.setattr(
        legacy,
        "LEGACY_MIGRATIONS",
        [("add_to_missing_table", "ALTER TABLE nope ADD COLUMN x INTEGER")],
    )
    with pytest.raises(LegacyMigrationError, match="add_to_missing_table"):
        upgrade_schema(scratch_engine)
    assert _revision(scratch_engine) is None


def test_incomplete_legacy_schema_is_not_stamped(scratch_engine, monkeypatch):
    """Si la mise à niveau legacy laisse des colonnes manquantes, pas de stamp."""
    with scratch_engine.connect() as conn:
        build_legacy_database(conn, "oct_2025")
    monkeypatch.setattr(db_migrate, "apply_legacy_migrations", lambda connection: None)
    with pytest.raises(SchemaMigrationError, match="add_column users.auth_provider"):
        upgrade_schema(scratch_engine)
    assert _revision(scratch_engine) is None


def test_unknown_revision_is_refused(scratch_engine):
    upgrade_schema(scratch_engine)
    with scratch_engine.begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = 'f00dcafe'"))
    with pytest.raises(SchemaMigrationError, match="f00dcafe"):
        upgrade_schema(scratch_engine)


# ---------- Verrou ----------

def test_lock_timeout_setting_is_validated(monkeypatch):
    monkeypatch.setenv(db_migrate.LOCK_TIMEOUT_ENV, "12")
    assert db_migrate._lock_timeout_from_env() == 12
    for invalid in ("abc", "-1", ""):
        monkeypatch.setenv(db_migrate.LOCK_TIMEOUT_ENV, invalid)
        with pytest.raises(SchemaMigrationError, match=db_migrate.LOCK_TIMEOUT_ENV):
            db_migrate._lock_timeout_from_env()


def test_lock_name_is_scoped_to_the_database():
    engine = create_engine("mysql+pymysql://u:p@db/labondemand")
    connection = type("FakeConnection", (), {"engine": engine})()
    name = db_migrate.schema_lock_name(connection)
    assert name == "labondemand_schema:labondemand"
    assert len(name) <= 64


# ---------- Démarrage de l'API ----------

async def _run_lifespan(app, messages: list[str], sent: list[dict]) -> None:
    """Pilote le protocole ASGI lifespan comme uvicorn ; messages émis dans ``sent``."""
    incoming: asyncio.Queue = asyncio.Queue()
    for message in messages:
        incoming.put_nowait({"type": message})

    async def receive() -> dict:
        return await incoming.get()

    async def send(message: dict) -> None:
        sent.append(message)

    before = asyncio.all_tasks()
    try:
        await app({"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}, receive, send)
    finally:
        # Tâches de fond démarrées par les hooks (nettoyage des sessions…).
        leaked = asyncio.all_tasks() - before - {asyncio.current_task()}
        for task in leaked:
            task.cancel()
        await asyncio.gather(*leaked, return_exceptions=True)


async def test_schema_failure_aborts_startup(monkeypatch, caplog):
    def broken_upgrade() -> str:
        raise SchemaMigrationError("migration cassée (test)")

    seeds_called: list[str] = []
    monkeypatch.setattr(main_module, "upgrade_schema", broken_upgrade)
    monkeypatch.setattr(main_module, "seed_admin", lambda db: seeds_called.append("admin"))

    sent: list[dict] = []
    with pytest.raises(SchemaMigrationError):
        await _run_lifespan(main_module.app, ["lifespan.startup"], sent)

    # uvicorn reçoit startup.failed et s'arrête ; aucun seed n'a tourné.
    assert [m["type"] for m in sent] == ["lifespan.startup.failed"]
    assert "migration cassée" in sent[0]["message"]
    assert not seeds_called
    critical = [r for r in caplog.records if r.getMessage() == "schema_upgrade_failed"]
    assert len(critical) == 1 and critical[0].levelname == "CRITICAL"


def test_uvicorn_exits_non_zero_when_schema_upgrade_fails(tmp_path):
    """Bout en bout : uvicorn s'arrête (code 3, échec de démarrage)."""
    script = (
        "import uvicorn\n"
        "import backend.tests.conftest  # doublures Redis/Kubernetes/SQLite de la suite\n"
        "import backend.main as main\n"
        "from backend.db_migrate import SchemaMigrationError\n"
        "def broken():\n"
        "    raise SchemaMigrationError('migration cassée (test)')\n"
        "main.upgrade_schema = broken\n"
        "uvicorn.run(main.app, host='127.0.0.1', port=0, lifespan='on', log_config=None)\n"
        "print('SERVER_RETURNED_NORMALLY')\n"
    )
    env = {**os.environ, "LOG_ENABLE_CONSOLE": "true", "LOG_DIR": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 3, output
    assert "schema_upgrade_failed" in output
    assert "SERVER_RETURNED_NORMALLY" not in output


def test_seed_failure_is_logged_but_not_fatal(monkeypatch, caplog):
    called: list[str] = []

    def failing_seed(db) -> None:
        raise RuntimeError("seed cassé (test)")

    monkeypatch.setattr(main_module, "seed_admin", failing_seed)
    monkeypatch.setattr(main_module, "seed_templates", lambda db: called.append("templates"))
    monkeypatch.setattr(
        main_module, "seed_runtime_configs", lambda db: called.append("runtime_configs")
    )

    main_module.run_seeds()

    assert called == ["templates", "runtime_configs"]
    failures = [r for r in caplog.records if r.getMessage() == "seed_failed"]
    assert len(failures) == 1 and failures[0].levelname == "ERROR"


async def test_startup_completes_despite_seed_failure(monkeypatch):
    import backend.tasks.cleanup as cleanup

    async def idle_cleanup_loop() -> None:
        return None

    def failing_seed(db) -> None:
        raise RuntimeError("seed cassé (test)")

    monkeypatch.setattr(main_module, "upgrade_schema", lambda: get_head_revision())
    monkeypatch.setattr(main_module, "seed_admin", failing_seed)
    monkeypatch.setattr(cleanup, "run_cleanup_loop", idle_cleanup_loop)

    sent: list[dict] = []
    await _run_lifespan(main_module.app, ["lifespan.startup", "lifespan.shutdown"], sent)
    assert [m["type"] for m in sent] == [
        "lifespan.startup.complete",
        "lifespan.shutdown.complete",
    ]


# ---------- Ligne de commande ----------

def test_cli_upgrade_current_check(app_engine, capfd):
    assert db_migrate.main(["current"]) == 0
    assert "vierge" in capfd.readouterr().out

    assert db_migrate.main(["upgrade"]) == 0
    assert db_migrate.main(["current"]) == 0
    out = capfd.readouterr().out
    assert "à jour" in out and get_head_revision() in out

    assert db_migrate.main(["check"]) == 0
    assert db_migrate.main(["heads"]) == 0
    assert db_migrate.main(["history"]) == 0
    assert get_head_revision() in capfd.readouterr().out


def test_env_uses_application_engine_without_shared_connection(app_engine):
    upgrade_schema()
    command.check(get_alembic_config())  # env.py ouvre database.engine lui-même


def test_cli_reports_errors_with_exit_code(app_engine):
    upgrade_schema()
    assert db_migrate.main(["stamp", "f00dcafe"]) == 1
    # La baseline refuse de se rétrograder : aucune table supprimée.
    assert db_migrate.main(["downgrade", "base"]) == 1
    assert "users" in _tables(app_engine)
    assert _revision(app_engine) == get_head_revision()


def test_cli_legacy_database_shows_legacy_state(app_engine, capfd):
    with app_engine.connect() as conn:
        build_legacy_database(conn, "latest")
    assert db_migrate.main(["current"]) == 0
    assert "legacy" in capfd.readouterr().out


def test_cli_revision_autogenerate_without_model_change(app_engine, monkeypatch, tmp_path):
    """Plomberie de ``revision --autogenerate`` sur une copie du dossier alembic."""
    alembic_copy = tmp_path / "alembic"
    shutil.copytree(
        db_migrate.ALEMBIC_DIR, alembic_copy, ignore=shutil.ignore_patterns("__pycache__")
    )
    monkeypatch.setattr(db_migrate, "ALEMBIC_DIR", alembic_copy)
    upgrade_schema()
    head = get_head_revision()

    assert db_migrate.main(
        ["revision", "--autogenerate", "-m", "no change", "--rev-id", "0002_test"]
    ) == 0
    [generated] = alembic_copy.glob("versions/*_0002_test_no_change.py")
    content = generated.read_text()
    assert f"down_revision: Union[str, Sequence[str], None] = '{head}'" in content
    upgrade_body = content.split("def upgrade() -> None:")[1].split("def downgrade")[0]
    statements = [
        line.strip()
        for line in upgrade_body.splitlines()
        if line.strip() and not line.strip().startswith(("#", '"""'))
    ]
    assert statements == ["pass"]
