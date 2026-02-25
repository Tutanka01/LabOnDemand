"""Tests for the seed module (admin, templates, runtime_configs)."""
import pytest

from backend.seed import seed_admin, seed_templates, seed_runtime_configs
from backend.models import User, UserRole, Template, RuntimeConfig


def test_seed_admin_creates_admin(db):
    seed_admin(db)
    admin = db.query(User).filter(User.role == UserRole.admin).first()
    assert admin is not None
    assert admin.username == "admin"
    assert admin.is_active is True
    assert admin.auth_provider == "local"


def test_seed_admin_idempotent(db):
    """Calling seed_admin twice must not create a duplicate."""
    seed_admin(db)
    seed_admin(db)
    count = db.query(User).filter(User.role == UserRole.admin).count()
    assert count == 1


def test_seed_admin_skips_if_admin_exists(db, admin_user):
    """If an admin already exists, seed_admin must not create another."""
    seed_admin(db)
    count = db.query(User).filter(User.role == UserRole.admin).count()
    assert count == 1


def test_seed_templates_creates_templates(db):
    seed_templates(db)
    count = db.query(Template).count()
    assert count > 0


def test_seed_templates_idempotent(db):
    seed_templates(db)
    first_count = db.query(Template).count()
    seed_templates(db)
    assert db.query(Template).count() == first_count


def test_seed_templates_all_have_keys(db):
    seed_templates(db)
    templates = db.query(Template).all()
    for t in templates:
        assert t.key and t.key.strip()
        assert t.name and t.name.strip()


def test_seed_runtime_configs_creates_configs(db):
    seed_runtime_configs(db)
    count = db.query(RuntimeConfig).count()
    assert count > 0


def test_seed_runtime_configs_idempotent(db):
    seed_runtime_configs(db)
    first_count = db.query(RuntimeConfig).count()
    seed_runtime_configs(db)
    assert db.query(RuntimeConfig).count() == first_count


def test_seed_runtime_configs_vscode_exists(db):
    seed_runtime_configs(db)
    vscode = db.query(RuntimeConfig).filter(RuntimeConfig.key == "vscode").first()
    assert vscode is not None
    assert vscode.active is True
