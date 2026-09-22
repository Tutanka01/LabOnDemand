"""Tests de l'explorateur de fichiers des volumes persistants."""
from collections import namedtuple
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from kubernetes.client.exceptions import ApiException

from backend.k8s_utils import build_user_namespace
from backend.routers._helpers import raise_k8s_http

WSResponse = namedtuple("WSResponse", ["data"])
MARKER = "\x01lod-exit\x01"


def _exec_result(stdout: str = "", code: int = 0) -> WSResponse:
    """Réponse d'un exec one-shot terminé, marqueur de sortie compris."""
    return WSResponse(f"{stdout}\n{MARKER}{code}")


def _make_pod(name, namespace, user_id, app_type="vscode", phase="Running", component=None, pvcs=()):
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.namespace = namespace
    pod.metadata.labels = {
        "managed-by": "labondemand",
        "user-id": str(user_id),
        "app-type": app_type,
    }
    if component:
        pod.metadata.labels["component"] = component
    pod.status.phase = phase
    pod.spec.volumes = [
        MagicMock(persistent_volume_claim=MagicMock(claim_name=claim)) for claim in pvcs
    ]
    return pod


def _make_pvc(name, namespace, user_id, phase="Bound"):
    pvc = MagicMock()
    pvc.metadata.name = name
    pvc.metadata.namespace = namespace
    pvc.metadata.labels = {"managed-by": "labondemand", "user-id": str(user_id)}
    pvc.status.phase = phase
    return pvc


class _FakeStreamClient:
    """Remplace le WSClient du client Kubernetes pour les transferts."""

    def __init__(self, chunks, return_code=0, errors=b""):
        self._chunks = list(chunks)
        self._return_code = return_code
        self._errors = errors
        self.writes = []
        self.closed = False

    def read_channel(self, channel, timeout=0):
        return self._chunks.pop(0) if self._chunks else b""

    def is_open(self):
        return bool(self._chunks)

    def write_stdin(self, data):
        self.writes.append(data)

    def update(self, timeout=0):
        self._chunks = []

    def read_all(self):
        return self._errors

    @property
    def returncode(self):
        return self._return_code

    def close(self):
        self.closed = True


def _install_exec(handler):
    """Patche l'exec Kubernetes avec un handler `(script, kwargs) -> réponse`."""

    def _side_effect(_func, _pod, _namespace, **kwargs):
        return handler(kwargs["command"][2], kwargs)

    return patch("backend.routers.k8s_files.k8s_stream", side_effect=_side_effect)


def _find_line(entry_type: str, size: int, mtime: float, name: str) -> str:
    return f"{entry_type}\x00{size}\x00{mtime}\x00{name}\x00"


# ─── Listing ────────────────────────────────────────────


async def test_list_files_requires_auth(client, mock_k8s):
    r = await client.get("/api/v1/k8s/files", params={"namespace": "ns", "pod": "pod-1"})
    assert r.status_code == 401


