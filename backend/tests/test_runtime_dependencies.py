"""Dépendances d'exécution de l'image API.

Garde-fous contre deux régressions déjà rencontrées :

- uvicorn installé sans ``[standard]`` : aucune bibliothèque WebSocket
  (``websockets`` / ``wsproto``) n'est présente et uvicorn répond à la poignée
  de main du terminal web (``/api/v1/k8s/terminal/...``) par un refus
  « Unsupported upgrade request » ;
- retour accidentel à une version vulnérable d'une dépendance sensible.

Ces tests tournent dans l'image de test, construite depuis le même stage
``base`` que l'image d'exécution : ils vérifient donc ce qui sera déployé.
"""
import importlib.metadata
import importlib.util
import socket
import threading
import time

import pytest
import uvicorn
from fastapi import FastAPI, WebSocket
from packaging.version import Version


def _minimal_app() -> FastAPI:
    """Application jetable : écho puis fermeture avec un code applicatif."""
    app = FastAPI()

    @app.websocket("/ws/echo")
    async def echo(websocket: WebSocket) -> None:
        await websocket.accept()
        message = await websocket.receive_text()
        await websocket.send_text(f"echo:{message}")
        # Même famille de codes que le terminal (4401, 4403, 4404…)
        await websocket.close(code=4401)

    return app


# ============= Bibliothèque WebSocket =============

def test_websocket_library_is_installed():
    assert (
        importlib.util.find_spec("websockets") is not None
        or importlib.util.find_spec("wsproto") is not None
    ), "Installer uvicorn[standard] : aucune implémentation WebSocket disponible"


def test_uvicorn_auto_ws_resolves_to_an_implementation():
    # log_config=None : ne pas reconfigurer la journalisation de la suite.
    config = uvicorn.Config(_minimal_app(), ws="auto", log_config=None)
    config.load()
    assert config.ws_protocol_class is not None


def test_uvicorn_serves_websocket_end_to_end():
    """Poignée de main réelle via uvicorn (ws="auto", parseur HTTP par défaut)."""
    # Import local : sans bibliothèque WebSocket, seuls ces tests échouent.
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.client import connect

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    config = uvicorn.Config(
        _minimal_app(),
        ws="auto",
        lifespan="off",
        log_config=None,
        # Boucle asyncio standard : pas d'effet de bord sur celle de pytest.
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            assert thread.is_alive(), "uvicorn s'est arrêté au démarrage"
            assert time.monotonic() < deadline, "uvicorn n'a pas démarré à temps"
            time.sleep(0.02)

        with connect(f"ws://127.0.0.1:{port}/ws/echo", open_timeout=5, close_timeout=5) as ws:
            ws.send("ping")
            assert ws.recv(timeout=5) == "echo:ping"
            with pytest.raises(ConnectionClosed) as closed:
                ws.recv(timeout=5)
        assert closed.value.rcvd is not None
        assert closed.value.rcvd.code == 4401
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


# ============= Versions minimales des dépendances sensibles =============

@pytest.mark.parametrize(
    "distribution, minimum",
    [
        ("starlette", "0.49.1"),  # CVE-2025-54121, CVE-2025-62727
        ("python-multipart", "0.0.18"),  # CVE-2024-24762, CVE-2024-53981
        ("PyMySQL", "1.1.1"),  # CVE-2024-36039
    ],
)
def test_security_sensitive_dependency_is_recent_enough(distribution, minimum):
    installed = Version(importlib.metadata.version(distribution))
    assert installed >= Version(minimum), f"{distribution} {installed} < {minimum}"


def test_passlib_is_not_installed():
    """passlib (non maintenu) a été remplacé par bcrypt : voir password_hashing.py."""
    assert importlib.util.find_spec("passlib") is None
