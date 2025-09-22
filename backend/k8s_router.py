"""
Routeur pour les opérations Kubernetes
Principe KISS : endpoints focalisés et simples
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi import WebSocket, WebSocketDisconnect
from kubernetes import client
from typing import List, Dict, Any, Optional
import urllib3

from .security import get_current_user, is_admin, is_teacher_or_admin
from .session_store import session_store
from .models import User, UserRole, Template, RuntimeConfig
from .k8s_utils import validate_k8s_name, parse_cpu_to_millicores, parse_memory_to_mi
from .deployment_service import deployment_service
from .templates import get_deployment_templates, get_resource_presets_for_role
from .config import settings
from sqlalchemy.orm import Session
from .database import get_db
from . import schemas
import base64
import asyncio
import threading
from kubernetes.stream import stream as k8s_stream

router = APIRouter(prefix="/api/v1/k8s", tags=["kubernetes"])

# ============= ENDPOINTS DE LISTING =============

# Helper centralisé pour mapper les erreurs K8s -> HTTPException propres
def _raise_k8s_http(e: Exception):
    try:
        # ApiException du client Kubernetes
        if isinstance(e, client.exceptions.ApiException):
            status = getattr(e, "status", 500) or 500
            reason = getattr(e, "reason", None) or str(e)
            # Harmoniser le message 503
            if status == 503:
                reason = "Kubernetes apiserver indisponible (503: Service Unavailable)"
            raise HTTPException(status_code=status, detail=reason)

        # Erreurs de connexion sous-jacentes (urllib3)
        if isinstance(e, (urllib3.exceptions.MaxRetryError, urllib3.exceptions.NewConnectionError)):
            raise HTTPException(status_code=503, detail="Impossible de joindre l'API Kubernetes (connexion refusée)")

        # Timeouts / OS
        if isinstance(e, (TimeoutError, ConnectionError, OSError)):
            raise HTTPException(status_code=503, detail="Kubernetes indisponible (erreur de connexion)")

        # Fallback générique
        raise HTTPException(status_code=500, detail=f"Erreur Kubernetes: {str(e)}")
    except HTTPException:
        # Laisser passer tel quel
        raise


# ============= AUTH POUR WEBSOCKETS (TERMINAL) =============

async def _ws_authenticate_and_authorize_terminal(websocket: WebSocket, namespace: str, pod_name: str) -> dict:
    """Vérifie la session via cookie et l'accès au pod ciblé.
    Retourne un dict {user_id, role} en cas de succès, sinon lève HTTPException-like via close.
    """
    # Extraire le cookie de session
    session_id = (websocket.cookies or {}).get("session_id")
    if not session_id:
        await websocket.close(code=4401)
        raise WebSocketDisconnect(code=4401)

    sess = session_store.get(session_id)
    if not sess:
        await websocket.close(code=4401)
        raise WebSocketDisconnect(code=4401)

    # Vérifier le pod et les labels
    core_v1 = client.CoreV1Api()
    try:
        pod = core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
    except Exception:
        await websocket.close(code=4404)
        raise WebSocketDisconnect(code=4404)

    labels = pod.metadata.labels or {}
    managed = labels.get("managed-by")
    owner_id = labels.get("user-id")
    role = sess.get("role")
    user_id = sess.get("user_id")

    # Autorisation: les étudiants ne peuvent accéder qu'à leurs pods LabOnDemand
    if role == UserRole.student.value:
        if managed != "labondemand" or owner_id != str(user_id):
            await websocket.close(code=4403)
            raise WebSocketDisconnect(code=4403)
        # Durcissement: empêcher l'accès terminal aux pods de base de données (mysql/mariadb)
        comp = (pod.metadata.labels or {}).get("component", "")
        app_type = (pod.metadata.labels or {}).get("app-type", "")
        if comp == "database" and app_type in {"mysql", "wordpress", "lamp"}:
            await websocket.close(code=4403)
            raise WebSocketDisconnect(code=4403)
    else:
        # Enseignants/Admins: limiter aux ressources LabOnDemand par prudence
        if managed != "labondemand":
            await websocket.close(code=4403)
            raise WebSocketDisconnect(code=4403)

    return {"user_id": user_id, "role": role}


# ============= WEBSOCKET TERMINAL POD (exec) =============

@router.websocket("/terminal/{namespace}/{pod}")
async def ws_pod_terminal(websocket: WebSocket, namespace: str, pod: str):
    """Terminal web sans SSH: ouvre un exec /bin/sh dans le pod ciblé (TTY),
    et relaye l'entrée/sortie via WebSocket. Limité aux ressources LabOnDemand.
    Requiert cookie de session pour auth.
    """
    namespace = validate_k8s_name(namespace)
    pod = validate_k8s_name(pod)

    await websocket.accept()

    # Auth + autorisation
    try:
        _ = await _ws_authenticate_and_authorize_terminal(websocket, namespace, pod)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close(code=1011)
        finally:
            return

    # Paramètres optionnels: container & commande par query string
    container = websocket.query_params.get("container")
    # Commande par défaut: /bin/sh
    cmd = websocket.query_params.get("cmd") or "/bin/sh"
    command = [cmd]
    # Ajuster pour un environnement coloré (non bloquant si absent)
    if cmd == "/bin/sh":
        command = ["/bin/sh"]

    core_v1 = client.CoreV1Api()
    ws_client = None
    loop = asyncio.get_event_loop()
    closed = False

    try:
        # Ouvrir un exec websocket vers le pod
        ws_client = k8s_stream(
            core_v1.connect_get_namespaced_pod_exec,
            pod,
            namespace,
            container=container,
            command=command,
            stderr=True,
            stdin=True,
            stdout=True,
            tty=True,
            _preload_content=False,
        )

        # Thread lecteur depuis le pod -> client
        def _reader():
            try:
                while True:
                    out = None
                    err = None
                    try:
                        out = ws_client.read_stdout(timeout=1)
                    except Exception:
                        pass
                    try:
                        err = ws_client.read_stderr(timeout=1)
                    except Exception:
                        pass
                    if out:
                        loop.call_soon_threadsafe(asyncio.create_task, websocket.send_text(out))
                    if err:
                        loop.call_soon_threadsafe(asyncio.create_task, websocket.send_text(err))
                    if getattr(ws_client, "is_closed", False):
                        break
            except Exception:
                # Fin silencieuse
                pass

        reader_thread = threading.Thread(target=_reader, daemon=True)
        reader_thread.start()

        # Envoyer une première taille si fournie par le client via message JSON
        # Boucle de réception: texte normal -> stdin; JSON {type: 'resize', cols, rows}
        while True:
            try:
                msg = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            except Exception:
                break
            if not msg:
                continue
            # Détecter un JSON de resize
            if msg.startswith("{"):
                try:
                    import json as _json
                    payload = _json.loads(msg)
                    if payload.get("type") == "resize":
                        cols = int(payload.get("cols") or 80)
                        rows = int(payload.get("rows") or 24)
                        try:
                            ws_client.resize_terminal(width=cols, height=rows)
                        except Exception:
                            pass
                        continue
                except Exception:
                    # Si pas un JSON valide, traiter comme entrée utilisateur
                    pass
            # Écrire sur stdin du conteneur
            try:
                ws_client.write_stdin(msg)
            except Exception:
                break

    finally:
        try:
            closed = True
            if ws_client is not None:
                try:
                    ws_client.close()
                except Exception:
                    pass
        finally:
            try:
                if websocket.client_state.value == 1:  # CONNECTED
                    await websocket.close()
            except Exception:
                pass


# ============= ENDPOINT STATS CLUSTER/NODES (ADMIN) =============

def _parse_cpu_metrics_to_millicores(cpu: str) -> float:
    """Convertit une valeur CPU des metrics (ex: '123456789n', '250m', '1') en millicores."""
    try:
        s = str(cpu).strip()
        if s.endswith('n'):  # nanocores -> m
            return float(s[:-1]) / 1_000_000.0
        if s.endswith('u'):  # microcores éventuels
            return float(s[:-1]) / 1000.0
        if s.endswith('m'):
            return float(s[:-1])
        # sinon considéré comme cores
        return float(s) * 1000.0
    except Exception:
        # Fallback prudent
        return 0.0


@router.get("/stats/cluster")
async def get_cluster_stats(
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin)
):
    """Statistiques globales du cluster et par nœud (admin seulement).
    - Tente d'utiliser metrics-server; sinon fallback en sommant les requests des pods par nœud.
    - Renvoie des unités simples: cpu_m (millicores), mem_mi (Mi), avec pourcentages calculés.
    """
    try:
        core_v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()

        # Données globales
        nodes_resp = core_v1.list_node()
        deployments_resp = apps_v1.list_deployment_for_all_namespaces()
        pods_resp = core_v1.list_pod_for_all_namespaces()
        namespaces_resp = core_v1.list_namespace()

        # Index pods par nœud (pour fallback)
        pods_by_node: Dict[str, list] = {}
        for pod in pods_resp.items:
            node_name = getattr(pod.spec, 'node_name', None) or getattr(pod.spec, 'nodeName', None)
            if node_name:
                pods_by_node.setdefault(node_name, []).append(pod)

        # Essayer de récupérer les metrics du cluster (metrics.k8s.io)
        metrics_index: Dict[str, Dict[str, Any]] = {}
        try:
            custom_api = client.CustomObjectsApi()
            metrics_nodes = custom_api.list_cluster_custom_object(
                group="metrics.k8s.io", version="v1beta1", plural="nodes"
            )
            for item in metrics_nodes.get('items', []):
                name = (item.get('metadata') or {}).get('name')
                if name:
                    metrics_index[name] = item.get('usage') or {}
        except Exception:
            # Pas de metrics-server ou accès refusé -> fallback
            metrics_index = {}

        # Compteurs globaux
        deployments = deployments_resp.items
        pods = pods_resp.items
        namespaces = namespaces_resp.items

        deployments_count = len(deployments)
        pods_count = len(pods)
        namespaces_count = len(namespaces)
        nodes_count = len(nodes_resp.items)
        ready_deployments = sum(1 for d in deployments if (getattr(d.status, 'ready_replicas', 0) or 0) > 0)
        lab_apps_count = sum(1 for d in deployments if (getattr(d.metadata, 'labels', {}) or {}).get('managed-by') == 'labondemand')

        # Détails par nœud
        nodes_data: list[Dict[str, Any]] = []
        for node in nodes_resp.items:
            name = node.metadata.name
            labels = node.metadata.labels or {}
            alloc_cpu_m = parse_cpu_to_millicores(node.status.allocatable.get('cpu', '0')) if node.status.allocatable else 0.0
            cap_cpu_m = parse_cpu_to_millicores(node.status.capacity.get('cpu', '0')) if node.status.capacity else 0.0
            alloc_mem_mi = parse_memory_to_mi(node.status.allocatable.get('memory', '0Mi')) if node.status.allocatable else 0.0
            cap_mem_mi = parse_memory_to_mi(node.status.capacity.get('memory', '0Mi')) if node.status.capacity else 0.0

            # Usage CPU/Mem: metrics ou fallback requests
            usage_cpu_m = 0.0
            usage_mem_mi = 0.0
            m = metrics_index.get(name)
            if m:
                usage_cpu_m = _parse_cpu_metrics_to_millicores(str(m.get('cpu', '0')))
                usage_mem_mi = parse_memory_to_mi(str(m.get('memory', '0Mi')))
            else:
                for pod in pods_by_node.get(name, []):
                    for c in (getattr(pod.spec, 'containers', None) or []):
                        res = getattr(c, 'resources', None)
                        if res and res.requests:
                            cpu_req = res.requests.get('cpu')
                            mem_req = res.requests.get('memory')
                            if cpu_req:
                                try:
                                    usage_cpu_m += parse_cpu_to_millicores(str(cpu_req))
                                except Exception:
                                    pass
                            if mem_req:
                                try:
                                    usage_mem_mi += parse_memory_to_mi(str(mem_req))
                                except Exception:
                                    pass

            # Statut Ready
            ready = False
            for cond in (node.status.conditions or []):
                if getattr(cond, 'type', '') == 'Ready':
                    ready = (getattr(cond, 'status', '') == 'True')
                    break

            # Rôles
            roles: list[str] = []
            for k, v in labels.items():
                if k.startswith('node-role.kubernetes.io/'):
                    role = k.split('/', 1)[1] or 'worker'
                    roles.append(role)
            if not roles:
                # heuristique simple
                roles = ['control-plane'] if labels.get('node-role.kubernetes.io/control-plane') is not None else ['worker']

            pods_on_node = len(pods_by_node.get(name, []))
            version = getattr(getattr(node.status, 'node_info', None), 'kubelet_version', '')

            def pct(part: float, whole: float) -> float:
                return round((part / whole * 100.0), 1) if whole and part >= 0 else 0.0

            nodes_data.append({
                "name": name,
                "ready": ready,
                "roles": roles,
                "kubelet_version": version,
                "pods": pods_on_node,
                "cpu": {
                    "usage_m": round(usage_cpu_m, 1),
                    "allocatable_m": round(alloc_cpu_m, 1),
                    "capacity_m": round(cap_cpu_m, 1),
                    "usage_pct": pct(usage_cpu_m, alloc_cpu_m or cap_cpu_m)
                },
                "memory": {
                    "usage_mi": round(usage_mem_mi, 1),
                    "allocatable_mi": round(alloc_mem_mi, 1),
                    "capacity_mi": round(cap_mem_mi, 1),
                    "usage_pct": pct(usage_mem_mi, alloc_mem_mi or cap_mem_mi)
                }
            })

        return {
            "k8s_available": True,
            "cluster": {
                "nodes": nodes_count,
                "deployments": deployments_count,
                "deployments_ready": ready_deployments,
                "lab_apps": lab_apps_count,
                "pods": pods_count,
                "namespaces": namespaces_count,
            },
            "nodes": nodes_data,
        }
    except Exception as e:
        # Mode dégradé
        print(f"[cluster-stats] Erreur: {e}")
        return {
            "k8s_available": False,
            "cluster": {"nodes": 0, "deployments": 0, "deployments_ready": 0, "lab_apps": 0, "pods": 0, "namespaces": 0},
            "nodes": []
        }

@router.get("/ping")
async def ping_k8s(current_user: User = Depends(get_current_user)):
    """Vérifie la disponibilité de l'API Kubernetes (léger)."""
    try:
        v1 = client.CoreV1Api()
        # Requête très légère: limiter à 1 item
        v1.list_namespace(_preload_content=False, limit=1)
        return {"k8s": True}
    except Exception:
        # Mode dégradé: indiquer indisponible mais ne pas renvoyer d'erreur HTTP
        return {"k8s": False}

