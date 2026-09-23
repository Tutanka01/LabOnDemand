"""Endpoint WebSocket terminal (exec pod)."""
import asyncio
import concurrent.futures
import json
import logging
import threading
import time
from typing import Any, Callable, List, Optional, Tuple

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from kubernetes import client
from kubernetes.stream import stream as k8s_stream
from kubernetes.stream.ws_client import RESIZE_CHANNEL
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketState

from ..security import get_current_user
from ..session_store import session_store
from ..models import User, UserRole
from ..k8s_utils import validate_k8s_name
from ..database import SessionLocal
from ..deployment_service import deployment_service
from ..config import settings

router = APIRouter(prefix="/api/v1/k8s", tags=["kubernetes"])
logger = logging.getLogger("labondemand.terminal")

# Attente maximale d'une trame du flux exec par le thread lecteur : borne la
# latence d'arrêt du thread sans jamais tourner à vide.
_READ_POLL_SECONDS = 0.5
# Regroupement en un seul message WebSocket des trames déjà reçues.
_MAX_BATCH_FRAMES = 16
_MAX_BATCH_CHARS = 64 * 1024
# Délai laissé au thread lecteur pour s'arrêter et fermer le flux exec
# (WSClient.close attend jusqu'à 3 s l'acquittement de l'API server).
_READER_STOP_TIMEOUT_SECONDS = 10.0
# Bornes des dimensions TTY acceptées depuis le navigateur.
_MAX_TTY_DIMENSION = 1000
_DEFAULT_TTY_SIZE = (80, 24)
# Codes de fermeture WebSocket (4408 : inactivité, sur le modèle HTTP 408).
_CLOSE_NORMAL = 1000
_CLOSE_GOING_AWAY = 1001
_CLOSE_INTERNAL_ERROR = 1011
_CLOSE_IDLE_TIMEOUT = 4408


def _load_user(user_id: Any) -> Optional[User]:
    """Charge l'utilisateur (bloquant, hors boucle) ; l'instance reste lisible
    après fermeture de la session."""
    with SessionLocal() as db:
        return db.query(User).filter(User.id == user_id).first()


async def _ws_authenticate_and_authorize_terminal(websocket: WebSocket, namespace: str, pod_name: str) -> dict:
    """Vérifie la session via cookie et l'accès au pod ciblé."""
    session_id = (websocket.cookies or {}).get("session_id")
    if not session_id:
        await websocket.close(code=4401)
        raise WebSocketDisconnect(code=4401)

    sess = await run_in_threadpool(session_store.get, session_id)
    if not sess:
        await websocket.close(code=4401)
        raise WebSocketDisconnect(code=4401)

    core_v1 = client.CoreV1Api()
    try:
        pod = await run_in_threadpool(
            core_v1.read_namespaced_pod, name=pod_name, namespace=namespace
        )
    except Exception as exc:
        logger.info(
            "terminal_pod_lookup_failed",
            extra={"extra_fields": {"namespace": namespace, "pod": pod_name, "error": str(exc)}},
        )
        await websocket.close(code=4404)
        raise WebSocketDisconnect(code=4404)

    labels = pod.metadata.labels or {}
    managed = labels.get("managed-by")
    owner_id = labels.get("user-id")
    user_id = sess.get("user_id")
    user = await run_in_threadpool(_load_user, user_id)
    if not user or not user.is_active:
        await websocket.close(code=4401)
        raise WebSocketDisconnect(code=4401)
    role = user.role.value if hasattr(user.role, "value") else str(user.role)

    try:
        deployment_service._assert_deployment_access(
            labels, user, namespace, pod_name
        )
    except Exception:
        await websocket.close(code=4403)
        raise WebSocketDisconnect(code=4403)

    comp = labels.get("component", "")
    app_type = labels.get("app-type", "")
    if comp == "database" and app_type in {"mysql", "wordpress", "lamp"}:
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

    log_fields = {"namespace": namespace, "pod": pod, "container": container}
    try:
        ws_client = await run_in_threadpool(
            _open_exec_stream, namespace, pod, container, command
        )
    except Exception:
        logger.exception("terminal_exec_open_failed", extra={"extra_fields": log_fields})
        await _close_websocket(websocket, _CLOSE_INTERNAL_ERROR)
        return

    bridge = _TerminalBridge(
        websocket,
        ws_client,
        idle_timeout=settings.TERMINAL_IDLE_TIMEOUT_SECONDS,
        log_fields=log_fields,
    )
    await bridge.run()


