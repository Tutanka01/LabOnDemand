"""Endpoints de stockage (PVCs) Kubernetes."""
from fastapi import APIRouter, Depends, HTTPException, Query
from kubernetes import client

from ..security import get_current_user, is_teacher_or_admin
from ..models import User, UserRole
from ..k8s_utils import validate_k8s_name, build_user_namespace
from .. import schemas
from ._helpers import raise_k8s_http, audit_logger

router = APIRouter(prefix="/api/v1/k8s", tags=["kubernetes"])


def _map_pvc(pvc: client.V1PersistentVolumeClaim) -> schemas.PVCInfo:
    status = getattr(pvc, "status", None) or client.V1PersistentVolumeClaimStatus()
    spec = getattr(pvc, "spec", None) or client.V1PersistentVolumeClaimSpec()
    labels = pvc.metadata.labels or {}
    annotations = pvc.metadata.annotations or {}
    access_modes = list(getattr(status, "access_modes", None) or getattr(spec, "access_modes", []) or [])
    storage = None
    if getattr(status, "capacity", None):
        storage = status.capacity.get("storage")
    if not storage and getattr(spec, "resources", None) and getattr(spec.resources, "requests", None):
        storage = spec.resources.requests.get("storage")

    return schemas.PVCInfo(
        name=pvc.metadata.name,
        namespace=pvc.metadata.namespace,
        phase=getattr(status, "phase", None),
        storage=storage,
        access_modes=access_modes,
        storage_class=getattr(spec, "storage_class_name", None),
        volume_name=getattr(status, "volume_name", None) or getattr(spec, "volume_name", None),
        managed_by=labels.get("managed-by"),
        app_type=labels.get("app-type"),
        last_bound_app=labels.get("labondemand/last-bound-app"),
        created_at=pvc.metadata.creation_timestamp.isoformat() if pvc.metadata.creation_timestamp else None,
        bound=((getattr(status, "phase", "") or "").lower() == "bound"),
        labels=labels,
        annotations=annotations,
    )


def _ensure_pvc_access(pvc: client.V1PersistentVolumeClaim, user: User) -> None:
    labels = pvc.metadata.labels or {}
    if user.role == UserRole.student:
        if labels.get("managed-by") != "labondemand" or labels.get("user-id") != str(user.id):
            raise HTTPException(status_code=403, detail="Accès refusé à ce volume")


@router.get("/pvcs", response_model=schemas.PVCListResponse)
async def list_user_pvcs(current_user: User = Depends(get_current_user)):
    """Lister les volumes persistants du namespace utilisateur."""
    namespace = build_user_namespace(current_user)
    core_v1 = client.CoreV1Api()
    label_selector = f"managed-by=labondemand,user-id={current_user.id}"

    try:
        listing = core_v1.list_namespaced_persistent_volume_claim(namespace, label_selector=label_selector)
    except client.exceptions.ApiException as e:
        if e.status == 404:
            return schemas.PVCListResponse(items=[])
        raise_k8s_http(e)
    except Exception as e:
        raise_k8s_http(e)

    pvcs = [_map_pvc(pvc) for pvc in getattr(listing, "items", []) or []]
    return schemas.PVCListResponse(items=pvcs)


@router.get("/pvcs/{name}", response_model=schemas.PVCInfo)
async def get_user_pvc(
    name: str,
    current_user: User = Depends(get_current_user),
):
    """Obtenir les détails d'un PVC utilisateur."""
    namespace = build_user_namespace(current_user)
    name = validate_k8s_name(name)
    core_v1 = client.CoreV1Api()
    try:
        pvc = core_v1.read_namespaced_persistent_volume_claim(name, namespace)
    except Exception as e:
        raise_k8s_http(e)

    _ensure_pvc_access(pvc, current_user)
    return _map_pvc(pvc)


@router.delete("/pvcs/{name}")
async def delete_user_pvc(
    name: str,
    force: bool = Query(False, description="Supprimer même si le volume est encore Bound"),
    current_user: User = Depends(get_current_user),
):
    """Supprimer un PVC utilisateur (optionnellement de force)."""
    namespace = build_user_namespace(current_user)
    name = validate_k8s_name(name)
    core_v1 = client.CoreV1Api()

    try:
        pvc = core_v1.read_namespaced_persistent_volume_claim(name, namespace)
    except Exception as e:
        raise_k8s_http(e)

    _ensure_pvc_access(pvc, current_user)

    phase = (getattr(getattr(pvc, "status", None), "phase", "") or "").lower()
    if phase == "bound" and not force:
        raise HTTPException(status_code=409, detail="Volume encore attaché. Ajoutez force=true pour le supprimer quand même.")

    try:
        core_v1.delete_namespaced_persistent_volume_claim(name, namespace)
    except Exception as e:
        raise_k8s_http(e)

    audit_logger.info(
        "pvc_deleted",
        extra={
            "extra_fields": {
                "pvc_name": name,
                "namespace": namespace,
                "user_id": getattr(current_user, "id", None),
                "forced": force,
            }
        },
    )

    return {"message": f"Volume {name} supprimé", "forced": force}


@router.get("/pvcs/all", response_model=schemas.PVCListResponse)
async def list_all_labondemand_pvcs(
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_teacher_or_admin),
):
    """Lister tous les PVC LabOnDemand (enseignant/admin)."""
    core_v1 = client.CoreV1Api()
    label_selector = "managed-by=labondemand"
    try:
        listing = core_v1.list_persistent_volume_claim_for_all_namespaces(label_selector=label_selector)
    except client.exceptions.ApiException as e:
        raise_k8s_http(e)
    except Exception as e:
        raise_k8s_http(e)

    pvcs = [_map_pvc(pvc) for pvc in getattr(listing, "items", []) or []]
    return schemas.PVCListResponse(items=pvcs)
