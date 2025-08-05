"""
Routeur pour les opérations Kubernetes
Principe KISS : endpoints focalisés et simples
"""
from fastapi import APIRouter, Depends, HTTPException
from kubernetes import client
from typing import List, Dict, Any, Optional

from .security import get_current_user, is_admin, is_teacher_or_admin
from .models import User
from .k8s_utils import validate_k8s_name
from .deployment_service import deployment_service
from .templates import get_deployment_templates, get_resource_presets_for_role

router = APIRouter(prefix="/api/v1/k8s", tags=["kubernetes"])

# ============= ENDPOINTS DE LISTING =============

@router.get("/pods")
async def get_pods(current_user: User = Depends(get_current_user), _: bool = Depends(is_admin)):
    """Lister tous les pods (admin uniquement)"""
    v1 = client.CoreV1Api()
    ret = v1.list_pod_for_all_namespaces(watch=False)
    pods = [
        {
            "name": pod.metadata.name, 
            "namespace": pod.metadata.namespace, 
            "ip": pod.status.pod_ip
        } 
        for pod in ret.items
    ]
    return {"pods": pods}

@router.get("/namespaces")
async def get_namespaces(current_user: User = Depends(get_current_user), _: bool = Depends(is_teacher_or_admin)):
    """Lister les namespaces (admin ou enseignant)"""
    v1 = client.CoreV1Api()
    ret = v1.list_namespace(watch=False)
    namespaces = [ns.metadata.name for ns in ret.items]
    return {"namespaces": namespaces}

@router.get("/deployments")
async def get_deployments(current_user: User = Depends(get_current_user), _: bool = Depends(is_teacher_or_admin)):
    """Lister tous les déploiements (admin ou enseignant)"""
    v1 = client.AppsV1Api()
    ret = v1.list_deployment_for_all_namespaces(watch=False)
    deployments = [
        {
            "name": dep.metadata.name, 
            "namespace": dep.metadata.namespace
        } 
        for dep in ret.items
    ]
    return {"deployments": deployments}

@router.get("/deployments/labondemand")
async def get_labondemand_deployments(current_user: User = Depends(get_current_user)):
    """Récupérer uniquement les déploiements LabOnDemand"""
    try:
        v1 = client.AppsV1Api()
        # Filtrer par label managed-by=labondemand
        ret = v1.list_deployment_for_all_namespaces(
            label_selector="managed-by=labondemand"
        )
        
        deployments = []
        for dep in ret.items:
            # Extraire le type depuis les labels
            app_type = dep.metadata.labels.get("app-type", "custom") if dep.metadata.labels else "custom"
            
            deployments.append({
                "name": dep.metadata.name,
                "namespace": dep.metadata.namespace,
                "type": app_type,  # Ajouter le type pour le frontend
                "labels": dep.metadata.labels,
                "replicas": dep.spec.replicas,
                "ready_replicas": dep.status.ready_replicas or 0,
                "image": dep.spec.template.spec.containers[0].image if dep.spec.template.spec.containers else "Unknown"
            })
        
        return {"deployments": deployments}
    except client.exceptions.ApiException as e:
        raise HTTPException(status_code=e.status, detail=f"Erreur Kubernetes: {e.reason}")

@router.get("/pods/{namespace}")
async def get_pods_by_namespace(
    namespace: str, 
    current_user: User = Depends(get_current_user), 
    _: bool = Depends(is_teacher_or_admin)
):
    """Lister les pods d'un namespace spécifique"""
    namespace = validate_k8s_name(namespace)
    v1 = client.CoreV1Api()
    ret = v1.list_namespaced_pod(namespace, watch=False)
    pods = [
        {
            "name": pod.metadata.name, 
            "ip": pod.status.pod_ip
        } 
        for pod in ret.items
    ]
    return {"namespace": namespace, "pods": pods}

# ============= ENDPOINTS DE DÉTAILS =============

@router.get("/deployments/{namespace}/{name}/details")
async def get_deployment_details(
    namespace: str, 
    name: str, 
    current_user: User = Depends(get_current_user)
):
    """Obtenir les détails d'un déploiement"""
    namespace = validate_k8s_name(namespace)
    name = validate_k8s_name(name)
    
    try:
        apps_v1 = client.AppsV1Api()
        core_v1 = client.CoreV1Api()
        
        # Récupérer le déploiement
        deployment = apps_v1.read_namespaced_deployment(name, namespace)
        
        # Récupérer les pods associés
        pods = core_v1.list_namespaced_pod(
            namespace, 
            label_selector=f"app={name}"
        )
        
        # Récupérer les services associés
        services = core_v1.list_namespaced_service(namespace, label_selector=f"app={name}")
        
        # Construire les URLs d'accès si des services NodePort existent
        access_urls = []
        service_data = []
        
        for svc in services.items:
            service_info = {
                "name": svc.metadata.name,
                "type": svc.spec.type,
                "cluster_ip": svc.spec.cluster_ip,
                "ports": []
            }
            
            for port in svc.spec.ports or []:
                port_info = {
                    "name": port.name,
                    "port": port.port,
                    "target_port": str(port.target_port) if port.target_port else str(port.port),
                    "protocol": port.protocol
                }
                
                if port.node_port:
                    port_info["node_port"] = port.node_port
                    # Construire l'URL d'accès pour les services NodePort
                    if svc.spec.type == "NodePort":
                        access_urls.append({
                            "url": f"http://localhost:{port.node_port}",
                            "service": svc.metadata.name,
                            "node_port": port.node_port
                        })
                
                service_info["ports"].append(port_info)
            
            service_data.append(service_info)
        
        return {
            "deployment": {
                "name": deployment.metadata.name,
                "namespace": deployment.metadata.namespace,
                "replicas": deployment.spec.replicas,
                "ready_replicas": deployment.status.ready_replicas or 0,
                "available_replicas": deployment.status.available_replicas or 0,
                "image": deployment.spec.template.spec.containers[0].image if deployment.spec.template.spec.containers else None,
                "labels": dict(deployment.metadata.labels) if deployment.metadata.labels else {}
            },
            "pods": [
                {
                    "name": pod.metadata.name,
                    "status": pod.status.phase,
                    "pod_ip": pod.status.pod_ip,
                    "node_name": pod.spec.node_name
                } 
                for pod in pods.items
            ],
            "services": service_data,
            "access_urls": access_urls
        }
        
    except client.exceptions.ApiException as e:
        raise HTTPException(status_code=e.status, detail=f"Erreur: {e.reason}")