@router.get("/pods")
async def get_pods(current_user: User = Depends(get_current_user), _: bool = Depends(is_admin)):
    """Lister tous les pods (admin uniquement)"""
    try:
        v1 = client.CoreV1Api()
        ret = v1.list_pod_for_all_namespaces(watch=False)
        pods = [
            {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "ip": pod.status.pod_ip,
            }
            for pod in ret.items
        ]
        return {"pods": pods, "k8s_available": True}
    except Exception:
        # Mode dégradé: retourner une liste vide
        return {"pods": [], "k8s_available": False}

@router.get("/namespaces")
async def get_namespaces(current_user: User = Depends(get_current_user), _: bool = Depends(is_teacher_or_admin)):
    """Lister les namespaces (admin ou enseignant)"""
    try:
        v1 = client.CoreV1Api()
        ret = v1.list_namespace(watch=False)
        namespaces = [ns.metadata.name for ns in ret.items]
        return {"namespaces": namespaces, "k8s_available": True}
    except Exception:
        return {"namespaces": [], "k8s_available": False}

@router.get("/deployments")
async def get_deployments(current_user: User = Depends(get_current_user), _: bool = Depends(is_teacher_or_admin)):
    """Lister tous les déploiements (admin ou enseignant)"""
    try:
        v1 = client.AppsV1Api()
        ret = v1.list_deployment_for_all_namespaces(watch=False)
        deployments = [
            {
                "name": dep.metadata.name,
                "namespace": dep.metadata.namespace,
            }
            for dep in ret.items
        ]
        return {"deployments": deployments, "k8s_available": True}
    except Exception:
        return {"deployments": [], "k8s_available": False}

