"""Endpoint WebSocket terminal (exec pod)."""
import asyncio
import threading
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from kubernetes import client
from kubernetes.stream import stream as k8s_stream

from ..security import get_current_user
from ..session_store import session_store
from ..models import UserRole
from ..k8s_utils import validate_k8s_name

router = APIRouter(prefix="/api/v1/k8s", tags=["kubernetes"])


async def _ws_authenticate_and_authorize_terminal(websocket: WebSocket, namespace: str, pod_name: str) -> dict:
    """Vérifie la session via cookie et l'accès au pod ciblé."""
    session_id = (websocket.cookies or {}).get("session_id")
    if not session_id:
        await websocket.close(code=4401)
        raise WebSocketDisconnect(code=4401)

    sess = session_store.get(session_id)
    if not sess:
        await websocket.close(code=4401)
        raise WebSocketDisconnect(code=4401)

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

    if role == UserRole.student.value:
        if managed != "labondemand" or owner_id != str(user_id):
            await websocket.close(code=4403)
            raise WebSocketDisconnect(code=4403)
        comp = (pod.metadata.labels or {}).get("component", "")
        app_type = (pod.metadata.labels or {}).get("app-type", "")
        if comp == "database" and app_type in {"mysql", "wordpress", "lamp"}:
            await websocket.close(code=4403)
            raise WebSocketDisconnect(code=4403)
    else:
        if managed != "labondemand":
            await websocket.close(code=4403)
            raise WebSocketDisconnect(code=4403)

    return {"user_id": user_id, "role": role}


@router.websocket("/terminal/{namespace}/{pod}")
async def ws_pod_terminal(websocket: WebSocket, namespace: str, pod: str):
    """Terminal web: ouvre un exec /bin/sh dans le pod ciblé via WebSocket."""
    namespace = validate_k8s_name(namespace)
    pod = validate_k8s_name(pod)

    await websocket.accept()

    try:
        _ = await _ws_authenticate_and_authorize_terminal(websocket, namespace, pod)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close(code=1011)
        finally:
            return

    container = websocket.query_params.get("container")
    cmd = websocket.query_params.get("cmd") or "/bin/sh"
    command = [cmd]
    if cmd == "/bin/sh":
        command = ["/bin/sh"]

    core_v1 = client.CoreV1Api()
    ws_client = None
    loop = asyncio.get_event_loop()

    try:
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

        def _reader():
            try:
                short = 0.02
                idle_sleep = 0.012
                while True:
                    got_data = False
                    for _ in range(6):
                        try:
                            out = ws_client.read_stdout(timeout=short)
                        except Exception:
                            out = None
                        if out:
                            got_data = True
                            loop.call_soon_threadsafe(asyncio.create_task, websocket.send_text(out))

                        try:
                            err = ws_client.read_stderr(timeout=short)
                        except Exception:
                            err = None
                        if err:
                            got_data = True
                            loop.call_soon_threadsafe(asyncio.create_task, websocket.send_text(err))

                        if getattr(ws_client, "is_closed", False):
                            return

                    if not got_data:
                        time.sleep(idle_sleep)
                    else:
                        time.sleep(0.001)
            except Exception:
                pass

        reader_thread = threading.Thread(target=_reader, daemon=True)
        reader_thread.start()

        while True:
            try:
                msg = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            except Exception:
                break
            if not msg:
                continue
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
                    pass
            try:
                ws_client.write_stdin(msg)
            except Exception:
                break

    finally:
        try:
            if ws_client is not None:
                try:
                    ws_client.close()
                except Exception:
                    pass
        finally:
            try:
                if websocket.client_state.value == 1:
                    await websocket.close()
            except Exception:
                pass
