"""
Seeding des données initiales pour LabOnDemand.
Fonctions idempotentes appelées au démarrage.
"""
import logging
import secrets
from typing import Optional
from sqlalchemy.orm import Session

from .config import settings
from .k8s_utils import parse_cpu_to_millicores, parse_memory_to_mi
from .models import User, UserRole, Template, RuntimeConfig
from .security import get_password_hash
from .templates import ECLIPSE_IMAGE, VSCODE_IMAGE, get_deployment_templates

logger = logging.getLogger("labondemand.seed")


def seed_admin(db: Session) -> None:
    """Crée le compte administrateur par défaut s'il n'existe pas encore."""
    admin = db.query(User).filter(User.role == UserRole.admin).first()
    if admin:
        return

    admin_password = settings.ADMIN_DEFAULT_PASSWORD
    if not admin_password:
        admin_password = secrets.token_urlsafe(24)
        logger.warning(
            "ADMIN_DEFAULT_PASSWORD not set; generated temporary admin password",
            extra={
                "extra_fields": {
                    "action": "bootstrap_admin",
                    "password_generated": True,
                    "temporary_password": admin_password,
                }
            },
        )
    else:
        logger.info(
            "Using configured ADMIN_DEFAULT_PASSWORD for admin bootstrap",
            extra={"extra_fields": {"action": "bootstrap_admin", "password_generated": False}},
        )

    db.add(User(
        username="admin",
        email="admin@labondemand.local",
        full_name="Administrateur",
        hashed_password=get_password_hash(admin_password),
        role=UserRole.admin,
        is_active=True,
        auth_provider="local",
        external_id=None,
    ))
    db.commit()
    logger.info(
        "Default admin created",
        extra={
            "extra_fields": {
                "action": "bootstrap_admin",
                "admin_created": True,
                "password_generated": not bool(settings.ADMIN_DEFAULT_PASSWORD),
                "temporary_password": admin_password if not settings.ADMIN_DEFAULT_PASSWORD else None,
            }
        },
    )


def _ensure_template(db: Session, key: str, defaults: dict) -> None:
    """Insère un template s'il n'existe pas déjà."""
    if db.query(Template).filter(Template.key == key).first():
        return
    d = defaults.get(key, {})
    db.add(Template(
        key=key,
        name=d.get("name", key),
        description=d.get("description"),
        icon=d.get("icon"),
        deployment_type=d.get("deployment_type", "custom"),
        default_image=d.get("default_image"),
        default_port=d.get("default_port"),
        default_service_type=d.get("default_service_type", "NodePort"),
        tags=",".join(d.get("tags", []) or []),
        active=True,
    ))
    db.commit()


def seed_templates(db: Session) -> None:
    """Peuple la table templates avec les templates par défaut s'ils manquent."""
    all_templates = get_deployment_templates().get("templates", [])
    defaults = {t["id"]: t for t in all_templates}

    if db.query(Template).count() == 0:
        for t in all_templates:
            db.add(Template(
                key=t.get("id"),
                name=t.get("name"),
                description=t.get("description"),
                icon=t.get("icon"),
                deployment_type=t.get("deployment_type", "custom"),
                default_image=t.get("default_image"),
                default_port=t.get("default_port"),
                default_service_type=t.get("default_service_type", "NodePort"),
                active=True,
            ))
        db.commit()
        return

    # Assurer la présence des templates essentiels
    for key in ("wordpress", "mysql", "lamp", "netbeans", "eclipse"):
        _ensure_template(db, key, defaults)