# ============= USAGE PAR APPLICATION (UTILISATEUR) =============

@router.get("/usage/my-apps")
async def get_my_apps_usage(current_user: User = Depends(get_current_user)):
    """Retourne l’usage CPU/Mémoire par application de l’utilisateur courant.
    - Tente d’utiliser metrics-server (metrics.k8s.io) pour l’usage temps-réel.
    - Fallback: somme des requests des containers si metrics indisponible.
    - Agrégation par stack-name si présent, sinon par label app (nom du déploiement).
    - Uniquement les ressources managées par LabOnDemand (labels managed-by=labondemand,user-id=<id>)."""
    try:
        core_v1 = client.CoreV1Api()
        # Lister les pods de l’utilisateur (labels)
        label_selector = f"managed-by=labondemand,user-id={current_user.id}"
        pods_list = core_v1.list_pod_for_all_namespaces(label_selector=label_selector)

        # Index pods -> labels utiles
        tracked_pods = {}
        for pod in pods_list.items:
            labels = pod.metadata.labels or {}
            namespace = pod.metadata.namespace
            name = pod.metadata.name
            group_key = labels.get("stack-name") or labels.get("app") or name
            app_type = labels.get("app-type", labels.get("component", "custom"))
            tracked_pods[(namespace, name)] = {
                "group": group_key,
                "namespace": namespace,
                "app_type": app_type,
            }

        # Préparer l’agrégateur
        usage_index: dict[tuple[str, str], dict] = {}

        # Essayer metrics-server
        metrics_ok = False
        try:
            custom_api = client.CustomObjectsApi()
            pods_metrics = custom_api.list_cluster_custom_object(
                group="metrics.k8s.io", version="v1beta1", plural="pods"
            )
            for item in pods_metrics.get("items", []):
                ns = (item.get("metadata") or {}).get("namespace")
                pod_name = (item.get("metadata") or {}).get("name")
                key = (ns, pod_name)
                if key not in tracked_pods:
                    continue
                entry = tracked_pods[key]
                grp = (entry["namespace"], entry["group"])  # (namespace, app/stack)
                agg = usage_index.setdefault(grp, {
                    "name": entry["group"],
                    "namespace": entry["namespace"],
                    "app_type": entry["app_type"],
                    "cpu_m": 0.0,
                    "mem_mi": 0.0,
                    "pods": set(),
                })
                # Additionner les containers
                for c in item.get("containers", []):
                    usage = c.get("usage", {})
                    cpu = _parse_cpu_metrics_to_millicores(str(usage.get("cpu", "0")))
                    mem_mi = parse_memory_to_mi(str(usage.get("memory", "0Mi")))
                    agg["cpu_m"] += cpu
                    agg["mem_mi"] += mem_mi
                agg["pods"].add(pod_name)
            metrics_ok = True
        except Exception:
            metrics_ok = False

        # Fallback: si aucun metrics, utiliser requests
        if not metrics_ok:
            for pod in pods_list.items:
                key = (pod.metadata.namespace, pod.metadata.name)
                entry = tracked_pods.get(key)
                if not entry:
                    continue
                grp = (entry["namespace"], entry["group"])  # (namespace, app/stack)
                agg = usage_index.setdefault(grp, {
                    "name": entry["group"],
                    "namespace": entry["namespace"],
                    "app_type": entry["app_type"],
                    "cpu_m": 0.0,
                    "mem_mi": 0.0,
                    "pods": set(),
                })
                # Somme des requests des containers
                for c in (getattr(pod.spec, 'containers', None) or []):
                    res = getattr(c, 'resources', None)
                    if res and res.requests:
                        cpu_req = res.requests.get('cpu')
                        mem_req = res.requests.get('memory')
                        if cpu_req:
                            try:
                                agg["cpu_m"] += parse_cpu_to_millicores(str(cpu_req))
                            except Exception:
                                pass
                        if mem_req:
                            try:
                                agg["mem_mi"] += parse_memory_to_mi(str(mem_req))
                            except Exception:
                                pass
                agg["pods"].add(pod.metadata.name)

        # Construire la réponse, triée par CPU desc
        items = []
        for (_, _), v in usage_index.items():
            items.append({
                "name": v["name"],
                "namespace": v["namespace"],
                "app_type": v["app_type"],
                "cpu_m": round(v["cpu_m"], 1),
                "mem_mi": round(v["mem_mi"], 1),
                "pods": len(v["pods"]),
                "source": "live" if metrics_ok else "requests"
            })
        items.sort(key=lambda x: x["cpu_m"], reverse=True)
        return {"items": items, "k8s_available": True, "metrics": metrics_ok}

    except Exception as e:
        print(f"[my-apps-usage] Erreur: {e}")
        return {"items": [], "k8s_available": False, "metrics": False}

