"""
Utilitaires Kubernetes - Fonctions de base pour les opérations K8s
Principe KISS : fonctions simples et focalisées
"""
import re
import datetime
from typing import Dict, Any, Optional
from fastapi import HTTPException
from kubernetes import client

# Types légers pour éviter des imports circulaires coûteux
try:
    from .models import User, UserRole  # type: ignore
except Exception:  # lors de l'import utilitaire isolé
    User = Any  # type: ignore
    class UserRole:  # type: ignore
        student = "student"

def validate_k8s_name(name: str) -> str:
    """
    Valide et formate un nom pour Kubernetes
    Applique les règles RFC 1123
    """
    # Nettoyer le nom
    name = name.replace('_', '-').lower()
    
    # Valider le format
    if not re.match(r'^[a-z0-9]([-a-z0-9]*[a-z0-9])?$', name):
        raise HTTPException(
            status_code=400, 
            detail=f"Le nom '{name}' n'est pas valide pour Kubernetes. "
                   f"Les noms doivent être en minuscules, ne contenir que des "
                   f"caractères alphanumériques ou des tirets."
        )
    return name

def parse_cpu_to_millicores(cpu_str: str) -> float:
    """Convertit une valeur CPU en millicores"""
    if cpu_str.endswith('m'):
        return float(cpu_str[:-1])
    else:
        return float(cpu_str) * 1000

def parse_memory_to_mi(mem_str: str) -> float:
    """Convertit une valeur mémoire en Mi"""
    units = {'Ki': 1/1024, 'Mi': 1, 'Gi': 1024, 'Ti': 1024*1024}
    
    for unit, multiplier in units.items():
        if mem_str.endswith(unit):
            return float(mem_str[:-len(unit)]) * multiplier
    
    # Si aucune unité, assume Mi
    return float(mem_str)

def max_resource(res1: str, res2: str) -> str:
    """
    Compare deux ressources et retourne la plus grande
    Supporte CPU (millicores) et mémoire (Mi, Gi, etc.)
    """
    # Déterminer le type de ressource
    is_memory = any(u in res1 for u in ['Ki', 'Mi', 'Gi', 'Ti'])
    
    if is_memory:
        val1 = parse_memory_to_mi(res1)
        val2 = parse_memory_to_mi(res2)
    else:
        val1 = parse_cpu_to_millicores(res1)
        val2 = parse_cpu_to_millicores(res2)
    
    return res1 if val1 > val2 else res2

