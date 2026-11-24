"""Endpoint quotas utilisateur."""
from typing import Any, Dict

from fastapi import APIRouter, Depends
from kubernetes import client

from ..deployment_service import deployment_service
from ..models import User
from ..security import get_current_user
from ._helpers import K8S_TRANSPORT_ERRORS, raise_k8s_http

quotas_router = APIRouter(prefix="/api/v1/quotas", tags=["quotas"])


@quotas_router.get("/me")
def get_my_quotas(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    try:
        return deployment_service.get_user_quota_summary(current_user)
    except (client.exceptions.ApiException, *K8S_TRANSPORT_ERRORS) as e:
        raise_k8s_http(e)
