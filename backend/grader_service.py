"""
Service d'orchestration du Grader Pod (MVP-2).

Modèle d'exécution = **pull** : l'API crée un Job Kubernetes isolé dans un namespace
verrouillé, surveille sa fin via l'API K8s (qu'elle possède déjà via le kubeconfig),
puis **lit le stdout du pod** pour récupérer le verdict. Le grader ne rappelle jamais
l'API — décision prise car l'API tourne en Docker Compose face à un cluster distant et
n'a pas d'adresse fiable joignable depuis le cluster.

Garanties de sécurité du Job (voir ``build_job_manifest``) :
  - ServiceAccount sans token monté, aucun droit RBAC, aucun kubeconfig ;
  - NetworkPolicy egress restreinte (namespaces de labs + DNS uniquement) ;
  - limites CPU/RAM, ``activeDeadlineSeconds`` et ``ttlSecondsAfterFinished`` courts ;
  - conteneur non-root, capabilities droppées, privilege escalation interdite.

Périmètre MVP-2 : probes *outside* (http / tcp / sql) + script. Les probes *inside*
(file/command) sont marquées ``skip`` par le grader (elles casseraient l'isolation).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Coroutine, List, Optional

import anyio
import anyio.to_thread
from kubernetes import client

from .config import settings
from .database import SessionLocal
from .k8s_utils import ensure_namespace_baseline
from .models import (
    Assignment,
    Deployment,
    GradingRun,
    GradingSpec,
    RuntimeConfig,
    Template,
)

logger = logging.getLogger("labondemand.grader")

RESULT_BEGIN = "===GRADER_RESULT_BEGIN==="
RESULT_END = "===GRADER_RESULT_END==="

GRADER_SA_NAME = "grader-sa"
_NETWORK_POLICY_NAME = "grader-egress"

# Kinds exécutables par le grader isolé (depuis l'extérieur du lab).
SUPPORTED_KINDS = {"http", "tcp", "sql", "script"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Provisionnement de l'infrastructure grader (idempotent) ──────────────────


def ensure_grader_infra() -> None:
    """Crée (si besoin) le namespace grader, son ServiceAccount sans droits et la
    NetworkPolicy egress restreinte. Idempotent : sûr à appeler avant chaque run."""
    ns = settings.GRADER_NAMESPACE
    core = client.CoreV1Api()

    # 1. Namespace dédié, labellisé pour être identifiable / nettoyable.
    try:
        core.read_namespace(ns)
    except client.exceptions.ApiException as exc:
        if exc.status == 404:
            core.create_namespace({
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {
                    "name": ns,
                    "labels": {"managed-by": "labondemand", "labondemand.io/role": "grader"},
                },
            })
        elif exc.status != 403:
            raise

    # Quota/LimitRange stricts (réutilise la baseline « student », volontairement basse).
    ensure_namespace_baseline(ns, "student")

    # 2. ServiceAccount SANS token monté et SANS aucun RoleBinding.
    try:
        core.read_namespaced_service_account(GRADER_SA_NAME, ns)
    except client.exceptions.ApiException as exc:
        if exc.status == 404:
            core.create_namespaced_service_account(ns, {
                "apiVersion": "v1",
                "kind": "ServiceAccount",
                "metadata": {"name": GRADER_SA_NAME, "namespace": ns},
                "automountServiceAccountToken": False,
            })
        elif exc.status != 403:
            raise

    # 3. NetworkPolicy : ingress refusé, egress limité aux labs + DNS.
    _ensure_network_policy(ns)


def _ensure_network_policy(ns: str) -> None:
    net = client.NetworkingV1Api()
    body = build_network_policy(ns)
    try:
        net.read_namespaced_network_policy(_NETWORK_POLICY_NAME, ns)
        net.patch_namespaced_network_policy(_NETWORK_POLICY_NAME, ns, body)
    except client.exceptions.ApiException as exc:
        if exc.status == 404:
            net.create_namespaced_network_policy(ns, body)
        elif exc.status != 403:
            raise


def build_network_policy(ns: str) -> dict:
    """NetworkPolicy du namespace grader.

    - Ingress : aucune règle → tout trafic entrant refusé.
    - Egress : uniquement vers les namespaces de labs (label ``managed-by=labondemand``)
      et vers le DNS du cluster (port 53). Tout le reste (Internet, API, infra) est bloqué.

    NB : l'enforcement effectif dépend du CNI du cluster (Calico/Cilium...). Sur un CNI
    sans support NetworkPolicy, cette politique est ignorée silencieusement — les autres
    garde-fous (SA sans droits, pas de kubeconfig, quotas, TTL) restent actifs.
    """
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": _NETWORK_POLICY_NAME, "namespace": ns},
        "spec": {
            "podSelector": {},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [],
            "egress": [
                {  # vers les pods des namespaces gérés par LabOnDemand (les labs)
                    "to": [
                        {"namespaceSelector": {"matchLabels": {"managed-by": "labondemand"}}}
                    ]
                },
                {  # résolution DNS du cluster
                    "ports": [
                        {"protocol": "UDP", "port": 53},
                        {"protocol": "TCP", "port": 53},
                    ]
                },
            ],
        },
    }


# ── Construction du Job ──────────────────────────────────────────────────────


def job_name_for_run(run_id: int) -> str:
    return f"grader-r{run_id}"


def build_job_manifest(
    run_id: int,
    image: str,
    timeout_seconds: int,
    spec_json: str,
    target: dict,
    custom_script: Optional[str],
) -> dict:
    """Construit le manifeste du Job grader isolé."""
    name = job_name_for_run(run_id)
    # Timeout par probe : le budget global réparti sur les probes, borné à [5s, timeout].
    per_probe_timeout = max(5, min(timeout_seconds, timeout_seconds // _probe_count(spec_json)))
    env = [
        {"name": "GRADER_SPEC", "value": spec_json},
        {"name": "GRADER_TARGET_URL", "value": target.get("url", "")},
        {"name": "GRADER_TARGET_HOST", "value": target.get("host", "")},
        {"name": "GRADER_TARGET_PORT", "value": str(target.get("port", 80))},
        {"name": "GRADER_TIMEOUT", "value": str(per_probe_timeout)},
    ]
    if custom_script:
        env.append({"name": "GRADER_SCRIPT", "value": custom_script})

    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": name,
            "namespace": settings.GRADER_NAMESPACE,
            "labels": {"managed-by": "labondemand", "labondemand.io/grading-run": str(run_id)},
        },
        "spec": {
            "backoffLimit": 0,
            "ttlSecondsAfterFinished": settings.GRADER_JOB_TTL_SECONDS,
            "activeDeadlineSeconds": timeout_seconds,
            "template": {
                "metadata": {
                    "labels": {"managed-by": "labondemand", "labondemand.io/grading-run": str(run_id)},
                },
                "spec": {
                    "restartPolicy": "Never",
                    "serviceAccountName": GRADER_SA_NAME,
                    "automountServiceAccountToken": False,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 10001,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "grader",
                            "image": image,
                            "imagePullPolicy": "IfNotPresent",
                            "env": env,
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "128Mi"},
                                "limits": {"cpu": "500m", "memory": "256Mi"},
                            },
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": False,
                                "capabilities": {"drop": ["ALL"]},
                            },
                        }
                    ],
                },
            },
        },
    }


def _probe_count(spec_json: str) -> int:
    try:
        return max(1, len(json.loads(spec_json).get("checks") or []))
    except (ValueError, TypeError):
        return 1


# ── Résolution de la cible (lab de l'étudiant / du prof) ─────────────────────


def resolve_target(run: GradingRun, db) -> Optional[dict]:
    """Construit l'URL interne du lab visé par un run, à partir de son deployment_id.

    Retourne ``{name, namespace, host, port, url, deployment_id}`` ou ``None`` si le lab
    n'existe plus (mortel : le lab a pu être supprimé/expiré entre-temps).
    """
    if not run.deployment_id:
        return None
    dep = db.query(Deployment).filter(Deployment.id == run.deployment_id).first()
    if not dep or dep.status not in ("active", "paused"):
        return None
    port = _resolve_port(dep, run.assignment_id, db)
    host = f"{dep.name}-service.{dep.namespace}.svc.cluster.local"
    return {
        "name": dep.name,
        "namespace": dep.namespace,
        "host": host,
        "port": port,
        "url": f"http://{host}:{port}",
        "deployment_id": dep.id,
    }


def _resolve_port(dep: Deployment, assignment_id: int, db) -> int:
    """Port d'écoute du service du lab (cohérent avec deploy-all)."""
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if assignment and assignment.template_key:
        tpl = db.query(Template).filter(Template.key == assignment.template_key).first()
        if tpl and tpl.default_port:
            return tpl.default_port
    rc = db.query(RuntimeConfig).filter(RuntimeConfig.key == dep.deployment_type).first()
    if rc and rc.target_port:
        return rc.target_port
    return 80


