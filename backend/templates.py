"""
Templates et presets pour les déploiements
Principe KISS : données structurées simples
"""
from typing import Dict, List, Any
from .models import UserRole

def get_deployment_templates() -> Dict[str, List[Dict[str, Any]]]:
    """
    Retourne les templates de déploiement disponibles
    """
    return {
        "templates": [
            {
                "id": "custom",
                "name": "Déploiement personnalisé",
                "description": "Déployez n'importe quelle image Docker avec exposition réseau optionnelle.",
                "icon": "fa-solid fa-cube",
                "deployment_type": "custom",
                "default_service_type": "NodePort",
                "tags": ["générique", "docker", "custom", "service"]
            },
            {
                "id": "wordpress",
                "name": "WordPress (Web + DB)",
                "description": "Déployer WordPress avec base MariaDB, clés générées automatiquement.",
                "icon": "fa-brands fa-wordpress",
                "default_image": "bitnami/wordpress:latest",
                "default_port": 8080,
                "deployment_type": "wordpress",
                "default_service_type": "NodePort",
                "tags": ["cms", "web", "database"]
            },
            {
                "id": "vscode",
                "name": "VS Code Online",
                "description": "Environnement VS Code dans le navigateur, idéal pour TP et démos. Mot de passe par défaut: labondemand.",
                "icon": "fa-solid fa-code",
                "default_image": "tutanka01/k8s:vscode",
                "default_port": 8080,
                "deployment_type": "vscode",
                "default_service_type": "NodePort",
                "tags": ["ide", "développement", "web", "nodeport", "enseignement"]
            },
            {
                "id": "jupyter",
                "name": "Jupyter Notebook",
                "description": "Jupyter pour data science, avec support notebooks et bibliothèques courantes.",
                "icon": "fa-brands fa-python",
                "default_image": "tutanka01/k8s:jupyter",
                "default_port": 8888,
                "deployment_type": "jupyter",
                "default_service_type": "NodePort",
                "tags": ["data", "notebooks", "python", "apprentissage", "web", "nodeport"]
            }
        ]
    }

def get_resource_presets_for_role(user_role: UserRole) -> Dict[str, List[Dict[str, str]]]:
    """
    Retourne les presets de ressources selon le rôle utilisateur
    """
    student_presets = {
        "cpu": [
            {"label": "Faible (0.1 CPU)", "request": "100m", "limit": "200m"},
            {"label": "Moyen (0.25 CPU)", "request": "250m", "limit": "500m"}
        ],
        "memory": [
            {"label": "Faible (128 Mi)", "request": "128Mi", "limit": "256Mi"},
            {"label": "Moyen (256 Mi)", "request": "256Mi", "limit": "512Mi"},
            {"label": "Élevé (512 Mi)", "request": "512Mi", "limit": "1Gi"}
        ]
    }
    
    teacher_presets = {
        "cpu": [
            {"label": "Faible (0.1 CPU)", "request": "100m", "limit": "200m"},
            {"label": "Moyen (0.25 CPU)", "request": "250m", "limit": "500m"},
            {"label": "Élevé (0.5 CPU)", "request": "500m", "limit": "1000m"}
        ],
        "memory": [
            {"label": "Faible (128 Mi)", "request": "128Mi", "limit": "256Mi"},
            {"label": "Moyen (256 Mi)", "request": "256Mi", "limit": "512Mi"},
            {"label": "Élevé (512 Mi)", "request": "512Mi", "limit": "1Gi"},
            {"label": "Très élevé (1 Gi)", "request": "1Gi", "limit": "2Gi"}
        ]
    }
    
    admin_presets = {
        "cpu": [
            {"label": "Très faible (0.1 CPU)", "request": "100m", "limit": "200m"},
            {"label": "Faible (0.25 CPU)", "request": "250m", "limit": "500m"},
            {"label": "Moyen (0.5 CPU)", "request": "500m", "limit": "1000m"},
            {"label": "Élevé (1 CPU)", "request": "1000m", "limit": "2000m"},
            {"label": "Très élevé (2 CPU)", "request": "2000m", "limit": "4000m"}
        ],
        "memory": [
            {"label": "Très faible (128 Mi)", "request": "128Mi", "limit": "256Mi"},
            {"label": "Faible (256 Mi)", "request": "256Mi", "limit": "512Mi"},
            {"label": "Moyen (512 Mi)", "request": "512Mi", "limit": "1Gi"},
            {"label": "Élevé (1 Gi)", "request": "1Gi", "limit": "2Gi"},
            {"label": "Très élevé (2 Gi)", "request": "2Gi", "limit": "4Gi"}
        ]
    }
    
    presets_map = {
        UserRole.student: student_presets,
        UserRole.teacher: teacher_presets,
        UserRole.admin: admin_presets
    }
    
    return presets_map.get(user_role, student_presets)

class DeploymentConfig:
    """
    Configuration pour les différents types de déploiements
    """
    
    VSCODE_CONFIG = {
        "image": "tutanka01/k8s:vscode",
        "target_port": 8080,
        "service_type": "NodePort",
        "min_cpu_request": "200m",
        "min_memory_request": "256Mi",
        "min_cpu_limit": "500m",
        "min_memory_limit": "512Mi"
    }
    
    JUPYTER_CONFIG = {
        "image": "tutanka01/k8s:jupyter",
        "target_port": 8888,
        "service_type": "NodePort",
        "min_cpu_request": "250m",
        "min_memory_request": "512Mi",
        "min_cpu_limit": "500m",
        "min_memory_limit": "1Gi"
    }
    
    @classmethod
    def get_config(cls, deployment_type: str) -> Dict[str, Any]:
        """Retourne la configuration pour un type de déploiement"""
        configs = {
            "vscode": cls.VSCODE_CONFIG,
            "jupyter": cls.JUPYTER_CONFIG
        }
        return configs.get(deployment_type, {})
