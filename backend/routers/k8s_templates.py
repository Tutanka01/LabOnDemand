"""Endpoints templates et resource-presets."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..security import get_current_user, is_admin
from ..models import User, UserRole, Template, RuntimeConfig
from ..database import get_db
from ..templates import get_deployment_templates, get_resource_presets_for_role
from .. import schemas

router = APIRouter(prefix="/api/v1/k8s", tags=["kubernetes"])


@router.get("/templates")
async def get_deployment_templates_endpoint(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupérer les templates actifs; pour les étudiants, filtrer via RuntimeConfig.allowed_for_students."""
    try:
        templates = db.query(Template).filter(Template.active == True).all()
        runtime_configs = db.query(RuntimeConfig).filter(RuntimeConfig.active == True).all()
    except Exception:
        templates = []
        runtime_configs = []

    allowed_set = set()
    if runtime_configs:
        for rc in runtime_configs:
            if rc.allowed_for_students:
                allowed_set.add(rc.key)
    else:
        allowed_set = {"jupyter", "vscode", "wordpress", "mysql", "netbeans"}

    def map_template(t: Template):
        return {
            "id": t.key,
            "name": t.name,
            "description": t.description,
            "icon": t.icon,
            "default_image": t.default_image,
            "default_port": t.default_port,
            "deployment_type": t.deployment_type,
            "default_service_type": t.default_service_type,
            "tags": [s for s in (t.tags or '').split(',') if s]
        }

    if templates:
        defaults = get_deployment_templates().get("templates", [])
        defaults_map = {d.get("id"): d for d in defaults}

        def enrich(tpl_dict):
            did = tpl_dict.get("id")
            d = defaults_map.get(did, {})
            tpl_dict.setdefault("icon", d.get("icon"))
            tpl_dict.setdefault("description", d.get("description"))
            tpl_dict.setdefault("default_service_type", d.get("default_service_type"))
            if not tpl_dict.get("tags") and d.get("tags"):
                tpl_dict["tags"] = d["tags"]
            return tpl_dict

        items = [enrich(map_template(t)) for t in templates]
        if current_user.role == UserRole.student:
            items = [tpl for tpl in items if (tpl.get("deployment_type") in allowed_set or tpl.get("id") in allowed_set)]
        return {"templates": items}

    defaults = get_deployment_templates()
    if current_user.role == UserRole.student:
        filtered = [tpl for tpl in defaults.get("templates", []) if tpl.get("deployment_type") in allowed_set or tpl.get("id") in allowed_set]
        return {"templates": filtered}
    return defaults


@router.post("/templates", response_model=schemas.TemplateResponse)
async def create_template(
    payload: schemas.TemplateCreate,
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
    db: Session = Depends(get_db)
):
    """Créer un template (admin)."""
    if db.query(Template).filter(Template.key == payload.key).first():
        raise HTTPException(status_code=400, detail="La clé du template existe déjà")
    tpl = Template(
        key=payload.key,
        name=payload.name,
        description=payload.description,
        icon=payload.icon,
        deployment_type=payload.deployment_type,
        default_image=payload.default_image,
        default_port=payload.default_port,
        default_service_type=payload.default_service_type,
        tags=','.join(payload.tags) if payload.tags else None,
        active=payload.active,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return _tpl_response(tpl)


@router.get("/templates/all", response_model=List[schemas.TemplateResponse])
async def list_all_templates(
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
    db: Session = Depends(get_db)
):
    """Lister tous les templates (admin)."""
    rows = db.query(Template).order_by(Template.id.desc()).all()
    return [_tpl_response(t) for t in rows]


@router.put("/templates/{template_id}", response_model=schemas.TemplateResponse)
async def update_template(
    template_id: int,
    payload: schemas.TemplateUpdate,
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
    db: Session = Depends(get_db)
):
    tpl = db.query(Template).filter(Template.id == template_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template non trouvé")
    updates = payload.model_dump(exclude_unset=True)
    if "tags" in updates:
        updates["tags"] = ','.join(updates["tags"]) if updates["tags"] else None
    for field, value in updates.items():
        setattr(tpl, field, value)
    db.commit()
    db.refresh(tpl)
    return _tpl_response(tpl)


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: int,
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
    db: Session = Depends(get_db)
):
    tpl = db.query(Template).filter(Template.id == template_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template non trouvé")
    db.delete(tpl)
    db.commit()
    return {"message": "Template supprimé"}


@router.get("/resource-presets")
async def get_resource_presets(current_user: User = Depends(get_current_user)):
    """Récupérer les presets de ressources selon le rôle."""
    return get_resource_presets_for_role(current_user.role)


def _tpl_response(tpl: Template) -> schemas.TemplateResponse:
    return schemas.TemplateResponse(
        id=tpl.id,
        key=tpl.key,
        name=tpl.name,
        description=tpl.description,
        icon=tpl.icon,
        deployment_type=tpl.deployment_type,
        default_image=tpl.default_image,
        default_port=tpl.default_port,
        default_service_type=tpl.default_service_type,
        active=tpl.active,
        tags=[s for s in (tpl.tags or '').split(',') if s],
        created_at=tpl.created_at,
        updated_at=tpl.updated_at,
    )
