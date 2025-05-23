from fastapi import FastAPI, HTTPException, Depends, Response, Request
import uvicorn # Importé juste pour pouvoir le lancer depuis ce fichier si besoin
from kubernetes import client, config
import os
import re
import datetime
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, List, Optional

# Importations locales pour l'authentification
from .database import Base, engine, get_db
from sqlalchemy.orm import Session
from .session import setup_session_handler
from .auth_router import router as auth_router
from .security import get_current_user, is_admin, is_teacher_or_admin
from .models import User, UserRole

# Charger les variables d'environnement depuis le fichier .env
load_dotenv()

# Configuration Kubernetes - utilisation uniquement du fichier kubeconfig
config.load_kube_config()

# Crée une instance de l'application FastAPI
# Le titre et la version apparaîtront dans la documentation automatique
app = FastAPI(
    title="LabOnDemand API",
    description="API pour gérer le déploiement de laboratoires à la demande.",
    version="0.7.0",
    debug=True,
)

# Configuration CORS pour permettre les requêtes depuis le frontend
origins = [
    "http://localhost",
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration du middleware de session
setup_session_handler(app)

# Création des tables de base de données au démarrage
Base.metadata.create_all(bind=engine)

# Inclusion des routeurs
from .auth_router import router as auth_router
from .lab_router import router as lab_router

app.include_router(auth_router)
app.include_router(lab_router)

# Endpoint de diagnostic pour vérifier l'authentification
@app.post("/api/v1/diagnostic/test-auth")
async def test_auth(request: Request, db: Session = Depends(get_db)):
    """
    Endpoint de diagnostic pour tester l'authentification
    Ne pas utiliser en production!
    """
    try:
        body = await request.json()
        username = body.get("username")
        password = body.get("password")
        
        if not username or not password:
            return {
                "success": False,
                "message": "Le nom d'utilisateur et le mot de passe sont requis",
                "details": None
            }
        
        from .security import authenticate_user
        user = authenticate_user(db, username, password)
        
        if user:
            return {
                "success": True,
                "message": "Authentification réussie",
                "details": {
                    "user_id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "role": user.role.value,
                    "is_active": user.is_active
                }
            }
        else:
            return {
                "success": False,
                "message": "Échec de l'authentification",
                "details": None
            }
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return {
            "success": False,
            "message": f"Erreur lors de l'authentification: {str(e)}",
            "details": tb
        }

# Fonction pour valider et formater les noms Kubernetes
def validate_k8s_name(name):
    # Remplacer les underscores par des tirets
    name = name.replace('_', '-')
    # Convertir en minuscules
    name = name.lower()
    # Vérifier si le nom est conforme au format RFC 1123
    if not re.match(r'^[a-z0-9]([-a-z0-9]*[a-z0-9])?$', name):
        raise HTTPException(status_code=400, 
                           detail=f"Le nom '{name}' n'est pas valide pour Kubernetes. Les noms doivent être en minuscules, ne contenir que des caractères alphanumériques ou des tirets, et commencer et se terminer par un caractère alphanumérique.")
    return name

# Fonction pour comparer et prendre la plus grande valeur de ressource
def max_resource(res1, res2):
    """
    Compare deux chaînes de ressources (CPU ou mémoire) et retourne la plus grande.
    Supporte les formats:
    - CPU: '100m', '0.1', '1'
    - Mémoire: '100Mi', '1Gi', etc.
    """
    # Convertir les valeurs CPU en millicores
    def parse_cpu(cpu_str):
        if cpu_str.endswith('m'):
            return float(cpu_str[:-1])
        else:
            return float(cpu_str) * 1000
    
    # Convertir les valeurs mémoire en Mi
    def parse_memory(mem_str):
        units = {'Ki': 1/1024, 'Mi': 1, 'Gi': 1024, 'Ti': 1024*1024}
        
        if any(mem_str.endswith(unit) for unit in units.keys()):
            for unit, multiplier in units.items():
                if mem_str.endswith(unit):
                    return float(mem_str[:-len(unit)]) * multiplier
        else:
            # Assume Mi if no unit specified
            return float(mem_str)
    
    # Déterminer le type de ressource et comparer
    if any(u in res1 for u in ['Ki', 'Mi', 'Gi', 'Ti']):
        # Ressource mémoire
        val1 = parse_memory(res1)
        val2 = parse_memory(res2)
        return res1 if val1 > val2 else res2
    else:
        # Ressource CPU
        val1 = parse_cpu(res1)
        val2 = parse_cpu(res2)
        return res1 if val1 > val2 else res2

# Définit une première "route" (endpoint)
# @app.get("/") signifie : quand quelqu'un accède à la racine ("/") via une requête GET HTTP...
@app.get("/")
async def read_root():
    # ...retourne ce dictionnaire (FastAPI le convertira automatiquement en JSON)
    return {"message": "Bienvenue sur l'API LabOnDemand !"}

# Ajoutons un autre endpoint simple pour tester
@app.get("/api/v1/status")
async def get_status():
    return {"status": "API en cours d'exécution", "version": app.version}

# Lister les pods Kubernetes en format liste (admin uniquement)
@app.get("/api/v1/get-pods")
async def get_pods(current_user: User = Depends(get_current_user), is_admin_user: bool = Depends(is_admin)):
    v1 = client.CoreV1Api()
    ret = v1.list_pod_for_all_namespaces(watch=False)
    pods = [{"name": pod.metadata.name, "namespace": pod.metadata.namespace, "ip": pod.status.pod_ip} for pod in ret.items]
    return {"pods": pods}

# Lister les namespaces Kubernetes (admin ou enseignant)
@app.get("/api/v1/get-namespaces")
async def get_namespaces(current_user: User = Depends(get_current_user), is_teacher: bool = Depends(is_teacher_or_admin)):
    v1 = client.CoreV1Api()
    ret = v1.list_namespace(watch=False)
    namespaces = [ns.metadata.name for ns in ret.items]
    return {"namespaces": namespaces}

# Lister les deployments Kubernetes (admin ou enseignant)
@app.get("/api/v1/get-deployments")
async def get_deployments(current_user: User = Depends(get_current_user), is_teacher: bool = Depends(is_teacher_or_admin)):
    v1 = client.AppsV1Api()
    ret = v1.list_deployment_for_all_namespaces(watch=False)
    deployments = [{"name": dep.metadata.name, "namespace": dep.metadata.namespace} for dep in ret.items]
    return {"deployments": deployments}

# Obtenir les détails d'un déploiement, incluant le service et les pods associés (authentifié)
@app.get("/api/v1/get-deployment-details/{namespace}/{name}")
async def get_deployment_details(namespace: str, name: str, current_user: User = Depends(get_current_user)):
    # Valider et formater les noms pour qu'ils soient conformes aux règles Kubernetes
    namespace = validate_k8s_name(namespace)
    name = validate_k8s_name(name)
    
    try:
        # Obtenir le déploiement
        apps_v1 = client.AppsV1Api()
        deployment = apps_v1.read_namespaced_deployment(name, namespace)
        
        # Obtenir les pods associés au déploiement
        core_v1 = client.CoreV1Api()
        pod_list = core_v1.list_namespaced_pod(
            namespace, 
            label_selector=f"app={name}"
        )
        
        # Récupérer les informations des nœuds pour chaque pod
        pods_info = []
        for pod in pod_list.items:
            # Obtenir l'objet node complet pour récupérer ses adresses
            node_name = pod.spec.node_name
            node_info = None
            node_addresses = []
            
            if node_name:
                node = core_v1.read_node(node_name)
                node_addresses = [
                    {"type": addr.type, "address": addr.address}
                    for addr in node.status.addresses
                ]
            
            pods_info.append({
                "name": pod.metadata.name,
                "node_name": node_name,
                "node_addresses": node_addresses,
                "pod_ip": pod.status.pod_ip,
                "status": pod.status.phase
            })
            
        # Obtenir le service associé (basé sur le selector app=name)
        service_list = core_v1.list_namespaced_service(
            namespace,
            label_selector=f"app={name}"
        )
        
        services_info = []
        for svc in service_list.items:
            ports_info = []
            for port in svc.spec.ports:
                port_info = {
                    "name": port.name if hasattr(port, "name") else None,
                    "port": port.port,
                    "target_port": port.target_port,
                    "protocol": port.protocol
                }
                
                # Ajouter le nodePort s'il existe
                if hasattr(port, "node_port") and port.node_port:
                    port_info["node_port"] = port.node_port
                    
                ports_info.append(port_info)
            
            services_info.append({
                "name": svc.metadata.name,
                "type": svc.spec.type,
                "cluster_ip": svc.spec.cluster_ip,
                "ports": ports_info,
                "selectors": svc.spec.selector
            })
            
        # Construire l'URL d'accès pour chaque service exposé
        access_urls = []
        for svc in services_info:
            if svc["type"] == "NodePort" or svc["type"] == "LoadBalancer":
                for port in svc["ports"]:
                    if "node_port" in port:
                        for pod in pods_info:
                            for addr in pod["node_addresses"]:
                                if addr["type"] == "InternalIP" or addr["type"] == "ExternalIP":
                                    access_urls.append({
                                        "service": svc["name"],
                                        "url": f"http://{addr['address']}:{port['node_port']}",
                                        "node": pod["node_name"],
                                        "node_port": port["node_port"]
                                    })
            
        return {
            "deployment": {
                "name": deployment.metadata.name,
                "namespace": deployment.metadata.namespace,
                "replicas": deployment.spec.replicas,
                "available_replicas": deployment.status.available_replicas,
                "image": deployment.spec.template.spec.containers[0].image if deployment.spec.template.spec.containers else None
            },
            "pods": pods_info,
            "services": services_info,
            "access_urls": access_urls
        }
        
    except client.exceptions.ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=404, detail=f"Déploiement {name} non trouvé dans le namespace {namespace}")
        raise HTTPException(status_code=e.status, detail=f"Erreur lors de la récupération des détails: {e.reason}")

