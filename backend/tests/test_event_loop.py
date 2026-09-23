"""
Tests de non-blocage de la boucle asyncio et de bornage des appels K8s.

Sections :
  - délais par défaut du client REST Kubernetes (backend/k8s_timeouts.py).
"""

from __future__ import annotations

import functools
from typing import Any, Dict
from unittest.mock import MagicMock

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
