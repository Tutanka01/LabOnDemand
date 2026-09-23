"""
Centralized configuration for LabOnDemand.

All settings are read from environment variables (with sensible defaults).
Group overview:

- **API**: title, version, port, debug flag, logging.
- **CORS**: allowed origins (comma-separated ``CORS_ORIGINS`` env var).
- **Kubernetes**: cluster external IP, NodePort mode, user namespace prefix.
- **Ingress**: toggle, base domain, IngressClass, TLS secret, per-type opt-in/out.
- **Sessions**: Redis URL, expiry, cookie flags (SameSite, Secure, Domain),
  rate limiting (storage, login / deployment limits).
- **SSO / OIDC**: issuer, client credentials, redirect URI, role-claim mapping.
- **Admin**: default admin password seeded on first boot.

Usage::

    from .config import settings
    print(settings.INGRESS_BASE_DOMAIN)
"""

import os
from pathlib import Path
from typing import Dict, Set
from urllib.parse import urlparse

from dotenv import load_dotenv
from kubernetes import client, config

# Charger les variables d'environnement
load_dotenv()


class Settings:
    """Configuration centralisée de l'application"""

    # API Configuration
    API_TITLE = "LabOnDemand API"
    API_DESCRIPTION = "API pour gérer le déploiement de laboratoires à la demande."
    API_VERSION = "0.9.0"
    API_PORT = int(os.getenv("API_PORT", 8000))
    DEBUG_MODE = os.getenv("DEBUG_MODE", "False").lower() in ["true", "1", "yes"]
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR = Path(os.getenv("LOG_DIR", Path(__file__).resolve().parents[1] / "logs"))
    LOG_MAX_BYTES = int(
        os.getenv("LOG_MAX_BYTES", str(5 * 1024 * 1024))
    )  # 5 MiB par défaut
    LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "10"))
    LOG_ENABLE_CONSOLE = os.getenv("LOG_ENABLE_CONSOLE", "True").lower() in [
        "true",
        "1",
        "yes",
    ]
    # Rotation spécifique à audit.log (rétention plus longue que app.log / access.log)
    # Par défaut : 10 MiB × 30 archives = ~300 MiB d'historique audit conservés
    AUDIT_LOG_MAX_BYTES = int(
        os.getenv("AUDIT_LOG_MAX_BYTES", str(10 * 1024 * 1024))
    )  # 10 MiB
    AUDIT_LOG_BACKUP_COUNT = int(os.getenv("AUDIT_LOG_BACKUP_COUNT", "30"))

    # CORS Configuration (configurable via env: CORS_ORIGINS="http://foo,https://bar")
    _CORS_ENV = os.getenv("CORS_ORIGINS", "").strip()
    if _CORS_ENV:
        CORS_ORIGINS = [o.strip() for o in _CORS_ENV.split(",") if o.strip()]
    else:
        CORS_ORIGINS = [
            "http://localhost",
            "http://localhost:8000",
            "http://127.0.0.1",
            "http://127.0.0.1:8000",
        ]

    # Kubernetes Configuration
    CLUSTER_EXTERNAL_IP = os.getenv(
        "CLUSTER_EXTERNAL_IP", None
    )  # IP externe du cluster K8s
    # Si True, les URLs NodePort pointent vers l'IP du node où le pod tourne
    # Si False, utilise CLUSTER_EXTERNAL_IP ou une IP générique du cluster
    NODEPORT_USE_POD_NODE_IP = os.getenv(
        "NODEPORT_USE_POD_NODE_IP", "true"
    ).lower() in ["true", "1", "yes"]
    # Préfixe des namespaces utilisateur (un namespace par utilisateur)
    USER_NAMESPACE_PREFIX = os.getenv("USER_NAMESPACE_PREFIX", "labondemand-user")
    # Taille du volume persistant créé pour les labs qui conservent les données
    # (VS Code, Jupyter, bureau VNC). Les PVC existants ne sont pas redimensionnés.
    LAB_PVC_SIZE = os.getenv("LAB_PVC_SIZE", "5Gi").strip() or "5Gi"

    # Ingress Controller
    INGRESS_ENABLED = os.getenv("INGRESS_ENABLED", "false").lower() in [
        "true",
        "1",
        "yes",
    ]
    INGRESS_BASE_DOMAIN = os.getenv("INGRESS_BASE_DOMAIN", "").strip().lower() or None
    INGRESS_CLASS_NAME = os.getenv("INGRESS_CLASS_NAME", "traefik").strip() or None
    INGRESS_TLS_SECRET = os.getenv("INGRESS_TLS_SECRET", "").strip() or None
    INGRESS_DEFAULT_PATH = os.getenv("INGRESS_DEFAULT_PATH", "/") or "/"
    INGRESS_PATH_TYPE = os.getenv("INGRESS_PATH_TYPE", "Prefix").strip() or "Prefix"
    INGRESS_FORCE_TLS_REDIRECT = os.getenv(
        "INGRESS_FORCE_TLS_REDIRECT", "true"
    ).lower() in ["true", "1", "yes"]

    _INGRESS_EXTRA_ANNOTATIONS = os.getenv("INGRESS_EXTRA_ANNOTATIONS", "")
    INGRESS_EXTRA_ANNOTATIONS: Dict[str, str] = {}
    if _INGRESS_EXTRA_ANNOTATIONS:
        for entry in _INGRESS_EXTRA_ANNOTATIONS.split(","):
            if not entry:
                continue
            if "=" in entry:
                key, value = entry.split("=", 1)
                INGRESS_EXTRA_ANNOTATIONS[key.strip()] = value.strip()

    _AUTO_TYPES_RAW = os.getenv(
        "INGRESS_AUTO_TYPES",
        "custom,jupyter,vscode,wordpress,mysql,lamp",
    )
    INGRESS_AUTO_TYPES: Set[str] = {
        item.strip().lower() for item in _AUTO_TYPES_RAW.split(",") if item.strip()
    }

    _EXCLUDE_TYPES_RAW = os.getenv("INGRESS_EXCLUDED_TYPES", "netbeans")
    INGRESS_EXCLUDED_TYPES: Set[str] = {
        item.strip().lower() for item in _EXCLUDE_TYPES_RAW.split(",") if item.strip()
    }

    @staticmethod
    def init_kubernetes():
        """Initialise la configuration Kubernetes"""
        config.load_kube_config()
        # urllib3 (appels REST) ignore les proxies d'environnement, mais
        # websocket-client (exec, port-forward) les route via HTTPS_PROXY :
        # la poignée de main websocket part alors via un proxy qui la coupe
        # (« Connection to remote host was lost. ») alors que le REST marche.
        # On force le chemin direct déjà utilisé par les appels REST, sauf si
        # le kubeconfig déclare explicitement un proxy.
        configuration = client.Configuration.get_default_copy()
        if not (configuration.proxy or configuration.proxy_headers):
            host = (urlparse(configuration.host or "").hostname or "").lower()
            if host:
                for var in ("no_proxy", "NO_PROXY"):
                    entries = [h.strip() for h in os.getenv(var, "").split(",") if h.strip()]
                    if host not in entries:
                        entries.append(host)
                    os.environ[var] = ",".join(entries)

    # Grader Pod (MVP-2) — exécution isolée des tests boîte noire
    # Image du grader (publiée sur le registre du cluster). Voir dockerfiles/grader/.
    GRADER_IMAGE = os.getenv("GRADER_IMAGE", "labondemand/grader:latest")
    # Namespace dédié, verrouillé, où tournent les Jobs grader éphémères.
    GRADER_NAMESPACE = os.getenv("GRADER_NAMESPACE", "labondemand-grader")
    # Filets de sécurité : suppression auto du Job et marge de surveillance.
    GRADER_JOB_TTL_SECONDS = int(os.getenv("GRADER_JOB_TTL_SECONDS", "180"))
    GRADER_POLL_INTERVAL_SECONDS = int(os.getenv("GRADER_POLL_INTERVAL_SECONDS", "3"))
    # Marge ajoutée au timeout de la spec avant de déclarer un run en erreur.
    GRADER_WATCH_GRACE_SECONDS = int(os.getenv("GRADER_WATCH_GRACE_SECONDS", "30"))

    # Namespaces par défaut
    DEFAULT_NAMESPACES = {
        "jupyter": "labondemand-jupyter",
        "vscode": "labondemand-vscode",
        "wordpress": "labondemand-wordpress",
        "mysql": "labondemand-mysql",
        "lamp": "labondemand-lamp",
        "custom": "labondemand-custom",
    }

    # Sessions (Redis)
    # Source unique de vérité pour les cookies de session : session.py et
    # auth_router.py lisent ces valeurs, aucune autre lecture d'environnement.
    REDIS_URL = os.getenv("REDIS_URL", None)
    SESSION_EXPIRY_HOURS = int(os.getenv("SESSION_EXPIRY_HOURS", "24"))
    # Lax par défaut (valeur effective historique) : Strict supprime le cookie
    # lors du retour de l'IdP OIDC et des liens entrants, sans gain réel
    # puisque les requêtes mutantes sont protégées par backend/csrf.py.
    # Normalisé en minuscules ; validé au démarrage (lax, strict, none).
    SESSION_SAMESITE = os.getenv("SESSION_SAMESITE", "Lax").strip().lower() or "lax"
    SECURE_COOKIES = os.getenv("SECURE_COOKIES", "True").lower() in ["true", "1", "yes"]
    # Laisser vide (cookie limité à l'hôte) sauf besoin explicite. Ne doit
    # jamais englober INGRESS_BASE_DOMAIN : contrôle bloquant au démarrage.
    COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", "").strip() or None
    # Limitation de débit (backend/rate_limit.py). Syntaxe « limits » :
    # « 30/minute », « 10/5minute », plusieurs limites séparées par « ; ».
    # Compteurs dans Redis (partagés entre workers) ; RATE_LIMIT_STORAGE_URI
    # permet un stockage dédié (« memory:// » = compteurs par processus).
    RATE_LIMIT_STORAGE_URI = (
        os.getenv("RATE_LIMIT_STORAGE_URI", "").strip() or REDIS_URL or "memory://"
    )
    # Connexion, par IP cliente : assez large pour une salle derrière un NAT.
    RATE_LIMIT_LOGIN = os.getenv("RATE_LIMIT_LOGIN", "").strip() or "30/minute"
    # Échecs de connexion par nom d'utilisateur (toutes IP confondues) ;
    # remis à zéro par une connexion réussie.
    RATE_LIMIT_LOGIN_FAILURES = (
        os.getenv("RATE_LIMIT_LOGIN_FAILURES", "").strip() or "10/15minute"
    )
    # Création de déploiements, par utilisateur authentifié (IP à défaut).
    RATE_LIMIT_DEPLOY = os.getenv("RATE_LIMIT_DEPLOY", "").strip() or "10/5minute"

    # SSO (OpenID Connect — OIDC)
    SSO_ENABLED = os.getenv("SSO_ENABLED", "False").lower() in ["true", "1", "yes"]
    FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "").strip() or None

    # URL de base de l'IdP OIDC (ex: https://sso.univ-pau.fr/cas/oidc)
    OIDC_ISSUER = os.getenv("OIDC_ISSUER", "").strip() or None
    # Identifiants de l'application enregistrée auprès de l'IdP
    OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "").strip() or None
    OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET", "").strip() or None
    # URL de callback (doit correspondre exactement à ce qui est enregistré chez l'IdP)
    # Par défaut: FRONTEND_BASE_URL + /api/v1/auth/sso/callback
    OIDC_REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI", "").strip() or None

    # Mapping des rôles depuis les claims OIDC
    # Claim OIDC contenant le rôle (ex: eduPersonAffiliation pour les universités françaises)
    OIDC_ROLE_CLAIM = os.getenv("OIDC_ROLE_CLAIM", "eduPersonAffiliation").strip()
    OIDC_TEACHER_VALUES = os.getenv(
        "OIDC_TEACHER_VALUES", "staff,employee,faculty,enseignant,teacher"
    )
    OIDC_STUDENT_VALUES = os.getenv("OIDC_STUDENT_VALUES", "student,etudiant")
    OIDC_DEFAULT_ROLE = os.getenv("OIDC_DEFAULT_ROLE", "student").strip().lower()
    # Domaine email de secours si l'IdP ne fournit pas d'email
    OIDC_EMAIL_FALLBACK_DOMAIN = os.getenv(
        "OIDC_EMAIL_FALLBACK_DOMAIN", "sso.local"
    ).strip()
    # TTL du cache de découverte OIDC en secondes (défaut : 1 heure)
    OIDC_DISCOVERY_TTL_SECONDS = int(os.getenv("OIDC_DISCOVERY_TTL_SECONDS", "3600"))

    # Sécurité / Admin
    ADMIN_DEFAULT_PASSWORD = os.getenv("ADMIN_DEFAULT_PASSWORD", None)


# Instance globale des paramètres
settings = Settings()
