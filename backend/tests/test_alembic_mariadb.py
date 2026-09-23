"""Migrations Alembic sur un vrai MariaDB (opt-in : TEST_MARIADB=1).

Lancé par le profil « mariadb » de compose.test.yaml, contre un serveur jetable
(tmpfs) ; chaque test crée puis supprime sa propre base :

    docker compose -f compose.test.yaml --profile mariadb run --rm --build tests-mariadb
    docker compose -f compose.test.yaml --profile mariadb down -v
"""
import logging
import os
import re
import threading
import time
import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

import backend.database as database
import backend.db_migrate as db_migrate
import backend.migrations as legacy
from backend.db_migrate import (
    SchemaLockTimeout,
    get_current_revision,
    get_head_revision,
    schema_lock_name,
    upgrade_schema,
)
from backend.migrations import LegacyMigrationError
from backend.tests.legacy_schema import (
    LEGACY_VARIANTS,
    build_legacy_database,
    insert_legacy_rows,
    schema_snapshot,
)

pytestmark = pytest.mark.skipif(
    os.getenv("TEST_MARIADB") != "1",
    reason="MariaDB réel requis : profil « mariadb » de compose.test.yaml (TEST_MARIADB=1)",
)

# Garde-fou : uniquement le serveur jetable du réseau de test, jamais la base
# du projet (service « db », volume mariadb_data, port 3306 de l'hôte).
_DISPOSABLE_HOST = "mariadb-test"


def _server_url():
    url = make_url(os.environ["TEST_MARIADB_URL"])
    if url.host != _DISPOSABLE_HOST:
        pytest.fail(f"TEST_MARIADB_URL doit viser {_DISPOSABLE_HOST}, pas {url.host!r}")
    return url


@pytest.fixture()
def new_database():
    """Fabrique de bases vides ``lod_scratch_*`` ; retourne un moteur par base."""
    server = create_engine(_server_url())
    created: list[str] = []
    engines = []

    def factory():
        name = f"lod_scratch_{uuid.uuid4().hex[:10]}"
        with server.begin() as conn:
            conn.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4"))
        created.append(name)
        engine = create_engine(_server_url().set(database=name))
        engines.append(engine)
        return engine

    try:
        yield factory
    finally:
        for engine in engines:
            engine.dispose()
        with server.begin() as conn:
            for name in created:
                conn.execute(text(f"DROP DATABASE IF EXISTS `{name}`"))
        server.dispose()


def _diffs(engine) -> list:
    with engine.connect() as conn:
        context = MigrationContext.configure(
            conn, opts={"compare_type": True, "include_object": db_migrate.include_object}
        )
        return compare_metadata(context, database.Base.metadata)


def _revision(engine) -> str | None:
    with engine.connect() as conn:
        return get_current_revision(conn)


def _normalize_ddl(ddl: str) -> tuple[list[str], list[str]]:
    """DDL de SHOW CREATE TABLE comparable entre deux bases.

    L'ordre des lignes KEY dépend de l'ordre (arbitraire) de création des index
    et n'a pas de sens : elles sont triées. Tout le reste (colonnes, types,
    défauts, noms et ordre des contraintes <table>_ibfk_N) doit être identique.
    """
    lines = [
        line.strip().rstrip(",")
        for line in re.sub(r" AUTO_INCREMENT=\d+", "", ddl).splitlines()
    ]
    keys = sorted(line for line in lines if re.match(r"(UNIQUE )?KEY ", line))
    others = [line for line in lines if not re.match(r"(UNIQUE )?KEY ", line)]
    return others, keys


def _show_create_tables(engine) -> dict[str, tuple[list[str], list[str]]]:
    with engine.connect() as conn:
        tables = [t for t in inspect(conn).get_table_names() if t != "alembic_version"]
        return {
            table: _normalize_ddl(conn.execute(text(f"SHOW CREATE TABLE `{table}`")).one()[1])
            for table in tables
        }


def _lock_is_free(engine) -> bool:
    with engine.connect() as conn:
        name = schema_lock_name(conn)
        return conn.execute(text("SELECT IS_FREE_LOCK(:n)"), {"n": name}).scalar() == 1


# ---------- Base vierge ----------

def test_fresh_upgrade_matches_models(new_database):
    engine = new_database()
    assert engine.dialect.name in ("mysql", "mariadb")
    assert upgrade_schema(engine) == get_head_revision()
    assert _revision(engine) == get_head_revision()
    assert _diffs(engine) == []
    assert _lock_is_free(engine)


def test_baseline_ddl_is_identical_to_create_all(new_database):
    migrated, created = new_database(), new_database()
    upgrade_schema(migrated)
    database.Base.metadata.create_all(bind=created)

    assert _show_create_tables(migrated) == _show_create_tables(created)
    with migrated.connect() as a, created.connect() as b:
        assert schema_snapshot(a) == schema_snapshot(b)


def test_upgrade_through_application_engine_and_cli(new_database, monkeypatch, capfd):
    engine = new_database()
    monkeypatch.setattr(database, "engine", engine)
    assert db_migrate.main(["upgrade"]) == 0
    assert db_migrate.main(["check"]) == 0
    assert db_migrate.main(["upgrade", "--sql"]) == 0
    out = capfd.readouterr().out
    assert "CREATE TABLE users" in out and "ENUM('student','teacher','admin')" in out
    assert _revision(engine) == get_head_revision()


# ---------- Bases legacy ----------