# ── Lecture / parsing des résultats ──────────────────────────────────────────


def parse_results_from_logs(logs: str) -> Optional[list]:
    """Extrait la liste de checks JSON imprimée par le grader entre ses marqueurs."""
    if not logs or RESULT_BEGIN not in logs:
        return None
    try:
        chunk = logs.split(RESULT_BEGIN, 1)[1].split(RESULT_END, 1)[0].strip()
        data = json.loads(chunk)
    except (IndexError, ValueError):
        return None
    checks = data.get("checks")
    return checks if isinstance(checks, list) else None


def summarize(results: list) -> dict:
    """Calcule total/passed/score_suggestion à partir des verdicts (hors ``skip``)."""
    considered = [r for r in results if r.get("status") != "skip"]
    total = len(considered)
    passed = sum(1 for r in considered if r.get("status") == "pass")
    total_weight = sum(int(r.get("weight", 1) or 0) for r in considered)
    passed_weight = sum(int(r.get("weight", 1) or 0) for r in considered if r.get("status") == "pass")
    score = None
    if total_weight > 0:
        score = f"{round(passed_weight / total_weight * 20)}/20"
    return {"total": total, "passed": passed, "score_suggestion": score}


# ── Watcher : crée le Job, surveille, récupère les résultats ─────────────────


