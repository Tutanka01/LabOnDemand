"""Tests de la mise à niveau des bases legacy (backend/migrations.py)."""
import sqlite3

import pymysql
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

import backend.database as database
import backend.migrations as legacy
from backend.migrations import (
    LEGACY_MIGRATIONS,
    LegacyMigrationError,
    apply_legacy_migrations,
    is_already_applied_error,
)
from backend.tests.legacy_schema import (
    LEGACY_VARIANTS,
    build_legacy_database,
    insert_legacy_rows,
)


@pytest.fixture()
def scratch_engine():
    """Base SQLite en mémoire dédiée, indépendante de la base partagée des tests."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        yield engine
    finally:
        engine.dispose()


def _users_indexes(connection) -> dict:
    indexes = {ix["name"]: ix for ix in inspect(connection).get_indexes("users")}
    connection.commit()
    return indexes


def _db_error(orig: Exception) -> OperationalError:
    return OperationalError("ALTER TABLE ...", {}, orig)


# ---------- Contenu de la liste legacy ----------

def test_legacy_list_only_adds_columns():
    """Les CREATE TABLE historiques (morts : create_all passait avant) ont disparu."""
    assert LEGACY_MIGRATIONS
    names = [name for name, _ in LEGACY_MIGRATIONS]
    assert len(names) == len(set(names))
    for name, sql in LEGACY_MIGRATIONS:
        assert name.startswith("add_")
        assert sql.startswith("ALTER TABLE ") and " ADD COLUMN " in sql


# ---------- Discrimination des erreurs ----------

@pytest.mark.parametrize("code", [1050, 1060, 1061, 1091])
def test_mysql_already_applied_codes_are_ignored(code):
    exc = _db_error(pymysql.err.OperationalError(code, "already there"))
    assert is_already_applied_error(exc, "mysql")
    assert is_already_applied_error(exc, "mariadb")


@pytest.mark.parametrize(
    "code",
    [
        1062,  # Duplicate entry (doublons bloquant un index UNIQUE)
        1205,  # Lock wait timeout exceeded
        1064,  # Erreur de syntaxe
        1146,  # Table inexistante
        2013,  # Connexion perdue
    ],
)
def test_mysql_real_errors_are_not_ignored(code):
    exc = _db_error(pymysql.err.OperationalError(code, "boom"))
    assert not is_already_applied_error(exc, "mysql")


@pytest.mark.parametrize(
    "message, ignorable",
    [
        ("duplicate column name: tags", True),
        ("table users already exists", True),
        ("index ix_users_external_id already exists", True),
        ("no such index: idx_users_external_id_unique", True),
        ("no such table: nope", False),
        ('near "ADDD": syntax error', False),
        ("database is locked", False),
        ("UNIQUE constraint failed: users.external_id", False),
    ],
)
def test_sqlite_error_discrimination(message, ignorable):
    exc = _db_error(sqlite3.OperationalError(message))
    assert is_already_applied_error(exc, "sqlite") is ignorable


def test_unknown_dialect_never_ignores_errors():
    exc = _db_error(Exception("duplicate column name: tags"))
    assert not is_already_applied_error(exc, "postgresql")


def test_genuine_error_propagates(scratch_engine, monkeypatch):
    monkeypatch.setattr(
        legacy,
        "LEGACY_MIGRATIONS",
        [("add_to_missing_table", "ALTER TABLE nope ADD COLUMN x INTEGER")],
    )
    with scratch_engine.connect() as conn:
        with pytest.raises(LegacyMigrationError, match="add_to_missing_table"):
            apply_legacy_migrations(conn)


def test_syntax_error_propagates(scratch_engine, monkeypatch):
    monkeypatch.setattr(
        legacy,
        "LEGACY_MIGRATIONS",
        [("typo", "ALTER TABLE users ADDD COLUMN x INTEGER")],
    )
    with scratch_engine.connect() as conn:
        with pytest.raises(LegacyMigrationError, match="typo"):
            apply_legacy_migrations(conn)


# ---------- Mise à niveau des bases legacy ----------

def test_apply_is_idempotent_on_current_schema():
    """La base partagée des tests est déjà à jour : aucune erreur, rien ne change."""
    with database.engine.connect() as conn:
        before = _users_indexes(conn)
        apply_legacy_migrations(conn)
        apply_legacy_migrations(conn)
        assert _users_indexes(conn) == before


@pytest.mark.parametrize("variant", LEGACY_VARIANTS)
def test_legacy_variants_reach_model_state(scratch_engine, variant):
    with scratch_engine.connect() as conn:
        build_legacy_database(conn, variant)
        insert_legacy_rows(conn)

        apply_legacy_migrations(conn)
        apply_legacy_migrations(conn)  # idempotent

        insp = inspect(conn)
        tables = set(insp.get_table_names())
        assert {"users", "templates", "runtime_configs", "grading_runs"} <= tables
        user_columns = {c["name"] for c in insp.get_columns("users")}
        assert {"auth_provider", "external_id", "role_override"} <= user_columns
        assignment_columns = {c["name"] for c in insp.get_columns("assignments")}
        assert {"deliverables", "grading_mode"} <= assignment_columns
        conn.commit()

        indexes = _users_indexes(conn)
        assert indexes["ix_users_external_id"]["unique"]
        assert indexes["ix_users_external_id"]["column_names"] == ["external_id"]
        assert "idx_users_external_id_unique" not in indexes

        # Données conservées, défauts SQL appliqués aux colonnes ajoutées.
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


def test_duplicate_external_ids_fail_loudly(scratch_engine):
    """Des doublons SSO empêchent l'index unique : erreur explicite, index intacts."""
    with scratch_engine.connect() as conn:
        build_legacy_database(conn, "oct_2025")
        insert_legacy_rows(conn)
        conn.execute(text("ALTER TABLE users ADD COLUMN external_id VARCHAR(255) NULL"))
        conn.execute(text("CREATE INDEX ix_users_external_id ON users (external_id)"))
        conn.execute(text("UPDATE users SET external_id = 'same-sub'"))
        conn.commit()

        with pytest.raises(LegacyMigrationError, match="Dédoublonnez"):
            apply_legacy_migrations(conn)

        # L'index existant n'a pas été supprimé avant l'échec.
        indexes = _users_indexes(conn)
        assert "ix_users_external_id" in indexes
        assert not indexes["ix_users_external_id"]["unique"]