def create_labondemand_labels(
    deployment_type: str, 
    user_id: str, 
    user_role: str,
    additional_labels: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    """
    Crée les labels standards LabOnDemand
    """
    labels = {
        "managed-by": "labondemand",
        "app-type": deployment_type,
        "user-id": user_id,
        "user-role": user_role,
        "created-at": datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    }
    
    if additional_labels:
        labels.update(additional_labels)
        
    return labels

def get_namespace_for_deployment(deployment_type: str, user_namespace: Optional[str] = None) -> str:
    """
    Détermine le namespace approprié pour un déploiement
    """
    from .config import settings
    
    if user_namespace:
        return user_namespace
    
    return settings.DEFAULT_NAMESPACES.get(deployment_type, "labondemand-custom")

def build_user_namespace(user: Any) -> str:
    """
    Construit le namespace dédié à un utilisateur.
    Format: <prefix>-<user_id>
    """
    from .config import settings
    prefix = validate_k8s_name(settings.USER_NAMESPACE_PREFIX)
    return validate_k8s_name(f"{prefix}-{user.id}")

def should_use_user_namespace(user: Any, deployment_type: str, explicit_namespace: Optional[str]) -> bool:
    """
    Stratégie d'isolation:
    - Étudiants: namespace dédié obligatoire (ignore le namespace explicite non autorisé)
    - Enseignants/Admins: utilisent leur namespace dédié par défaut, sauf si un namespace explicite est fourni
    """
    try:
        role_val = getattr(user.role, "value", str(user.role))
    except Exception:
        role_val = str(getattr(user, "role", ""))
    role_val = str(role_val)
    if role_val == "student":
        return True
    # Pour teacher/admin: si un namespace explicite est fourni, on le respecte, sinon namespace user
    return explicit_namespace is None

def ensure_namespace_baseline(namespace_name: str, role: str) -> bool:
    """
    Applique des garde-fous de base au namespace (idempotent):
    - ResourceQuota (pods, CPU, mémoire)
    - LimitRange (requests/limits par container)
    Retourne True si OK, False si erreur non fatale.
    """
    try:
        core = client.CoreV1Api()
        # Baselines différentes selon le rôle (plus strict pour les étudiants)
        if role == "student":
            rq_hard = {
                "pods": "5",
                "requests.cpu": "2000m",
                "requests.memory": "6Gi",
                "limits.cpu": "4",
                "limits.memory": "8Gi",
                # Limites d'objets (quotas par rôle)
                "count/deployments.apps": "8",
                "count/services": "10",
            }
            lr_default = {"cpu": "500m", "memory": "512Mi"}
            lr_request = {"cpu": "100m", "memory": "128Mi"}
        else:
            rq_hard = {
                "pods": "20",
                "requests.cpu": "4000m",
                "requests.memory": "8Gi",
                "limits.cpu": "8",
                "limits.memory": "16Gi",
                "count/deployments.apps": "20",
                "count/services": "25",
            }
            lr_default = {"cpu": "1000m", "memory": "1Gi"}
            lr_request = {"cpu": "250m", "memory": "256Mi"}

        # ResourceQuota
        rq_name = "baseline-quota"
        try:
            core.read_namespaced_resource_quota(rq_name, namespace_name)
        except client.exceptions.ApiException as e:
            if e.status == 404:
                rq_manifest = {
                    "apiVersion": "v1",
                    "kind": "ResourceQuota",
                    "metadata": {"name": rq_name},
                    "spec": {"hard": rq_hard},
                }
                core.create_namespaced_resource_quota(namespace_name, rq_manifest)
            elif e.status == 403:
                # Pas les droits pour gérer la quota, on ignore sans bloquer
                return True
            else:
                raise

        # LimitRange
        lr_name = "baseline-limits"
        try:
            core.read_namespaced_limit_range(lr_name, namespace_name)
        except client.exceptions.ApiException as e:
            if e.status == 404:
                lr_manifest = {
                    "apiVersion": "v1",
                    "kind": "LimitRange",
                    "metadata": {"name": lr_name},
                    "spec": {
                        "limits": [
                            {
                                "type": "Container",
                                "default": lr_default,
                                "defaultRequest": lr_request,
                            }
                        ]
                    },
                }
                core.create_namespaced_limit_range(namespace_name, lr_manifest)
            elif e.status == 403:
                return True
            else:
                raise

        return True
    except Exception as e:
        print(f"[namespace-baseline] Erreur sur {namespace_name}: {e}")
        return False


def get_role_limits(role: str) -> Dict[str, Any]:
    """Exposer des plafonds cohérents utilisés à la fois pour les ResourceQuota et les vérifications applicatives.
    Retourne: {
      max_apps: int,  # notion logique d'apps (stack wordpress = 1)
      max_requests_cpu_m: int,
      max_requests_mem_mi: int,
      max_pods: int
    }
    """
    if role == "student":
        return {
            "max_apps": 4,
            "max_requests_cpu_m": 2000,
            "max_requests_mem_mi": 6144,
            "max_pods": 5,
        }
    elif role == "teacher":
        return {
            "max_apps": 10,
            "max_requests_cpu_m": 4000,
            "max_requests_mem_mi": 8192,
            "max_pods": 20,
        }
    else:  # admin
        return {
            "max_apps": 100,
            "max_requests_cpu_m": 16000,
            "max_requests_mem_mi": 65536,
            "max_pods": 100,
        }

async def ensure_namespace_exists(namespace_name: str) -> bool:
    """
    Vérifie qu'un namespace existe et le crée si nécessaire
    """
    try:
        v1 = client.CoreV1Api()
        try:
            v1.read_namespace(namespace_name)
            return True
        except client.exceptions.ApiException as e:
            if e.status == 404:
                # Créer le namespace
                namespace_manifest = {
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {
                        "name": namespace_name,
                        "labels": {
                            "managed-by": "labondemand",
                            "created-at": datetime.datetime.now().strftime("%Y-%m-%d")
                        }
                    }
                }
                v1.create_namespace(namespace_manifest)
                print(f"Namespace {namespace_name} créé avec succès")
                return True
            else:
                raise e
    except Exception as e:
        print(f"Erreur lors de la gestion du namespace {namespace_name}: {e}")
        return False

def validate_resource_format(cpu_request: str, cpu_limit: str, memory_request: str, memory_limit: str):
    """
    Valide le format des ressources CPU et mémoire
    """
    # Valider CPU
    for cpu_val, cpu_type in [(cpu_request, "request"), (cpu_limit, "limit")]:
        if not re.match(r'^(\d+m|[0-9]*\.?[0-9]+)$', cpu_val):
            raise ValueError(
                f"Format CPU {cpu_type} invalide: {cpu_val}. "
                f"Utilisez un nombre suivi de 'm' (millicores) ou un nombre décimal."
            )
    
    # Valider mémoire
    for mem_val, mem_type in [(memory_request, "request"), (memory_limit, "limit")]:
        if not re.match(r'^(\d+)(Ki|Mi|Gi|Ti|Pi|Ei|[kMGTPE]i?)?$', mem_val):
            raise ValueError(
                f"Format memory {mem_type} invalide: {mem_val}. "
                f"Utilisez un nombre suivi d'une unité (Mi, Gi, etc.)."
            )


def clamp_resources_for_role(role: str, cpu_request: str, cpu_limit: str, memory_request: str, memory_limit: str, replicas: int) -> Dict[str, Any]:
    """Applique des plafonds stricts selon le rôle.
    Retourne les valeurs corrigées: cpu_request, cpu_limit, memory_request, memory_limit, replicas.
    """
    # Bornes maximales par rôle (sécuritaires; cohérentes avec ensure_namespace_baseline)
    if role == "student":
        max_cpu_req = "500m"
        max_cpu_lim = "1000m"
        max_mem_req = "512Mi"
        max_mem_lim = "1Gi"
        max_replicas = 1
    elif role == "teacher":
        max_cpu_req = "1000m"
        max_cpu_lim = "2000m"
        max_mem_req = "1Gi"
        max_mem_lim = "2Gi"
        max_replicas = 2
    else:  # admin
        max_cpu_req = "2000m"
        max_cpu_lim = "4000m"
        max_mem_req = "2Gi"
        max_mem_lim = "4Gi"
        max_replicas = 5

    def min_resource(a: str, b: str) -> str:
        # retourne la plus petite des deux (pour plafonner)
        is_mem = any(u in a for u in ['Ki', 'Mi', 'Gi', 'Ti']) or any(u in b for u in ['Ki', 'Mi', 'Gi', 'Ti'])
        if is_mem:
            va = parse_memory_to_mi(a)
            vb = parse_memory_to_mi(b)
            return a if va < vb else b
        else:
            va = parse_cpu_to_millicores(a)
            vb = parse_cpu_to_millicores(b)
            return a if va < vb else b

    cpu_request = min_resource(cpu_request, max_cpu_req)
    cpu_limit = min_resource(cpu_limit, max_cpu_lim)
    memory_request = min_resource(memory_request, max_mem_req)
    memory_limit = min_resource(memory_limit, max_mem_lim)
    replicas = min(replicas, max_replicas)

    return {
        "cpu_request": cpu_request,
        "cpu_limit": cpu_limit,
        "memory_request": memory_request,
        "memory_limit": memory_limit,
        "replicas": replicas,
    }
