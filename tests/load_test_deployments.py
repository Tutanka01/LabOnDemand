"""Load test helper for creating multiple LabOnDemand deployments.

This script logs into the LabOnDemand backend and triggers the creation of
multiple Kubernetes deployments (e.g. VS Code) in quick succession.  It is
intended for local load-testing scenarios such as validating quota settings or
observing scheduler behaviour when many labs are started at once.

Usage
-----
    python tests/load_test_deployments.py \
        --base-url http://localhost:8000 \
        --username admin \
        --password admin123 \
        --count 60

By default the script starts 60 VS Code deployments using the "low" CPU/RAM
preset (0.25 vCPU, 256 Mi).  See ``python tests/load_test_deployments.py --help`` for the available
options (different template, resource presets, pacing delay, automatic cleanup,
etc.).

The script requires the ``requests`` package (already listed in ``requirements.txt``).
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

try:
    import requests
except ImportError as exc:  # pragma: no cover - convenience for CLI usage
    raise SystemExit(
        "The 'requests' package is required. Install it with 'pip install requests' or add it to requirements.txt"
    ) from exc

# ----- Presets borrowed from the frontend (frontend/script.js) -----------------
CPU_PRESETS: Dict[str, Tuple[str, str]] = {
    "very-low": ("100m", "200m"),
    "low": ("250m", "500m"),
    "medium": ("500m", "1000m"),
    "high": ("1000m", "2000m"),
    "very-high": ("2000m", "4000m"),
}

RAM_PRESETS: Dict[str, Tuple[str, str]] = {
    "very-low": ("128Mi", "256Mi"),
    "low": ("256Mi", "512Mi"),
    "medium": ("512Mi", "1Gi"),
    "high": ("1Gi", "2Gi"),
    "very-high": ("2Gi", "4Gi"),
}

@dataclass(frozen=True)
class TemplatePreset:
    image: str
    create_service: bool
    service_type: str
    service_port: int
    service_target_port: int
    replicas: int = 1


def _load_template_presets() -> Dict[str, TemplatePreset]:
    """Return the deployment templates supported by the load test.

    These values mirror those used by the frontend when a student launches an
    application (see ``frontend/script.js``).  Add more entries here if you want
    to stress-test other templates.
    """

    return {
        "vscode": TemplatePreset(
            image="tutanka01/k8s:vscode",
            create_service=True,
            service_type="NodePort",
            service_port=8080,
            service_target_port=80,
        ),
        "jupyter": TemplatePreset(
            image="tutanka01/k8s:jupyter",
            create_service=True,
            service_type="NodePort",
            service_port=8888,
            service_target_port=8888,
        ),
        "netbeans": TemplatePreset(
            image="tutanka01/k8s:netbeans",
            create_service=True,
            service_type="NodePort",
            service_port=6080,
            service_target_port=6080,
        ),
        "lamp": TemplatePreset(
            image="tutanka01/k8s:lamp-stack",
            create_service=True,
            service_type="NodePort",
            service_port=8080,
            service_target_port=80,
        ),
        "mysql": TemplatePreset(
            image="phpmyadmin:latest",
            create_service=True,
            service_type="NodePort",
            service_port=8080,
            service_target_port=80,
        ),
    }


TEMPLATE_PRESETS = _load_template_presets()


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bulk create LabOnDemand deployments for load testing")
    parser.add_argument("--base-url", default="http://localhost:8000", help="LabOnDemand backend URL")
    parser.add_argument("--username", required=True, help="Account used to authenticate against the API")
    parser.add_argument("--password", required=True, help="Password for the account")
    parser.add_argument("--count", type=int, default=60, help="Number of deployments to create")
    parser.add_argument(
        "--template",
        choices=sorted(TEMPLATE_PRESETS.keys()),
        default="vscode",
        help="Template to launch for each deployment",
    )
    parser.add_argument(
        "--cpu",
        choices=sorted(CPU_PRESETS.keys()),
        default="low",
        help="CPU preset to request (mirrors the frontend options)",
    )
    parser.add_argument(
        "--ram",
        choices=sorted(RAM_PRESETS.keys()),
        default="medium",
        help="Memory preset to request (mirrors the frontend options)",
    )
    parser.add_argument(
        "--prefix",
        default="loadtest",
        help="Prefix used when generating deployment names",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Optional delay (in seconds) between successive deployment creations",
    )
    parser.add_argument(
        "--pvc",
        default=None,
        help="Reuse an existing PersistentVolumeClaim instead of creating a fresh volume",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete the created deployments at the end of the test",
    )
    parser.add_argument(
        "--namespace-prefix",
        default="labondemand",
        help="Namespace prefix (matches USER_NAMESPACE_PREFIX in backend settings)",
    )
    return parser.parse_args(argv)


def login(session: requests.Session, base_url: str, username: str, password: str) -> Dict[str, object]:
    response = session.post(
        f"{base_url}/api/v1/auth/login",
        json={"username": username, "password": password},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Login failed: {response.status_code} {response.text}")
    return response.json()


def get_current_user(session: requests.Session, base_url: str) -> Dict[str, object]:
    response = session.get(f"{base_url}/api/v1/auth/me", timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"Unable to fetch current user: {response.status_code} {response.text}")
    return response.json()


def build_deployment_params(
    name: str,
    template_key: str,
    template: TemplatePreset,
    cpu_key: str,
    ram_key: str,
    existing_pvc_name: Optional[str] = None,
) -> Dict[str, object]:
    cpu_request, cpu_limit = CPU_PRESETS[cpu_key]
    mem_request, mem_limit = RAM_PRESETS[ram_key]
    params: Dict[str, object] = {
        "name": name,
        "image": template.image,
        "replicas": template.replicas,
        "create_service": "true" if template.create_service else "false",
        "service_port": template.service_port,
        "service_target_port": template.service_target_port,
        "service_type": template.service_type,
        "deployment_type": template_key,
        "cpu_request": cpu_request,
        "cpu_limit": cpu_limit,
        "memory_request": mem_request,
        "memory_limit": mem_limit,
    }
    if existing_pvc_name:
        params["existing_pvc_name"] = existing_pvc_name
    return params


def create_deployment(
    session: requests.Session,
    base_url: str,
    params: Dict[str, object],
) -> Dict[str, object]:
    response = session.post(f"{base_url}/api/v1/k8s/deployments", params=params, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(f"Deployment creation failed: {response.status_code} {response.text}")
    return response.json()


def delete_deployment(
    session: requests.Session,
    base_url: str,
    namespace: str,
    name: str,
) -> None:
    response = session.delete(
        f"{base_url}/api/v1/k8s/deployments/{namespace}/{name}",
        params={"delete_service": "true", "delete_persistent": "false"},
        timeout=60,
    )
    if response.status_code not in (200, 202, 204, 404):
        raise RuntimeError(f"Unable to delete deployment {name}: {response.status_code} {response.text}")


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    template = TEMPLATE_PRESETS[args.template]

    session = requests.Session()
    session.headers.update({"User-Agent": "LabOnDemand-LoadTest/1.0"})

    print(f"🔐 Logging in as {args.username} @ {args.base_url}")
    login(session, args.base_url, args.username, args.password)
    user = get_current_user(session, args.base_url)
    user_id = user.get("id")
    if user_id is None:
        raise RuntimeError("Backend did not return a user id; cannot derive namespace")

    namespace = f"{args.namespace_prefix}-{user_id}"
    print(f"✅ Authenticated as {user['username']} (role={user['role']}) -> namespace {namespace}")

    created_names: List[str] = []
    start = time.perf_counter()

    try:
        for idx in range(args.count):
            deployment_name = f"{args.prefix}-{idx + 1:03d}"
            params = build_deployment_params(
                deployment_name,
                args.template,
                template,
                args.cpu,
                args.ram,
                existing_pvc_name=args.pvc,
            )
            print(f"🚀 [{idx + 1}/{args.count}] Launching {deployment_name} ({args.template})")
            result = create_deployment(session, args.base_url, params)
            if isinstance(result, dict):
                namespace = result.get("namespace") or namespace
                details = result.get("message") or result.get("status") or result.get("deployment_name")
            else:
                details = str(result)
            print(f"   ↳ {details or 'submitted'}")
            created_names.append(deployment_name)
            if args.delay:
                time.sleep(args.delay)
    except Exception as exc:
        print(f"❌ Error while creating deployments: {exc}", file=sys.stderr)
        return 1
    finally:
        duration = time.perf_counter() - start
        print(f"⏱️  Completed in {duration:.1f}s ({len(created_names)} deployments launched)")

        if args.cleanup and created_names:
            print("🧹 Cleanup requested -> deleting created deployments")
            for name in created_names:
                try:
                    delete_deployment(session, args.base_url, namespace, name)
                    print(f"   • Deleted {name}")
                except Exception as cleanup_exc:
                    print(f"   ⚠️ Failed to delete {name}: {cleanup_exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
