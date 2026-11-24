"""Shared Kubernetes connection pool (config.install_shared_k8s_connection_pool)."""

from kubernetes import client

from backend.config import install_shared_k8s_connection_pool


def _configuration(host: str) -> client.Configuration:
    configuration = client.Configuration()
    configuration.host = host
    return configuration


def test_api_clients_with_same_configuration_share_one_pool():
    install_shared_k8s_connection_pool()
    first = client.CoreV1Api(client.ApiClient(_configuration("https://k8s.invalid:6443")))
    second = client.AppsV1Api(client.ApiClient(_configuration("https://k8s.invalid:6443")))

    # Separate ApiClient objects (stream() patches ApiClient.request per instance)...
    assert first.api_client is not second.api_client
    # ...but a single urllib3 pool, so connections are kept alive between calls.
    assert first.api_client.rest_client.pool_manager is second.api_client.rest_client.pool_manager


def test_different_clusters_do_not_share_a_pool():
    install_shared_k8s_connection_pool()
    one = client.ApiClient(_configuration("https://one.invalid:6443"))
    other = client.ApiClient(_configuration("https://other.invalid:6443"))

    assert one.rest_client.pool_manager is not other.rest_client.pool_manager


def test_install_is_idempotent():
    install_shared_k8s_connection_pool()
    wrapped = client.rest.RESTClientObject.__init__
    install_shared_k8s_connection_pool()

    assert client.rest.RESTClientObject.__init__ is wrapped
