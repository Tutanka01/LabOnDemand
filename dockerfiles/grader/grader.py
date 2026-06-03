#!/usr/bin/env python3
"""
Grader LabOnDemand — exécute une batterie de probes "boîte noire" contre le lab
d'un étudiant et imprime un verdict structuré en JSON sur stdout.

Contrat (lu par ``backend/grader_service.py`` via les logs du pod, modèle pull) :

  - Entrée (variables d'environnement) :
      GRADER_SPEC          JSON {"checks": [<probe>, ...]} (probes de l'enseignant)
      GRADER_TARGET_URL    URL HTTP de base du lab (ex: http://lab-svc.ns.svc:80)
      GRADER_TARGET_HOST   hostname du lab (pour les probes tcp/sql)
      GRADER_TARGET_PORT   port par défaut du lab
      GRADER_TIMEOUT       timeout par probe en secondes (défaut 15)
      GRADER_SCRIPT        (optionnel) script bash/python fourni par l'enseignant

  - Sortie : entre deux marqueurs, une ligne JSON ``{"checks": [<result>, ...]}``
      ===GRADER_RESULT_BEGIN===
      {"checks": [{"id","name","status","message","output","weight","visibility"}]}
      ===GRADER_RESULT_END===

    ``status`` ∈ pass | fail | error | skip. Le script ne plante jamais : une probe
    qui échoue produit un résultat ``error``/``fail``, pas un exit non nul qui
    masquerait les autres verdicts.

Le script n'utilise que la bibliothèque standard (urllib, socket, subprocess) :
aucune dépendance pip, image légère et reproductible.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request

RESULT_BEGIN = "===GRADER_RESULT_BEGIN==="
RESULT_END = "===GRADER_RESULT_END==="

DEFAULT_TIMEOUT = 15


# ── Helpers ──────────────────────────────────────────────────────────────────


def _truncate(value: str, limit: int = 2000) -> str:
    """Borne la taille d'une sortie pour ne pas noyer les logs / la DB."""
    if value is None:
        return ""
    value = str(value)
    return value if len(value) <= limit else value[:limit] + "…[tronqué]"


def _result(probe: dict, status: str, message: str = "", output: str = "") -> dict:
    return {
        "id": str(probe.get("id", "")),
        "name": str(probe.get("name", probe.get("id", "probe"))),
        "status": status,
        "message": _truncate(message, 500),
        "output": _truncate(output, 2000),
        "weight": int(probe.get("weight", 1) or 0),
        "visibility": str(probe.get("visibility", "student")),
    }


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


# ── Probes ───────────────────────────────────────────────────────────────────


def run_http(probe: dict, base_url: str, timeout: int) -> dict:
    config = probe.get("config") or {}
    expect = probe.get("expect") or {}

    url = (config.get("url") or "").strip()
    path = (config.get("path") or "").strip()
    if not url:
        # Construire l'URL à partir de la base + path.
        target = base_url.rstrip("/")
        if path and not path.startswith("/"):
            path = "/" + path
        url = target + path
    elif url.startswith("/"):
        url = base_url.rstrip("/") + url
    if not url:
        return _result(probe, "error", "Aucune URL cible pour la probe HTTP")

    method = (config.get("method") or "GET").upper()
    headers = config.get("headers") or {}
    body = config.get("body")
    data = body.encode("utf-8") if isinstance(body, str) and body else None

    req = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers.items() if isinstance(headers, dict) else []):
        req.add_header(str(key), str(value))

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.getcode()
            raw = resp.read(65536).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        # Une réponse HTTP d'erreur (404, 500...) reste une réponse mesurable.
        status_code = exc.code
        try:
            raw = exc.read(65536).decode("utf-8", errors="replace")
        except Exception:
            raw = ""
    except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
        return _result(probe, "fail", f"Connexion impossible à {url} : {exc}", "")
    except Exception as exc:  # garde-fou : ne jamais planter
        return _result(probe, "error", f"Erreur HTTP inattendue : {exc}", "")

    failures = []

    expected_status = expect.get("status")
    if expected_status is not None:
        try:
            if int(status_code) != int(expected_status):
                failures.append(f"status {status_code} attendu {expected_status}")
        except (TypeError, ValueError):
            pass

    contains = expect.get("body_contains") or expect.get("contains")
    if contains:
        if str(contains) not in raw:
            failures.append(f"corps ne contient pas « {contains} »")

    regex = expect.get("regex")
    if regex:
        try:
            if not re.search(regex, raw):
                failures.append(f"corps ne matche pas /{regex}/")
        except re.error as exc:
            failures.append(f"regex invalide : {exc}")

    output = f"HTTP {status_code} — {_truncate(raw, 500)}"
    if failures:
        return _result(probe, "fail", "; ".join(failures), output)
    return _result(probe, "pass", f"HTTP {status_code} conforme", output)


