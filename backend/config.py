"""
Configuration centralisée pour l'application LabOnDemand
Applique le principe KISS pour une configuration simple et claire
"""
import os
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
    CLUSTER_EXTERNAL_IP = os.getenv("CLUSTER_EXTERNAL_IP", None)  # IP externe du cluster K8s
    # Préfixe des namespaces utilisateur (un namespace par utilisateur)
    USER_NAMESPACE_PREFIX = os.getenv("USER_NAMESPACE_PREFIX", "labondemand-user")
    
    @staticmethod
    def init_kubernetes():
        """Initialise la configuration Kubernetes"""
        config.load_kube_config()
    
    # Namespaces par défaut
    DEFAULT_NAMESPACES = {
        "jupyter": "labondemand-jupyter",
        "vscode": "labondemand-vscode",
        "wordpress": "labondemand-wordpress",
        "mysql": "labondemand-mysql",
        "lamp": "labondemand-lamp",
        "custom": "labondemand-custom"
    }

    # Sessions (Redis)
    REDIS_URL = os.getenv("REDIS_URL", None)
    SESSION_EXPIRY_HOURS = int(os.getenv("SESSION_EXPIRY_HOURS", "24"))
    SESSION_SAMESITE = os.getenv("SESSION_SAMESITE", "Lax")
    SECURE_COOKIES = os.getenv("SECURE_COOKIES", "True").lower() in ["true", "1", "yes"]
    COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", None)

    # Sécurité / Admin
    ADMIN_DEFAULT_PASSWORD = os.getenv("ADMIN_DEFAULT_PASSWORD", None)

# Instance globale des paramètres
settings = Settings()