@dataclass(frozen=True)
class _GradingPlan:
    """Ce dont le watcher a besoin après la phase DB (valeurs simples)."""

    manifest: dict
    timeout: int


def _prepare_run(run_id: int) -> Optional[_GradingPlan]:
    """Phase DB initiale (thread de travail, session dédiée).

    Charge le run, résout la cible et construit le manifeste ; passe le run en
    ``running``. Retourne None si le run est absent ou déjà clos en erreur.
    """
    with SessionLocal() as db:
        run = db.query(GradingRun).filter(GradingRun.id == run_id).first()
        if not run:
            return None
        spec = db.query(GradingSpec).filter(GradingSpec.assignment_id == run.assignment_id).first()
        if not spec:
            _finish_error(db, run, "Aucune batterie de tests définie pour ce devoir")
            return None

        target = resolve_target(run, db)
        if target is None:
            _finish_error(db, run, "Lab introuvable : impossible de lancer les tests")
            return None

        probes = _load_probes(spec)
        spec_json = json.dumps({"checks": probes})
        image = spec.grader_image or settings.GRADER_IMAGE
        timeout = spec.timeout_seconds or 120

        manifest = build_job_manifest(
            run_id=run.id,
            image=image,
            timeout_seconds=timeout,
            spec_json=spec_json,
            target=target,
            custom_script=spec.custom_script,
        )

        run.status = "running"
        run.started_at = _now()
        db.commit()
        return _GradingPlan(manifest=manifest, timeout=timeout)


def _finish_run_error(run_id: int, message: str) -> None:
    """Clôt un run en erreur s'il ne l'est pas déjà (thread de travail)."""
    with SessionLocal() as db:
        run = db.query(GradingRun).filter(GradingRun.id == run_id).first()
        if run and run.status not in ("done", "error"):
            _finish_error(db, run, message)


def _finish_run_done(run_id: int, results: list) -> None:
    """Enregistre le verdict d'un run (thread de travail)."""
    with SessionLocal() as db:
        run = db.query(GradingRun).filter(GradingRun.id == run_id).first()
        if not run:
            return
        summary = summarize(results)
        run.status = "done"
        run.results = json.dumps(results, ensure_ascii=False)
        run.total_checks = summary["total"]
        run.passed_checks = summary["passed"]
        run.score_suggestion = summary["score_suggestion"]
        run.finished_at = _now()
        db.commit()
    logger.info(
        "grading_run_done",
        extra={"extra_fields": {"run_id": run_id, "passed": summary["passed"], "total": summary["total"]}},
    )


