from fastapi import FastAPI
import uvicorn # Importé juste pour pouvoir le lancer depuis ce fichier si besoin
from kubernetes import client, config


config.load_kube_config()

# Crée une instance de l'application FastAPI
# Le titre et la version apparaîtront dans la documentation automatique
app = FastAPI(
    title="LabOnDemand API",
    description="API pour gérer le déploiement de laboratoires à la demande.",
    version="0.1.0",
)

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

# Lister les pods Kubernetes
@app.get("/api/v1/get-pods")
async def get_pods():
    v1 = client.CoreV1Api()
    v1 = client.CoreV1Api()
    ret = v1.list_pod_for_all_namespaces(watch=False)
    for i in ret.items:
        return {
            "pod_ip": i.status.pod_ip,
            "namespace": i.metadata.namespace,
            "name": i.metadata.name
        }

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
    v1 = client.CoreV1Api()
    ret = v1.list_namespaced_pod(namespace, watch=False)
    pods = [{"name": pod.metadata.name, "ip": pod.status.pod_ip} for pod in ret.items]
    return {"namespace": namespace, "pods": pods}

# Create new pod with an image and name
@app.post("/api/v1/create-pod")
async def create_pod(name: str, image: str, namespace: str = "default"):
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

## Comment creer le pod ?
# curl -X POST "http://127.0.1:8000/api/v1/create-pod?name=mon_pod&image=nginx&namespace=default"

