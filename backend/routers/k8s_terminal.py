"""WebSocket terminal endpoint (exec into a lab pod).

The handler must stay ``async`` (WebSocket), so every blocking call — Redis
session lookup, DB user lookup, Kubernetes pod read, exec stream open, stdin
writes and close — runs in a worker thread. A dedicated reader thread pumps
the pod's output back to the browser.
"""
import asyncio
import json
import logging
import threading
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from kubernetes import client
from kubernetes.stream import stream as k8s_stream
from starlette.websockets import WebSocketState

from .. import database
from ..deployment_service import deployment_service
from ..k8s_utils import validate_k8s_name
from ..models import User
from ..session_store import session_store

router = APIRouter(prefix="/api/v1/k8s", tags=["kubernetes"])
logger = logging.getLogger("labondemand.terminal")

# WebSocket close codes sent to the browser.
_CLOSE_UNAUTHORIZED = 4401
_CLOSE_FORBIDDEN = 4403
_CLOSE_NOT_FOUND = 4404
_CLOSE_INTERNAL = 1011

# A browser that does not drain the output for this long ends the session.
_SEND_TIMEOUT = 60

# Database pods never get an interactive shell (same rule as the file explorer).
_DB_APP_TYPES = {"mysql", "wordpress", "lamp"}


def _authorize_terminal(session_id: Optional[str], namespace: str, pod_name: str) -> Optional[int]:
    """Check the session and the access to the target pod (blocking).

    Returns ``None`` when access is granted, otherwise the WebSocket close code.
    """
    if not session_id:
        return _CLOSE_UNAUTHORIZED
    sess = session_store.get(session_id)
    if not sess:
        return _CLOSE_UNAUTHORIZED

    with database.SessionLocal() as db:
        user = db.query(User).filter(User.id == sess.get("user_id")).first()
        if not user or not user.is_active:
            return _CLOSE_UNAUTHORIZED
        db.expunge(user)

    try:
        pod = client.CoreV1Api().read_namespaced_pod(name=pod_name, namespace=namespace)
    except Exception as exc:
        logger.info(
            "terminal_pod_unavailable",
            extra={"extra_fields": {"namespace": namespace, "pod": pod_name, "error": str(exc)}},
        )
        return _CLOSE_NOT_FOUND

    labels = pod.metadata.labels or {}
    try:
        deployment_service._assert_deployment_access(labels, user, namespace, pod_name)
    except HTTPException:
        return _CLOSE_FORBIDDEN

    if labels.get("component") == "database" and labels.get("app-type", "") in _DB_APP_TYPES:
        return _CLOSE_FORBIDDEN
    return None


def _open_exec(namespace: str, pod: str, container: Optional[str], command: list[str]) -> Any:
    return k8s_stream(
        client.CoreV1Api().connect_get_namespaced_pod_exec,
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


def _pump_output(ws_client: Any, websocket: WebSocket, loop: asyncio.AbstractEventLoop, stop: threading.Event) -> None:
    """Reader thread: forward stdout/stderr to the browser until the exec ends.

    Each chunk is sent on the event loop and awaited from this thread, which
    keeps the output ordered and gives natural back-pressure.
    """
    short = 0.02
    idle_sleep = 0.012
    try:
        while not stop.is_set() and ws_client.is_open():
            got_data = False
            for read in (ws_client.read_stdout, ws_client.read_stderr):
                chunk = read(timeout=short)
                if chunk:
                    got_data = True
                    asyncio.run_coroutine_threadsafe(websocket.send_text(chunk), loop).result(timeout=_SEND_TIMEOUT)
            time.sleep(0.001 if got_data else idle_sleep)
    except Exception as exc:  # stream or browser gone: end the session quietly
        if not stop.is_set():
            logger.debug("terminal_reader_stopped", extra={"extra_fields": {"error": str(exc)}})
    finally:
        if not stop.is_set():
            # The shell exited on its own: close the browser side too.
            asyncio.run_coroutine_threadsafe(_close_quietly(websocket), loop)


async def _close_quietly(websocket: WebSocket, code: int = 1000) -> None:
    if (
        websocket.application_state == WebSocketState.CONNECTED
        and websocket.client_state == WebSocketState.CONNECTED
    ):
        try:
            await websocket.close(code=code)
        except RuntimeError:  # already closing
            pass


def _apply_input(ws_client: Any, msg: str) -> None:
    """Forward one browser message: resize control frame or raw keystrokes."""
    if msg.startswith("{"):
        try:
            payload = json.loads(msg)
        except ValueError:
            payload = None
        if isinstance(payload, dict) and payload.get("type") == "resize":
            cols = int(payload.get("cols") or 80)
            rows = int(payload.get("rows") or 24)
            ws_client.resize_terminal(width=cols, height=rows)
            return
    ws_client.write_stdin(msg)


@router.websocket("/terminal/{namespace}/{pod}")
async def ws_pod_terminal(websocket: WebSocket, namespace: str, pod: str) -> None:
    """Web terminal: open an exec /bin/sh in the target pod over a WebSocket."""
    namespace = validate_k8s_name(namespace)
    pod = validate_k8s_name(pod)

    await websocket.accept()

    try:
        denied = await asyncio.to_thread(
            _authorize_terminal, (websocket.cookies or {}).get("session_id"), namespace, pod
        )
    except Exception:
        logger.exception("terminal_authorization_failed", extra={"extra_fields": {"namespace": namespace, "pod": pod}})
        denied = _CLOSE_INTERNAL
    if denied is not None:
        await _close_quietly(websocket, code=denied)
        return

    container = websocket.query_params.get("container")
    command = [websocket.query_params.get("cmd") or "/bin/sh"]

    try:
        ws_client = await asyncio.to_thread(_open_exec, namespace, pod, container, command)
    except Exception as exc:
        logger.warning(
            "terminal_exec_failed",
            extra={"extra_fields": {"namespace": namespace, "pod": pod, "error": str(exc)}},
        )
        await _close_quietly(websocket, code=_CLOSE_INTERNAL)
        return

    stop = threading.Event()
    reader = threading.Thread(
        target=_pump_output,
        args=(ws_client, websocket, asyncio.get_running_loop(), stop),
        name=f"terminal-{namespace}-{pod}",
        daemon=True,
    )
    reader.start()

    try:
        while True:
            try:
                msg = await websocket.receive_text()
            except (WebSocketDisconnect, RuntimeError):
                break
            if not msg:
                continue
            try:
                await asyncio.to_thread(_apply_input, ws_client, msg)
            except Exception as exc:
                logger.debug("terminal_write_failed", extra={"extra_fields": {"error": str(exc)}})
                break
    finally:
        stop.set()
        try:
            await asyncio.to_thread(ws_client.close)
        except Exception as exc:
            logger.debug("terminal_close_failed", extra={"extra_fields": {"error": str(exc)}})
        await _close_quietly(websocket)
