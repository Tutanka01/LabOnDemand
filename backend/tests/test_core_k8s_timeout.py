"""Global Kubernetes client timeouts (config.install_default_k8s_timeout)."""

from unittest.mock import MagicMock

import pytest
import urllib3
from kubernetes import client
from kubernetes.client import rest
from kubernetes.stream.stream import _websocket_request

from backend.config import install_default_k8s_timeout, settings


@pytest.fixture()
def rest_client():
    install_default_k8s_timeout(5, 30)
    rc = rest.RESTClientObject(client.Configuration(host="http://k8s.invalid"))
    rc.pool_manager = MagicMock()
    rc.pool_manager.request.return_value = MagicMock(status=200, reason="OK", data=b"{}")
    yield rc
    install_default_k8s_timeout(
        settings.K8S_CONNECT_TIMEOUT_SECONDS, settings.K8S_READ_TIMEOUT_SECONDS
    )


def _sent_timeout(rc) -> urllib3.Timeout:
    return rc.pool_manager.request.call_args.kwargs["timeout"]


def test_default_timeout_is_applied_to_rest_calls(rest_client):
    rest_client.GET("http://k8s.invalid/api/v1/namespaces")
    timeout = _sent_timeout(rest_client)
    assert isinstance(timeout, urllib3.Timeout)
    assert timeout.connect_timeout == 5
    assert timeout.read_timeout == 30

    rest_client.POST("http://k8s.invalid/api/v1/namespaces", body={})
    assert _sent_timeout(rest_client).read_timeout == 30


def test_explicit_request_timeout_overrides_default(rest_client):
    rest_client.GET("http://k8s.invalid/api/v1/pods", _request_timeout=(1, 2))
    timeout = _sent_timeout(rest_client)
    assert timeout.connect_timeout == 1
    assert timeout.read_timeout == 2


def test_install_is_idempotent(rest_client):
    install_default_k8s_timeout(3, 7)
    install_default_k8s_timeout(3, 7)
    rest_client.GET("http://k8s.invalid/api/v1/nodes")
    timeout = _sent_timeout(rest_client)
    assert (timeout.connect_timeout, timeout.read_timeout) == (3, 7)


def test_stream_exec_does_not_get_the_default_timeout(rest_client):
    """kubernetes.stream.stream() swaps ApiClient.request for a websocket call:
    it must neither reach the REST client nor receive our default timeout
    (websocket_call uses _request_timeout as the session duration)."""
    api_client = client.ApiClient(client.Configuration(host="http://k8s.invalid"))
    api_client.rest_client = rest_client
    core = client.CoreV1Api(api_client)
    received = {}

    def fake_websocket_call(configuration, method, url, **kwargs):
        received.update(kwargs)
        return "ws-session"

    out = _websocket_request(
        fake_websocket_call,
        None,
        core.connect_get_namespaced_pod_exec,
        "pod",
        "ns",
        command=["sh"],
        stdin=True,
        stdout=True,
        stderr=True,
        tty=True,
        _preload_content=False,
    )

    assert out == "ws-session"
    assert received["_request_timeout"] is None
    rest_client.pool_manager.request.assert_not_called()


def test_init_kubernetes_bounds_retries():
    settings.init_kubernetes()
    retries = client.Configuration.get_default_copy().retries
    assert isinstance(retries, urllib3.Retry)
    assert retries.total == settings.K8S_MAX_RETRIES