# Lister les pods d'un namespace spécifique (admin ou enseignant)
@app.get("/api/v1/get-pods/{namespace}")
async def get_pods_by_namespace(namespace: str, current_user: User = Depends(get_current_user), is_teacher: bool = Depends(is_teacher_or_admin)):
    namespace = validate_k8s_name(namespace)
    v1 = client.CoreV1Api()
    ret = v1.list_namespaced_pod(namespace, watch=False)
    pods = [{"name": pod.metadata.name, "ip": pod.status.pod_ip} for pod in ret.items]
    return {"namespace": namespace, "pods": pods}

# Create new pod with an image and name (admin uniquement)
@app.post("/api/v1/create-pod")
async def create_pod(name: str, image: str, namespace: str = "default", current_user: User = Depends(get_current_user), is_admin_user: bool = Depends(is_admin)):
    # Valider et formater les noms pour qu'ils soient conformes aux règles Kubernetes
    name = validate_k8s_name(name)
    namespace = validate_k8s_name(namespace)
    
    try:
        v1 = client.CoreV1Api()
        pod_manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": name},
            "spec": {
                "containers": [{"name": name, "image": image}]
            }
        }
        v1.create_namespaced_pod(namespace, pod_manifest)
        return {"message": f"Pod {name} créé dans le namespace {namespace} avec l'image {image}"}
    except client.exceptions.ApiException as e:
        raise HTTPException(status_code=e.status, detail=f"Erreur lors de la création du pod: {e.reason} - {e.body}")