# Configurations runtime par défaut, indexées par clé.
_DEFAULT_RUNTIME_CONFIGS: list[dict] = [
    {
        "key": "vscode",
        "default_image": VSCODE_IMAGE,
        "target_port": 8080,
        "default_service_type": "NodePort",
        "allowed_for_students": True,
        "min_cpu_request": "150m",
        "min_memory_request": "256Mi",
        "min_cpu_limit": "500m",
        "min_memory_limit": "512Mi",
    },
    {
        "key": "jupyter",
        "default_image": "tutanka01/k8s:jupyter",
        "target_port": 8888,
        "default_service_type": "NodePort",
        "allowed_for_students": True,
        "min_cpu_request": "250m",
        "min_memory_request": "512Mi",
        "min_cpu_limit": "500m",
        "min_memory_limit": "1Gi",
    },
    {
        "key": "wordpress",
        "default_image": "bitnamilegacy/wordpress:6.8.2-debian-12-r5",
        "target_port": 8080,
        "default_service_type": "NodePort",
        "allowed_for_students": True,
    },
    {
        "key": "mysql",
        "default_image": "phpmyadmin:latest",
        "target_port": 8080,
        "default_service_type": "NodePort",
        "allowed_for_students": True,
    },
    {
        "key": "lamp",
        "default_image": "php:8.2-apache",
        "target_port": 8080,
        "default_service_type": "NodePort",
        "allowed_for_students": True,
    },
    {
        "key": "netbeans",
        "default_image": "tutanka01/labondemand:netbeansjava",
        "target_port": 6901,
        "default_service_type": "NodePort",
        "allowed_for_students": True,
        "min_cpu_request": "500m",
        "min_memory_request": "1Gi",
        "min_cpu_limit": "1000m",
        "min_memory_limit": "2Gi",
    },
    {
        "key": "eclipse",
        "default_image": ECLIPSE_IMAGE,
        "target_port": 6901,
        "default_service_type": "NodePort",
        "allowed_for_students": True,
        "min_cpu_request": "500m",
        "min_memory_request": "1Gi",
        "min_cpu_limit": "1000m",
        # 3 Gi mesurés nécessaires (Eclipse + Xvnc/XFCE + Firefox + Maven/Gradle) :
        # à 2 Gi les sessions actives finissaient en OOMKilled (137).
        "min_memory_limit": "3Gi",
    },
]


def _is_below_default(existing: Optional[str], default: Optional[str], is_memory: bool) -> bool:
    """Vrai si ``existing`` est absent ou inférieur à ``default`` (jamais si supérieur).

    Sert aux planchers de ressources : le défaut de plateforme ne doit jamais être
    abaissé (un lab qui démarre en OOMKilled est pire qu'un pod au-dessus du plafond),
    mais une valeur administrateur plus haute est conservée.
    """
    if not default:
        return False
    if not existing:
        return True
    try:
        to_units = parse_memory_to_mi if is_memory else parse_cpu_to_millicores
        return to_units(str(existing)) < to_units(str(default))
    except (TypeError, ValueError):
        return False


def _ensure_runtime_config(db: Session, cfg: dict) -> None:
    """Insère ou met à jour une runtime config."""
    key = cfg["key"]
    existing = db.query(RuntimeConfig).filter(RuntimeConfig.key == key).first()
    if not existing:
        db.add(RuntimeConfig(active=True, **cfg))
        db.commit()
        return

    changed = False
    if existing.allowed_for_students is None:
        existing.allowed_for_students = True
        changed = True

    legacy_images = {
        "vscode": {"tutanka01/k8s:vscode", "codercom/code-server:latest"},
        # Ancien tag mutable remplacé par un tag daté immuable (correctif mémoire
        # Eclipse : heap piloté par la limite conteneur).
        "eclipse": {"tutanka01/labondemand:eclipsejava"},
    }
    if existing.default_image in legacy_images.get(key, set()):
        existing.default_image = cfg["default_image"]
        changed = True

    # Planchers CPU/RAM : uniquement vers le haut, pour rattraper les configs DB
    # créées avant un relèvement du défaut de plateforme.
    for field in (
        "min_cpu_request",
        "min_cpu_limit",
        "min_memory_request",
        "min_memory_limit",
    ):
        default_value = cfg.get(field)
        if _is_below_default(
            getattr(existing, field), default_value, field.startswith("min_memory")
        ):
            logger.info(
                "runtime_config_floor_raised",
                extra={
                    "extra_fields": {
                        "key": key,
                        "field": field,
                        "previous": getattr(existing, field),
                        "new": default_value,
                    }
                },
            )
            setattr(existing, field, default_value)
            changed = True

    if changed:
        db.commit()


def seed_runtime_configs(db: Session) -> None:
    """Peuple la table runtime_configs avec les configurations par défaut."""
    if db.query(RuntimeConfig).count() == 0:
        for cfg in _DEFAULT_RUNTIME_CONFIGS:
            db.add(RuntimeConfig(active=True, **cfg))
        db.commit()
        return

    # Assurer la présence de chaque config essentielle
    for cfg in _DEFAULT_RUNTIME_CONFIGS:
        _ensure_runtime_config(db, cfg)
