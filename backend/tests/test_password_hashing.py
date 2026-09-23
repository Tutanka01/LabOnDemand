"""Hachage des mots de passe : bcrypt direct, compatible avec l'ère passlib.

Les hachages « passlib » ci-dessous ont été générés une fois avec
passlib 1.7.4 + bcrypt 4.0.1 (l'image de l'API avant la migration), via
``CryptContext(schemes=["bcrypt"], deprecated="auto")`` — exactement la
configuration de production. Ils figent le contrat : tout compte créé avant la
suppression de passlib doit continuer à se connecter.
"""
import pytest
from httpx import ASGITransport, AsyncClient

from backend import password_hashing
from backend.database import get_db
from backend.main import app
from backend.models import User, UserRole
from backend.password_hashing import (
    BCRYPT_MAX_PASSWORD_BYTES,
    hash_password,
    verify_password,
)
from backend.security import get_password_hash, verify_password as security_verify_password

# ---------- Hachages produits par passlib (littéraux, ne pas régénérer) ----------

PASSLIB_PASSWORD = "LabOnDemand@2024!"
# ctx.hash(PASSLIB_PASSWORD) — identifiant par défaut de passlib : $2b$, coût 12
PASSLIB_HASH_2B = "$2b$12$MzivWV7vtnk3nTNVM7hYSeXxTHEQhACwl0ET9127d7ClgauM08YY."
# passlib.hash.bcrypt.using(ident="2a", rounds=12).hash(PASSLIB_PASSWORD)
PASSLIB_HASH_2A = "$2a$12$dauBsZOaEYCdQnAGbsLzBuE9echUsGfFfJxAGjlKrsRjVlx6RfDAG"
# passlib.hash.bcrypt.using(ident="2y", rounds=12).hash(PASSLIB_PASSWORD)
PASSLIB_HASH_2Y = "$2y$12$QofbWCj84J80PIE6ICJJm.VXaJqQFzmZziqbqD0zHLFUBNUDRFt2C"

# Mot de passe de 102 octets UTF-8 : la limite de 72 octets tombe au milieu
# du dernier « é » conservé (octets 71-72), comme passlib l'appliquait.
PASSLIB_LONG_PASSWORD = "Tr0ub4dor&3-!" + "é" * 30 + "-correct-horse-battery-staple"
PASSLIB_LONG_HASH = "$2b$12$coUE95yYjrJ3G6eY3u91w.FBuUDn9H0zIAbht0W3De4/kraPondOO"


# ============= Compatibilité avec les hachages existants =============

@pytest.mark.parametrize("stored_hash", [PASSLIB_HASH_2B, PASSLIB_HASH_2A, PASSLIB_HASH_2Y])
def test_passlib_hashes_still_verify(stored_hash):
    assert verify_password(PASSLIB_PASSWORD, stored_hash) is True


@pytest.mark.parametrize("stored_hash", [PASSLIB_HASH_2B, PASSLIB_HASH_2A, PASSLIB_HASH_2Y])
def test_passlib_hashes_reject_wrong_password(stored_hash):
    assert verify_password("LabOnDemand@2024?", stored_hash) is False
    assert verify_password("", stored_hash) is False


