"""
Utilitaires Kubernetes - Fonctions de base pour les opérations K8s
Principe KISS : fonctions simples et focalisées
"""
import re
import datetime
from typing import Dict, Any, Optional
from fastapi import HTTPException
from kubernetes import client

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
