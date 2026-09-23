"""Limitation de débit : connexion (IP + nom d'utilisateur) et déploiements.

Couvre aussi l'égalisation du temps de réponse de ``authenticate_user`` :
un nom inconnu ne doit pas répondre plus vite qu'un mauvais mot de passe.
"""
from unittest.mock import patch

from backend import security


# ============================================================
# Égalisation du temps de réponse (énumération des comptes)
# ============================================================

def test_unknown_user_still_runs_a_password_check(db):
    with patch("backend.security.verify_password", wraps=security.verify_password) as verify:
        assert security.authenticate_user(db, "nobody", "whatever") is False
    verify.assert_called_once_with("whatever", security._DUMMY_PASSWORD_HASH)


def test_sso_account_still_runs_a_password_check(db, oidc_user):
    with patch("backend.security.verify_password", wraps=security.verify_password) as verify:
        assert security.authenticate_user(db, "ssouser", "whatever") is False
    verify.assert_called_once_with("whatever", security._DUMMY_PASSWORD_HASH)


def test_wrong_password_checks_the_real_hash(db, admin_user):
    with patch("backend.security.verify_password", wraps=security.verify_password) as verify:
        assert security.authenticate_user(db, "testadmin", "wrong") is False
    verify.assert_called_once_with("wrong", admin_user.hashed_password)


def test_dummy_hash_has_the_same_cost_as_real_hashes():
    """Même coût bcrypt que les empreintes réelles : même durée de vérification."""
    dummy_prefix = security._DUMMY_PASSWORD_HASH.split("$")[1:3]
    real_prefix = security.get_password_hash("Some@Password123").split("$")[1:3]
    assert dummy_prefix == real_prefix


def test_dummy_hash_never_matches():
    for candidate in ("", "password", "admin", "changez-moi-en-dev"):
        assert not security.verify_password(candidate, security._DUMMY_PASSWORD_HASH)
