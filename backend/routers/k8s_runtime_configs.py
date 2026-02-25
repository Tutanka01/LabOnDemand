"""Endpoints CRUD RuntimeConfig."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..security import get_current_user, is_admin
from ..models import User, RuntimeConfig
from ..database import get_db
from .. import schemas

router = APIRouter(prefix="/api/v1/k8s", tags=["kubernetes"])


@router.get("/runtime-configs", response_model=List[schemas.RuntimeConfigResponse])
async def list_runtime_configs(
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
    db: Session = Depends(get_db)
):
    rows = db.query(RuntimeConfig).order_by(RuntimeConfig.id.desc()).all()
    return [schemas.RuntimeConfigResponse.model_validate(r) for r in rows]


@router.post("/runtime-configs", response_model=schemas.RuntimeConfigResponse)
async def create_runtime_config(
    payload: schemas.RuntimeConfigCreate,
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
    db: Session = Depends(get_db)
):
    if db.query(RuntimeConfig).filter(RuntimeConfig.key == payload.key).first():
        raise HTTPException(status_code=400, detail="Cette clé existe déjà")
    rc = RuntimeConfig(**payload.model_dump())
    db.add(rc)
    db.commit()
    db.refresh(rc)
    return schemas.RuntimeConfigResponse.model_validate(rc)


@router.put("/runtime-configs/{rc_id}", response_model=schemas.RuntimeConfigResponse)
async def update_runtime_config(
    rc_id: int,
    payload: schemas.RuntimeConfigUpdate,
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
    db: Session = Depends(get_db)
):
    rc = db.query(RuntimeConfig).filter(RuntimeConfig.id == rc_id).first()
    if not rc:
        raise HTTPException(status_code=404, detail="Runtime config non trouvée")
    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(rc, k, v)
    db.commit()
    db.refresh(rc)
    return schemas.RuntimeConfigResponse.model_validate(rc)


@router.delete("/runtime-configs/{rc_id}")
async def delete_runtime_config(
    rc_id: int,
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
    db: Session = Depends(get_db)
):
    rc = db.query(RuntimeConfig).filter(RuntimeConfig.id == rc_id).first()
    if not rc:
        raise HTTPException(status_code=404, detail="Runtime config non trouvée")
    db.delete(rc)
    db.commit()
    return {"message": "Runtime config supprimée"}