# ============= ENDPOINTS DE CRÉATION =============

@router.post("/pods")
async def create_pod(
    name: str, 
    image: str, 
    namespace: str = "default", 
    current_user: User = Depends(get_current_user), 
    _: bool = Depends(is_admin)
):
    """Créer un pod (admin uniquement)"""
    name = validate_k8s_name(name)
    namespace = validate_k8s_name(namespace)
    
    try:
        v1 = client.CoreV1Api()
        pod_manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": name},
            "spec": {
                "containers": [{
                    "name": name,
                    "image": image,
                    "ports": [{"containerPort": 80}]
                }]
            }
        }
        v1.create_namespaced_pod(namespace, pod_manifest)
        return {"message": f"Pod {name} créé avec succès dans le namespace {namespace}"}
    except client.exceptions.ApiException as e:
        raise HTTPException(status_code=e.status, detail=f"Erreur: {e.reason}")

@router.post("/deployments")
async def create_deployment(
    name: str,
    image: str,
    replicas: int = 1,
    namespace: Optional[str] = None,
    create_service: bool = False,
    service_port: int = 80,
    service_target_port: int = 80,
    service_type: str = "ClusterIP",
    deployment_type: str = "custom",
    cpu_request: str = "100m",
    cpu_limit: str = "500m",
    memory_request: str = "128Mi",
    memory_limit: str = "512Mi",
    additional_labels: Optional[Dict[str, str]] = None,
    current_user: User = Depends(get_current_user)
):
    """Créer un déploiement avec service optionnel"""
    return await deployment_service.create_deployment(
        name=name,
        image=image,
        replicas=replicas,
        namespace=namespace,
        create_service=create_service,
        service_port=service_port,
        service_target_port=service_target_port,
        service_type=service_type,
        deployment_type=deployment_type,
        cpu_request=cpu_request,
        cpu_limit=cpu_limit,
        memory_request=memory_request,
        memory_limit=memory_limit,
        additional_labels=additional_labels,
        current_user=current_user
    )

# ============= ENDPOINTS DE SUPPRESSION =============

@router.delete("/pods/{namespace}/{name}")
async def delete_pod(
    namespace: str, 
    name: str, 
    current_user: User = Depends(get_current_user), 
    _: bool = Depends(is_admin)
):
    """Supprimer un pod (admin uniquement)"""
    namespace = validate_k8s_name(namespace)
    name = validate_k8s_name(name)
    
    try:
        v1 = client.CoreV1Api()
        v1.delete_namespaced_pod(name, namespace)
        return {"message": f"Pod {name} supprimé du namespace {namespace}"}
    except client.exceptions.ApiException as e:
        raise HTTPException(status_code=e.status, detail=f"Erreur: {e.reason}")

@router.delete("/deployments/{namespace}/{name}")
async def delete_deployment(
    namespace: str,
    name: str,
    delete_service: bool = True,
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_teacher_or_admin)
):
    """Supprimer un déploiement et son service"""
    namespace = validate_k8s_name(namespace)
    name = validate_k8s_name(name)
    
    try:
        apps_v1 = client.AppsV1Api()
        core_v1 = client.CoreV1Api()
        
        # Supprimer le déploiement
        apps_v1.delete_namespaced_deployment(name, namespace)
        
        # Supprimer le service associé si demandé
        if delete_service:
            try:
                core_v1.delete_namespaced_service(f"{name}-service", namespace)
            except client.exceptions.ApiException:
                pass  # Service n'existe pas
        
        return {"message": f"Déploiement {name} supprimé du namespace {namespace}"}
    except client.exceptions.ApiException as e:
        raise HTTPException(status_code=e.status, detail=f"Erreur: {e.reason}")

# ============= ENDPOINTS DE TEMPLATES ET PRESETS =============

@router.get("/templates")
async def get_deployment_templates_endpoint(current_user: User = Depends(get_current_user)):
    """Récupérer les templates de déploiement"""
    return get_deployment_templates()

@router.get("/resource-presets")
async def get_resource_presets(current_user: User = Depends(get_current_user)):
    """Récupérer les presets de ressources selon le rôle"""
    return get_resource_presets_for_role(current_user.role)
