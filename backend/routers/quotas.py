"""Endpoint quotas utilisateur."""
from fastapi import APIRouter, Depends, HTTPException

from ..security import get_current_user
from ..models import User
from ..deployment_service import deployment_service

quotas_router = APIRouter(prefix="/api/v1/quotas", tags=["quotas"])


@quotas_router.get("/me")
async def get_my_quotas(current_user: User = Depends(get_current_user)):
    try:
        return deployment_service.get_user_quota_summary(current_user)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur quotas: {e}")