@pytest.mark.parametrize("variant", LEGACY_VARIANTS)
def test_legacy_database_is_upgraded_and_stamped(new_database, variant):
    engine = new_database()
    with engine.connect() as conn:
        build_legacy_database(conn, variant)
        insert_legacy_rows(conn)

    head = get_head_revision()
    assert upgrade_schema(engine) == head
    assert upgrade_schema(engine) == head  # idempotent
    assert _revision(engine) == head
    assert _diffs(engine) == []

    with engine.connect() as conn:
        indexes = {ix["name"]: ix for ix in inspect(conn).get_indexes("users")}
        assert indexes["ix_users_external_id"]["unique"]
        assert "idx_users_external_id_unique" not in indexes
        rows = conn.execute(
            text(
                "SELECT username, auth_provider, external_id, role_override "
                "FROM users ORDER BY username"
            )
        ).all()
        assert [tuple(r) for r in rows] == [
            ("legacy_admin", "local", None, 0),
            ("legacy_student", "local", None, 0),
        ]
        if variant == "oct_2025":
            assert "labs" in inspect(conn).get_table_names()


def test_genuine_legacy_error_propagates(new_database, monkeypatch):
    engine = new_database()
    with engine.connect() as conn:
        build_legacy_database(conn, "latest")
    monkeypatch.setattr(
        legacy,
        "LEGACY_MIGRATIONS",
        [("add_to_missing_table", "ALTER TABLE nope ADD COLUMN x INT")],  # 1146
    )
    with pytest.raises(LegacyMigrationError, match="add_to_missing_table"):
        upgrade_schema(engine)
    assert _revision(engine) is None
    assert _lock_is_free(engine)


def test_duplicate_external_ids_block_the_upgrade(new_database):
    engine = new_database()
    with engine.connect() as conn:
        build_legacy_database(conn, "sso_2026")
        conn.execute(text("DROP INDEX idx_users_external_id_unique ON users"))
        insert_legacy_rows(conn)
        conn.execute(text("UPDATE users SET external_id = 'same-sub'"))
        conn.commit()
    with pytest.raises(LegacyMigrationError, match="Dédoublonnez"):
        upgrade_schema(engine)
    assert _revision(engine) is None


# ---------- Verrou de schéma (GET_LOCK) ----------

def _wait_for_lock_waiters(engine, expected: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    with engine.connect() as conn:
        while time.monotonic() < deadline:
            waiting = conn.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.PROCESSLIST "
                    "WHERE INFO LIKE 'SELECT GET_LOCK(%' AND ID <> CONNECTION_ID()"
                )
            ).scalar()
            conn.commit()
            if waiting >= expected:
                return
            time.sleep(0.1)
    pytest.fail(f"{expected} démarrages attendus en attente du verrou")


def test_concurrent_bootstraps_are_serialized(new_database, caplog):
    holder_engine = new_database()
    url = holder_engine.url
    caplog.set_level(logging.INFO, logger="labondemand.db_migrate")

    results: dict[int, object] = {}

    def start_instance(index: int) -> None:
        engine = create_engine(url)  # une « instance » = son propre pool
        try:
            results[index] = upgrade_schema(engine, lock_timeout=120)
        except Exception as exc:  # remonté par l'assertion ci-dessous
            results[index] = exc
        finally:
            engine.dispose()

    with holder_engine.connect() as holder:
        name = schema_lock_name(holder)
        assert holder.execute(text("SELECT GET_LOCK(:n, 0)"), {"n": name}).scalar() == 1
        holder.commit()

        threads = [threading.Thread(target=start_instance, args=(i,)) for i in (1, 2)]
        for thread in threads:
            thread.start()
        _wait_for_lock_waiters(holder_engine, expected=2)
        # Les deux instances attendent : rien n'a encore été créé.
        assert inspect(holder_engine).get_table_names() == []

        holder.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": name})
        holder.commit()
        for thread in threads:
            thread.join(timeout=180)
            assert not thread.is_alive()

    head = get_head_revision()
    assert results == {1: head, 2: head}
    # L'une a migré la base vierge, l'autre l'a trouvée déjà à jour.
    states = sorted(
        r.extra_fields["state"] for r in caplog.records if r.getMessage() == "schema_state"
    )
    assert states == ["fresh", "versioned"]
    with holder_engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all() == [
            head
        ]
    assert _diffs(holder_engine) == []
    assert _lock_is_free(holder_engine)


def test_lock_timeout_aborts_without_touching_the_schema(new_database):
    engine = new_database()
    with engine.connect() as holder:
        name = schema_lock_name(holder)
        assert holder.execute(text("SELECT GET_LOCK(:n, 0)"), {"n": name}).scalar() == 1
        holder.commit()
        other_instance = create_engine(engine.url)
        try:
            with pytest.raises(SchemaLockTimeout, match="non obtenu"):
                upgrade_schema(other_instance, lock_timeout=1)
        finally:
            other_instance.dispose()
        holder.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": name})
        holder.commit()
    assert inspect(engine).get_table_names() == []


def test_lock_name_isolates_databases_on_the_same_server(new_database):
    first, second = new_database(), new_database()
    with first.connect() as a, second.connect() as b:
        first_lock, second_lock = schema_lock_name(a), schema_lock_name(b)
    assert first_lock != second_lock
    assert first_lock.startswith("labondemand_schema:lod_scratch_")

    with first.connect() as a:
        assert a.execute(text("SELECT GET_LOCK(:n, 0)"), {"n": first_lock}).scalar() == 1
        # Une autre base du même serveur migre sans attendre.
        assert upgrade_schema(second, lock_timeout=1) == get_head_revision()
        a.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": first_lock})
