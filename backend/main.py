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
    version="0.1.0",
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
    service_type: str = "ClusterIP"
):
    # Valider et formater les noms pour qu'ils soient conformes aux règles Kubernetes
    name = validate_k8s_name(name)
    namespace = validate_k8s_name(namespace)
    
    # Valider le type de service
    valid_service_types = ["ClusterIP", "NodePort", "LoadBalancer"]
    if service_type not in valid_service_types:
        raise HTTPException(status_code=400, detail=f"Type de service invalide. Types valides: {', '.join(valid_service_types)}")
    
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
                                    "cpu": "100m",
                                    "memory": "128Mi"
                                },
                                "limits": {
                                    "cpu": "500m",
                                    "memory": "512Mi"
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
        
        return {"message": result_message}
    except client.exceptions.ApiException as e:
        raise HTTPException(status_code=e.status, detail=f"Erreur lors de la création: {e.reason} - {e.body}")


# Point d'entrée pour lancer l'API directement
if __name__ == "__main__":
    port = int(os.getenv("API_PORT", 8000))
    debug = os.getenv("DEBUG_MODE", "False").lower() in ["true", "1", "yes"]
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=debug)

