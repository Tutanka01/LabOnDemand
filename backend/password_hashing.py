"""Hachage des mots de passe avec bcrypt.

Remplace passlib (plus maintenu, et qui bloquait bcrypt en ``<4.1``) par la
bibliothèque ``bcrypt`` utilisée directement. Module volontairement sans
dépendance applicative (ni Redis, ni base) : les scripts d'administration
peuvent l'importer seuls.

Compatibilité avec les hachages produits par passlib :

- passlib générait des hachages bcrypt standards ``$2b$12$...`` ; les variantes
  ``$2a$`` et ``$2y$`` (autres outils, imports) restent vérifiables ;
- le coût reste 12 pour les nouveaux hachages ;
- **limite de 72 octets** : bcrypt n'utilise que les 72 premiers octets du
  mot de passe encodé en UTF-8. passlib (avec bcrypt < 4.1) les tronquait en
  silence, alors que bcrypt >= 5 lève une erreur au-delà. On applique ici la
  même troncature, explicitement et au niveau de l'octet (même si elle coupe
  un caractère multi-octets), à la vérification *et* au hachage :

  * un utilisateur ayant choisi un mot de passe de plus de 72 octets sous
    passlib continue de se connecter en tapant le même mot de passe ;
  * un hachage produit par ce module est identique, pour un même sel, à celui
    que produisait passlib : les deux implémentations restent interchangeables.

  Rejeter les nouveaux mots de passe trop longs changerait le contrat de l'API
  (inscription, import CSV, changement de mot de passe) sans gain de sécurité
  réel : 72 octets dépassent largement la politique minimale de 12 caractères,
  et seul le mot de passe est haché (aucune concaténation avec un identifiant
  qui pourrait repousser le secret au-delà de la limite).
"""
import logging
from typing import Optional

import bcrypt

logger = logging.getLogger("labondemand.security")

# Coût bcrypt (2^12 itérations), identique à la valeur par défaut de passlib.
BCRYPT_ROUNDS = 12
# bcrypt ignore tout ce qui dépasse 72 octets.
BCRYPT_MAX_PASSWORD_BYTES = 72
# Préfixes bcrypt acceptés à la vérification (``$2b$`` est produit par défaut).
_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")


def _password_bytes(password: str) -> bytes:
    """Encode le mot de passe en UTF-8 et le tronque à la limite de bcrypt.

    Lève ``ValueError`` si le mot de passe contient un octet NUL : bcrypt
    arrêterait sinon le secret à ce caractère (passlib les refusait aussi).
    """
    if not isinstance(password, str):
        raise TypeError("Le mot de passe doit être une chaîne de caractères")
    secret = password.encode("utf-8")
    if b"\x00" in secret:
        raise ValueError("Le mot de passe ne peut pas contenir de caractère NUL")
    return secret[:BCRYPT_MAX_PASSWORD_BYTES]


def hash_password(password: str) -> str:
    """Retourne le hachage bcrypt (``$2b$12$...``) du mot de passe."""
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS, prefix=b"2b")
    return bcrypt.hashpw(_password_bytes(password), salt).decode("ascii")


def verify_password(password: Optional[str], hashed_password: Optional[str]) -> bool:
    """Vérifie un mot de passe contre un hachage bcrypt stocké.

    Ne lève jamais d'exception pour une entrée invalide : un hachage vide
    (comptes SSO), inconnu ou corrompu, ou un mot de passe non valide, donne
    simplement ``False``. Le contenu du hachage n'est jamais journalisé.
    """
    if not isinstance(password, str) or not isinstance(hashed_password, str):
        return False
    if not hashed_password.startswith(_BCRYPT_PREFIXES):
        if hashed_password:
            logger.warning(
                "password_hash_unsupported",
                extra={"extra_fields": {"reason": "unknown_scheme"}},
            )
        return False
    try:
        secret = _password_bytes(password)
    except ValueError:
        return False
    try:
        return bcrypt.checkpw(secret, hashed_password.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        logger.warning(
            "password_hash_unsupported",
            extra={"extra_fields": {"reason": "malformed_hash"}},
        )
        return False