## Comment creer le pod ?
# curl -X POST "http://127.0.0.1:8000/api/v1/create-pod?name=mon-pod&image=nginx"

# Supprimer un pod specifique (admin uniquement)
@app.delete("/api/v1/delete-pod/{namespace}/{name}")
async def delete_pod(namespace: str, name: str, current_user: User = Depends(get_current_user), is_admin_user: bool = Depends(is_admin)):
    # Valider et formater les noms pour qu'ils soient conformes aux règles Kubernetes
    namespace = validate_k8s_name(namespace)
    name = validate_k8s_name(name)
    
    try:
        v1 = client.CoreV1Api()
        v1.delete_namespaced_pod(name, namespace)
        return {"message": f"Pod {name} supprimé du namespace {namespace}"}
    except client.exceptions.ApiException as e:
        raise HTTPException(status_code=e.status, detail=f"Erreur lors de la suppression du pod: {e.reason} - {e.body}")
    
## Comment supprimer le pod ?
# curl -X DELETE "http://localhost:8000/api/v1/delete-pod/default/mon-pod"

# Supprimer un déploiement et son service associé (admin ou enseignant)
@app.delete("/api/v1/delete-deployment/{namespace}/{name}")
async def delete_deployment(
    namespace: str, 
    name: str, 
    delete_service: bool = True,
    current_user: User = Depends(get_current_user),
    is_teacher: bool = Depends(is_teacher_or_admin)
):
    # Valider et formater les noms pour qu'ils soient conformes aux règles Kubernetes
    namespace = validate_k8s_name(namespace)
    name = validate_k8s_name(name)
    
    try:
        # Supprimer le déploiement
        apps_v1 = client.AppsV1Api()
        apps_v1.delete_namespaced_deployment(name, namespace)
        
        result_message = f"Déploiement {name} supprimé du namespace {namespace}"
        
        # Supprimer le service associé si demandé
        if delete_service:
            try:
                core_v1 = client.CoreV1Api()
                service_name = f"{name}-service"
                core_v1.delete_namespaced_service(service_name, namespace)
                result_message += f" avec son service {service_name}"
            except client.exceptions.ApiException as e:
                if e.status != 404:  # Ignorer l'erreur si le service n'existe pas
                    result_message += f". Avertissement: Le service {name}-service n'a pas pu être supprimé: {e.reason}"
        
        return {"message": result_message}
    except client.exceptions.ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=404, detail=f"Déploiement {name} non trouvé dans le namespace {namespace}")
        raise HTTPException(status_code=e.status, detail=f"Erreur lors de la suppression du déploiement: {e.reason} - {e.body}")