# ============= ENDPOINT QUOTAS UTILISATEUR =============

from fastapi import APIRouter as _APIRouter2  # évite l'erreur d'import croisé si renommage
quotas_router = _APIRouter2(prefix="/api/v1/quotas", tags=["quotas"])

@quotas_router.get("/me")
async def get_my_quotas(current_user: User = Depends(get_current_user)):
    try:
        return deployment_service.get_user_quota_summary(current_user)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur quotas: {e}")

@router.get("/deployments/labondemand")
async def get_labondemand_deployments(current_user: User = Depends(get_current_user)):
    """Récupérer uniquement les déploiements LabOnDemand"""
    try:
        v1 = client.AppsV1Api()
        # Toujours filtrer par user-id pour n'afficher que les labs de l'utilisateur courant
        label_selector = f"managed-by=labondemand,user-id={current_user.id}"
        ret = v1.list_deployment_for_all_namespaces(label_selector=label_selector)
        
        # Regrouper par stack si présent (labels stack-name)
        stacks: Dict[str, Dict[str, Any]] = {}
        singles: list = []

        for dep in ret.items:
            labels = dep.metadata.labels or {}
            stack_name = labels.get("stack-name")
            app_type = labels.get("app-type", "custom")
            dep_name = dep.metadata.name or ""

            # Fallback heuristique: stack WordPress sans labels
            if not stack_name and app_type == "wordpress":
                if dep_name.endswith("-mariadb"):
                    stack_name = dep_name[: -len("-mariadb")]
                else:
                    stack_name = dep_name

            entry = {
                "name": dep.metadata.name,
                "namespace": dep.metadata.namespace,
                "type": app_type,
                "labels": labels,
                "replicas": dep.spec.replicas,
                "ready_replicas": dep.status.ready_replicas or 0,
                "image": dep.spec.template.spec.containers[0].image if dep.spec.template.spec.containers else "Unknown"
            }

            if stack_name:
                # pour une stack, on expose un seul item avec le nom de la stack
                agg = stacks.get(stack_name)
                if not agg:
                    stacks[stack_name] = {
                        "name": stack_name,
                        "namespace": dep.metadata.namespace,
                        "type": app_type,
                        "labels": labels,
                        "replicas": dep.spec.replicas,
                        "ready_replicas": dep.status.ready_replicas or 0,
                        "components": [entry],
                    }
                else:
                    agg["components"].append(entry)
                    # consolider readiness simple: si au moins un composant ready, laisser comme tel; sinon prendre min
                    agg["ready_replicas"] = max(agg.get("ready_replicas", 0), entry["ready_replicas"])
            else:
                singles.append(entry)

        # Concaténer: stacks (une entrée par stack) + déploiements unitaires
        deployments = list(stacks.values()) + singles
        return {"deployments": deployments, "k8s_available": True}
    except Exception:
        return {"deployments": [], "k8s_available": False}

