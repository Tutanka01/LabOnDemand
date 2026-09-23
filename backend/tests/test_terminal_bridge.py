"""Terminal WebSocket : pont exec hors boucle, nettoyage et inactivité.

Le flux exec Kubernetes est remplacé par un double (``FakeExecStream``) qui
reproduit l'API de ``kubernetes.stream.ws_client.WSClient`` utilisée par le
pont ; un test de contrat vérifie cette API sur la vraie classe.
"""
import asyncio
import json
import socket
import threading
import time
from types import SimpleNamespace
from typing import Callable, List
from unittest.mock import MagicMock

import pytest
from kubernetes.client.exceptions import ApiException
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.main import app
from backend.routers import k8s_terminal
from backend.routers.k8s_terminal import _TerminalBridge, _parse_resize

TERMINAL_PATH = "/api/v1/k8s/terminal/lab-ns/lab-pod"


def _on_event_loop() -> bool:
    """True si l'appelant s'exécute sur un thread de boucle asyncio."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class FakeExecStream:
    """Double du WSClient exec : trames poussées par le test, écritures
    enregistrées, ``update`` bloquant au plus ``timeout`` secondes."""

    _CLOSE_FRAME = object()

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._frames: list = []
        self._buffer = ""
        self._open = True
        self.update_calls = 0
        self.reader_threads: set = set()
        self.writes: List[tuple] = []
        self.writes_on_loop: List[bool] = []
        self.close_calls = 0
        self.closed = threading.Event()

    # --- pilotage par le test ---
    def push(self, data: str) -> None:
        with self._cond:
            self._frames.append(data)
            self._cond.notify_all()

    def finish(self) -> None:
        """Le processus du pod se termine : trame de fermeture après la sortie."""
        self.push(self._CLOSE_FRAME)

    # --- API WSClient ---
    def is_open(self) -> bool:
        return self._open

    def update(self, timeout=0) -> None:
        self.update_calls += 1
        self.reader_threads.add(threading.current_thread())
        with self._cond:
            if not self._open:
                return
            if not self._frames and timeout:
                self._cond.wait(timeout)
            if self._frames:
                frame = self._frames.pop(0)
                if frame is self._CLOSE_FRAME:
                    self._open = False
                else:
                    self._buffer += frame

    def read_all(self) -> str:
        with self._cond:
            out, self._buffer = self._buffer, ""
        return out

    def write_stdin(self, data: str) -> None:
        self.write_channel(0, data)

    def write_channel(self, channel: int, data: str) -> None:
        self.writes_on_loop.append(_on_event_loop())
        self.writes.append((channel, data))

    def close(self, **kwargs) -> None:
        with self._cond:
            self._open = False
            self._cond.notify_all()
        self.close_calls += 1
        self.closed.set()


@pytest.fixture()
def lookup_threads() -> List[bool]:
    return []


@pytest.fixture()
def terminal_pod(mock_k8s, student_user, lookup_threads):
    """Pod LabOnDemand appartenant à l'étudiant ; la lecture du pod note si
    elle a lieu sur la boucle."""
    pod = MagicMock()
    pod.metadata.labels = {
        "managed-by": "labondemand",
        "user-id": str(student_user.id),
        "app-type": "jupyter",
    }

    def _read_pod(*args, **kwargs):
        lookup_threads.append(_on_event_loop())
        return pod

    mock_k8s["core"].read_namespaced_pod.side_effect = _read_pod
    return pod


@pytest.fixture()
def fake_exec(monkeypatch) -> FakeExecStream:
    stream = FakeExecStream()
    stream.calls = []

    def _fake_k8s_stream(api_method, pod, namespace, **kwargs):
        stream.calls.append(
            {"on_loop": _on_event_loop(), "pod": pod, "namespace": namespace, **kwargs}
        )
        return stream

    monkeypatch.setattr(k8s_terminal, "k8s_stream", _fake_k8s_stream)
    return stream


def _connect(token: str = None, path: str = TERMINAL_PATH):
    headers = {"origin": "http://testserver"}
    if token:
        headers["cookie"] = f"session_id={token}"
    return TestClient(app).websocket_connect(path, headers=headers)


def _assert_reader_stopped(stream: FakeExecStream) -> None:
    assert stream.reader_threads, "le thread lecteur n'a jamais lu le flux"
    for thread in stream.reader_threads:
        assert thread is not threading.main_thread()
        thread.join(timeout=3)
        assert not thread.is_alive()


# ---------------------------------------------------------------------------
# Bout en bout via la route WebSocket
# ---------------------------------------------------------------------------

def test_terminal_relays_io_off_loop_and_cleans_up_on_client_disconnect(
    student_token, terminal_pod, fake_exec, lookup_threads
):
    with _connect(student_token) as ws:
        fake_exec.push("bienvenue$ ")
        assert ws.receive_text() == "bienvenue$ "

        ws.send_text("ls\n")
        ws.send_text(json.dumps({"type": "resize", "cols": 120, "rows": 40}))
        assert _wait_until(lambda: len(fake_exec.writes) == 2)

        # Session inactive : le lecteur attend dans update(timeout), sans
        # tourner à vide (l'ancienne boucle faisait des centaines d'appels/s).
        before = fake_exec.update_calls
        time.sleep(1.0)
        assert fake_exec.update_calls - before <= 6

    # Fermeture côté navigateur : flux exec fermé une fois, thread terminé.
    assert fake_exec.closed.wait(3)
    assert fake_exec.close_calls == 1
    _assert_reader_stopped(fake_exec)

    # Rien de bloquant sur la boucle : lecture du pod, ouverture du flux,
    # écritures (saisie + redimensionnement sur le canal 4).
    assert lookup_threads == [False]
    [call] = fake_exec.calls
    assert call["on_loop"] is False
    assert (call["pod"], call["namespace"]) == ("lab-pod", "lab-ns")
    assert call["command"] == ["/bin/sh"]
    assert call["tty"] is True and call["stdin"] is True
    assert call["_preload_content"] is False
    assert fake_exec.writes == [
        (0, "ls\n"),
        (k8s_terminal.RESIZE_CHANNEL, '{"Width": 120, "Height": 40}'),
    ]
    assert fake_exec.writes_on_loop == [False, False]


def test_terminal_closes_websocket_when_exec_process_ends(
    student_token, terminal_pod, fake_exec
):
    with _connect(student_token) as ws:
        fake_exec.push("exit\r\n")
        fake_exec.finish()
        # La dernière sortie est transmise avant la fermeture normale.
        assert ws.receive_text() == "exit\r\n"
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_text()
        assert exc_info.value.code == 1000

    assert fake_exec.close_calls == 1
    _assert_reader_stopped(fake_exec)


def test_terminal_idle_timeout_closes_session(
    student_token, terminal_pod, fake_exec, monkeypatch
):
    monkeypatch.setattr(k8s_terminal.settings, "TERMINAL_IDLE_TIMEOUT_SECONDS", 0.3)
    started = time.monotonic()
    with _connect(student_token) as ws:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_text()
        assert exc_info.value.code == 4408
    assert time.monotonic() - started < 3
    assert fake_exec.closed.is_set()
    _assert_reader_stopped(fake_exec)


def test_terminal_activity_in_both_directions_postpones_idle_timeout(
    student_token, terminal_pod, fake_exec, monkeypatch
):
    monkeypatch.setattr(k8s_terminal.settings, "TERMINAL_IDLE_TIMEOUT_SECONDS", 0.6)
    with _connect(student_token) as ws:
        started = time.monotonic()
        # 1,2 s d'activité alternée (sortie du pod puis saisie) : plus que le
        # délai d'inactivité, la session doit rester ouverte.
        for index in range(4):
            fake_exec.push(f"ligne {index}\n")
            assert ws.receive_text() == f"ligne {index}\n"
            time.sleep(0.15)
            ws.send_text("x")
            time.sleep(0.15)
        assert time.monotonic() - started >= 1.2
        assert not fake_exec.closed.is_set()

        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_text()
        assert exc_info.value.code == 4408


def test_terminal_without_session_is_rejected_before_exec(fake_exec, mock_k8s):
    with _connect(None) as ws:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_text()
        assert exc_info.value.code == 4401
    assert fake_exec.calls == []


def test_terminal_unknown_pod_is_rejected_before_exec(
    student_token, mock_k8s, fake_exec
):
    mock_k8s["core"].read_namespaced_pod.side_effect = ApiException(status=404)
    with _connect(student_token) as ws:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_text()
        assert exc_info.value.code == 4404
    assert fake_exec.calls == []


def test_terminal_exec_failure_closes_with_internal_error(
    student_token, terminal_pod, monkeypatch
):
    def _failing_stream(*args, **kwargs):
        raise ApiException(status=0, reason="handshake failed")

    monkeypatch.setattr(k8s_terminal, "k8s_stream", _failing_stream)
    with _connect(student_token) as ws:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_text()
        assert exc_info.value.code == 1011


# ---------------------------------------------------------------------------
# Unitaires
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "message, expected",
    [
        ('{"type": "resize", "cols": 132, "rows": 43}', (132, 43)),
        ('{"type": "resize"}', (80, 24)),
        ('{"type": "resize", "cols": "abc", "rows": 10}', (80, 24)),
        ('{"type": "resize", "cols": 0, "rows": -5}', (80, 1)),
        ('{"type": "resize", "cols": 100000, "rows": 100000}', (1000, 1000)),
        ('{"type": "other"}', None),
        ('{"cols": 10}', None),
        ("[1, 2]", None),
        ("{pas du json", None),
        ("ls -la\n", None),
    ],
)
def test_parse_resize(message, expected):
    assert _parse_resize(message) == expected


def test_idle_timeout_zero_disables_idle_close():
    disabled = _TerminalBridge(MagicMock(), MagicMock(), idle_timeout=0)
    assert disabled._idle_remaining() is None

    enabled = _TerminalBridge(MagicMock(), MagicMock(), idle_timeout=1800)
    remaining = enabled._idle_remaining()
    assert remaining is not None and 1799 < remaining <= 1800


def test_idle_timeout_setting_default_is_30_minutes():
    from backend.config import Settings

    assert Settings.TERMINAL_IDLE_TIMEOUT_SECONDS == 1800


def test_wsclient_contract_used_by_the_bridge(monkeypatch):
    """Vérifie sur la vraie classe WSClient l'API dont dépend le pont :
    update(timeout) borné, read_all (stdout+stderr dans l'ordre, tampon vidé),
    is_open, write_stdin, write_channel(RESIZE_CHANNEL) et close.

    Compatible kubernetes 32.x (v4.channel.k8s.io) et 36.x, qui négocie
    v5.channel.k8s.io et lit ``subprotocol`` / ``getheaders()`` du socket."""
    from kubernetes.stream import ws_client as ws_mod
    from websocket import ABNF

    readable, writer = socket.socketpair()
    frames: list = []
    sent: list = []

    class _FakeWebSocket:
        connected = True
        subprotocol = "v5.channel.k8s.io"

        def __init__(self):
            self.sock = readable

        def getheaders(self):
            return {"sec-websocket-protocol": self.subprotocol}

        def recv_data_frame(self, control_frame=False):
            readable.recv(1)
            return frames.pop(0)

        def send(self, payload, opcode=ABNF.OPCODE_TEXT):
            sent.append((payload, opcode))

        def close(self, **kwargs):
            self.connected = False

    def _frame(opcode, data: bytes) -> None:
        frames.append((opcode, SimpleNamespace(data=data)))
        writer.send(b"x")

    monkeypatch.setattr(
        ws_mod, "create_websocket", lambda configuration, url, headers=None: _FakeWebSocket()
    )
    try:
        exec_client = ws_mod.websocket_call(
            MagicMock(),
            "GET",
            "https://k8s.invalid/api/v1/namespaces/ns/pods/p/exec",
            headers={},
            _preload_content=False,
        )
        assert exec_client.is_open()

        # Sans donnée, update(timeout) rend la main après le délai.
        started = time.monotonic()
        exec_client.update(timeout=0.2)
        assert 0.15 <= time.monotonic() - started < 1
        assert exec_client.read_all() == ""

        _frame(ABNF.OPCODE_TEXT, b"\x01hello ")
        _frame(ABNF.OPCODE_TEXT, b"\x02oops")
        # Signal CLOSE v5 (canal 255) : jamais mêlé à la sortie du terminal.
        _frame(ABNF.OPCODE_BINARY, bytes([255, 1]))
        exec_client.update(timeout=1)
        exec_client.update(timeout=0)
        exec_client.update(timeout=0)
        assert exec_client.read_all() == "hello oops"
        assert exec_client.is_open()
        assert exec_client.read_all() == ""

        exec_client.write_stdin("ls\n")
        exec_client.write_channel(
            ws_mod.RESIZE_CHANNEL, json.dumps({"Width": 100, "Height": 30})
        )
        assert ws_mod.RESIZE_CHANNEL == 4
        assert sent == [
            ("\x00ls\n", ABNF.OPCODE_TEXT),
            ('\x04{"Width": 100, "Height": 30}', ABNF.OPCODE_TEXT),
        ]

        _frame(ABNF.OPCODE_CLOSE, b"")
        exec_client.update(timeout=1)
        assert not exec_client.is_open()
        exec_client.close()
    finally:
        readable.close()
        writer.close()