# Fonction utilitaire pour créer automatiquement des namespaces s'ils n'existent pas
async def ensure_namespace_exists(namespace_name):
    """
    Vérifie si un namespace existe et le crée s'il n'existe pas
    """
    try:
        v1 = client.CoreV1Api()
        try:
            v1.read_namespace(namespace_name)
            print(f"Le namespace {namespace_name} existe déjà.")
            return True
        except client.exceptions.ApiException as e:
            if e.status == 404:
                # Le namespace n'existe pas, on le crée
                namespace_manifest = {
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {
                        "name": namespace_name,
                        "labels": {
                            "managed-by": "labondemand",
                            "created-at": datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
                        }
                    }
                }
                v1.create_namespace(namespace_manifest)
                print(f"Namespace {namespace_name} créé avec succès.")
                return True
            else:
                raise
    except Exception as e:
        print(f"Erreur lors de la vérification/création du namespace {namespace_name}: {e}")
        return False

# Fonction pour déterminer le namespace en fonction du type de déploiement
def get_namespace_for_deployment_type(deployment_type, user_namespace=None):
    """
    Retourne le namespace approprié pour un type de déploiement
    Si user_namespace est fourni, il sera utilisé comme préfixe
    """
    if user_namespace:
        # Si l'utilisateur a spécifié un namespace (cas des enseignants ou admins)
        return user_namespace
    
    # Sinon, on utilise un namespace dédié par type de service
    if deployment_type == "jupyter":
        return "labondemand-jupyter"
    elif deployment_type == "vscode":
        return "labondemand-vscode"
    else:
        return "labondemand-custom"

# Labels standard à appliquer à tous les déploiements gérés par LabOnDemand
def get_labondemand_labels(deployment_type, additional_labels=None):
    """
    Retourne un dictionnaire de labels standard pour les ressources gérées par LabOnDemand
    """
    labels = {
        "managed-by": "labondemand",
        "app-type": deployment_type,
        "created-at": datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    }
    
    # Ajouter les labels supplémentaires s'il y en a
    if additional_labels:
        labels.update(additional_labels)
        
    return labels

# Fonction pour récupérer uniquement les déploiements gérés par LabOnDemand (authentifié)
@app.get("/api/v1/get-labondemand-deployments")
async def get_labondemand_deployments(current_user: User = Depends(get_current_user)):
    """
    Récupère uniquement les déploiements créés par LabOnDemand dans tous les namespaces
    """
    try:
        apps_v1 = client.AppsV1Api()
        deployments = apps_v1.list_deployment_for_all_namespaces(
            label_selector="managed-by=labondemand"
        )
        
        result = []
        for dep in deployments.items:
            result.append({
                "name": dep.metadata.name,
                "namespace": dep.metadata.namespace,
                "labels": dep.metadata.labels,
                "type": dep.metadata.labels.get("app-type", "unknown")
            })
        
        return {"deployments": result}
    except client.exceptions.ApiException as e:
        raise HTTPException(status_code=e.status, detail=f"Erreur Kubernetes: {e.reason}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des déploiements: {str(e)}")

