"""Resource specs of the multi-component stacks and quota planning helpers.

Each stack (WordPress, MySQL + phpMyAdmin, LAMP) is described as data: the
default resources of its components and the DeploymentService method that
builds it. ``create_deployment`` and the stack builders read these specs so the
numbers used for quota checks are exactly the ones sent to Kubernetes.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Tuple

from ..k8s_utils import (
    clamp_resources_for_role,
    parse_cpu_to_millicores,
    parse_memory_to_mi,
)


@dataclass(frozen=True)
class ComponentResources:
    """Default requests/limits of one stack component (one replica)."""

    cpu_request: str
    cpu_limit: str
    memory_request: str
    memory_limit: str

    def clamp(self, role: str) -> Dict[str, Any]:
        """Return the resources capped by the role ceilings (1 replica)."""
        return clamp_resources_for_role(
            role,
            self.cpu_request,
            self.cpu_limit,
            self.memory_request,
            self.memory_limit,
            1,
        )


DATABASE_RESOURCES = ComponentResources("250m", "500m", "256Mi", "512Mi")
WORDPRESS_RESOURCES = ComponentResources("250m", "1000m", "512Mi", "1Gi")
PHPMYADMIN_RESOURCES = ComponentResources("150m", "300m", "128Mi", "256Mi")
LAMP_WEB_RESOURCES = ComponentResources("250m", "500m", "256Mi", "512Mi")


@dataclass(frozen=True)
class StackSpec:
    """A multi-component application created as one LabOnDemand stack."""

    deployment_type: str
    builder: str  # name of the DeploymentService method creating the stack
    components: Tuple[ComponentResources, ...]


STACK_SPECS: Dict[str, StackSpec] = {
    "wordpress": StackSpec(
        "wordpress",
        "_create_wordpress_stack",
        (DATABASE_RESOURCES, WORDPRESS_RESOURCES),
    ),
    "mysql": StackSpec(
        "mysql",
        "_create_mysql_pma_stack",
        (DATABASE_RESOURCES, PHPMYADMIN_RESOURCES),
    ),
    "lamp": StackSpec(
        "lamp",
        "_create_lamp_stack",
        (LAMP_WEB_RESOURCES, DATABASE_RESOURCES, PHPMYADMIN_RESOURCES),
    ),
}


@dataclass(frozen=True)
class ResourcePlan:
    """What a creation (or a resume) adds to a namespace, for quota checks."""

    requests_cpu_m: int
    limits_cpu_m: int
    requests_mem_mi: int
    limits_mem_mi: int
    pods: int
    deployments: int


def plan_resources(
    components: Iterable[Dict[str, Any]], replicas: int, deployments: int
) -> ResourcePlan:
    """Sum clamped component resources (dicts as returned by the role clamp)."""
    components = list(components)

    def total(key: str, parse) -> int:
        return int(sum(parse(str(c[key])) * replicas for c in components))

    return ResourcePlan(
        requests_cpu_m=total("cpu_request", parse_cpu_to_millicores),
        limits_cpu_m=total("cpu_limit", parse_cpu_to_millicores),
        requests_mem_mi=total("memory_request", parse_memory_to_mi),
        limits_mem_mi=total("memory_limit", parse_memory_to_mi),
        pods=replicas * len(components),
        deployments=deployments,
    )