async def run_grading(run_id: int) -> None:
    """Tâche de fond : provisionne le Job grader, attend sa fin, enregistre le verdict.

    Les accès DB et les API K8s sont synchrones : chaque phase s'exécute dans un
    thread de travail (``anyio.to_thread``) pour ne jamais bloquer la boucle
    asyncio. Chaque phase DB ouvre sa propre session (la tâche survit à la
    requête HTTP qui l'a déclenchée) et aucune session n'est tenue pendant
    l'attente du Job."""
    job_name = job_name_for_run(run_id)
    try:
        plan = await anyio.to_thread.run_sync(_prepare_run, run_id)
        if plan is None:
            return

        # Provisionner l'infra puis créer le Job (appels K8s bloquants → thread).
        await anyio.to_thread.run_sync(ensure_grader_infra)
        await anyio.to_thread.run_sync(_create_job, plan.manifest)

        logs = await _watch_job(job_name, plan.timeout)

        if logs is None:
            await anyio.to_thread.run_sync(
                _finish_run_error, run_id, f"Timeout : le grader n'a pas répondu en {plan.timeout}s"
            )
            return

        results = parse_results_from_logs(logs)
        if results is None:
            await anyio.to_thread.run_sync(
                _finish_run_error, run_id, "Verdict illisible : le grader n'a pas produit de résultat JSON"
            )
            return

        await anyio.to_thread.run_sync(_finish_run_done, run_id, results)
    except Exception as exc:  # garde-fou : un run ne doit jamais rester bloqué
        logger.exception("grading_run_failed", extra={"extra_fields": {"run_id": run_id, "error": str(exc)}})
        try:
            await anyio.to_thread.run_sync(_finish_run_error, run_id, f"Erreur interne du grader : {exc}")
        except Exception:
            logger.exception("grading_run_finalize_failed", extra={"extra_fields": {"run_id": run_id}})
    finally:
        # Nettoyage best-effort du Job (le TTL est le filet de sécurité).
        try:
            await anyio.to_thread.run_sync(_delete_job, job_name)
        except Exception as exc:
            logger.warning(
                "grading_job_cleanup_failed",
                extra={"extra_fields": {"run_id": run_id, "job_name": job_name, "error": str(exc)}},
            )


# ── Planification des runs (tâches de fond) ───────────────────────────────────

# Références fortes vers les tâches en cours : la boucle asyncio ne garde que
# des références faibles, une tâche non référencée peut être collectée en
# plein vol.
_background_tasks: "set[asyncio.Task[None]]" = set()


def _track(coro: Coroutine[Any, Any, None]) -> "asyncio.Task[None]":
    task = asyncio.get_running_loop().create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def schedule_grading(run_id: int) -> "asyncio.Task[None]":
    """Lance ``run_grading`` en tâche de fond (à appeler depuis la boucle)."""
    return _track(run_grading(run_id))


async def _run_grading_batch(
    runner: Callable[[int], Awaitable[None]], run_ids: List[int], concurrency: int
) -> None:
    limiter = anyio.CapacityLimiter(max(1, concurrency))

    async def _one(run_id: int) -> None:
        async with limiter:
            try:
                await runner(run_id)
            except Exception:
                # run_grading ne lève pas ; garde-fou pour ne pas annuler le lot.
                logger.exception("grading_run_failed", extra={"extra_fields": {"run_id": run_id}})

    async with anyio.create_task_group() as tg:
        for run_id in run_ids:
            tg.start_soon(_one, run_id)


def schedule_grading_batch(run_ids: List[int], concurrency: int) -> Optional["asyncio.Task[None]"]:
    """Lance un lot de runs en tâche de fond, au plus ``concurrency`` à la fois.

    À appeler depuis la boucle. Retourne None si le lot est vide.
    """
    if not run_ids:
        return None
    # run_grading est résolu maintenant (et non au démarrage de la tâche).
    return _track(_run_grading_batch(run_grading, list(run_ids), concurrency))


def _load_probes(spec: GradingSpec) -> list:
    if not spec.checks:
        return []
    try:
        raw = json.loads(spec.checks)
        return raw if isinstance(raw, list) else []
    except (ValueError, TypeError):
        return []


def _create_job(manifest: dict) -> None:
    batch = client.BatchV1Api()
    batch.create_namespaced_job(settings.GRADER_NAMESPACE, manifest)