# Creer un deployment avec un service optionnel (VERSION MISE À JOUR)
@app.post("/api/v1/create-deployment")
async def create_deployment(
    name: str, 
    image: str, 
    replicas: int = 1, 
    namespace: str = None,  # Namespace devient optionnel
    create_service: bool = False,
    service_port: int = 80,
    service_target_port: int = 80,
    service_type: str = "ClusterIP",
    deployment_type: str = "custom",
    cpu_request: str = "100m",
    cpu_limit: str = "500m",
    memory_request: str = "128Mi",
    memory_limit: str = "512Mi",
    additional_labels: dict = None,
    current_user: User = Depends(get_current_user)  # Utilisateur connecté requis
):
    # Valider et formater le nom pour qu'il soit conforme aux règles Kubernetes
    name = validate_k8s_name(name)
    
    # Déterminer le namespace approprié
    effective_namespace = get_namespace_for_deployment_type(deployment_type, namespace)
    
    # S'assurer que le namespace existe
    await ensure_namespace_exists(effective_namespace)
    
    # Valider le type de service
    valid_service_types = ["ClusterIP", "NodePort", "LoadBalancer"]
    if service_type not in valid_service_types:
        raise HTTPException(status_code=400, detail=f"Type de service invalide. Types valides: {', '.join(valid_service_types)}")
    
    # Valider les formats des ressources (code existant)
    try:
        # Valider le format des CPU
        if not re.match(r'^(\d+m|[0-9]*\.?[0-9]+)$', cpu_request):
            raise ValueError(f"Format CPU request invalide: {cpu_request}. Utilisez un nombre suivi de 'm' (millicores) ou un nombre décimal.")
        if not re.match(r'^(\d+m|[0-9]*\.?[0-9]+)$', cpu_limit):
            raise ValueError(f"Format CPU limit invalide: {cpu_limit}. Utilisez un nombre suivi de 'm' (millicores) ou un nombre décimal.")
            
        # Valider le format de la mémoire
        if not re.match(r'^(\d+)(Ki|Mi|Gi|Ti|Pi|Ei|[kMGTPE]i?)?$', memory_request):
            raise ValueError(f"Format memory request invalide: {memory_request}. Utilisez un nombre suivi d'une unité (Mi, Gi, etc.).")
        if not re.match(r'^(\d+)(Ki|Mi|Gi|Ti|Pi|Ei|[kMGTPE]i?)?$', memory_limit):
            raise ValueError(f"Format memory limit invalide: {memory_limit}. Utilisez un nombre suivi d'une unité (Mi, Gi, etc.).")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Préparer les labels standards
    labels = get_labondemand_labels(deployment_type, additional_labels)
      # Ajouter l'ID et le rôle de l'utilisateur aux labels
    if additional_labels is None:
        additional_labels = {}
    additional_labels["user-id"] = str(current_user.id)
    additional_labels["user-role"] = current_user.role.value
    
    # Vérifier les permissions selon le rôle
    if current_user.role == UserRole.student:
        # Les étudiants ne peuvent créer que certains types de déploiements et avec des limites
        if deployment_type not in ["jupyter", "vscode"]:
            raise HTTPException(
                status_code=403,
                detail="Les étudiants ne peuvent créer que des environnements Jupyter ou VS Code"
            )
    
    # Adapter les paramètres selon le type de déploiement
    if deployment_type == "vscode":
        # Pour VS Code Online, on utilise l'image spécifique et les paramètres appropriés
        image = "tutanka01/k8s:vscode"
        service_target_port = 8080  # Port sur lequel code-server écoute
        create_service = True  # Toujours créer un service pour VS Code
        service_type = "NodePort"  # Utiliser NodePort pour accéder depuis l'extérieur
        
        # Assurer des ressources minimales pour VS Code
        cpu_request = max_resource(cpu_request, "200m")
        memory_request = max_resource(memory_request, "256Mi")
        
        # Définir les minimums pour VS Code
        min_cpu_limit = "500m"
        min_memory_limit = "512Mi"
        
        # Vérifier que les limites sont au moins égales aux minimums
        cpu_limit = max_resource(cpu_limit, min_cpu_limit)
        memory_limit = max_resource(memory_limit, min_memory_limit)
    
    elif deployment_type == "jupyter":
        # Pour Jupyter Notebook, utiliser l'image Jupyter et configurer les ports appropriés
        image = "tutanka01/k8s:jupyter"
        service_target_port = 8888  # Port sur lequel Jupyter écoute
        create_service = True  # Toujours créer un service pour Jupyter
        service_type = "NodePort"  # Utiliser NodePort pour accéder depuis l'extérieur
        
        # Assurer des ressources minimales pour Jupyter (data science nécessite plus de ressources)
        cpu_request = max_resource(cpu_request, "250m")
        memory_request = max_resource(memory_request, "512Mi")
        
        # Minimums pour Jupyter
        min_cpu_limit = "500m"
        min_memory_limit = "1Gi"
        
        # Vérifier que les limites sont au moins égales aux minimums
        cpu_limit = max_resource(cpu_limit, min_cpu_limit)
        memory_limit = max_resource(memory_limit, min_memory_limit)
    
    try:
        # Créer le laboratoire dans la base de données
        lab_data = {
            "name": name,
            "description": f"Labo {deployment_type} créé le {datetime.datetime.now().strftime('%Y-%m-%d')}",
            "lab_type": deployment_type,
            "k8s_namespace": effective_namespace,
            "deployment_name": name,
            "service_name": f"{name}-service" if create_service else None,
            "owner_id": current_user.id
        }
        
        # Ajouter à la base de données
        db = next(get_db())
        new_lab = Lab(**lab_data)
        db.add(new_lab)
        db.commit()
        
        # Créer le deployment avec les labels LabOnDemand
        apps_v1 = client.AppsV1Api()
        dep_manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": name,
                "labels": labels
            },
            "spec": {
                "replicas": replicas,
                "selector": {
                    "matchLabels": {"app": name}
                },
                "template": {
                    "metadata": {
                        "labels": {
                            "app": name,
                            **labels  # Inclure les labels LabOnDemand
                        }
                    },
                    "spec": {
                        "containers": [{
                            "name": name,
                            "image": image,
                            "ports": [{"containerPort": service_target_port}],
                            "resources": {
                                "requests": {
                                    "cpu": cpu_request,
                                    "memory": memory_request
                                },
                                "limits": {
                                    "cpu": cpu_limit,
                                    "memory": memory_limit
                                }
                            },
                            "livenessProbe": {
                                "httpGet": {
                                    "path": "/",
                                    "port": service_target_port
                                },
                                "initialDelaySeconds": 30,
                                "periodSeconds": 10,
                                "timeoutSeconds": 5
                            },
                            "readinessProbe": {
                                "httpGet": {
                                    "path": "/",
                                    "port": service_target_port
                                },
                                "initialDelaySeconds": 5,
                                "periodSeconds": 5
                            }
                        }]
                    }
                }
            }
        }
        
        apps_v1.create_namespaced_deployment(effective_namespace, dep_manifest)
        
        # Créer le service si demandé
        result_message = f"Deployment {name} créé dans le namespace {effective_namespace} avec l'image {image}"
        result_message += f" (CPU: {cpu_request}-{cpu_limit}, RAM: {memory_request}-{memory_limit})"
        
        if create_service:
            core_v1 = client.CoreV1Api()
            service_manifest = {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {
                    "name": f"{name}-service",
                    "labels": {
                        "app": name,
                        **labels  # Inclure les labels LabOnDemand
                    }
                },
                "spec": {
                    "selector": {"app": name},
                    "type": service_type,
                    "ports": [{
                        "port": service_port,
                        "targetPort": service_target_port,
                        "protocol": "TCP"
                    }]
                }
            }
            
            # Ajouter nodePort si c'est un service de type NodePort ou LoadBalancer
            if service_type in ["NodePort", "LoadBalancer"]:
                # Kubernetes assigne automatiquement un nodePort si non spécifié
                pass
                
            created_service = core_v1.create_namespaced_service(effective_namespace, service_manifest)
            service_port_info = ""
            
            # Récupérer le nodePort s'il est disponible
            if service_type in ["NodePort", "LoadBalancer"]:
                node_port = created_service.spec.ports[0].node_port
                service_port_info = f", NodePort: {node_port}"
            
            # Pour un LoadBalancer, on peut attendre l'assignation d'une IP externe
            if service_type == "LoadBalancer":
                result_message += f". Service {name}-service créé (type: {service_type}, port: {service_port}{service_port_info}). L'adresse IP externe sera disponible une fois attribuée par le fournisseur."
            else:
                result_message += f". Service {name}-service créé (type: {service_type}, port: {service_port}{service_port_info})."
                
            # Ajout d'instructions d'accès
            if service_type == "ClusterIP":
                result_message += f" Accessible dans le cluster via: http://{name}-service:{service_port}/"
            elif service_type == "NodePort":
                result_message += f" Accessible depuis l'extérieur via: http://<IP_DU_NOEUD>:{node_port}/"
            
            # Instructions spécifiques pour VS Code
            if deployment_type == "vscode":
                if service_type == "NodePort":
                    result_message += f" VS Code Online sera accessible à l'adresse http://<IP_DU_NOEUD>:{node_port}/ (mot de passe: labondemand)"
        
        # Ajouter le type de déploiement et les ressources à la réponse
        return {
            "message": result_message, 
            "deployment_type": deployment_type,
            "namespace": effective_namespace,
            "resources": {
                "cpu_request": cpu_request,
                "cpu_limit": cpu_limit,
                "memory_request": memory_request,
                "memory_limit": memory_limit
            }
        }
    except client.exceptions.ApiException as e:
        raise HTTPException(status_code=e.status, detail=f"Erreur lors de la création: {e.reason} - {e.body}")

