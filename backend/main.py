from fastapi import FastAPI, HTTPException
import uvicorn # Importé juste pour pouvoir le lancer depuis ce fichier si besoin
from kubernetes import client, config
import os
import re
from dotenv import load_dotenv

# Charger les variables d'environnement depuis le fichier .env
load_dotenv()

# Configuration Kubernetes - utilisation uniquement du fichier kubeconfig
config.load_kube_config()

# Crée une instance de l'application FastAPI
# Le titre et la version apparaîtront dans la documentation automatique
app = FastAPI(
    title="LabOnDemand API",
    description="API pour gérer le déploiement de laboratoires à la demande.",
    version="0.5.1",
)

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

# Lister les pods Kubernetes en format liste
@app.get("/api/v1/get-pods")
async def get_pods():
    v1 = client.CoreV1Api()
    ret = v1.list_pod_for_all_namespaces(watch=False)
    pods = [{"name": pod.metadata.name, "namespace": pod.metadata.namespace, "ip": pod.status.pod_ip} for pod in ret.items]
    return {"pods": pods}

# Lister les namespaces Kubernetes
@app.get("/api/v1/get-namespaces")
async def get_namespaces():
    v1 = client.CoreV1Api()
    ret = v1.list_namespace(watch=False)
    namespaces = [ns.metadata.name for ns in ret.items]
    return {"namespaces": namespaces}

# Lister les deployments Kubernetes
@app.get("/api/v1/get-deployments")
async def get_deployments():
    v1 = client.AppsV1Api()
    ret = v1.list_deployment_for_all_namespaces(watch=False)
    deployments = [{"name": dep.metadata.name, "namespace": dep.metadata.namespace} for dep in ret.items]
    return {"deployments": deployments}

# Obtenir les détails d'un déploiement, incluant le service et les pods associés
@app.get("/api/v1/get-deployment-details/{namespace}/{name}")
async def get_deployment_details(namespace: str, name: str):
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

# Lister les pods d'un namespace spécifique
@app.get("/api/v1/get-pods/{namespace}")
async def get_pods_by_namespace(namespace: str):
    namespace = validate_k8s_name(namespace)
    v1 = client.CoreV1Api()
    ret = v1.list_namespaced_pod(namespace, watch=False)
    pods = [{"name": pod.metadata.name, "ip": pod.status.pod_ip} for pod in ret.items]
    return {"namespace": namespace, "pods": pods}

# Create new pod with an image and name
@app.post("/api/v1/create-pod")
async def create_pod(name: str, image: str, namespace: str = "default"):
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

# Supprimer un pod specifique
@app.delete("/api/v1/delete-pod/{namespace}/{name}")
async def delete_pod(namespace: str, name: str):
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

# Supprimer un déploiement et son service associé
@app.delete("/api/v1/delete-deployment/{namespace}/{name}")
async def delete_deployment(namespace: str, name: str, delete_service: bool = True):
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

# Creer un deployment avec un service optionnel
@app.post("/api/v1/create-deployment")
async def create_deployment(
    name: str, 
    image: str, 
    replicas: int = 1, 
    namespace: str = "default", 
    create_service: bool = False,
    service_port: int = 80,
    service_target_port: int = 80,
    service_type: str = "ClusterIP",
    deployment_type: str = "custom",
    cpu_request: str = "100m",
    cpu_limit: str = "500m",
    memory_request: str = "128Mi",
    memory_limit: str = "512Mi"
):
    # Valider et formater les noms pour qu'ils soient conformes aux règles Kubernetes
    name = validate_k8s_name(name)
    namespace = validate_k8s_name(namespace)
    
    # Valider le type de service
    valid_service_types = ["ClusterIP", "NodePort", "LoadBalancer"]
    if service_type not in valid_service_types:
        raise HTTPException(status_code=400, detail=f"Type de service invalide. Types valides: {', '.join(valid_service_types)}")
    
    # Valider les formats des ressources
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
        
        # Le backend ne devrait pas remplacer les limites de ressources choisies par l'utilisateur
        # sauf si elles sont inférieures aux minimums requis
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
        # Créer le deployment
        apps_v1 = client.AppsV1Api()
        dep_manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": name},
            "spec": {
                "replicas": replicas,
                "selector": {
                    "matchLabels": {"app": name}
                },
                "template": {
                    "metadata": {
                        "labels": {"app": name}
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
        
        apps_v1.create_namespaced_deployment(namespace, dep_manifest)
        
        # Créer le service si demandé
        result_message = f"Deployment {name} créé dans le namespace {namespace} avec l'image {image}"
        result_message += f" (CPU: {cpu_request}-{cpu_limit}, RAM: {memory_request}-{memory_limit})"
        
        if create_service:
            core_v1 = client.CoreV1Api()
            service_manifest = {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {
                    "name": f"{name}-service",
                    "labels": {"app": name}
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
                
            created_service = core_v1.create_namespaced_service(namespace, service_manifest)
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
            "resources": {
                "cpu_request": cpu_request,
                "cpu_limit": cpu_limit,
                "memory_request": memory_request,
                "memory_limit": memory_limit
            }
        }
    except client.exceptions.ApiException as e:
        raise HTTPException(status_code=e.status, detail=f"Erreur lors de la création: {e.reason} - {e.body}")

# Récupérer les templates disponibles
@app.get("/api/v1/get-deployment-templates")
async def get_deployment_templates():
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

# Récupérer les options de ressources prédéfinies
@app.get("/api/v1/get-resource-presets")
async def get_resource_presets():
    presets = {
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
    return presets

# Point d'entrée pour lancer l'API directement
if __name__ == "__main__":
    port = int(os.getenv("API_PORT", 8000))
    debug = os.getenv("DEBUG_MODE", "False").lower() in ["true", "1", "yes"]
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=debug)