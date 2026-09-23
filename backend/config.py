"""
Centralized configuration for LabOnDemand.

All settings are read from environment variables (with sensible defaults).
Group overview:

- **API**: title, version, port, debug flag, logging.
- **CORS**: allowed origins (comma-separated ``CORS_ORIGINS`` env var).
- **Kubernetes**: cluster external IP, NodePort mode, user namespace prefix.
- **Ingress**: toggle, base domain, IngressClass, TLS secret, per-type opt-in/out.
- **Sessions**: Redis URL, expiry, cookie flags (SameSite, Secure, Domain).
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
        # Délais REST par défaut (voir backend/k8s_timeouts.py), installés
        # avant tout appel au cluster.
        from .k8s_timeouts import install_default_request_timeout

        install_default_request_timeout(
            Settings.K8S_REQUEST_TIMEOUT_CONNECT, Settings.K8S_REQUEST_TIMEOUT_READ
        )
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

    # ===================== Concurrence & client Kubernetes =====================
    # Délais par défaut (secondes) des appels REST Kubernetes : connexion puis
    # lecture. Un _request_timeout explicite reste prioritaire ; 0 désactive.
    # Les flux (watch, logs suivis) ne reçoivent jamais de délai de lecture.
    K8S_REQUEST_TIMEOUT_CONNECT = float(os.getenv("K8S_REQUEST_TIMEOUT_CONNECT", "5"))
    K8S_REQUEST_TIMEOUT_READ = float(os.getenv("K8S_REQUEST_TIMEOUT_READ", "30"))
    # Taille du pool de threads AnyIO qui exécute les endpoints `def`, les
    # dépendances synchrones et les appels déportés (run_in_threadpool).
    # À garder <= pool_size + max_overflow du moteur SQLAlchemy : chaque thread
    # peut tenir une connexion, au-delà les requêtes attendent le pool DB.
    API_THREADPOOL_SIZE = max(1, int(os.getenv("API_THREADPOOL_SIZE", "40")))
    # Déploiements simultanés (threads dédiés) lors d'un déploiement en masse
    # d'un devoir sur une classe, par requête.
    BULK_SPAWN_CONCURRENCY = max(1, int(os.getenv("BULK_SPAWN_CONCURRENCY", "5")))
    # Grading Runs simultanés lors d'un « lancer les tests sur toute la classe »
    # (par lot ; les runs suivants attendent leur tour en arrière-plan).
    BULK_GRADING_CONCURRENCY = max(1, int(os.getenv("BULK_GRADING_CONCURRENCY", "5")))
    # TTL (s) du verrou Redis de leader de la tâche de nettoyage. Doit dépasser
    # une itération (intervalle + durée d'un cycle). 0 = auto : 2 x intervalle
    # (CLEANUP_INTERVAL_MINUTES), minimum 120 s.
    CLEANUP_LOCK_TTL_SECONDS = max(0, int(os.getenv("CLEANUP_LOCK_TTL_SECONDS", "0")))

    @staticmethod
    def configure_threadpool() -> int:
        """Applique API_THREADPOOL_SIZE au limiteur de threads AnyIO par défaut.

        Le limiteur est propre à la boucle d'événements : appeler depuis un
        événement de démarrage de l'application. Retourne la taille appliquée.
        """
        import anyio.to_thread

        limiter = anyio.to_thread.current_default_thread_limiter()
        limiter.total_tokens = Settings.API_THREADPOOL_SIZE
        return int(limiter.total_tokens)
    # ===================== Fin concurrence & client Kubernetes =====================

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
    REDIS_URL = os.getenv("REDIS_URL", None)
    SESSION_EXPIRY_HOURS = int(os.getenv("SESSION_EXPIRY_HOURS", "24"))
    SESSION_SAMESITE = os.getenv("SESSION_SAMESITE", "Strict")
    SECURE_COOKIES = os.getenv("SECURE_COOKIES", "True").lower() in ["true", "1", "yes"]
    COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", None)

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
