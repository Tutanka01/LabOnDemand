"""
Routeurs Kubernetes découpés par domaine fonctionnel.
Chaque sous-module expose un ``router`` APIRouter.
"""
from .k8s_deployments import router as deployments_router
from .k8s_storage import router as storage_router
from .k8s_terminal import router as terminal_router
from .k8s_templates import router as templates_router
from .k8s_runtime_configs import router as runtime_configs_router
from .k8s_monitoring import router as monitoring_router
from .quotas import quotas_router

__all__ = [
    "deployments_router",
    "storage_router",
    "terminal_router",
    "templates_router",
    "runtime_configs_router",
    "monitoring_router",
    "quotas_router",
]