def run_tcp(probe: dict, default_host: str, default_port: int, timeout: int) -> dict:
    config = probe.get("config") or {}
    expect = probe.get("expect") or {}

    host = (config.get("host") or default_host or "").strip()
    try:
        port = int(config.get("port") or default_port)
    except (TypeError, ValueError):
        return _result(probe, "error", "Port TCP invalide")
    if not host:
        return _result(probe, "error", "Aucun hôte cible pour la probe TCP")

    want_open = expect.get("open", True)
    is_open = False
    detail = ""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            is_open = True
    except (OSError, socket.timeout) as exc:
        detail = str(exc)

    output = f"{host}:{port} {'ouvert' if is_open else 'fermé'}"
    if bool(want_open) == is_open:
        return _result(probe, "pass", output, detail)
    expected = "ouvert" if want_open else "fermé"
    return _result(probe, "fail", f"{host}:{port} attendu {expected}", detail)


def run_sql(probe: dict, default_host: str, timeout: int) -> dict:
    config = probe.get("config") or {}
    expect = probe.get("expect") or {}

    engine = (config.get("engine") or "mysql").lower()
    host = (config.get("host") or default_host or "").strip()
    user = config.get("user") or ("postgres" if engine in ("postgres", "postgresql") else "root")
    password = config.get("password") or ""
    database = config.get("database") or ""
    query = (config.get("query") or "").strip()
    if not query:
        return _result(probe, "error", "Aucune requête SQL fournie")
    if not host:
        return _result(probe, "error", "Aucun hôte cible pour la probe SQL")

    if engine in ("postgres", "postgresql"):
        port = str(config.get("port") or 5432)
        cmd = ["psql", "-h", host, "-p", port, "-U", str(user), "-t", "-A", "-c", query]
        if database:
            cmd[1:1] = ["-d", database]  # insère après psql (ordre indifférent pour psql)
        env = dict(os.environ, PGPASSWORD=str(password), PGCONNECT_TIMEOUT=str(timeout))
    else:  # mysql / mariadb
        port = str(config.get("port") or 3306)
        cmd = ["mysql", "-h", host, "-P", port, "-u", str(user), "-N", "-B",
               f"--connect-timeout={timeout}", "-e", query]
        if password:
            cmd.insert(1, f"-p{password}")
        if database:
            cmd += ["-D", database]
        env = dict(os.environ)

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout + 5, env=env
        )
    except subprocess.TimeoutExpired:
        return _result(probe, "fail", f"Timeout SQL ({timeout}s)")
    except Exception as exc:
        return _result(probe, "error", f"Erreur exécution SQL : {exc}")

    if proc.returncode != 0:
        return _result(probe, "fail", "Requête SQL en échec", proc.stderr or proc.stdout)

    lines = [l for l in proc.stdout.splitlines() if l.strip() != ""]
    row_count = len(lines)
    output = _truncate(proc.stdout, 1000)

    min_rows = expect.get("min_rows")
    if min_rows is not None:
        try:
            if row_count < int(min_rows):
                return _result(probe, "fail", f"{row_count} ligne(s), attendu ≥ {min_rows}", output)
        except (TypeError, ValueError):
            pass

    contains = expect.get("contains")
    if contains and str(contains) not in proc.stdout:
        return _result(probe, "fail", f"résultat ne contient pas « {contains} »", output)

    return _result(probe, "pass", f"{row_count} ligne(s) retournée(s)", output)