def _open_exec_stream(
    namespace: str, pod: str, container: Optional[str], command: List[str]
) -> Any:
    """Ouvre le flux exec TTY du pod (bloquant : poignée de main WebSocket
    avec l'API server), à appeler hors de la boucle d'événements."""
    core_v1 = client.CoreV1Api()
    return k8s_stream(
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


async def _close_websocket(websocket: WebSocket, code: int, reason: str = "") -> None:
    """Ferme le WebSocket navigateur s'il est encore ouvert des deux côtés."""
    if (
        websocket.application_state != WebSocketState.CONNECTED
        or websocket.client_state != WebSocketState.CONNECTED
    ):
        return
    try:
        await websocket.close(code=code, reason=reason)
    except Exception:
        # Le client est parti entre-temps : il n'y a plus rien à fermer.
        logger.debug("terminal_websocket_close_failed", exc_info=True)


def _parse_resize(message: str) -> Optional[Tuple[int, int]]:
    """Renvoie (colonnes, lignes) si le message est une commande de
    redimensionnement ``{"type": "resize", "cols": N, "rows": N}``.

    Tout autre texte (y compris du JSON collé dans le shell) est de la saisie.
    """
    if not message.startswith("{"):
        return None
    try:
        payload = json.loads(message)
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get("type") != "resize":
        return None
    try:
        cols = int(payload.get("cols") or _DEFAULT_TTY_SIZE[0])
        rows = int(payload.get("rows") or _DEFAULT_TTY_SIZE[1])
    except (TypeError, ValueError):
        cols, rows = _DEFAULT_TTY_SIZE
    return (
        min(max(cols, 1), _MAX_TTY_DIMENSION),
        min(max(rows, 1), _MAX_TTY_DIMENSION),
    )


class _TerminalBridge:
    """Relie le WebSocket navigateur au flux exec Kubernetes sans bloquer la
    boucle d'événements.

    - Un thread lecteur dédié est le seul à lire le flux (``update`` bloquant
      avec délai, jamais d'attente active) et à le fermer : ``WSClient.close``
      lit l'acquittement de fermeture, ce qui ne doit pas concurrencer une
      lecture en cours. La sortie est transmise via la boucle et le thread
      attend chaque envoi (contre-pression vers le pod).
    - La boucle relaie la saisie et les redimensionnements ; les écritures sur
      le flux passent par le pool de threads.
    - La session se termine quand le client part, quand le processus du pod
      se termine ou après ``idle_timeout`` secondes sans échange dans un sens
      ou dans l'autre (0 = jamais) ; le flux et le thread sont alors libérés.
    """

    def __init__(
        self,
        websocket: WebSocket,
        ws_client: Any,
        *,
        idle_timeout: float,
        log_fields: Optional[dict] = None,
        poll_interval: float = _READ_POLL_SECONDS,
        stop_timeout: float = _READER_STOP_TIMEOUT_SECONDS,
    ) -> None:
        self._websocket = websocket
        self._ws_client = ws_client
        self._idle_timeout = max(0.0, float(idle_timeout or 0))
        self._log_fields = dict(log_fields or {})
        self._poll_interval = poll_interval
        self._stop_timeout = stop_timeout
        self._stop = threading.Event()
        self._close_lock = threading.Lock()
        self._stream_closed = False
        self._last_activity = time.monotonic()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._reader_done: Optional[asyncio.Event] = None
        self.reader: Optional[threading.Thread] = None

    async def run(self) -> None:
        """Relaie les deux sens jusqu'à la fin de la session, puis nettoie."""
        self._loop = asyncio.get_running_loop()
        self._reader_done = asyncio.Event()
        self._touch()
        self.reader = threading.Thread(
            target=self._pump_output, name="terminal-reader", daemon=True
        )
        self.reader.start()
        outcome: Tuple[Optional[int], str] = (_CLOSE_INTERNAL_ERROR, "")
        try:
            outcome = await self._forward_input()
        except asyncio.CancelledError:
            outcome = (_CLOSE_GOING_AWAY, "")
            raise
        except Exception:
            logger.exception(
                "terminal_bridge_failed", extra={"extra_fields": self._log_fields}
            )
        finally:
            await self._stop_reader()
            code, reason = outcome
            if code is not None:
                await _close_websocket(self._websocket, code, reason)

    # ---- sens navigateur -> pod (boucle d'événements) ----

    async def _forward_input(self) -> Tuple[Optional[int], str]:
        """Relaie la saisie ; renvoie le code de fermeture à envoyer au
        navigateur (None si le navigateur est déjà parti)."""
        assert self._reader_done is not None
        reader_done = asyncio.ensure_future(self._reader_done.wait())
        receive: Optional[asyncio.Future] = None
        try:
            while True:
                if receive is None:
                    receive = asyncio.ensure_future(self._websocket.receive())
                done, _ = await asyncio.wait(
                    {receive, reader_done},
                    timeout=self._idle_remaining(),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if receive in done:
                    message, receive = receive.result(), None
                    if message["type"] == "websocket.disconnect":
                        return None, ""
                    self._touch()
                    if not await self._write(_message_text(message)):
                        if self._reader_done.is_set():
                            return _CLOSE_NORMAL, ""
                        return _CLOSE_INTERNAL_ERROR, "exec stream write failed"
                    continue
                if reader_done in done:
                    # Le processus du pod s'est terminé (ou le flux a été coupé).
                    return _CLOSE_NORMAL, ""
                remaining = self._idle_remaining()
                if remaining is not None and remaining <= 0:
                    logger.info(
                        "terminal_idle_timeout",
                        extra={
                            "extra_fields": {
                                **self._log_fields,
                                "idle_timeout_seconds": self._idle_timeout,
                            }
                        },
                    )
                    return _CLOSE_IDLE_TIMEOUT, "idle timeout"
        finally:
            pending = [task for task in (receive, reader_done) if task is not None]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    async def _write(self, message: str) -> bool:
        """Écrit la saisie (ou le redimensionnement) sur le flux exec."""
        if not message:
            return True
        size = _parse_resize(message)
        try:
            if size is not None:
                # Canal 4 du protocole exec : {"Width": colonnes, "Height": lignes}.
                payload = json.dumps({"Width": size[0], "Height": size[1]})
                await run_in_threadpool(
                    self._ws_client.write_channel, RESIZE_CHANNEL, payload
                )
            else:
                await run_in_threadpool(self._ws_client.write_stdin, message)
        except Exception:
            if not self._stop.is_set() and not self._reader_done.is_set():
                logger.warning(
                    "terminal_stream_write_failed",
                    exc_info=True,
                    extra={"extra_fields": self._log_fields},
                )
            return False
        return True

    # ---- sens pod -> navigateur (thread lecteur) ----

    def _pump_output(self) -> None:
        """Thread lecteur : seul à lire et à fermer le flux exec."""
        ws_client = self._ws_client
        try:
            while not self._stop.is_set() and ws_client.is_open():
                ws_client.update(timeout=self._poll_interval)
                chunk = self._drain()
                if chunk and not self._deliver(chunk):
                    break
        except Exception:
            if not self._stop.is_set():
                logger.warning(
                    "terminal_stream_read_failed",
                    exc_info=True,
                    extra={"extra_fields": self._log_fields},
                )
        finally:
            self._close_stream()
            self._call_in_loop(self._reader_done.set)

    def _drain(self) -> str:
        """Vide stdout/stderr dans l'ordre d'arrivée en regroupant les trames
        déjà disponibles.

        ``read_all`` vide aussi le tampon de capture complet du WSClient, qui
        grossirait sinon pendant toute la session.
        """
        ws_client = self._ws_client
        parts: List[str] = []
        size = 0
        data = ws_client.read_all()
        while data:
            parts.append(data)
            size += len(data)
            if (
                len(parts) >= _MAX_BATCH_FRAMES
                or size >= _MAX_BATCH_CHARS
                or not ws_client.is_open()
            ):
                break
            ws_client.update(timeout=0)
            data = ws_client.read_all()
        return "".join(parts)

    def _deliver(self, chunk: str) -> bool:
        """Envoie la sortie au navigateur et attend l'envoi ; False si le
        navigateur est parti ou si l'arrêt est demandé."""
        assert self._loop is not None
        self._touch()
        coro = self._websocket.send_text(chunk)
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        except RuntimeError:
            # Boucle déjà fermée (arrêt du serveur).
            coro.close()
            return False
        while True:
            try:
                future.result(timeout=self._poll_interval)
                return True
            except concurrent.futures.TimeoutError:
                if self._stop.is_set():
                    future.cancel()
                    return False
            except Exception:
                logger.debug(
                    "terminal_output_send_failed",
                    exc_info=True,
                    extra={"extra_fields": self._log_fields},
                )
                return False

    def _close_stream(self) -> None:
        with self._close_lock:
            if self._stream_closed:
                return
            self._stream_closed = True
        try:
            self._ws_client.close()
        except Exception:
            logger.debug(
                "terminal_stream_close_failed",
                exc_info=True,
                extra={"extra_fields": self._log_fields},
            )

    def _call_in_loop(self, callback: Callable[[], Any]) -> None:
        assert self._loop is not None
        try:
            self._loop.call_soon_threadsafe(callback)
        except RuntimeError:
            # Boucle déjà fermée : plus personne n'attend ce signal.
            logger.debug("terminal_loop_closed", extra={"extra_fields": self._log_fields})

    # ---- arrêt ----

    async def _stop_reader(self) -> None:
        """Demande l'arrêt du thread lecteur (qui ferme le flux exec) et
        l'attend sans bloquer la boucle."""
        self._stop.set()
        if self._reader_done is None or self.reader is None:
            return
        try:
            await asyncio.wait_for(self._reader_done.wait(), timeout=self._stop_timeout)
        except asyncio.TimeoutError:
            # Lecture bloquée sur une trame incomplète : le thread (démon)
            # fermera le flux dès qu'il sera débloqué.
            logger.warning(
                "terminal_reader_stop_timeout", extra={"extra_fields": self._log_fields}
            )

    # ---- inactivité ----

    def _touch(self) -> None:
        self._last_activity = time.monotonic()

    def _idle_remaining(self) -> Optional[float]:
        """Secondes restantes avant fermeture pour inactivité (None = jamais)."""
        if self._idle_timeout <= 0:
            return None
        return max(0.0, self._last_activity + self._idle_timeout - time.monotonic())


def _message_text(message: dict) -> str:
    """Contenu texte d'un message WebSocket reçu (binaire décodé en UTF-8)."""
    text = message.get("text")
    if text is not None:
        return text
    return (message.get("bytes") or b"").decode("utf-8", "replace")
