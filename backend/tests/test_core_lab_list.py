"""Lab list (access_url, bounded Kubernetes calls, 503) and /details endpoints."""

import datetime
from unittest.mock import MagicMock

from kubernetes import client as k8s_client

from backend.models import Deployment
from backend.services import access_urls
from backend.services.access_urls import build_endpoints, get_node_addresses


def _deployment(name, user_id, namespace, labels=None, created_at=None):
    dep = MagicMock()
    dep.metadata.name = name
    dep.metadata.namespace = namespace
    dep.metadata.labels = {
        "managed-by": "labondemand",
        "user-id": str(user_id),
        "app-type": "vscode",
        "app": name,
        **(labels or {}),
    }
    dep.metadata.annotations = {}
    dep.metadata.creation_timestamp = created_at
    dep.spec.replicas = 1
    dep.spec.template.spec.containers = [MagicMock(image="img:1")]
    dep.status.ready_replicas = 1
    dep.status.available_replicas = 1
    return dep


def _service(name, namespace, labels, selector, node_port, port_name=None, svc_type="NodePort"):
    port = MagicMock()
    port.name = port_name
    port.port = 8080
    port.target_port = 8080
    port.protocol = "TCP"
    port.node_port = node_port
    svc = MagicMock()
    svc.metadata.name = name
    svc.metadata.namespace = namespace
    svc.metadata.labels = labels
    svc.spec.type = svc_type
    svc.spec.cluster_ip = "10.0.0.1"
    svc.spec.ports = [port]
    svc.spec.selector = selector
    return svc


def _pod(name, namespace, labels, node_name, phase="Running"):
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.namespace = namespace
    pod.metadata.labels = labels
    pod.spec.node_name = node_name
    pod.status.phase = phase
    pod.status.pod_ip = "10.1.0.1"
    return pod


def _node(name, internal, external=None):
    node = MagicMock()
    node.metadata.name = name
    addresses = [MagicMock(type="InternalIP", address=internal)]
    if external:
        addresses.append(MagicMock(type="ExternalIP", address=external))
    node.status.addresses = addresses
    return node


# ---------------------------------------------------------------- access_urls


def test_node_addresses_are_cached(mock_k8s):
    mock_k8s["core"].list_node.return_value = MagicMock(
        items=[_node("n1", "192.168.0.1", "203.0.113.1"), _node("n2", "192.168.0.2")]
    )
    assert get_node_addresses() == {"n1": "203.0.113.1", "n2": "192.168.0.2"}
    assert get_node_addresses() == {"n1": "203.0.113.1", "n2": "192.168.0.2"}
    assert mock_k8s["core"].list_node.call_count == 1


def _fake_clock(monkeypatch) -> list:
    from types import SimpleNamespace

    from backend import ttl_cache

    now = [1000.0]
    monkeypatch.setattr(ttl_cache, "time", SimpleNamespace(monotonic=lambda: now[0]))
    return now


def test_node_listing_failure_backs_off_briefly_and_is_not_cached(mock_k8s, monkeypatch):
    now = _fake_clock(monkeypatch)
    core = mock_k8s["core"]
    core.list_node.side_effect = k8s_client.exceptions.ApiException(status=503)
    assert get_node_addresses() == {}
    assert get_node_addresses() == {}  # short back-off: not retried by every request
    assert core.list_node.call_count == 1

    core.list_node.side_effect = None
    core.list_node.return_value = MagicMock(items=[_node("n1", "10.0.0.7")])
    now[0] += access_urls.NODE_LIST_RETRY_SECONDS + 1  # well under the 60 s TTL
    assert get_node_addresses() == {"n1": "10.0.0.7"}
    now[0] += 30
    assert get_node_addresses() == {"n1": "10.0.0.7"}  # the success is cached
    assert core.list_node.call_count == 2


def test_missing_pod_node_refreshes_the_cached_view_once(mock_k8s, monkeypatch):
    now = _fake_clock(monkeypatch)
    core = mock_k8s["core"]
    core.list_node.return_value = MagicMock(items=[_node("n1", "10.0.0.1")])
    assert get_node_addresses(["n1"]) == {"n1": "10.0.0.1"}

    # n2 joined the cluster since the view was cached.
    core.list_node.return_value = MagicMock(
        items=[_node("n1", "10.0.0.1"), _node("n2", "10.0.0.2")]
    )
    assert get_node_addresses(["n2"])["n2"] == "10.0.0.2"
    assert core.list_node.call_count == 2
    # An unknown node does not trigger a refresh storm.
    get_node_addresses(["ghost"])
    get_node_addresses(["ghost"])
    assert core.list_node.call_count == 2
    now[0] += access_urls.NODE_FORCED_REFRESH_SECONDS + 1
    get_node_addresses(["ghost"])
    assert core.list_node.call_count == 3


