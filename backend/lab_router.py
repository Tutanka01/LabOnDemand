import logging
from fastapi import APIRouter, Depends, HTTPException, Response, Request, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from .database import get_db
from .models import User, Lab, UserRole
from .schemas import LabCreate, LabResponse, LabUpdate
from .security import get_current_user, is_admin, is_teacher_or_admin

router = APIRouter(prefix="/api/v1/labs", tags=["labs"])
audit_logger = logging.getLogger("labondemand.audit")

# Créer un nouveau laboratoire
@router.post("/", response_model=LabResponse, status_code=status.HTTP_201_CREATED)
def create_lab(lab: LabCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Crée un nouveau laboratoire pour l'utilisateur actuel
    """
    # Créer un nouveau laboratoire
    # Validation de sécurité : empêcher les étudiants de déployer dans les namespaces système
    if current_user.role == UserRole.student:
        if lab.k8s_namespace and lab.k8s_namespace.startswith("kube-"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Vous ne pouvez pas déployer dans les namespaces système"
            )

    db_lab = Lab(
        name=lab.name,
        description=lab.description,
        lab_type=lab.lab_type,
        k8s_namespace=lab.k8s_namespace,
        deployment_name=lab.deployment_name,
        service_name=lab.service_name,
        owner_id=current_user.id
    )
    
    db.add(db_lab)
    db.commit()
    db.refresh(db_lab)

    audit_logger.info(
        "lab_created",
        extra={
            "extra_fields": {
                "lab_id": db_lab.id,
                "lab_name": db_lab.name,
                "user_id": current_user.id,
                "username": current_user.username,
                "role": current_user.role.value,
            }
        },
    )
    
    return db_lab

# Récupérer tous les laboratoires de l'utilisateur actuel
@router.get("/my-labs", response_model=List[LabResponse])
def get_my_labs(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Récupère tous les laboratoires de l'utilisateur actuellement connecté
    """
    labs = db.query(Lab).filter(Lab.owner_id == current_user.id).all()
    return labs

# Récupérer un laboratoire spécifique
@router.get("/{lab_id}", response_model=LabResponse)
def get_lab(lab_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Récupère les détails d'un laboratoire spécifique
    """
    lab = db.query(Lab).filter(Lab.id == lab_id).first()
    
    if lab is None:
        raise HTTPException(status_code=404, detail="Laboratoire non trouvé")
        
    # Vérifier que l'utilisateur est le propriétaire ou un admin/enseignant
    if lab.owner_id != current_user.id and current_user.role == UserRole.student:
        raise HTTPException(status_code=403, detail="Vous n'avez pas accès à ce laboratoire")
        
    return lab

# Mettre à jour un laboratoire
@router.put("/{lab_id}", response_model=LabResponse)
def update_lab(
    lab_id: int, 
    lab_update: LabUpdate, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    """
    Met à jour les informations d'un laboratoire
    """
    db_lab = db.query(Lab).filter(Lab.id == lab_id).first()
    
    if db_lab is None:
        raise HTTPException(status_code=404, detail="Laboratoire non trouvé")
        
    # Vérifier que l'utilisateur est le propriétaire ou un admin
    if db_lab.owner_id != current_user.id and current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Vous n'avez pas la permission de modifier ce laboratoire")
    
    # Mise à jour des champs fournis
    if lab_update.name is not None:
        db_lab.name = lab_update.name
    
    if lab_update.description is not None:
        db_lab.description = lab_update.description
        
    # Les autres champs peuvent être mis à jour selon les besoins
    
    db.commit()
    db.refresh(db_lab)
    
    return db_lab

# Supprimer un laboratoire
@router.delete("/{lab_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lab(lab_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Supprime un laboratoire
    """
    db_lab = db.query(Lab).filter(Lab.id == lab_id).first()
    
    if db_lab is None:
        raise HTTPException(status_code=404, detail="Laboratoire non trouvé")
        
    # Vérifier que l'utilisateur est le propriétaire ou un admin
    if db_lab.owner_id != current_user.id and current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Vous n'avez pas la permission de supprimer ce laboratoire")
    
    db.delete(db_lab)
    db.commit()

    audit_logger.info(
        "lab_deleted",
        extra={
            "extra_fields": {
                "lab_id": lab_id,
                "lab_name": db_lab.name,
                "user_id": current_user.id,
                "username": current_user.username,
                "role": current_user.role.value,
            }
        },
    )
    
    return None

# Lister tous les laboratoires (admin uniquement)
@router.get("/", response_model=List[LabResponse], dependencies=[Depends(is_admin)])
def get_all_labs(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    Récupère tous les laboratoires (admin uniquement)
    """
    labs = db.query(Lab).offset(skip).limit(limit).all()
    return labs

# Lister les laboratoires d'un utilisateur spécifique (admin ou enseignant)
@router.get("/user/{user_id}", response_model=List[LabResponse], dependencies=[Depends(is_teacher_or_admin)])
def get_user_labs(user_id: int, db: Session = Depends(get_db)):
    """
    Récupère tous les laboratoires d'un utilisateur spécifique (admin ou enseignant uniquement)
    """
    labs = db.query(Lab).filter(Lab.owner_id == user_id).all()
    return labs