def test_passlib_long_password_hash_still_verifies():
    """bcrypt >= 5 lève au-delà de 72 octets : la troncature doit être explicite."""
    assert len(PASSLIB_LONG_PASSWORD.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES
    assert verify_password(PASSLIB_LONG_PASSWORD, PASSLIB_LONG_HASH) is True


def test_passlib_long_password_truncation_semantics_are_preserved():
    """Même sémantique que passlib : seuls les 72 premiers octets comptent.

    Ce suffixe partage les 72 premiers octets (y compris le premier octet du
    caractère coupé : « è » et « é » commencent tous deux par 0xC3).
    """
    other_suffix = "Tr0ub4dor&3-!" + "é" * 29 + "è-autre-suffixe"
    assert other_suffix.encode("utf-8")[:72] == PASSLIB_LONG_PASSWORD.encode("utf-8")[:72]
    assert verify_password(other_suffix, PASSLIB_LONG_HASH) is True
    # Une différence dans les 72 premiers octets est bien détectée.
    assert verify_password("X" + PASSLIB_LONG_PASSWORD[1:], PASSLIB_LONG_HASH) is False


# ============= Nouveaux hachages =============

def test_new_hash_is_standard_bcrypt_cost_12():
    hashed = hash_password("StrongP@ssw0rd123!")
    assert hashed.startswith("$2b$12$")
    assert len(hashed) == 60
    assert verify_password("StrongP@ssw0rd123!", hashed) is True
    assert verify_password("StrongP@ssw0rd123?", hashed) is False


def test_new_hash_uses_random_salt():
    assert hash_password("StrongP@ssw0rd123!") != hash_password("StrongP@ssw0rd123!")


def test_new_long_password_is_truncated_like_passlib():
    """Décision : troncature à 72 octets (pas de rejet), comme sous passlib."""
    long_password = "A1!a" + "x" * 100
    hashed = hash_password(long_password)  # ne doit pas lever (bcrypt >= 5)
    assert verify_password(long_password, hashed) is True
    assert verify_password(long_password[:72] + "suffixe-ignore", hashed) is True
    assert verify_password(long_password[:71], hashed) is False


def test_non_ascii_password_roundtrip():
    password = "Mot-de-passe-éèà-日本語-🔐-9!"
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True
    assert verify_password(password.replace("é", "e"), hashed) is False


# ============= Entrées invalides : jamais d'exception à la vérification =============

@pytest.mark.parametrize(
    "stored_hash",
    [
        "",  # comptes SSO (hashed_password vide)
        None,
        "not-a-hash",
        "$1$abc$def",  # md5-crypt : schéma non supporté
        "$2b$12$tropcourt",
        "$2b$12$" + "é" * 53,  # non ASCII
    ],
)
def test_invalid_stored_hash_returns_false(stored_hash):
    assert verify_password(PASSLIB_PASSWORD, stored_hash) is False


@pytest.mark.parametrize("password", [None, b"LabOnDemand@2024!", 12345])
def test_non_string_password_returns_false(password):
    assert verify_password(password, PASSLIB_HASH_2B) is False


def test_nul_byte_password_is_refused():
    with pytest.raises(ValueError):
        hash_password("abc\x00defGHI123!")
    # passlib levait aussi à la vérification ; ici on répond simplement « non ».
    assert verify_password("LabOnDemand@2024!\x00", PASSLIB_HASH_2B) is False


def test_malformed_hash_is_logged_without_its_content(caplog):
    with caplog.at_level("WARNING", logger=password_hashing.logger.name):
        assert verify_password(PASSLIB_PASSWORD, "$2b$12$tropcourt") is False
    assert "password_hash_unsupported" in caplog.text
    assert "tropcourt" not in caplog.text


# ============= Intégration : security.py et connexion =============

def test_security_helpers_delegate_to_bcrypt():
    hashed = get_password_hash("StrongP@ssw0rd123!")
    assert hashed.startswith("$2b$12$")
    assert security_verify_password("StrongP@ssw0rd123!", hashed) is True
    assert security_verify_password(PASSLIB_PASSWORD, PASSLIB_HASH_2B) is True


@pytest.fixture()
async def isolated_client(db):
    """Client HTTP avec sa propre adresse IP (TEST-NET-2).

    Le limiteur de /login compte les tentatives par IP sur toute la session de
    tests : une adresse dédiée évite de dépendre de l'ordre d'exécution.
    """
    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app, client=("198.51.100.72", 40072))
    # En-tête anti-CSRF exigé sur les requêtes non sûres (voir backend/csrf.py)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Requested-With": "XMLHttpRequest"},
    ) as c:
        yield c
    app.dependency_overrides.clear()


async def test_login_with_passlib_era_hash(isolated_client, db):
    """Un compte dont le hachage date de passlib se connecte normalement."""
    client = isolated_client
    db.add(User(
        username="legacyuser",
        email="legacy@test.lab",
        hashed_password=PASSLIB_HASH_2B,
        role=UserRole.student,
        is_active=True,
        auth_provider="local",
    ))
    db.commit()

    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "legacyuser", "password": PASSLIB_PASSWORD},
    )
    assert r.status_code == 200
    assert r.json()["user"]["username"] == "legacyuser"

    r = await client.post(
        "/api/v1/auth/login",
        json={"username": "legacyuser", "password": "LabOnDemand@2024?"},
    )
    assert r.status_code == 401
