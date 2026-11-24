"""Tests for the web terminal authorization step and the app lifespan.

``_authorize_terminal`` is the blocking part of the WebSocket handler (Redis,
DB, Kubernetes); the handler runs it in a worker thread.
"""
import asyncio
from unittest.mock import MagicMock

from kubernetes import client as k8s_client

from backend.routers.k8s_terminal import _authorize_terminal


def _pod(labels):
    pod = MagicMock()
    pod.metadata.labels = labels
    return pod


def test_terminal_requires_session(mock_k8s):
    assert _authorize_terminal(None, "ns", "pod") == 4401
    assert _authorize_terminal("unknown-session", "ns", "pod") == 4401
    mock_k8s["core"].read_namespaced_pod.assert_not_called()


def test_terminal_rejects_inactive_user(mock_k8s, db, student_user, student_token):
    student_user.is_active = False
    db.commit()
    assert _authorize_terminal(student_token, "ns", "pod") == 4401


def test_terminal_allows_own_pod(mock_k8s, student_user, student_token):
    mock_k8s["core"].read_namespaced_pod.return_value = _pod(
        {"managed-by": "labondemand", "user-id": str(student_user.id), "app-type": "vscode"}
    )
    assert _authorize_terminal(student_token, f"labondemand-user-{student_user.id}", "lab-0") is None


def test_terminal_denies_foreign_pod(mock_k8s, admin_user, student_token):
    mock_k8s["core"].read_namespaced_pod.return_value = _pod(
        {"managed-by": "labondemand", "user-id": str(admin_user.id)}
    )
    assert _authorize_terminal(student_token, "labondemand-admin", "lab-0") == 4403


def test_terminal_denies_database_pod(mock_k8s, student_user, student_token):
    mock_k8s["core"].read_namespaced_pod.return_value = _pod(
        {
            "managed-by": "labondemand",
            "user-id": str(student_user.id),
            "component": "database",
            "app-type": "mysql",
        }
    )
    assert _authorize_terminal(student_token, f"labondemand-user-{student_user.id}", "db-0") == 4403


def test_terminal_missing_pod(mock_k8s, student_token):
    mock_k8s["core"].read_namespaced_pod.side_effect = k8s_client.exceptions.ApiException(status=404)
    assert _authorize_terminal(student_token, "ns", "gone") == 4404


async def test_lifespan_cancels_background_tasks(monkeypatch):
    from backend import grader_service, main
    from backend.tasks import cleanup

    state = {"started": False, "cancelled": False, "shutdown": False}

    async def fake_cleanup_loop():
        state["started"] = True
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    monkeypatch.setattr(main, "_bootstrap_database", lambda: None)
    monkeypatch.setattr(cleanup, "run_cleanup_loop", fake_cleanup_loop)
    monkeypatch.setattr(grader_service, "shutdown", lambda: state.update(shutdown=True))

    async with main.lifespan(main.app):
        await asyncio.sleep(0)
        assert state["started"]

    assert state["cancelled"]
    assert state["shutdown"]



def test_terminal_websocket_closes_unauthenticated(mock_k8s):
    import pytest
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from backend.main import app

    client = TestClient(app)
    with client.websocket_connect("/api/v1/k8s/terminal/ns/pod") as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
    assert exc.value.code == 4401


class _FakeExec:
    """Minimal stand-in for the kubernetes exec WSClient (echo shell)."""

    def __init__(self) -> None:
        import queue

        self._open = True
        self._out: "queue.Queue[str]" = queue.Queue()
        self.stdin: list = []
        self.resized = None

    def is_open(self) -> bool:
        return self._open

    def read_stdout(self, timeout=None):
        import queue

        try:
            return self._out.get(timeout=timeout)
        except queue.Empty:
            return None

    def read_stderr(self, timeout=None):
        return None

    def write_stdin(self, data) -> None:
        self.stdin.append(data)
        if data == "exit":
            self._open = False
        else:
            self._out.put(f"echo:{data}")

    def resize_terminal(self, width, height) -> None:
        self.resized = (width, height)

    def close(self) -> None:
        self._open = False


def test_terminal_websocket_round_trip(mock_k8s, student_user, student_token):
    import pytest
    from unittest.mock import patch
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from backend.main import app

    mock_k8s["core"].read_namespaced_pod.return_value = _pod(
        {"managed-by": "labondemand", "user-id": str(student_user.id), "app-type": "vscode"}
    )
    fake = _FakeExec()
    ns = f"labondemand-user-{student_user.id}"
    with patch("backend.routers.k8s_terminal.k8s_stream", return_value=fake):
        client = TestClient(app)
        with client.websocket_connect(
            f"/api/v1/k8s/terminal/{ns}/lab-0", headers={"cookie": f"session_id={student_token}"}
        ) as ws:
            ws.send_text('{"type": "resize", "cols": 120, "rows": 40}')
            ws.send_text("ls")
            assert ws.receive_text() == "echo:ls"
            ws.send_text("exit")
            # The shell ended: the server closes the browser side.
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()

    assert fake.resized == (120, 40)
    assert fake.stdin == ["ls", "exit"]