async def test_list_files_parses_find_output(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    pod = _make_pod("vscode-1", namespace, student_user.id)
    mock_k8s["core"].read_namespaced_pod.return_value = pod

    listing = (
        _find_line("d", 4096, 1700000000.0, "tp1")
        + _find_line("f", 128, 1700000001.0, "notes.md")
        + _find_line("f", 64, 1700000002.0, ".secret")
        + _find_line("f", 10, 1700000003.0, "archive.bin")
    )

    def handler(script, kwargs):
        return _exec_result(listing)

    with _install_exec(handler):
        r = await student_client.get(
            "/api/v1/k8s/files", params={"namespace": namespace, "pod": "vscode-1"}
        )

    assert r.status_code == 200
    body = r.json()
    assert body["root"] == "/home/coder/project"
    assert body["path"] == "/home/coder/project"
    assert body["parent"] is None
    names = [entry["name"] for entry in body["entries"]]
    assert names == ["tp1", "archive.bin", "notes.md"]  # dossiers d'abord, cachés masqués
    by_name = {entry["name"]: entry for entry in body["entries"]}
    assert by_name["tp1"]["type"] == "dir"
    assert by_name["tp1"]["size"] is None
    assert by_name["notes.md"]["preview"] == "text"
    assert by_name["archive.bin"]["preview"] is None


async def test_list_files_include_hidden(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    pod = _make_pod("vscode-1", namespace, student_user.id)
    mock_k8s["core"].read_namespaced_pod.return_value = pod
    listing = _find_line("f", 64, 1700000002.0, ".bashrc")

    with _install_exec(lambda script, kwargs: _exec_result(listing)):
        r = await student_client.get(
            "/api/v1/k8s/files",
            params={"namespace": namespace, "pod": "vscode-1", "include_hidden": "true"},
        )

    assert r.status_code == 200
    assert [entry["name"] for entry in r.json()["entries"]] == [".bashrc"]


async def test_list_files_rejects_path_outside_volume(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    mock_k8s["core"].read_namespaced_pod.return_value = _make_pod("vscode-1", namespace, student_user.id)

    with _install_exec(lambda script, kwargs: _exec_result("")):
        r = await student_client.get(
            "/api/v1/k8s/files",
            params={"namespace": namespace, "pod": "vscode-1", "path": "/home/coder/project/../.ssh"},
        )

    assert r.status_code == 400


async def test_list_files_denies_foreign_pod(student_client, mock_k8s, admin_user):
    mock_k8s["core"].read_namespaced_pod.return_value = _make_pod(
        "vscode-1", f"labondemand-user-{admin_user.id}", admin_user.id
    )

    with _install_exec(lambda script, kwargs: _exec_result("")):
        r = await student_client.get(
            "/api/v1/k8s/files",
            params={"namespace": f"labondemand-user-{admin_user.id}", "pod": "vscode-1"},
        )

    assert r.status_code == 403


async def test_list_files_denies_database_pod(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    pod = _make_pod("mysql-1", namespace, student_user.id, app_type="mysql", component="database")
    mock_k8s["core"].read_namespaced_pod.return_value = pod

    with _install_exec(lambda script, kwargs: _exec_result("")):
        r = await student_client.get(
            "/api/v1/k8s/files", params={"namespace": namespace, "pod": "mysql-1"}
        )

    assert r.status_code == 403


async def test_list_files_rejects_paused_lab(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    pod = _make_pod("vscode-1", namespace, student_user.id, phase="Pending")
    mock_k8s["core"].read_namespaced_pod.return_value = pod

    with _install_exec(lambda script, kwargs: _exec_result("")):
        r = await student_client.get(
            "/api/v1/k8s/files", params={"namespace": namespace, "pod": "vscode-1"}
        )

    assert r.status_code == 409


async def test_list_files_by_pvc_without_running_pod(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    mock_k8s["core"].read_namespaced_persistent_volume_claim.return_value = _make_pvc(
        "vscode-pvc", namespace, student_user.id
    )
    mock_k8s["core"].list_namespaced_pod.return_value = MagicMock(items=[])

    with _install_exec(lambda script, kwargs: _exec_result("")):
        r = await student_client.get(
            "/api/v1/k8s/files", params={"namespace": namespace, "pvc": "vscode-pvc"}
        )

    assert r.status_code == 409
    assert "lab" in r.json()["detail"].lower()


async def test_list_files_by_pvc_with_stopped_pod(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    mock_k8s["core"].read_namespaced_persistent_volume_claim.return_value = _make_pvc(
        "vscode-pvc", namespace, student_user.id
    )
    mock_k8s["core"].list_namespaced_pod.return_value = MagicMock(
        items=[_make_pod("vscode-1", namespace, student_user.id, phase="Pending", pvcs=["vscode-pvc"])]
    )

    with _install_exec(lambda script, kwargs: _exec_result("")):
        r = await student_client.get(
            "/api/v1/k8s/files", params={"namespace": namespace, "pvc": "vscode-pvc"}
        )

    assert r.status_code == 409
    assert "pause" in r.json()["detail"].lower()


async def test_list_files_by_pvc_finds_pod(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    mock_k8s["core"].read_namespaced_persistent_volume_claim.return_value = _make_pvc(
        "vscode-pvc", namespace, student_user.id
    )
    mock_k8s["core"].list_namespaced_pod.return_value = MagicMock(
        items=[_make_pod("vscode-1", namespace, student_user.id, pvcs=["vscode-pvc"])]
    )
    listing = _find_line("f", 12, 1700000000.0, "main.py")

    with _install_exec(lambda script, kwargs: _exec_result(listing)):
        r = await student_client.get(
            "/api/v1/k8s/files", params={"namespace": namespace, "pvc": "vscode-pvc"}
        )

    assert r.status_code == 200
    assert r.json()["entries"][0]["name"] == "main.py"


# ─── Téléchargement ─────────────────────────────────────


async def test_download_file_streams_content(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    mock_k8s["core"].read_namespaced_pod.return_value = _make_pod("vscode-1", namespace, student_user.id)
    fake = _FakeStreamClient([b"hello ", b"world"])

    def handler(script, kwargs):
        if "elif [ -e" in script:
            return _exec_result("file")
        if "stat -c %s" in script:
            return _exec_result("11")
        return fake

    with _install_exec(handler):
        r = await student_client.get(
            "/api/v1/k8s/files/download",
            params={"namespace": namespace, "pod": "vscode-1", "path": "/home/coder/project/a.txt"},
        )

    assert r.status_code == 200
    assert r.content == b"hello world"
    assert r.headers["content-length"] == "11"
    assert "attachment" in r.headers["content-disposition"]
    assert fake.closed is True


async def test_download_directory_returns_tar(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    mock_k8s["core"].read_namespaced_pod.return_value = _make_pod("vscode-1", namespace, student_user.id)
    fake = _FakeStreamClient([b"tar-bytes"])

    def handler(script, kwargs):
        if "elif [ -e" in script:
            return _exec_result("dir")
        return fake

    with _install_exec(handler):
        r = await student_client.get(
            "/api/v1/k8s/files/download",
            params={"namespace": namespace, "pod": "vscode-1", "path": "/home/coder/project/tp1"},
        )

    assert r.status_code == 200
    assert r.content == b"tar-bytes"
    assert r.headers["content-type"] == "application/x-tar"
    assert 'filename="tp1.tar"' in r.headers["content-disposition"]


async def test_download_refuses_volume_root(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    mock_k8s["core"].read_namespaced_pod.return_value = _make_pod("vscode-1", namespace, student_user.id)

    with _install_exec(lambda script, kwargs: _exec_result("")):
        r = await student_client.get(
            "/api/v1/k8s/files/download",
            params={"namespace": namespace, "pod": "vscode-1", "path": "/home/coder/project"},
        )

    assert r.status_code == 400


# ─── Aperçu ─────────────────────────────────────────────


async def test_preview_truncates_large_text(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    mock_k8s["core"].read_namespaced_pod.return_value = _make_pod("vscode-1", namespace, student_user.id)
    fake = _FakeStreamClient([b"contenu"])

    def handler(script, kwargs):
        if "stat -c %s" in script:
            return _exec_result(str(10 * 1024 * 1024))
        return fake

    with _install_exec(handler):
        r = await student_client.get(
            "/api/v1/k8s/files/preview",
            params={"namespace": namespace, "pod": "vscode-1", "path": "/home/coder/project/log.txt"},
        )

    assert r.status_code == 200
    assert r.headers["x-labondemand-truncated"] == "1"
    assert r.headers["content-length"] == str(262144)
    assert r.headers["content-security-policy"] == "sandbox"


async def test_preview_refuses_binary(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    mock_k8s["core"].read_namespaced_pod.return_value = _make_pod("vscode-1", namespace, student_user.id)

    with _install_exec(lambda script, kwargs: _exec_result("")):
        r = await student_client.get(
            "/api/v1/k8s/files/preview",
            params={"namespace": namespace, "pod": "vscode-1", "path": "/home/coder/project/app.bin"},
        )

    assert r.status_code == 415


# ─── Dépôt, dossiers, renommage, suppression ────────────


async def test_upload_writes_file(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    mock_k8s["core"].read_namespaced_pod.return_value = _make_pod("vscode-1", namespace, student_user.id)
    fake = _FakeStreamClient([])
    scripts = []

    def handler(script, kwargs):
        scripts.append(script)
        if "stat -c %s" in script:
            return _exec_result("11")
        return fake

    with _install_exec(handler):
        r = await student_client.post(
            "/api/v1/k8s/files/upload",
            data={"namespace": namespace, "pod": "vscode-1", "path": "/home/coder/project"},
            files={"file": ("notes.txt", b"hello world", "text/plain")},
        )

    assert r.status_code == 200
    assert r.json()["name"] == "notes.txt"
    assert b"".join(fake.writes) == b"hello world"
    assert "head -c 11 > /home/coder/project/notes.txt" in scripts[0]


async def test_upload_strips_directory_from_filename(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    mock_k8s["core"].read_namespaced_pod.return_value = _make_pod("vscode-1", namespace, student_user.id)
    fake = _FakeStreamClient([])
    scripts = []

    def handler(script, kwargs):
        scripts.append(script)
        if "stat -c %s" in script:
            return _exec_result("1")
        return fake

    with _install_exec(handler):
        r = await student_client.post(
            "/api/v1/k8s/files/upload",
            data={"namespace": namespace, "pod": "vscode-1", "path": "/home/coder/project"},
            files={"file": ("../../etc/passwd", b"x", "text/plain")},
        )

    assert r.status_code == 200
    assert r.json()["name"] == "passwd"
    assert "> /home/coder/project/passwd" in scripts[0]
    assert "/etc/passwd" not in scripts[0]


async def test_upload_detects_truncated_write(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    mock_k8s["core"].read_namespaced_pod.return_value = _make_pod("vscode-1", namespace, student_user.id)
    fake = _FakeStreamClient([])

    def handler(script, kwargs):
        if "stat -c %s" in script:
            return _exec_result("3")  # 3 octets écrits au lieu de 11
        return fake

    with _install_exec(handler):
        r = await student_client.post(
            "/api/v1/k8s/files/upload",
            data={"namespace": namespace, "pod": "vscode-1", "path": "/home/coder/project"},
            files={"file": ("notes.txt", b"hello world", "text/plain")},
        )

    assert r.status_code == 422
    assert "incomplet" in r.json()["detail"]


async def test_upload_reports_pod_error(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    mock_k8s["core"].read_namespaced_pod.return_value = _make_pod("vscode-1", namespace, student_user.id)
    fake = _FakeStreamClient([], return_code=1, errors=b"head: cannot create: Permission denied")

    with _install_exec(lambda script, kwargs: fake):
        r = await student_client.post(
            "/api/v1/k8s/files/upload",
            data={"namespace": namespace, "pod": "vscode-1", "path": "/home/coder/project"},
            files={"file": ("notes.txt", b"data", "text/plain")},
        )

    assert r.status_code == 422
    assert "Permission denied" in r.json()["detail"]


async def test_mkdir_conflict(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    mock_k8s["core"].read_namespaced_pod.return_value = _make_pod("vscode-1", namespace, student_user.id)

    with _install_exec(lambda script, kwargs: _exec_result("exists", code=3)):
        r = await student_client.post(
            "/api/v1/k8s/files/mkdir",
            json={"namespace": namespace, "pod": "vscode-1", "path": "/home/coder/project", "name": "tp1"},
        )

    assert r.status_code == 409


async def test_rename_rejects_root(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    mock_k8s["core"].read_namespaced_pod.return_value = _make_pod("vscode-1", namespace, student_user.id)

    with _install_exec(lambda script, kwargs: _exec_result("")):
        r = await student_client.post(
            "/api/v1/k8s/files/rename",
            json={
                "namespace": namespace,
                "pod": "vscode-1",
                "path": "/home/coder/project",
                "new_name": "autre",
            },
        )

    assert r.status_code == 400


async def test_delete_rejects_root(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    mock_k8s["core"].read_namespaced_pod.return_value = _make_pod("vscode-1", namespace, student_user.id)

    with _install_exec(lambda script, kwargs: _exec_result("")):
        r = await student_client.delete(
            "/api/v1/k8s/files",
            params={"namespace": namespace, "pod": "vscode-1", "path": "/home/coder/project"},
        )

    assert r.status_code == 400


async def test_delete_missing_entry(student_client, mock_k8s, student_user):
    namespace = build_user_namespace(student_user)
    mock_k8s["core"].read_namespaced_pod.return_value = _make_pod("vscode-1", namespace, student_user.id)

    with _install_exec(lambda script, kwargs: _exec_result("missing", code=4)):
        r = await student_client.delete(
            "/api/v1/k8s/files",
            params={"namespace": namespace, "pod": "vscode-1", "path": "/home/coder/project/absent.txt"},
        )

    assert r.status_code == 404


# ─── Robustesse du transport exec ─────────────────────


class _DyingStreamClient:
    """WSClient dont le pair ferme la connexion sans frame CLOSE."""

    def __init__(self, collected: str):
        self._collected = collected

    def is_open(self):
        return True

    def update(self, timeout=0):
        raise RuntimeError("Connection to remote host was lost.")

    def read_all(self):
        return self._collected

    def close(self):
        pass


async def test_list_files_survives_abrupt_stream_close(student_client, mock_k8s, student_user):
    """La sortie déjà reçue survit à une coupure brutale du flux exec."""
    namespace = build_user_namespace(student_user)
    mock_k8s["core"].read_namespaced_pod.return_value = _make_pod(
        "vscode-1", namespace, student_user.id
    )
    listing = _find_line("f", 12, 1700000000.0, "notes.md")
    dead = _DyingStreamClient(f"{listing}\n{MARKER}0")

    with patch("backend.routers.k8s_files.k8s_stream", return_value=dead):
        r = await student_client.get(
            "/api/v1/k8s/files", params={"namespace": namespace, "pod": "vscode-1"}
        )

    assert r.status_code == 200
    assert [entry["name"] for entry in r.json()["entries"]] == ["notes.md"]


def test_transport_failure_is_not_a_500():
    """Un websocket coupé (ApiException sans status) doit donner 502, jamais 500."""
    with pytest.raises(HTTPException) as exc:
        raise_k8s_http(ApiException(status=0, reason="Connection to remote host was lost."))
    assert exc.value.status_code == 502


def test_http_exception_passes_through_untouched():
    """Une HTTPException ne doit jamais être re-emballée en erreur opaque."""
    with pytest.raises(HTTPException) as exc:
        raise_k8s_http(HTTPException(status_code=404, detail="Dossier introuvable"))
    assert exc.value.status_code == 404
    assert exc.value.detail == "Dossier introuvable"
