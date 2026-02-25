"""Tests for the migrations module."""
import pytest
from sqlalchemy import inspect, text

# conftest already imports backend; we can import directly
from backend.migrations import run_migrations, MIGRATIONS


def test_migrations_list_not_empty():
    assert len(MIGRATIONS) > 0


def test_each_migration_has_name_and_sql():
    for name, sql in MIGRATIONS:
        assert isinstance(name, str) and name.strip()
        assert isinstance(sql, str) and sql.strip()


def test_run_migrations_idempotent(db):
    """Running migrations twice must not raise."""
    run_migrations(db)
    run_migrations(db)  # second run should be safe


def test_run_migrations_on_sqlite(db):
    """Migrations that use MySQL-only syntax silently fail; core tables exist."""
    run_migrations(db)
    # Verify that the core tables created by Base.metadata.create_all still exist
    inspector = inspect(db.bind)
    tables = inspector.get_table_names()
    assert "users" in tables
    assert "templates" in tables


def test_runtime_configs_table_exists_after_migration(db):
    """runtime_configs table is created either by SQLAlchemy or the migration."""
    run_migrations(db)
    inspector = inspect(db.bind)
    tables = inspector.get_table_names()
    assert "runtime_configs" in tables