async def test_list_hides_labs_being_deleted(student_client, mock_k8s, student_user, db):
    ns = f"labondemand-user-{student_user.id}"
    gone = _deployment("gone", student_user.id, ns)
    gone.metadata.deletion_timestamp = datetime.datetime.now(datetime.timezone.utc)
    mock_k8s["apps"].list_deployment_for_all_namespaces.return_value = MagicMock(
        items=[gone, _deployment("kept", student_user.id, ns)]
    )

    r = await student_client.get("/api/v1/k8s/deployments/labondemand")

    assert r.status_code == 200
    assert [lab["name"] for lab in r.json()["deployments"]] == ["kept"]
    assert [row.name for row in db.query(Deployment).filter_by(user_id=student_user.id)] == ["kept"]


def test_build_endpoints_uses_pod_node_then_ingress(monkeypatch):
    monkeypatch.setattr(access_urls.settings, "NODEPORT_USE_POD_NODE_IP", True)
    monkeypatch.setattr(access_urls.settings, "CLUSTER_EXTERNAL_IP", None)
    svc = _service("lab-service", "ns", {"app": "lab"}, {"app": "lab"}, 31000, "novnc")
    pods = [
        _pod("lab-old", "ns", {"app": "lab"}, "n1", phase="Pending"),
        _pod("lab-new", "ns", {"app": "lab"}, "n2"),
    ]
    rule_path = MagicMock(path="/")
    rule_path.backend.service.name = "lab-service"
    rule_path.backend.service.port.number = 8080
    ingress = MagicMock()
    ingress.metadata.name = "lab-ingress"
    ingress.metadata.annotations = {}
    ingress.spec.ingress_class_name = "traefik"
    ingress.spec.tls = [MagicMock(hosts=["lab.example.org"])]
    ingress.spec.rules = [MagicMock(host="lab.example.org", http=MagicMock(paths=[rule_path]))]

    endpoints = build_endpoints([svc], pods, [ingress], {"n1": "1.1.1.1", "n2": "2.2.2.2"})

    urls = [a["url"] for a in endpoints["access_urls"]]
    assert urls == ["http://2.2.2.2:31000", "https://lab.example.org/"]
    assert endpoints["access_urls"][0]["node_name"] == "n2"
    assert endpoints["access_urls"][0]["cluster_ip"] == "1.1.1.1"
    assert endpoints["novnc_endpoint"] == "http://2.2.2.2:31000"
    assert endpoints["services"][0]["ingresses"][0]["host"] == "lab.example.org"
    assert endpoints["ingresses"][0]["tls"] is True


def test_build_endpoints_falls_back_to_cluster_external_ip(monkeypatch):
    monkeypatch.setattr(access_urls.settings, "CLUSTER_EXTERNAL_IP", "198.51.100.7")
    svc = _service("lab-service", "ns", {"app": "lab"}, {"app": "lab"}, 30500)
    endpoints = build_endpoints([svc], [], [], {})
    assert endpoints["access_urls"][0]["url"] == "http://198.51.100.7:30500"
    assert endpoints["novnc_endpoint"] is None


# ---------------------------------------------------------------- list endpoint


async def test_list_returns_access_url_with_bounded_k8s_calls(
    student_client, mock_k8s, student_user, db
):
    ns = f"labondemand-user-{student_user.id}"
    names = [f"lab{i}" for i in range(5)]
    mock_k8s["apps"].list_deployment_for_all_namespaces.return_value = MagicMock(
        items=[_deployment(n, student_user.id, ns) for n in names]
    )
    mock_k8s["core"].list_service_for_all_namespaces.return_value = MagicMock(
        items=[
            _service(f"{n}-service", ns, {"app": n}, {"app": n}, 31000 + i)
            for i, n in enumerate(names)
        ]
    )
    mock_k8s["core"].list_pod_for_all_namespaces.return_value = MagicMock(
        items=[_pod(f"{n}-pod", ns, {"app": n}, "n1") for n in names]
    )
    mock_k8s["core"].list_node.return_value = MagicMock(items=[_node("n1", "10.9.9.9")])

    r = await student_client.get("/api/v1/k8s/deployments/labondemand")

    assert r.status_code == 200
    labs = {d["name"]: d for d in r.json()["deployments"]}
    assert labs["lab3"]["access_url"] == "http://10.9.9.9:31003"
    assert all("_key" not in d and "_k8s_created_at" not in d for d in labs.values())
    # One call per kind, whatever the number of labs; nothing per lab. The
    # deployment list is re-read once more because the 5 labs have no DB row
    # yet: rows are only inserted after confirming the labs under the lock.
    assert mock_k8s["apps"].list_deployment_for_all_namespaces.call_count == 2
    assert mock_k8s["core"].list_service_for_all_namespaces.call_count == 1
    assert mock_k8s["core"].list_pod_for_all_namespaces.call_count == 1
    assert mock_k8s["core"].list_node.call_count == 1
    mock_k8s["core"].list_namespaced_service.assert_not_called()
    mock_k8s["core"].read_node.assert_not_called()
    mock_k8s["networking"].list_ingress_for_all_namespaces.assert_not_called()


