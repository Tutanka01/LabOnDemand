"""Configuration du moteur SQLAlchemy (backend/database.py).

La suite remplace le moteur MariaDB par SQLite juste après l'import de
``backend.database`` (voir conftest.py) : on teste donc les fonctions pures
qui construisent l'URL et les options, et un moteur MySQL créé à partir
d'elles (``create_engine`` n'ouvre aucune connexion).
"""
import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeMeta

from backend import database
from backend.database import build_database_url, engine_options


# ============= Options du pool =============

def test_engine_options_defaults():
    assert engine_options({}) == {
        "pool_size": 10,
        "max_overflow": 70,
        "pool_timeout": 30,
        "pool_recycle": 1800,
        "pool_pre_ping": True,
    }


def test_engine_options_read_from_environment():
    options = engine_options({
        "DB_POOL_SIZE": "20",
        "DB_MAX_OVERFLOW": "0",
        "DB_POOL_TIMEOUT": "5",
        "DB_POOL_RECYCLE": " 600 ",
    })
    assert options == {
        "pool_size": 20,
        "max_overflow": 0,
        "pool_timeout": 5,
        "pool_recycle": 600,
        "pool_pre_ping": True,
    }


def test_engine_options_blank_values_fall_back_to_defaults():
    options = engine_options({"DB_POOL_SIZE": "", "DB_POOL_RECYCLE": "  "})
    assert options["pool_size"] == 10
    assert options["pool_recycle"] == 1800


def test_pool_recycle_can_be_disabled():
    assert engine_options({"DB_POOL_RECYCLE": "-1"})["pool_recycle"] == -1


@pytest.mark.parametrize(
    "name, value",
    [
        ("DB_POOL_SIZE", "abc"),
        ("DB_POOL_SIZE", "0"),
        ("DB_POOL_SIZE", "2.5"),
        ("DB_MAX_OVERFLOW", "-1"),
        ("DB_POOL_TIMEOUT", "0"),
        ("DB_POOL_RECYCLE", "0"),
        ("DB_POOL_RECYCLE", "-2"),
    ],
)
def test_invalid_pool_setting_fails_fast_with_its_name(name, value):
    with pytest.raises(ValueError, match=name):
        engine_options({name: value})


def test_engine_options_are_accepted_by_create_engine():
    engine = create_engine(build_database_url({}), **engine_options({}))
    try:
        pool = engine.pool
        assert pool.size() == 10
        assert pool.timeout() == 30
        assert pool._max_overflow == 70
        assert pool._recycle == 1800
        assert pool._pre_ping is True
    finally:
        engine.dispose()


def test_module_exposes_engine_options_from_environment():
    """Le moteur applicatif est construit avec les options lues au démarrage."""
    assert database.ENGINE_OPTIONS == engine_options(os.environ)
    assert database.ENGINE_OPTIONS["pool_pre_ping"] is True


def test_default_pool_covers_two_connections_per_default_thread():
    """Session de requête + session de service, pour chacun des 40 threads."""
    defaults = engine_options({})
    assert database.pool_capacity(defaults) == 80
    assert database.pool_shortfall(40, defaults) == 0


def test_pool_shortfall_counts_missing_connections():
    options = engine_options({"DB_POOL_SIZE": "10", "DB_MAX_OVERFLOW": "30"})
    assert database.pool_shortfall(40, options) == 40
    assert database.pool_shortfall(20, options) == 0
    assert database.pool_shortfall(21, options) == 2


# ============= URL de connexion =============

def test_database_url_defaults():
    url = build_database_url({})
    assert url.drivername == "mysql+pymysql"
    assert (url.username, url.host, url.port, url.database) == (
        "labondemand", "localhost", 3306, "labondemand",
    )


@pytest.mark.parametrize("password", ["p@ss:w/rd", "a#b?c%d&e=f", "s p a c e", "é@ü/:"])
def test_database_url_keeps_special_characters_in_password(password):
    env = {
        "DB_USER": "lab@user",
        "DB_PASSWORD": password,
        "DB_HOST": "db",
        "DB_PORT": "3307",
        "DB_NAME": "labondemand",
    }
    url = build_database_url(env)
    assert url.password == password
    assert url.host == "db" and url.port == 3307

    # Le rendu textuel reste analysable sans ambiguïté…
    rendered = url.render_as_string(hide_password=False)
    assert make_url(rendered).password == password
    assert make_url(rendered).host == "db"

    # …et PyMySQL reçoit exactement les valeurs d'origine.
    engine = create_engine(url)
    try:
        _, kwargs = engine.dialect.create_connect_args(url)
    finally:
        engine.dispose()
    assert kwargs["password"] == password
    assert kwargs["user"] == "lab@user"
    assert kwargs["host"] == "db"
    assert kwargs["port"] == 3307
    assert kwargs["database"] == "labondemand"


def test_database_url_never_renders_password_by_default():
    url = build_database_url({"DB_PASSWORD": "tres-secret"})
    assert "tres-secret" not in str(url)
    assert "tres-secret" not in repr(url)


@pytest.mark.parametrize("port", ["abc", "0", "-3306"])
def test_invalid_db_port_fails_fast(port):
    with pytest.raises(ValueError, match="DB_PORT"):
        build_database_url({"DB_PORT": port})


# ============= Base déclarative =============

def test_base_is_a_declarative_base_with_models_registered():
    assert isinstance(database.Base, DeclarativeMeta)
    assert "users" in database.Base.metadata.tables


def test_database_module_imports_without_sqlalchemy_deprecation_warning():
    """Plus d'import de sqlalchemy.ext.declarative (MovedIn20Warning).

    Sous-processus : réimporter le module ici recréerait ``engine`` et
    ``Base`` que conftest.py a déjà remplacés.
    """
    code = (
        "import warnings\n"
        "from sqlalchemy.exc import SADeprecationWarning\n"
        "warnings.simplefilter('error', SADeprecationWarning)\n"
        "import backend.database\n"
    )
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=project_root,
    )
    assert result.returncode == 0, result.stderr
