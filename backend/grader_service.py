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

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional, Tuple

from kubernetes import client

from sqlalchemy import update

from .config import settings
from .database import SessionLocal
from .k8s_utils import ensure_namespace_baseline
from .lab_locks import KeyedLocks
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

# Grading runs watched at the same time (each worker mostly sleeps between polls).
GRADER_MAX_CONCURRENT_RUNS = max(1, int(os.getenv("GRADER_MAX_CONCURRENT_RUNS", "16")))
_EXECUTOR: Optional[ThreadPoolExecutor] = None
# Set by shutdown(): workers of that executor stop polling and give up.
_STOP_EVENT: Optional[threading.Event] = None
_EXECUTOR_LOCK = threading.Lock()

ACTIVE_RUN_STATUSES = ("queued", "running")
RUN_ALREADY_ACTIVE_DETAIL = (
    "Des tests sont déjà en cours pour ce devoir : attends leur résultat avant d'en relancer."
)
INTERRUPTED_BY_SHUTDOWN = "Run interrompu (arrêt du serveur)"
INTERRUPTED_BY_RESTART = "Run interrompu (redémarrage du serveur)"

# Serialises "is a run active? -> insert a queued run" per (user, assignment).
_ENQUEUE_LOCKS = KeyedLocks()


class _Stopped(Exception):
    """The grader pool is shutting down: stop watching the Job."""


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


def has_active_run(db, assignment_id: int, user_id: int) -> bool:
    """True when the user already has a queued or running run for this assignment."""
    return (
        db.query(GradingRun.id)
        .filter(
            GradingRun.assignment_id == assignment_id,
            GradingRun.user_id == user_id,
            GradingRun.status.in_(ACTIVE_RUN_STATUSES),
        )
        .first()
        is not None
    )


def enqueue_run(
    db, *, assignment_id: int, user_id: int, deployment_id: Optional[int], trigger: str
) -> Optional[GradingRun]:
    """Insert and commit a ``queued`` run, unless one is already active.

    Returns ``None`` when the user already has a queued/running run for this
    assignment: one user can occupy at most one grader worker per assignment,
    so a student hammering "run tests" cannot starve the others. The check
    and the insert are serialised per (user, assignment) in this process; the
    caller schedules the returned run.
    """
    with _ENQUEUE_LOCKS.hold((int(user_id), int(assignment_id))):
        # Fresh transaction: see runs committed by concurrent requests.
        db.rollback()
        if has_active_run(db, assignment_id, user_id):
            return None
        run = GradingRun(
            assignment_id=assignment_id,
            user_id=user_id,
            deployment_id=deployment_id,
            trigger=trigger,
            status="queued",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run


def _executor() -> Tuple[ThreadPoolExecutor, threading.Event]:
    global _EXECUTOR, _STOP_EVENT
    with _EXECUTOR_LOCK:
        if _EXECUTOR is None or _STOP_EVENT is None:
            _EXECUTOR = ThreadPoolExecutor(
                max_workers=GRADER_MAX_CONCURRENT_RUNS, thread_name_prefix="grader"
            )
            _STOP_EVENT = threading.Event()
        return _EXECUTOR, _STOP_EVENT


def schedule_grading(run_id: int) -> None:
    """Queue a grading run on the grader worker pool (callable from any thread).

    Runs execute in background threads, never on the event loop; at most
    ``GRADER_MAX_CONCURRENT_RUNS`` watch the cluster at the same time, the rest
    stay ``queued`` until a worker frees up.
    """
    executor, stop = _executor()
    executor.submit(_run_grading_logged, run_id, stop)


def _run_grading_logged(run_id: int, stop: Optional[threading.Event] = None) -> None:
    try:
        run_grading(run_id, stop=stop)
    except Exception:  # run_grading already records failures; never lose a traceback
        logger.exception("grading_worker_crashed", extra={"extra_fields": {"run_id": run_id}})


def shutdown() -> None:
    """Stop the grader pool without waiting (called on application shutdown).

    Queued runs that no worker picked up are dropped; workers watching a Job
    stop polling at once and mark their run as interrupted. Runs left
    queued/running in the DB are reconciled at the next start
    (``reconcile_orphaned_runs``) or by the cleanup loop.
    """
    global _EXECUTOR, _STOP_EVENT
    with _EXECUTOR_LOCK:
        executor, _EXECUTOR = _EXECUTOR, None
        stop, _STOP_EVENT = _STOP_EVENT, None
    if stop is not None:
        stop.set()
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)


def reconcile_orphaned_runs(db) -> int:
    """Mark every queued/running run as interrupted (call once at startup).

    The API is a single process and the grader pool lives in memory, so at
    startup no worker can own a run: those left active by the previous process
    (stopped, reloaded or killed) would otherwise block their student's next
    run until the cleanup loop's much larger bound.
    """
    result = db.execute(
        update(GradingRun)
        .where(GradingRun.status.in_(ACTIVE_RUN_STATUSES))
        .values(status="error", error=INTERRUPTED_BY_RESTART, finished_at=_now())
    )
    db.commit()
    count = result.rowcount or 0
    if count:
        logger.info("grading_runs_reconciled_at_startup", extra={"extra_fields": {"count": count}})
    return count