def _delete_job(job_name: str) -> None:
    batch = client.BatchV1Api()
    try:
        batch.delete_namespaced_job(
            job_name,
            settings.GRADER_NAMESPACE,
            propagation_policy="Background",
        )
    except client.exceptions.ApiException as exc:
        if exc.status != 404:
            raise


async def _watch_job(job_name: str, timeout: int) -> Optional[str]:
    """Poll le statut du Job jusqu'à complétion, puis renvoie les logs du pod.

    Retourne ``None`` en cas de timeout global."""
    ns = settings.GRADER_NAMESPACE
    deadline = timeout + settings.GRADER_WATCH_GRACE_SECONDS
    elapsed = 0
    poll = max(1, settings.GRADER_POLL_INTERVAL_SECONDS)

    while elapsed < deadline:
        await asyncio.sleep(poll)
        elapsed += poll
        status = await anyio.to_thread.run_sync(_read_job_status, job_name, ns)
        if status is None:
            continue
        succeeded = getattr(status, "succeeded", None) or 0
        failed = getattr(status, "failed", None) or 0
        if succeeded or failed:
            return await anyio.to_thread.run_sync(_read_job_logs, job_name, ns)
    return None


def _read_job_status(job_name: str, ns: str):
    batch = client.BatchV1Api()
    try:
        job = batch.read_namespaced_job_status(job_name, ns)
        return getattr(job, "status", None)
    except client.exceptions.ApiException:
        return None


def _read_job_logs(job_name: str, ns: str) -> str:
    """Récupère le stdout du pod créé par le Job."""
    core = client.CoreV1Api()
    try:
        pods = core.list_namespaced_pod(ns, label_selector=f"job-name={job_name}")
    except client.exceptions.ApiException:
        return ""
    items = getattr(pods, "items", []) or []
    if not items:
        return ""
    pod_name = items[0].metadata.name
    try:
        return core.read_namespaced_pod_log(pod_name, ns) or ""
    except client.exceptions.ApiException:
        return ""


def _finish_error(db, run: GradingRun, message: str) -> None:
    run.status = "error"
    run.error = message[:500]
    run.finished_at = _now()
    db.commit()
    logger.warning("grading_run_error", extra={"extra_fields": {"run_id": run.id, "error": message}})


# ── Présentation : conversion run → réponse + filtrage de visibilité ─────────


def _results_list(run: GradingRun) -> Optional[list]:
    if not run.results:
        return None
    try:
        data = json.loads(run.results)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, list) else None


def filter_results_for_student(results: list) -> list:
    """Applique la visibilité des probes pour la vue étudiant :
    ``teacher_only`` masquée, ``summary`` réduite à pass/fail (sans message ni sortie)."""
    out = []
    for r in results:
        vis = r.get("visibility", "student")
        if vis == "teacher_only":
            continue
        if vis == "summary":
            out.append({
                "id": r.get("id", ""),
                "name": r.get("name", ""),
                "status": r.get("status", "error"),
                "message": None,
                "output": None,
                "weight": int(r.get("weight", 1) or 0),
                "visibility": "summary",
            })
        else:
            out.append(r)
    return out


def run_to_response(run: GradingRun, *, for_student: bool):
    """Construit un ``GradingRunResponse`` (filtré pour l'étudiant si demandé)."""
    from .schemas import GradingRunResponse, ProbeResult

    results = _results_list(run)
    if results is not None and for_student:
        results = filter_results_for_student(results)
    return GradingRunResponse(
        id=run.id,
        assignment_id=run.assignment_id,
        user_id=run.user_id,
        submission_id=run.submission_id,
        deployment_id=run.deployment_id,
        trigger=run.trigger,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        total_checks=run.total_checks,
        passed_checks=run.passed_checks,
        score_suggestion=run.score_suggestion,
        results=[ProbeResult(**r) for r in results] if results is not None else None,
        error=run.error,
        created_at=run.created_at,
    )


def latest_run_for(assignment_id: int, user_id: int, db) -> Optional[GradingRun]:
    """Dernier Grading Run d'un étudiant pour un devoir (le plus récent)."""
    return (
        db.query(GradingRun)
        .filter(GradingRun.assignment_id == assignment_id, GradingRun.user_id == user_id)
        .order_by(GradingRun.id.desc())
        .first()
    )
