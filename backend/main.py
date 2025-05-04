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

# Point d'entrée pour lancer l'API directement
if __name__ == "__main__":
    port = int(os.getenv("API_PORT", 8000))
    debug = os.getenv("DEBUG_MODE", "False").lower() in ["true", "1", "yes"]
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=debug)

