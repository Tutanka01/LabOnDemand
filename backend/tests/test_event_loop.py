"""
Tests de non-blocage de la boucle asyncio et de bornage des appels K8s.

Sections :
  - délais par défaut du client REST Kubernetes (backend/k8s_timeouts.py) ;
  - dimensionnement du pool de threads AnyIO ;
  - services K8s synchrones (exécutés hors boucle par les appelants) ;
  - garde statique : endpoints/dépendances async limités à une liste blanche.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Dict
from unittest.mock import MagicMock

import anyio.to_thread
import pytest
import urllib3
from kubernetes import client as k8s_client
from kubernetes.client import rest

from backend import k8s_timeouts
from backend.config import settings


# ============================================================
# Délais par défaut du client REST Kubernetes
# ============================================================


@pytest.fixture()
def rest_client():
    """RESTClientObject réel dont le pool urllib3 est remplacé par un mock."""
    configuration = k8s_client.Configuration()
    configuration.host = "https://k8s.invalid:6443"
    rc = rest.RESTClientObject(configuration)
    response = MagicMock(status=200, reason="OK", data=b"{}", headers={})
    rc.pool_manager = MagicMock()
    rc.pool_manager.request.return_value = response
    return rc


@pytest.fixture()
def default_timeouts():
    """Installe des délais connus puis restaure la configuration applicative."""
    k8s_timeouts.install_default_request_timeout(5, 30)
    yield
    k8s_timeouts.install_default_request_timeout(
        settings.K8S_REQUEST_TIMEOUT_CONNECT, settings.K8S_REQUEST_TIMEOUT_READ
    )


def _sent_timeout(rc: rest.RESTClientObject) -> urllib3.Timeout:
    return rc.pool_manager.request.call_args.kwargs["timeout"]


def test_default_timeout_is_installed_at_startup():
    # init_kubernetes() (appelé à l'import de backend.main) installe l'enveloppe.
    assert getattr(rest.RESTClientObject.request, "__labondemand_default_timeout__", False)


def test_default_timeout_applied_when_caller_gives_none(rest_client, default_timeouts):
    rest_client.GET("https://k8s.invalid:6443/api/v1/namespaces")
    timeout = _sent_timeout(rest_client)
    assert isinstance(timeout, urllib3.Timeout)
    assert timeout.connect_timeout == 5
    assert timeout.read_timeout == 30


def test_default_timeout_applied_through_generated_api(default_timeouts):
    # Les API générées passent toujours _request_timeout=None explicitement.
    configuration = k8s_client.Configuration()
    configuration.host = "https://k8s.invalid:6443"
    api_client = k8s_client.ApiClient(configuration)
    response = MagicMock(status=200, reason="OK", data=b'{"items": []}', headers={})
    api_client.rest_client.pool_manager = MagicMock()
    api_client.rest_client.pool_manager.request.return_value = response
    k8s_client.CoreV1Api(api_client).list_namespace(limit=1)
    timeout = api_client.rest_client.pool_manager.request.call_args.kwargs["timeout"]
    assert (timeout.connect_timeout, timeout.read_timeout) == (5, 30)


def test_explicit_int_timeout_is_preserved(rest_client, default_timeouts):
    rest_client.GET("https://k8s.invalid:6443/api", _request_timeout=3)
    timeout = _sent_timeout(rest_client)
    assert timeout.total == 3


def test_explicit_tuple_timeout_is_preserved(rest_client, default_timeouts):
    rest_client.request("GET", "https://k8s.invalid:6443/api", _request_timeout=(1, 2))
    timeout = _sent_timeout(rest_client)
    assert (timeout.connect_timeout, timeout.read_timeout) == (1, 2)


def test_explicit_positional_timeout_is_preserved(rest_client, default_timeouts):
    # request(method, url, query_params, headers, body, post_params,
    #         _preload_content, _request_timeout)
    rest_client.request(
        "GET", "https://k8s.invalid:6443/api", None, None, None, None, True, 7
    )
    assert _sent_timeout(rest_client).total == 7


def test_opt_out_with_none_tuple(rest_client, default_timeouts):
    rest_client.GET("https://k8s.invalid:6443/api", _request_timeout=(None, None))
    timeout = _sent_timeout(rest_client)
    assert timeout.connect_timeout is None
    assert timeout.read_timeout is None


def test_streaming_call_gets_no_short_read_timeout(rest_client, default_timeouts):
    # watch / logs suivis : _preload_content=False → connexion bornée seulement.
    rest_client.GET("https://k8s.invalid:6443/api", _preload_content=False)
    timeout = _sent_timeout(rest_client)
    assert timeout.connect_timeout == 5
    assert timeout.read_timeout is None


def test_zero_disables_timeouts(rest_client):
    try:
        k8s_timeouts.install_default_request_timeout(0, 0)
        rest_client.GET("https://k8s.invalid:6443/api")
        # Aucun délai : comportement historique du client.
        assert _sent_timeout(rest_client) is None
    finally:
        k8s_timeouts.install_default_request_timeout(
            settings.K8S_REQUEST_TIMEOUT_CONNECT, settings.K8S_REQUEST_TIMEOUT_READ
        )


def test_install_is_idempotent(default_timeouts):
    original = k8s_timeouts._unwrap(rest.RESTClientObject.request)
    k8s_timeouts.install_default_request_timeout(1, 2)
    k8s_timeouts.install_default_request_timeout(3, 4)
    wrapper = rest.RESTClientObject.request
    assert wrapper.__wrapped__ is original


def test_resolve_request_timeout_rules():
    resolve = k8s_timeouts.resolve_request_timeout
    assert resolve(None, True, 5, 30) == (5, 30)
    assert resolve(None, False, 5, 30) == (5, None)
    assert resolve(9, True, 5, 30) == 9
    assert resolve((None, None), True, 5, 30) == (None, None)
    assert resolve(None, True, 0, 0) is None
    assert resolve(None, False, 0, 30) is None


def test_websocket_stream_path_is_untouched(default_timeouts):
    """kubernetes.stream.stream remplace ApiClient.request : REST jamais appelé."""
    from kubernetes.stream import stream as k8s_stream

    captured: Dict[str, Any] = {}

    def fake_websocket_call(configuration, *args, **kwargs):
        captured.update(kwargs)
        return "ws-result"

    configuration = k8s_client.Configuration()
    configuration.host = "https://k8s.invalid:6443"
    api_client = k8s_client.ApiClient(configuration)
    api_client.rest_client.pool_manager = MagicMock()
    core = k8s_client.CoreV1Api(api_client)

    # Même mécanique que kubernetes.stream.stream, avec un faux websocket_call.
    ws_request = functools.partial(k8s_stream.func, fake_websocket_call, None)
    ws_request(
        core.connect_get_namespaced_pod_exec,
        "pod",
        "ns",
        command=["ls"],
        stdout=True,
        _preload_content=False,
    )

    api_client.rest_client.pool_manager.request.assert_not_called()
    # Aucun délai injecté sur le chemin websocket (None = défaut du ws_client).
    assert captured.get("_request_timeout") is None
    assert captured.get("_preload_content") is False


# ============================================================
# Pool de threads AnyIO
# ============================================================


async def test_configure_threadpool_applies_setting(monkeypatch):
    from backend.config import Settings

    monkeypatch.setattr(Settings, "API_THREADPOOL_SIZE", 7)
    assert settings.configure_threadpool() == 7
    assert anyio.to_thread.current_default_thread_limiter().total_tokens == 7


async def test_threadpool_startup_hook_is_registered():
    from backend.main import app, configure_threadpool

    assert configure_threadpool in app.router.on_startup


# ============================================================
# Services K8s synchrones
# ============================================================


def test_blocking_services_are_plain_functions():
    from backend import k8s_utils
    from backend.deployment_service import deployment_service

    for func in (
        deployment_service.create_deployment,
        deployment_service.pause_application,
        deployment_service.resume_application,
        deployment_service._create_wordpress_stack,
        deployment_service._create_mysql_pma_stack,
        deployment_service._create_lamp_stack,
        k8s_utils.ensure_namespace_exists,
    ):
        assert not inspect.iscoroutinefunction(func), func.__name__


def test_ensure_namespace_exists_tolerates_concurrent_creation(mock_k8s):
    from backend.k8s_utils import ensure_namespace_exists

    mock_k8s["core"].create_namespace.side_effect = k8s_client.exceptions.ApiException(
        status=409
    )
    assert ensure_namespace_exists("labondemand-user-42") is True


def test_ensure_namespace_exists_reports_failure(mock_k8s):
    from backend.k8s_utils import ensure_namespace_exists

    mock_k8s["core"].create_namespace.side_effect = k8s_client.exceptions.ApiException(
        status=403
    )
    assert ensure_namespace_exists("labondemand-user-42") is False


# ============================================================
# Garde statique : endpoints et dépendances async
# ============================================================

# Seuls ces endpoints peuvent rester `async def` : ils attendent réellement
# quelque chose (WebSocket, orchestration concurrente, tâche de fond) et
# déportent chaque partie bloquante dans un thread. Tout autre endpoint doit
# être `def` pour que FastAPI l'exécute dans le pool de threads.
ASYNC_ENDPOINT_ALLOWLIST = {
    "backend.main.read_root",
    "backend.main.get_status",
    "backend.main.health_check",
    "backend.main.test_auth",
    "backend.routers.k8s_terminal.ws_pod_terminal",
    "backend.routers.classrooms.deploy_assignment_to_class",
    "backend.routers.classrooms.test_now",
    "backend.routers.classrooms.run_tests_all",
    "backend.routers.student.run_tests",
}


def _endpoint_id(func) -> str:
    func = inspect.unwrap(func)
    return f"{func.__module__}.{func.__qualname__}"


def _iter_dependency_calls(dependant):
    for dep in dependant.dependencies:
        if dep.call is not None:
            yield dep.call
        yield from _iter_dependency_calls(dep)


def test_async_endpoints_are_allowlisted():
    from backend.main import app

    offenders = sorted(
        _endpoint_id(route.endpoint)
        for route in app.routes
        if getattr(route, "endpoint", None) is not None
        and _endpoint_id(route.endpoint).startswith("backend.")
        and inspect.iscoroutinefunction(inspect.unwrap(route.endpoint))
        and _endpoint_id(route.endpoint) not in ASYNC_ENDPOINT_ALLOWLIST
    )
    assert offenders == [], f"endpoints async hors liste blanche : {offenders}"


def test_request_dependencies_are_sync():
    from backend.main import app

    offenders = set()
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        for call in _iter_dependency_calls(dependant):
            module = getattr(call, "__module__", "") or ""
            if module.startswith("backend.") and inspect.iscoroutinefunction(call):
                offenders.add(f"{module}.{getattr(call, '__qualname__', call)}")
    assert offenders == set(), f"dépendances async (bloquantes ?) : {sorted(offenders)}"