# Récupérer les templates disponibles (authentifié)
@app.get("/api/v1/get-deployment-templates")
async def get_deployment_templates(current_user: User = Depends(get_current_user)):
    templates = [
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
    return {"templates": templates}

# Récupérer les options de ressources prédéfinies (authentifié)
@app.get("/api/v1/get-resource-presets")
async def get_resource_presets(current_user: User = Depends(get_current_user)):
    # Les présets dépendent du rôle de l'utilisateur
    student_presets = {
        "cpu": [
            {"label": "Faible (0.25 CPU)", "request": "250m", "limit": "500m"},
            {"label": "Moyen (0.5 CPU)", "request": "500m", "limit": "1000m"}
        ],
        "memory": [
            {"label": "Faible (256 Mi)", "request": "256Mi", "limit": "512Mi"},
            {"label": "Moyen (512 Mi)", "request": "512Mi", "limit": "1Gi"}
        ]
    }
    
    teacher_presets = {
        "cpu": [
            {"label": "Très faible (0.1 CPU)", "request": "100m", "limit": "200m"},
            {"label": "Faible (0.25 CPU)", "request": "250m", "limit": "500m"},
            {"label": "Moyen (0.5 CPU)", "request": "500m", "limit": "1000m"},
            {"label": "Élevé (1 CPU)", "request": "1000m", "limit": "2000m"}
        ],
        "memory": [
            {"label": "Très faible (128 Mi)", "request": "128Mi", "limit": "256Mi"},
            {"label": "Faible (256 Mi)", "request": "256Mi", "limit": "512Mi"},
            {"label": "Moyen (512 Mi)", "request": "512Mi", "limit": "1Gi"},
            {"label": "Élevé (1 Gi)", "request": "1Gi", "limit": "2Gi"}
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
    
    # Retourne les présets en fonction du rôle
    if current_user.role == UserRole.admin:
        return admin_presets
    elif current_user.role == UserRole.teacher:
        return teacher_presets
    else:
        return student_presets

# Point d'entrée pour lancer l'API directement
if __name__ == "__main__":
    port = int(os.getenv("API_PORT", 8000))
    debug = os.getenv("DEBUG_MODE", "False").lower() in ["true", "1", "yes"]
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=debug)