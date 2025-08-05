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
                "description": "Déployer une image Docker de votre choix",
                "icon": "fa-docker"
            },
            {
                "id": "vscode",
                "name": "VS Code Online",
                "description": "Déployer un environnement de développement VS Code accessible via navigateur",
                "icon": "fa-code",
                "default_image": "tutanka01/k8s:vscode",
                "default_port": 8080
            },
            {
                "id": "jupyter",
                "name": "Jupyter Notebook",
                "description": "Déployer un environnement Jupyter Notebook pour l'analyse de données et le machine learning",
                "icon": "fa-chart-line",
                "default_image": "tutanka01/k8s:jupyter",
                "default_port": 8888
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
