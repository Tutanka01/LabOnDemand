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
    
    # CORS Configuration
    CORS_ORIGINS = [
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:8000",
    ]
    
    # Kubernetes Configuration
    @staticmethod
    def init_kubernetes():
        """Initialise la configuration Kubernetes"""
        config.load_kube_config()
    
    # Namespaces par défaut
    DEFAULT_NAMESPACES = {
        "jupyter": "labondemand-jupyter",
        "vscode": "labondemand-vscode",
        "custom": "labondemand-custom"
    }

# Instance globale des paramètres
settings = Settings()