def run_script(probe: dict, script: str, base_url: str, default_host: str, timeout: int) -> dict:
    """Exécute le script de l'enseignant et parse son contrat de sortie JSON.

    Contrat : le script imprime ``{"checks": [...]}`` sur stdout, OU renvoie
    exit code 0 (succès) / non-zéro (échec). Le script reçoit la cible via
    l'environnement (GRADER_TARGET_URL / GRADER_TARGET_HOST).
    """
    if not script:
        return _result(probe, "skip", "Aucun script fourni")

    env = dict(
        os.environ,
        GRADER_TARGET_URL=base_url,
        GRADER_TARGET_HOST=default_host,
    )
    try:
        proc = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        return _result(probe, "fail", f"Timeout script ({timeout}s)")
    except Exception as exc:
        return _result(probe, "error", f"Erreur exécution script : {exc}")

    stdout = proc.stdout or ""
    # 1) Tenter de parser un contrat JSON {"checks": [...]} sur la dernière ligne JSON.
    parsed = _extract_json_checks(stdout)
    if parsed is not None:
        return parsed  # liste de checks (gérée par l'appelant)

    # 2) Sinon, verdict binaire via exit code.
    if proc.returncode == 0:
        return _result(probe, "pass", "Script OK (exit 0)", stdout)
    return _result(probe, "fail", f"Script en échec (exit {proc.returncode})", proc.stderr or stdout)


def _extract_json_checks(text: str):
    """Cherche un objet JSON {"checks": [...]} dans la sortie d'un script.

    Retourne la liste de checks normalisée, ou None si rien d'exploitable.
    """
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not (line.startswith("{") and "checks" in line):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        checks = data.get("checks")
        if isinstance(checks, list):
            normalized = []
            for c in checks:
                if not isinstance(c, dict):
                    continue
                normalized.append({
                    "id": str(c.get("id", "")),
                    "name": str(c.get("name", c.get("id", "check"))),
                    "status": str(c.get("status", "error")),
                    "message": _truncate(c.get("message", ""), 500),
                    "output": _truncate(c.get("output", ""), 2000),
                    "weight": int(c.get("weight", 1) or 0),
                    "visibility": str(c.get("visibility", "student")),
                })
            return {"__checks__": normalized}
    return None


# ── Orchestration ────────────────────────────────────────────────────────────


def main() -> int:
    base_url = (os.environ.get("GRADER_TARGET_URL") or "").strip()
    default_host = (os.environ.get("GRADER_TARGET_HOST") or "").strip()
    default_port = _env_int("GRADER_TARGET_PORT", 80)
    timeout = _env_int("GRADER_TIMEOUT", DEFAULT_TIMEOUT)
    script = os.environ.get("GRADER_SCRIPT") or ""

    try:
        spec = json.loads(os.environ.get("GRADER_SPEC") or "{}")
    except ValueError as exc:
        _emit({"checks": [], "error": f"GRADER_SPEC invalide : {exc}"})
        return 0

    probes = spec.get("checks") or []
    results = []

    for probe in probes:
        if not isinstance(probe, dict):
            continue
        kind = (probe.get("kind") or "").lower()
        try:
            if kind == "http":
                results.append(run_http(probe, base_url, timeout))
            elif kind == "tcp":
                results.append(run_tcp(probe, default_host, default_port, timeout))
            elif kind == "sql":
                results.append(run_sql(probe, default_host, timeout))
            elif kind == "script":
                outcome = run_script(probe, script, base_url, default_host, timeout)
                if isinstance(outcome, dict) and "__checks__" in outcome:
                    results.extend(outcome["__checks__"])
                else:
                    results.append(outcome)
            else:
                # Probes inside (file/command) non supportées par le grader isolé (MVP-2).
                results.append(_result(probe, "skip", f"kind « {kind} » non supporté par le grader isolé"))
        except Exception as exc:  # garde-fou global par probe
            results.append(_result(probe, "error", f"Erreur interne : {exc}"))

    # Si la spec ne porte pas de probe mais un script global, on l'exécute seul.
    if not probes and script:
        outcome = run_script({"id": "script", "name": "Script de notation"}, script, base_url, default_host, timeout)
        if isinstance(outcome, dict) and "__checks__" in outcome:
            results.extend(outcome["__checks__"])
        else:
            results.append(outcome)

    _emit({"checks": results})
    return 0


def _emit(payload: dict) -> None:
    """Imprime le verdict entre les marqueurs attendus par l'API."""
    print(RESULT_BEGIN)
    print(json.dumps(payload, ensure_ascii=False))
    print(RESULT_END)
    sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