@router.get("/pods/{namespace}")
async def get_pods_by_namespace(
    namespace: str, 
    current_user: User = Depends(get_current_user), 
    _: bool = Depends(is_teacher_or_admin)
):
    """Lister les pods d'un namespace spécifique"""
    namespace = validate_k8s_name(namespace)
    try:
        v1 = client.CoreV1Api()
        ret = v1.list_namespaced_pod(namespace, watch=False)
        pods = [
            {
                "name": pod.metadata.name,
                "ip": pod.status.pod_ip,
            }
            for pod in ret.items
        ]
        return {"namespace": namespace, "pods": pods, "k8s_available": True}
    except Exception:
        return {"namespace": namespace, "pods": [], "k8s_available": False}

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
        
        # Récupérer le déploiement, avec fallbacks (stack-name puis label app)
        try:
            deployment = apps_v1.read_namespaced_deployment(name, namespace)
        except client.exceptions.ApiException as e:
            # Tenter par stack-name (WordPress regroupe plusieurs composants)
            label_selector = f"managed-by=labondemand,user-id={current_user.id},stack-name={name}"
            lst = apps_v1.list_namespaced_deployment(namespace, label_selector=label_selector)
            if lst.items:
                wp = [d for d in lst.items if (d.metadata.labels or {}).get("component") == "wordpress"]
                deployment = wp[0] if wp else lst.items[0]
                name = deployment.metadata.name
            else:
                # Tentative secondaire: via label app=name
                lst2 = apps_v1.list_namespaced_deployment(namespace, label_selector=f"app={name}")
                if lst2.items:
                    deployment = lst2.items[0]
                    name = deployment.metadata.name
                else:
                    # Si aucune correspondance n'est trouvée, renvoyer 404, peu importe le status initial
                    raise HTTPException(status_code=404, detail="Déploiement non trouvé")
        # Enforcer l'isolation: un étudiant ne peut voir que ses propres déploiements
        if current_user.role == UserRole.student:
            labels = deployment.metadata.labels or {}
            owner_id = labels.get("user-id")
            if owner_id != str(current_user.id):
                raise HTTPException(status_code=403, detail="Accès refusé à ce déploiement")
        
        # Déterminer si on est dans une "stack" (wordpress/mysql) pour agréger via stack-name
        dep_labels = deployment.metadata.labels or {}
        stack_name = dep_labels.get("stack-name")

        # Récupérer les pods associés (par stack-name si disponible)
        if stack_name:
            pods = core_v1.list_namespaced_pod(
                namespace,
                label_selector=f"managed-by=labondemand,stack-name={stack_name}"
            )
        else:
            pods = core_v1.list_namespaced_pod(
                namespace,
                label_selector=f"app={name}"
            )

        # Récupérer les services associés (par stack-name si disponible)
        if stack_name:
            services = core_v1.list_namespaced_service(
                namespace,
                label_selector=f"managed-by=labondemand,stack-name={stack_name}"
            )
        else:
            services = core_v1.list_namespaced_service(namespace, label_selector=f"app={name}")
        
        # Récupérer l'IP externe du cluster
        def get_cluster_external_ip():
            try:
                # Utiliser la configuration si définie
                if settings.CLUSTER_EXTERNAL_IP:
                    return settings.CLUSTER_EXTERNAL_IP
                
                # Essayer de récupérer l'IP externe via les nœuds
                nodes = core_v1.list_node()
                internal_ip = None
                
                for node in nodes.items:
                    if node.status.addresses:
                        for address in node.status.addresses:
                            if address.type == "ExternalIP" and address.address:
                                return address.address
                            elif address.type == "InternalIP" and address.address:
                                # Sauvegarder l'IP interne comme fallback
                                internal_ip = address.address
                
                # Si pas d'IP externe trouvée, essayer de récupérer via les services LoadBalancer
                lb_services = core_v1.list_service_for_all_namespaces()
                for svc in lb_services.items:
                    if svc.spec.type == "LoadBalancer" and svc.status.load_balancer:
                        if svc.status.load_balancer.ingress:
                            for ingress in svc.status.load_balancer.ingress:
                                if ingress.ip:
                                    return ingress.ip
                                elif ingress.hostname:
                                    return ingress.hostname
                
                # Fallback sur l'IP interne du premier nœud
                if internal_ip:
                    return internal_ip
                    
                # Dernière option : localhost (pour développement local)
                return "localhost"
            except Exception as e:
                print(f"Erreur lors de la récupération de l'IP du cluster: {e}")
                return "localhost"

        cluster_ip = get_cluster_external_ip()
        print(f"[DEBUG] IP du cluster détectée: {cluster_ip}")  # Pour debug

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
                        # Nommer intelligemment les endpoints pour LAMP (web vs phpMyAdmin)
                        label = ""
                        try:
                            lbls = svc.metadata.labels or {}
                            comp = lbls.get("component", "")
                            app_type = lbls.get("app-type", "")
                            if app_type == "lamp":
                                if comp == "web":
                                    label = "Web (Apache/PHP)"
                                elif comp == "phpmyadmin":
                                    label = "phpMyAdmin"
                        except Exception:
                            pass
                        access_urls.append({
                            "url": f"http://{cluster_ip}:{port.node_port}",
                            "service": svc.metadata.name,
                            "node_port": port.node_port,
                            "cluster_ip": cluster_ip,
                            "label": label or None
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
        
    except Exception as e:
        _raise_k8s_http(e)

# ============= ENDPOINT CREDENTIALS (SECRETS) =============

@router.get("/deployments/{namespace}/{name}/credentials")
async def get_deployment_credentials(
    namespace: str,
    name: str,
    current_user: User = Depends(get_current_user)
):
    """Récupère les identifiants (secrets) associés à un déploiement LabOnDemand.
    - Autorisé pour: propriétaire (user-id sur labels) ou rôles admin/teacher.
    - Spécifique WordPress: renvoie wordpress + database creds.
    """
    namespace = validate_k8s_name(namespace)
    name = validate_k8s_name(name)

    try:
        apps_v1 = client.AppsV1Api()
        core_v1 = client.CoreV1Api()

        # Vérifier le déploiement et les droits (avec fallback stack)
        requested_name = name  # conserver le nom demandé (peut être le nom de stack)
        try:
            deployment = apps_v1.read_namespaced_deployment(name, namespace)
        except client.exceptions.ApiException as e:
            if e.status == 404:
                # Essayer de retrouver par stack-name (= nom logique de la pile)
                label_selector = f"managed-by=labondemand,user-id={current_user.id},stack-name={name}"
                lst = apps_v1.list_namespaced_deployment(namespace, label_selector=label_selector)
                if not lst.items:
                    raise HTTPException(status_code=404, detail="Application introuvable pour récupérer les identifiants")
                wp = [d for d in lst.items if (d.metadata.labels or {}).get("component") == "wordpress"]
                deployment = wp[0] if wp else lst.items[0]
                # Ne pas écraser le nom de stack; conserver requested_name comme identifiant de pile
            else:
                raise
        labels = deployment.metadata.labels or {}
        owner_id = labels.get("user-id")
        app_type = labels.get("app-type", "custom")
        stack_name = labels.get("stack-name") or requested_name or deployment.metadata.name

        if current_user.role == UserRole.student and owner_id != str(current_user.id):
            raise HTTPException(status_code=403, detail="Accès refusé à ces identifiants")

        # Rechercher le secret par label stack-name=name ou fallback {name}-secret
        selector = f"managed-by=labondemand,stack-name={stack_name}"
        secrets_list = core_v1.list_namespaced_secret(namespace, label_selector=selector)
        secret_obj = None
        if secrets_list.items:
            secret_obj = secrets_list.items[0]
        else:
            # Fallback par nom conventionnel
            # WordPress: {stack}-secret ; MySQL: {stack}-db-secret ; sinon: {stack}-secret
            wp_secret = f"{stack_name}-secret"
            mysql_secret = f"{stack_name}-db-secret"
            try:
                # tenter MySQL d'abord si c'est une stack MySQL, sinon WordPress, sinon générique
                if app_type == "mysql":
                    secret_obj = core_v1.read_namespaced_secret(mysql_secret, namespace)
                else:
                    secret_obj = core_v1.read_namespaced_secret(wp_secret, namespace)
            except client.exceptions.ApiException as e:
                if e.status == 404:
                    raise HTTPException(status_code=404, detail="Aucun identifiant trouvé pour cette application")
                raise

        data = secret_obj.data or {}
        # Helper pour décoder une clé si présente
        def dec(key: str) -> Optional[str]:
            val = data.get(key)
            if not val:
                return None
            try:
                return base64.b64decode(val).decode("utf-8")
            except Exception:
                return None

        # Construire la réponse selon le type
        if app_type == "wordpress":
            wp_user = dec("WORDPRESS_USERNAME")
            wp_pass = dec("WORDPRESS_PASSWORD")
            wp_email = dec("WORDPRESS_EMAIL")

            db_user = dec("MARIADB_USER") or dec("WORDPRESS_DATABASE_USER")
            db_pass = dec("MARIADB_PASSWORD") or dec("WORDPRESS_DATABASE_PASSWORD")
            db_name = dec("MARIADB_DATABASE") or dec("WORDPRESS_DATABASE_NAME")
            # Host/port conventionnels pour la stack
            db_host = f"{stack_name}-mariadb-service"
            db_port = 3306

            return {
                "type": "wordpress",
                "wordpress": {
                    "username": wp_user,
                    "password": wp_pass,
                    "email": wp_email,
                },
                "database": {
                    "host": db_host,
                    "port": db_port,
                    "username": db_user,
                    "password": db_pass,
                    "database": db_name,
                },
            }

        if app_type == "mysql":
            # Secrets MySQL + interface phpMyAdmin
            db_user = dec("MYSQL_USER")
            db_pass = dec("MYSQL_PASSWORD")
            db_name = dec("MYSQL_DATABASE")
            db_host = f"{stack_name}-mysql-service"
            return {
                "type": "mysql",
                "database": {
                    "host": db_host,
                    "port": 3306,
                    "username": db_user,
                    "password": db_pass,
                    "database": db_name,
                },
                "phpmyadmin": {"url_hint": "http://<NODE_IP>:<NODE_PORT>/"},
            }
        if app_type == "lamp":
            # Stack LAMP: même secret que MySQL; ajouter un hint phpMyAdmin
            db_user = dec("MYSQL_USER")
            db_pass = dec("MYSQL_PASSWORD")
            db_name = dec("MYSQL_DATABASE")
            db_host = f"{stack_name}-mysql-service"
            return {
                "type": "lamp",
                "database": {
                    "host": db_host,
                    "port": 3306,
                    "username": db_user,
                    "password": db_pass,
                    "database": db_name,
                },
                "phpmyadmin": {"url_hint": "http://<NODE_IP>:<NODE_PORT>/"},
            }

        # Par défaut: retourner toutes les paires décodées disponibles
        decoded = {k: dec(k) for k in data.keys()}
        return {"type": app_type, "secrets": decoded}

    except Exception as e:
        _raise_k8s_http(e)

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
    except Exception as e:
        _raise_k8s_http(e)

@router.post("/deployments")
async def create_deployment(
    name: str,
    image: str,
    replicas: int = 1,
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
    namespace=None,
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
    except Exception as e:
        _raise_k8s_http(e)

@router.delete("/deployments/{namespace}/{name}")
async def delete_deployment(
    namespace: str,
    name: str,
    delete_service: bool = True,
    delete_persistent: bool = True,
    current_user: User = Depends(get_current_user),
):
    """Supprimer un déploiement et son service.

    Règles d'accès:
    - Admin/Teacher: peuvent supprimer n'importe quel déploiement LabOnDemand.
    - Student: peut supprimer uniquement ses propres déploiements (labels managed-by=labondemand,user-id=<id>).
    """
    namespace = validate_k8s_name(namespace)
    name = validate_k8s_name(name)
    
    try:
        apps_v1 = client.AppsV1Api()
        core_v1 = client.CoreV1Api()

        # Résoudre le déploiement cible avec fallbacks (stack-name puis label app)
        stack_mode = False
        try:
            dep = apps_v1.read_namespaced_deployment(name, namespace)
        except client.exceptions.ApiException as e:
            if e.status == 404:
                # Tenter par stack-name (ex: WordPress)
                try:
                    # Pour les étudiants, restreindre au user-id courant. Pour admin/teacher, ne pas filtrer par user-id.
                    if current_user.role == UserRole.student:
                        label_selector = f"managed-by=labondemand,user-id={current_user.id},stack-name={name}"
                    else:
                        label_selector = f"managed-by=labondemand,stack-name={name}"
                    lst = apps_v1.list_namespaced_deployment(namespace, label_selector=label_selector)
                except Exception:
                    lst = client.V1DeploymentList(items=[])
                if lst and lst.items:
                    # Si composant wordpress présent, l'utiliser comme référence
                    wp = [d for d in lst.items if (d.metadata.labels or {}).get("component") == "wordpress"]
                    dep = wp[0] if wp else lst.items[0]
                    stack_mode = True
                    # Ajuster name vers le vrai nom du déploiement résolu
                    name = dep.metadata.name
                else:
                    # Tentative secondaire: via label app=<name>
                    lst2 = apps_v1.list_namespaced_deployment(namespace, label_selector=f"app={name}")
                    if lst2.items:
                        dep = lst2.items[0]
                        name = dep.metadata.name
                    else:
                        raise HTTPException(status_code=404, detail="Déploiement non trouvé")
            else:
                raise

        labels = dep.metadata.labels or {}
        app_type = labels.get("app-type", "custom")

        # Autorisation: un étudiant ne peut supprimer que ses propres ressources LabOnDemand
        if current_user.role == UserRole.student:
            owner_id = labels.get("user-id")
            managed = labels.get("managed-by")
            if owner_id != str(current_user.id) or managed != "labondemand":
                raise HTTPException(status_code=403, detail="Accès refusé à ce déploiement")

        deleted = []

        if app_type == "wordpress" or (stack_mode and (labels.get("app-type") == "wordpress" or labels.get("component") == "wordpress")):
            # Supprimer la stack complète (web + db). Par défaut, on supprime aussi PVC/Secret pour éviter les conflits au redeploy.
            stack_name = labels.get("stack-name") or name
            wp_name = stack_name
            db_name = f"{stack_name}-mariadb"

            # Supprimer deployments
            for dep_name in [wp_name, db_name]:
                try:
                    apps_v1.delete_namespaced_deployment(dep_name, namespace)
                    deleted.append(dep_name)
                except client.exceptions.ApiException as e:
                    if e.status != 404:
                        raise

            # Supprimer services si demandé
            if delete_service:
                for svc_name in [f"{wp_name}-service", f"{db_name}-service"]:
                    try:
                        core_v1.delete_namespaced_service(svc_name, namespace)
                    except client.exceptions.ApiException:
                        pass

            # Supprimer PVC et Secret si demandé
            if delete_persistent:
                # PVC DB
                try:
                    core_v1.delete_namespaced_persistent_volume_claim(f"{db_name}-pvc", namespace)
                except client.exceptions.ApiException:
                    pass
                # Secret WP
                try:
                    core_v1.delete_namespaced_secret(f"{stack_name}-secret", namespace)
                except client.exceptions.ApiException:
                    pass

            return {"message": f"Stack WordPress '{stack_name}' supprimée: {', '.join(deleted)}"}
        elif app_type == "mysql" or stack_mode and (labels.get("app-type") == "mysql" or labels.get("component") in {"database", "phpmyadmin"}):
            # Supprimer la stack MySQL + phpMyAdmin
            stack_name = labels.get("stack-name") or name
            db_name = f"{stack_name}-mysql"
            pma_name = f"{stack_name}-phpmyadmin"

            # Supprimer deployments
            for dep_name in [db_name, pma_name]:
                try:
                    apps_v1.delete_namespaced_deployment(dep_name, namespace)
                    deleted.append(dep_name)
                except client.exceptions.ApiException as e:
                    if e.status != 404:
                        raise

            # Supprimer services si demandé
            if delete_service:
                for svc_name in [f"{db_name}-service", f"{pma_name}-service"]:
                    try:
                        core_v1.delete_namespaced_service(svc_name, namespace)
                    except client.exceptions.ApiException:
                        pass

            if delete_persistent:
                # PVC DB
                try:
                    core_v1.delete_namespaced_persistent_volume_claim(f"{db_name}-pvc", namespace)
                except client.exceptions.ApiException:
                    pass
                # Secret DB
                try:
                    core_v1.delete_namespaced_secret(f"{stack_name}-db-secret", namespace)
                except client.exceptions.ApiException:
                    pass

            return {"message": f"Stack MySQL/phpMyAdmin '{stack_name}' supprimée: {', '.join(deleted)}"}
        elif app_type == "lamp" or stack_mode and labels.get("app-type") == "lamp":
            # Supprimer la stack LAMP (web + db + pma)
            stack_name = labels.get("stack-name") or name
            web_name = f"{stack_name}-web"
            db_name = f"{stack_name}-mysql"
            pma_name = f"{stack_name}-phpmyadmin"

            # Supprimer deployments
            for dep_name in [web_name, db_name, pma_name]:
                try:
                    apps_v1.delete_namespaced_deployment(dep_name, namespace)
                    deleted.append(dep_name)
                except client.exceptions.ApiException as e:
                    if e.status != 404:
                        raise

            # Supprimer services si demandé
            if delete_service:
                for svc_name in [f"{web_name}-service", f"{db_name}-service", f"{pma_name}-service"]:
                    try:
                        core_v1.delete_namespaced_service(svc_name, namespace)
                    except client.exceptions.ApiException:
                        pass

            if delete_persistent:
                # PVC DB
                try:
                    core_v1.delete_namespaced_persistent_volume_claim(f"{db_name}-pvc", namespace)
                except client.exceptions.ApiException:
                    pass
                # Secret DB
                try:
                    core_v1.delete_namespaced_secret(f"{stack_name}-db-secret", namespace)
                except client.exceptions.ApiException:
                    pass

            return {"message": f"Stack LAMP '{stack_name}' supprimée: {', '.join(deleted)}"}
        else:
            # Comportement standard pour les apps unitaires
            apps_v1.delete_namespaced_deployment(name, namespace)
            if delete_service:
                try:
                    core_v1.delete_namespaced_service(f"{name}-service", namespace)
                except client.exceptions.ApiException:
                    pass
            return {"message": f"Déploiement {name} supprimé du namespace {namespace}"}
    except Exception as e:
        _raise_k8s_http(e)

# ============= ENDPOINTS DE TEMPLATES ET PRESETS =============

@router.get("/templates")
async def get_deployment_templates_endpoint(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupérer les templates actifs; pour les étudiants, filtrer via RuntimeConfig.allowed_for_students si dispo, sinon fallback jupyter/vscode."""
    try:
        templates = db.query(Template).filter(Template.active == True).all()
        runtime_configs = db.query(RuntimeConfig).filter(RuntimeConfig.active == True).all()
    except Exception:
        templates = []
        runtime_configs = []

    # Déterminer l'ensemble des runtimes autorisés aux étudiants
    allowed_set = set()
    if runtime_configs:
        for rc in runtime_configs:
            if rc.allowed_for_students:
                allowed_set.add(rc.key)
    else:
        # Fallback historique (étendu): autoriser aussi WordPress et MySQL aux étudiants
        allowed_set = {"jupyter", "vscode", "wordpress", "mysql"}

    def map_template(t: Template):
        return {
            "id": t.key,
            "name": t.name,
            "description": t.description,
            "icon": t.icon,
            "default_image": t.default_image,
            "default_port": t.default_port,
            "deployment_type": t.deployment_type,
            "default_service_type": t.default_service_type,
            "tags": [s for s in (t.tags or '').split(',') if s]
        }

    if templates:
        # Compléter depuis defaults si des champs manquent (icône, description, tags)
        defaults = get_deployment_templates().get("templates", [])
        defaults_map = {d.get("id"): d for d in defaults}

        def enrich(tpl_dict):
            did = tpl_dict.get("id")
            d = defaults_map.get(did, {})
            # Appliquer seulement si manquant côté DB
            tpl_dict.setdefault("icon", d.get("icon"))
            tpl_dict.setdefault("description", d.get("description"))
            tpl_dict.setdefault("default_service_type", d.get("default_service_type"))
            if not tpl_dict.get("tags") and d.get("tags"):
                tpl_dict["tags"] = d["tags"]
            return tpl_dict

        items = [enrich(map_template(t)) for t in templates]
        if current_user.role == UserRole.student:
            items = [tpl for tpl in items if (tpl.get("deployment_type") in allowed_set or tpl.get("id") in allowed_set)]
        return {"templates": items}

    # Fallback: templates codés + filtrage selon rôle
    defaults = get_deployment_templates()
    if current_user.role == UserRole.student:
        filtered = [tpl for tpl in defaults.get("templates", []) if tpl.get("deployment_type") in allowed_set or tpl.get("id") in allowed_set]
        return {"templates": filtered}
    return defaults


# ============= RUNTIME CONFIGS (dynamiques en base) =============

@router.get("/runtime-configs", response_model=List[schemas.RuntimeConfigResponse])
async def list_runtime_configs(
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
    db: Session = Depends(get_db)
):
    rows = db.query(RuntimeConfig).order_by(RuntimeConfig.id.desc()).all()
    return [schemas.RuntimeConfigResponse.model_validate(r) for r in rows]


@router.post("/runtime-configs", response_model=schemas.RuntimeConfigResponse)
async def create_runtime_config(
    payload: schemas.RuntimeConfigCreate,
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
    db: Session = Depends(get_db)
):
    if db.query(RuntimeConfig).filter(RuntimeConfig.key == payload.key).first():
        raise HTTPException(status_code=400, detail="Cette clé existe déjà")
    rc = RuntimeConfig(**payload.model_dump())
    db.add(rc)
    db.commit()
    db.refresh(rc)
    return schemas.RuntimeConfigResponse.model_validate(rc)


@router.put("/runtime-configs/{rc_id}", response_model=schemas.RuntimeConfigResponse)
async def update_runtime_config(
    rc_id: int,
    payload: schemas.RuntimeConfigUpdate,
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
    db: Session = Depends(get_db)
):
    rc = db.query(RuntimeConfig).filter(RuntimeConfig.id == rc_id).first()
    if not rc:
        raise HTTPException(status_code=404, detail="Runtime config non trouvée")
    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(rc, k, v)
    db.commit()
    db.refresh(rc)
    return schemas.RuntimeConfigResponse.model_validate(rc)


@router.delete("/runtime-configs/{rc_id}")
async def delete_runtime_config(
    rc_id: int,
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
    db: Session = Depends(get_db)
):
    rc = db.query(RuntimeConfig).filter(RuntimeConfig.id == rc_id).first()
    if not rc:
        raise HTTPException(status_code=404, detail="Runtime config non trouvée")
    db.delete(rc)
    db.commit()
    return {"message": "Runtime config supprimée"}


@router.post("/templates", response_model=schemas.TemplateResponse)
async def create_template(
    payload: schemas.TemplateCreate,
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
    db: Session = Depends(get_db)
):
    """Créer un template (admin)"""
    # Vérifier unicité de la clé
    if db.query(Template).filter(Template.key == payload.key).first():
        raise HTTPException(status_code=400, detail="La clé du template existe déjà")
    tpl = Template(
        key=payload.key,
        name=payload.name,
        description=payload.description,
        icon=payload.icon,
        deployment_type=payload.deployment_type,
        default_image=payload.default_image,
        default_port=payload.default_port,
        default_service_type=payload.default_service_type,
        tags=','.join(payload.tags) if payload.tags else None,
        active=payload.active,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return schemas.TemplateResponse(
        id=tpl.id,
        key=tpl.key,
        name=tpl.name,
        description=tpl.description,
        icon=tpl.icon,
        deployment_type=tpl.deployment_type,
        default_image=tpl.default_image,
        default_port=tpl.default_port,
        default_service_type=tpl.default_service_type,
        active=tpl.active,
        tags=[s for s in (tpl.tags or '').split(',') if s],
        created_at=tpl.created_at,
        updated_at=tpl.updated_at,
    )


@router.get("/templates/all", response_model=List[schemas.TemplateResponse])
async def list_all_templates(
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
    db: Session = Depends(get_db)
):
    """Lister tous les templates (admin)"""
    rows = db.query(Template).order_by(Template.id.desc()).all()
    return [
        schemas.TemplateResponse(
            id=t.id,
            key=t.key,
            name=t.name,
            description=t.description,
            icon=t.icon,
            deployment_type=t.deployment_type,
            default_image=t.default_image,
            default_port=t.default_port,
            default_service_type=t.default_service_type,
            active=t.active,
            tags=[s for s in (t.tags or '').split(',') if s],
            created_at=t.created_at,
            updated_at=t.updated_at,
        ) for t in rows
    ]


@router.put("/templates/{template_id}", response_model=schemas.TemplateResponse)
async def update_template(
    template_id: int,
    payload: schemas.TemplateUpdate,
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
    db: Session = Depends(get_db)
):
    tpl = db.query(Template).filter(Template.id == template_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template non trouvé")
    updates = payload.model_dump(exclude_unset=True)
    if "tags" in updates:
        updates["tags"] = ','.join(updates["tags"]) if updates["tags"] else None
    for field, value in updates.items():
        setattr(tpl, field, value)
    db.commit()
    db.refresh(tpl)
    return schemas.TemplateResponse(
        id=tpl.id,
        key=tpl.key,
        name=tpl.name,
        description=tpl.description,
        icon=tpl.icon,
        deployment_type=tpl.deployment_type,
        default_image=tpl.default_image,
        default_port=tpl.default_port,
        default_service_type=tpl.default_service_type,
        active=tpl.active,
        tags=[s for s in (tpl.tags or '').split(',') if s],
        created_at=tpl.created_at,
        updated_at=tpl.updated_at,
    )


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: int,
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
    db: Session = Depends(get_db)
):
    tpl = db.query(Template).filter(Template.id == template_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template non trouvé")
    db.delete(tpl)
    db.commit()
    return {"message": "Template supprimé"}

@router.get("/resource-presets")
async def get_resource_presets(current_user: User = Depends(get_current_user)):
    """Récupérer les presets de ressources selon le rôle"""
    return get_resource_presets_for_role(current_user.role)