async def test_list_groups_stack_components_with_stack_service(
    student_client, mock_k8s, student_user
):
    ns = f"labondemand-user-{student_user.id}"
    stack = {"stack-name": "shop", "app-type": "mysql"}
    mock_k8s["apps"].list_deployment_for_all_namespaces.return_value = MagicMock(
        items=[
            _deployment("shop-mysql", student_user.id, ns, stack),
            _deployment("shop-phpmyadmin", student_user.id, ns, stack),
        ]
    )
    mock_k8s["core"].list_service_for_all_namespaces.return_value = MagicMock(
        items=[
            _service("shop-mysql-service", ns, {"app": "shop-mysql", **stack}, {"app": "shop-mysql"}, None, svc_type="ClusterIP"),
            _service("shop-phpmyadmin-service", ns, {"app": "shop-phpmyadmin", **stack}, {"app": "shop-phpmyadmin"}, 30777),
        ]
    )

    r = await student_client.get("/api/v1/k8s/deployments/labondemand")

    assert r.status_code == 200
    (lab,) = r.json()["deployments"]
    assert lab["name"] == "shop"
    assert len(lab["components"]) == 2
    assert lab["access_url"].endswith(":30777")


async def test_list_answers_503_when_kubernetes_is_unreachable(student_client, mock_k8s):
    mock_k8s["apps"].list_deployment_for_all_namespaces.side_effect = (
        k8s_client.exceptions.ApiException(status=503)
    )
    r = await student_client.get("/api/v1/k8s/deployments/labondemand")
    assert r.status_code == 503
    assert r.json()["detail"]


async def test_list_keeps_labs_when_access_url_lookup_fails(
    student_client, mock_k8s, student_user
):
    ns = f"labondemand-user-{student_user.id}"
    mock_k8s["apps"].list_deployment_for_all_namespaces.return_value = MagicMock(
        items=[_deployment("lab", student_user.id, ns)]
    )
    mock_k8s["core"].list_service_for_all_namespaces.side_effect = (
        k8s_client.exceptions.ApiException(status=403)
    )
    r = await student_client.get("/api/v1/k8s/deployments/labondemand")
    assert r.status_code == 200
    (lab,) = r.json()["deployments"]
    assert lab["name"] == "lab"
    assert lab["access_url"] is None


async def test_list_reconciles_missing_db_row_from_k8s_creation_date(
    student_client, mock_k8s, student_user, db
):
    from backend.tasks.cleanup import LAB_TTL_STUDENT_DAYS

    ns = f"labondemand-user-{student_user.id}"
    created = datetime.datetime(2026, 1, 10, 8, 0, tzinfo=datetime.timezone.utc)
    mock_k8s["apps"].list_deployment_for_all_namespaces.return_value = MagicMock(
        items=[_deployment("lab", student_user.id, ns, created_at=created)]
    )

    for _ in range(2):
        r = await student_client.get("/api/v1/k8s/deployments/labondemand")
        assert r.status_code == 200

    rows = db.query(Deployment).filter_by(user_id=student_user.id, name="lab").all()
    assert len(rows) == 1
    expires = rows[0].expires_at.replace(tzinfo=datetime.timezone.utc)
    assert expires == created + datetime.timedelta(days=LAB_TTL_STUDENT_DAYS)
    assert r.json()["deployments"][0]["expires_at"].startswith("2026-01-")


# ---------------------------------------------------------------- details


async def test_details_reuses_cached_node_addresses(student_client, mock_k8s, student_user):
    ns = f"labondemand-user-{student_user.id}"
    mock_k8s["apps"].read_namespaced_deployment.return_value = _deployment(
        "lab", student_user.id, ns
    )
    mock_k8s["core"].list_namespaced_service.return_value = MagicMock(
        items=[_service("lab-service", ns, {"app": "lab"}, {"app": "lab"}, 31111)]
    )
    mock_k8s["core"].list_namespaced_pod.return_value = MagicMock(
        items=[_pod("lab-pod", ns, {"app": "lab"}, "n1")]
    )
    mock_k8s["core"].list_node.return_value = MagicMock(items=[_node("n1", "10.2.2.2")])

    for _ in range(3):
        r = await student_client.get(f"/api/v1/k8s/deployments/{ns}/lab/details")
        assert r.status_code == 200

    body = r.json()
    assert body["access_urls"][0]["url"] == "http://10.2.2.2:31111"
    assert body["deployment"]["available_replicas"] == 1
    assert body["lifecycle"]["state"] == "running"
    assert body["pods"][0]["node_name"] == "n1"
    assert mock_k8s["core"].list_node.call_count == 1
    mock_k8s["core"].read_node.assert_not_called()