def _claim_run(db, run_id: int) -> bool:
    """Atomically move a run from ``queued`` to ``running``.

    A conditional UPDATE, so a run the cleanup loop flipped to ``error`` while
    it waited in the queue is never started (and never overwritten).
    """
    result = db.execute(
        update(GradingRun)
        .where(GradingRun.id == run_id, GradingRun.status == "queued")
        .values(status="running", started_at=_now())
    )
    db.commit()
    return (result.rowcount or 0) == 1


def run_grading(run_id: int, stop: Optional[threading.Event] = None) -> None:
    """Provisionne le Job grader, attend sa fin et enregistre le verdict (bloquant).

    Exécuté dans un thread du pool grader (voir ``schedule_grading``). La fonction
    possède sa propre session DB : elle survit à la requête HTTP qui l'a déclenchée.
    ``stop`` (set by ``shutdown``) interrupts the wait for the Job."""
    db = SessionLocal()
    job_name = job_name_for_run(run_id)
    stopped = False
    try:
        if stop is not None and stop.is_set():
            return  # shutting down: leave the run queued for the startup reconciliation
        run = db.query(GradingRun).filter(GradingRun.id == run_id).first()
        if not run or run.status != "queued":
            # Inconnu, ou déjà réconcilié par la tâche de nettoyage pendant l'attente.
            return
        spec = db.query(GradingSpec).filter(GradingSpec.assignment_id == run.assignment_id).first()
        if not spec:
            _finish_error(db, run, "Aucune batterie de tests définie pour ce devoir")
            return

        target = resolve_target(run, db)
        if target is None:
            _finish_error(db, run, "Lab introuvable : impossible de lancer les tests")
            return

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

        if not _claim_run(db, run.id):
            return  # reconciled (error) while it waited in the queue
        db.refresh(run)

        ensure_grader_infra()
        _create_job(manifest)

        logs = _watch_job(job_name, timeout, stop)

        if logs is None:
            _finish_error(db, run, f"Timeout : le grader n'a pas répondu en {timeout}s")
            return

        results = parse_results_from_logs(logs)
        if results is None:
            _finish_error(db, run, "Verdict illisible : le grader n'a pas produit de résultat JSON")
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
            extra={"extra_fields": {"run_id": run.id, "passed": summary["passed"], "total": summary["total"]}},
        )
    except _Stopped:
        stopped = True
        _record_interrupted(db, run_id)
    except Exception as exc:  # garde-fou : un run ne doit jamais rester bloqué
        logger.exception("grading_run_failed", extra={"extra_fields": {"run_id": run_id, "error": str(exc)}})
        try:
            db.rollback()
            run = db.query(GradingRun).filter(GradingRun.id == run_id).first()
            if run and run.status not in ("done", "error"):
                _finish_error(db, run, f"Erreur interne du grader : {type(exc).__name__}")
        except Exception:
            logger.exception("grading_run_error_not_recorded", extra={"extra_fields": {"run_id": run_id}})
            db.rollback()
    finally:
        # Nettoyage best-effort du Job (le TTL est le filet de sécurité). Skipped
        # on shutdown: a Kubernetes call could delay the exit, and the Job's
        # activeDeadlineSeconds + ttlSecondsAfterFinished remove it anyway.
        if not stopped:
            try:
                _delete_job(job_name)
            except Exception as exc:
                logger.info("grader_job_delete_failed", extra={"extra_fields": {"job": job_name, "error": str(exc)}})
        db.close()


def _record_interrupted(db, run_id: int) -> None:
    """Mark a run interrupted by shutdown (best-effort, one quick UPDATE)."""
    try:
        db.rollback()
        db.execute(
            update(GradingRun)
            .where(GradingRun.id == run_id, GradingRun.status.in_(ACTIVE_RUN_STATUSES))
            .values(status="error", error=INTERRUPTED_BY_SHUTDOWN, finished_at=_now())
        )
        db.commit()
        logger.info("grading_run_interrupted", extra={"extra_fields": {"run_id": run_id}})
    except Exception:
        # Left running: reconciled at the next start.
        db.rollback()
        logger.warning("grading_run_interrupt_not_recorded", extra={"extra_fields": {"run_id": run_id}})


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


def _watch_job(
    job_name: str, timeout: int, stop: Optional[threading.Event] = None
) -> Optional[str]:
    """Poll le statut du Job jusqu'à complétion, puis renvoie les logs du pod.

    Retourne ``None`` en cas de timeout global ; lève ``_Stopped`` dès que
    ``stop`` est positionné (arrêt de l'API)."""
    ns = settings.GRADER_NAMESPACE
    deadline = time.monotonic() + timeout + settings.GRADER_WATCH_GRACE_SECONDS
    poll = max(1, settings.GRADER_POLL_INTERVAL_SECONDS)
    stop = stop or threading.Event()

    while time.monotonic() < deadline:
        if stop.wait(poll):
            raise _Stopped()
        status = _read_job_status(job_name, ns)
        if status is None:
            continue
        succeeded = getattr(status, "succeeded", None) or 0
        failed = getattr(status, "failed", None) or 0
        if succeeded or failed:
            return _read_job_logs(job_name, ns)
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
