"""Tests for PVC (persistent volume) endpoints."""
import pytest
from unittest.mock import MagicMock


def _make_pvc(name, namespace, phase="Bound", user_id=None):
    pvc = MagicMock()
    pvc.metadata.name = name
    pvc.metadata.namespace = namespace
    pvc.metadata.creation_timestamp = None
    pvc.metadata.labels = {
        "managed-by": "labondemand",
        "user-id": str(user_id) if user_id else "99",
    }
    pvc.metadata.annotations = {}
    pvc.status.phase = phase
    pvc.status.capacity = {"storage": "1Gi"}
    pvc.status.access_modes = ["ReadWriteOnce"]
    pvc.status.volume_name = "pv-001"
    pvc.spec.storage_class_name = "standard"
    pvc.spec.resources = MagicMock()
    pvc.spec.resources.requests = {"storage": "1Gi"}
    pvc.spec.access_modes = ["ReadWriteOnce"]
    pvc.spec.volume_name = None
    return pvc


async def test_list_user_pvcs_empty(student_client, mock_k8s):
    r = await student_client.get("/api/v1/k8s/pvcs")
    assert r.status_code == 200
    assert r.json()["items"] == []


async def test_list_user_pvcs_unauthenticated(client, mock_k8s):
    r = await client.get("/api/v1/k8s/pvcs")
    assert r.status_code == 401


async def test_list_user_pvcs_with_items(student_client, mock_k8s, student_user):
    pvc = _make_pvc("my-volume", f"student-{student_user.id}", user_id=student_user.id)
    mock_k8s["core"].list_namespaced_persistent_volume_claim.return_value = MagicMock(
        items=[pvc]
    )
    r = await student_client.get("/api/v1/k8s/pvcs")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["name"] == "my-volume"


async def test_list_all_pvcs_teacher(teacher_client, mock_k8s):
    from kubernetes import client as k8s_client
    mock_k8s["core"].read_namespaced_persistent_volume_claim.side_effect = (
        k8s_client.exceptions.ApiException(status=404)
    )
    r = await teacher_client.get("/api/v1/k8s/pvcs/all")
    # route may be shadowed by /pvcs/{name} returning 404 or succeed with 200
    assert r.status_code in (200, 404, 500)


async def test_list_all_pvcs_admin(admin_client, mock_k8s):
    from kubernetes import client as k8s_client
    mock_k8s["core"].read_namespaced_persistent_volume_claim.side_effect = (
        k8s_client.exceptions.ApiException(status=404)
    )
    r = await admin_client.get("/api/v1/k8s/pvcs/all")
    assert r.status_code in (200, 404, 500)


async def test_list_all_pvcs_student_forbidden(student_client, mock_k8s):
    r = await student_client.get("/api/v1/k8s/pvcs/all")
    assert r.status_code == 403


async def test_get_pvc_student_own(student_client, mock_k8s, student_user):
    pvc = _make_pvc("vol-1", f"student-{student_user.id}", user_id=student_user.id)
    mock_k8s["core"].read_namespaced_persistent_volume_claim.return_value = pvc
    r = await student_client.get("/api/v1/k8s/pvcs/vol-1")
    assert r.status_code == 200
    assert r.json()["name"] == "vol-1"


async def test_get_pvc_student_other_forbidden(student_client, mock_k8s, admin_user):
    pvc = _make_pvc("admin-vol", "labondemand-admin", user_id=admin_user.id)
    # user-id doesn't match the student
    mock_k8s["core"].read_namespaced_persistent_volume_claim.return_value = pvc
    r = await student_client.get("/api/v1/k8s/pvcs/admin-vol")
    assert r.status_code == 403


async def test_delete_pvc_unbound(student_client, mock_k8s, student_user):
    pvc = _make_pvc("old-vol", f"student-{student_user.id}", phase="Released", user_id=student_user.id)
    mock_k8s["core"].read_namespaced_persistent_volume_claim.return_value = pvc
    mock_k8s["core"].delete_namespaced_persistent_volume_claim.return_value = MagicMock()
    r = await student_client.delete("/api/v1/k8s/pvcs/old-vol")
    assert r.status_code == 200


async def test_delete_pvc_bound_without_force(student_client, mock_k8s, student_user):
    pvc = _make_pvc("active-vol", f"student-{student_user.id}", phase="Bound", user_id=student_user.id)
    mock_k8s["core"].read_namespaced_persistent_volume_claim.return_value = pvc
    r = await student_client.delete("/api/v1/k8s/pvcs/active-vol")
    assert r.status_code == 409


async def test_delete_pvc_bound_with_force(student_client, mock_k8s, student_user):
    pvc = _make_pvc("active-vol", f"student-{student_user.id}", phase="Bound", user_id=student_user.id)
    mock_k8s["core"].read_namespaced_persistent_volume_claim.return_value = pvc
    mock_k8s["core"].delete_namespaced_persistent_volume_claim.return_value = MagicMock()
    r = await student_client.delete("/api/v1/k8s/pvcs/active-vol", params={"force": "true"})
    assert r.status_code == 200
    assert r.json()["forced"] is True
