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
                "id": "lamp",
                "name": "Stack LAMP",
                "description": "Apache + PHP (web), MySQL (DB) et phpMyAdmin (admin DB) en une pile prête à l'emploi.",
                "icon": "fa-solid fa-server",
                "default_image": "php:8.2-apache",  # indicatif; la stack gère les composants
                "default_port": 8080,
                "deployment_type": "lamp",
                "default_service_type": "NodePort",
                "tags": ["web", "php", "apache", "mysql", "phpmyadmin", "apprentissage"]
            },
            {
                "id": "mysql",
                "name": "MySQL + phpMyAdmin",
                "description": "Base MySQL (ClusterIP) avec interface phpMyAdmin exposée pour l’apprentissage.",
                "icon": "fa-solid fa-database",
                "default_image": "mysql:9",  # indicatif; ignoré côté backend stack
                "default_port": 8080,
                "deployment_type": "mysql",
                "default_service_type": "NodePort",
                "tags": ["database", "mysql", "phpmyadmin", "apprentissage"]
            },
            {
                "id": "wordpress",
                "name": "WordPress (Web + DB)",
                "description": "Déployer WordPress avec base MariaDB, clés générées automatiquement.",
                "icon": "fa-brands fa-wordpress",
                "default_image": "bitnamilegacy/wordpress:6.8.2-debian-12-r5",
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
            },
            {
                "id": "netbeans",
                "name": "NetBeans Desktop (NoVNC)",
                "description": "Environnement bureau distant avec NetBeans, accessible via le navigateur (NoVNC).",
                "icon": "fa-solid fa-desktop",
                "default_image": "tutanka01/labondemand:netbeansjava",
                "default_port": 6901,
                "deployment_type": "netbeans",
                "default_service_type": "NodePort",
                "tags": ["bureau", "novnc", "ide", "java"]
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
        "min_cpu_request": "150m",
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
    
    MYSQL_PMA_CONFIG = {
        # L'image côté UI est indicative; la stack utilise mysql:8.0 + phpmyadmin:latest
        "image": "phpmyadmin:latest",
        "target_port": 8080,  # service externe cible 8080 (NodePort), targetPort=80 dans le pod pma
        "service_type": "NodePort",
        # Minimums pour l’UI générique (peu utilisés car stack spécifique)
        "min_cpu_request": "150m",
        "min_memory_request": "128Mi",
        "min_cpu_limit": "300m",
        "min_memory_limit": "256Mi"
    }
    
    LAMP_CONFIG = {
        # Vue d'ensemble pour le runtime; la stack crée 3 composants (web, db, pma)
        "image": "php:8.2-apache",
        "target_port": 8080,  # exposition principale: site web
        "service_type": "NodePort",
        "min_cpu_request": "250m",
        "min_memory_request": "256Mi",
        "min_cpu_limit": "500m",
        "min_memory_limit": "512Mi"
    }
    
    NETBEANS_CONFIG = {
        "image": "tutanka01/labondemand:netbeansjava",
        "target_port": 6901,
        "service_type": "NodePort",
        "min_cpu_request": "500m",
        "min_memory_request": "1Gi",
        "min_cpu_limit": "1000m",
        "min_memory_limit": "2Gi"
    }

    @classmethod
    def get_config(cls, deployment_type: str) -> Dict[str, Any]:
        """Retourne la configuration pour un type de déploiement"""
        configs = {
            "vscode": cls.VSCODE_CONFIG,
            "jupyter": cls.JUPYTER_CONFIG,
            "mysql": cls.MYSQL_PMA_CONFIG,
            "lamp": cls.LAMP_CONFIG,
            "netbeans": cls.NETBEANS_CONFIG
        }
        return configs.get(deployment_type, {})
