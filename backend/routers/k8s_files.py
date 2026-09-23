"""Explorateur de fichiers des volumes persistants.

Toutes les opérations passent par un exec one-shot dans le pod du lab
(équivalent de ``kubectl exec``). Conséquence assumée : un lab en pause
(``replicas=0``) n'a pas de pod, donc pas de navigation possible tant qu'il
n'est pas repris.
"""
from __future__ import annotations

import io
import os
import shlex
import shutil
import tarfile
import time
import zipfile
from typing import Iterator, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from kubernetes import client
from kubernetes.stream import stream as k8s_stream

from .. import schemas
from ..deployment_service import deployment_service
from ..k8s_utils import build_user_namespace, validate_k8s_name
from ..models import User, UserRole
from ..security import get_current_user
from ._helpers import audit_logger, raise_k8s_http
from .k8s_storage import _ensure_pvc_access

router = APIRouter(prefix="/api/v1/k8s", tags=["kubernetes"])

# Pods de base de données : même refus que le terminal web.
_DB_COMPONENT_TYPES = {"mysql", "wordpress", "lamp"}

_PREVIEW_MAX_BYTES = 262_144  # 256 Kio pour l'aperçu texte
_EXEC_TIMEOUT = 30  # secondes
_STREAM_TIMEOUT = 600  # 10 min pour un transfert
_CHUNK_SIZE = 65_536
# Marqueur de fin (avec un octet de contrôle pour ne jamais collisionner avec
# un nom de fichier réellement présent dans le volume).
_EXIT_MARKER = "\x01lod-exit\x01"
# Code de sortie du garde-fou anti-échappement (voir _guarded).
_GUARD_EXIT_CODE = 63

_TEXT_EXTENSIONS = {
    "txt", "md", "markdown", "rst", "log", "csv", "tsv", "json", "jsonl", "xml",
    "yml", "yaml", "toml", "ini", "cfg", "conf", "env", "properties", "sql",
    "py", "java", "kt", "c", "h", "cpp", "hpp", "cs", "go", "rs", "rb", "php",
    "js", "jsx", "ts", "tsx", "vue", "svelte", "sh", "bash", "zsh", "ps1",
    "bat", "dockerfile", "mk", "makefile", "gradle", "html", "htm", "css",
    "scss", "less", "svg", "r", "m", "pl", "lua", "tex", "ipynb", "gitignore",
}
_TEXT_NAMES = {"dockerfile", "makefile", "readme", "license", "changelog", "jenkinsfile"}
_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "avif", "svg"}
_IMAGE_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "ico": "image/x-icon",
    "avif": "image/avif",
    "svg": "image/svg+xml",
}


def _extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _preview_kind(name: str) -> Optional[str]:
    """Type d'aperçu possible pour un fichier (texte, image, ou aucun)."""
    ext = _extension(name)
    if ext in _IMAGE_EXTENSIONS:
        return "image"
    if ext in _TEXT_EXTENSIONS or name.lower() in _TEXT_NAMES:
        return "text"
    return None


def _normalize_path(raw: Optional[str], root: str) -> str:
    """Ramène un chemin dans le volume, refuse toute sortie de la racine."""
    if not raw:
        return root
    if "\x00" in raw:
        raise HTTPException(status_code=400, detail="Chemin invalide")
    path = os.path.normpath(raw)
    if not path.startswith("/"):
        raise HTTPException(status_code=400, detail="Chemin invalide")
    if path != root and not path.startswith(root.rstrip("/") + "/"):
        raise HTTPException(status_code=400, detail="Chemin hors du volume persistant")
    return path


def _validate_entry_name(name: str) -> str:
    """Nom de fichier ou dossier : jamais de séparateur ni de chemin relatif."""
    candidate = (name or "").strip()
    if not candidate or candidate in {".", ".."} or "/" in candidate or "\x00" in candidate:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")
    if len(candidate) > 255:
        raise HTTPException(status_code=400, detail="Nom de fichier trop long")
    return candidate


def _assert_navigable(labels: dict) -> None:
    """Les volumes de base de données restent inaccessibles, comme le terminal."""
    app_type = (labels.get("app-type") or "").lower()
    if labels.get("component") == "database" and app_type in _DB_COMPONENT_TYPES:
        raise HTTPException(status_code=403, detail="Ce volume n'est pas navigable")


def _pod_mounts_pvc(pod: client.V1Pod, pvc_name: str) -> bool:
    for volume in getattr(pod.spec, "volumes", None) or []:
        claim = getattr(volume, "persistent_volume_claim", None)
        if claim is not None and getattr(claim, "claim_name", None) == pvc_name:
            return True
    return False


def _claim_mounts(pod: client.V1Pod) -> Iterator[Tuple[str, str, str]]:
    """``(conteneur, claim, mountPath)`` des volumes persistants du pod.

    Seuls les conteneurs principaux sont pris en compte : un init container
    terminé n'est pas exécutable.
    """
    claims = {
        volume.name: volume.persistent_volume_claim.claim_name
        for volume in getattr(pod.spec, "volumes", None) or []
        if getattr(volume, "persistent_volume_claim", None)
        and getattr(volume.persistent_volume_claim, "claim_name", None)
    }
    for container in getattr(pod.spec, "containers", None) or []:
        for mount in getattr(container, "volume_mounts", None) or []:
            if mount.name in claims:
                yield container.name, claims[mount.name], mount.mount_path


def _browse_mount(pod: client.V1Pod, claim: Optional[str], container_hint: Optional[str]) -> Tuple[str, str]:
    """Retourne ``(conteneur, racine)`` : le ``mountPath`` réel du volume.

    Dérivé du spec du pod au lieu d'une table par type de lab (source de
    vérité unique, pas de dérive possible). ponytail: si un même claim est
    monté plusieurs fois, le premier montage du spec gagne ; le paramètre
    ``pvc`` permet de choisir le volume quand le pod en expose plusieurs.
    """
    mounts = [item for item in _claim_mounts(pod) if not claim or item[1] == claim]
    if container_hint:
        mounts = [item for item in mounts if item[0] == container_hint]
    if not mounts:
        raise HTTPException(
            status_code=400, detail="Ce lab n'expose pas de volume persistant navigable"
        )
    container, _, mount_path = mounts[0]
    return container, mount_path


def _resolve_target(
    namespace: str,
    pod: Optional[str],
    pvc: Optional[str],
    container: Optional[str],
    current_user: User,
) -> Tuple[str, str, str]:
    """Retourne ``(nom_du_pod, conteneur, racine_navigable)`` après contrôle d'accès."""
    namespace = validate_k8s_name(namespace)
    deployment_service._assert_namespace_allowed(namespace, current_user)
    core_v1 = client.CoreV1Api()

    if pod:
        pod = validate_k8s_name(pod)
        try:
            pod_obj = core_v1.read_namespaced_pod(pod, namespace)
        except Exception as e:
            raise_k8s_http(e)
        labels = pod_obj.metadata.labels or {}
        deployment_service._assert_deployment_access(labels, current_user, namespace, pod)
        if (pod_obj.status.phase or "") != "Running":
            raise HTTPException(status_code=409, detail="Le lab n'est pas démarré")
        _assert_navigable(labels)
        return pod, *_browse_mount(pod_obj, pvc, container)

    if not pvc:
        raise HTTPException(status_code=400, detail="Paramètre pod ou pvc requis")

    pvc = validate_k8s_name(pvc)
    try:
        pvc_obj = core_v1.read_namespaced_persistent_volume_claim(pvc, namespace)
    except Exception as e:
        raise_k8s_http(e)
    _ensure_pvc_access(pvc_obj, current_user)

    selector = "managed-by=labondemand"
    if current_user.role != UserRole.admin:
        selector += f",user-id={current_user.id}"
    try:
        pods = core_v1.list_namespaced_pod(namespace, label_selector=selector).items
    except Exception as e:
        raise_k8s_http(e)

    candidates = sorted(
        (p for p in pods if _pod_mounts_pvc(p, pvc)),
        key=lambda p: p.metadata.name,
    )
    running = [p for p in candidates if (p.status.phase or "") == "Running"]
    if not running:
        raise HTTPException(
            status_code=409,
            detail=(
                "Le lab qui utilise ce volume est en pause. Reprenez-le pour parcourir ses fichiers."
                if candidates
                else "Aucun lab en cours n'utilise ce volume. Démarrez un lab pour parcourir ses fichiers."
            ),
        )

    # Un claim peut être monté par plusieurs pods (RWX, composants) : le
    # premier pod *utilisable* dans l'ordre des noms gagne, sans quoi un pod
    # non navigable masquerait un pod valide. Le premier refus est conservé
    # pour rester explicite quand aucun candidat ne convient.
    denied: Optional[HTTPException] = None
    for pod_obj in running:
        labels = pod_obj.metadata.labels or {}
        try:
            _assert_navigable(labels)
            resolved = _browse_mount(pod_obj, pvc, container)
            deployment_service._assert_deployment_access(
                labels, current_user, namespace, pod_obj.metadata.name
            )
        except HTTPException as e:
            denied = denied or e
            continue
        return pod_obj.metadata.name, *resolved
    raise denied or HTTPException(
        status_code=409,
        detail="Aucun lab en cours n'utilise ce volume. Démarrez un lab pour parcourir ses fichiers.",
    )


def _collect_output(response, timeout: int) -> str:
    """Sortie brute d'un exec one-shot, jusqu'à la fermeture du flux.

    On pilote le websocket soi-même au lieu de laisser le client Kubernetes
    tout pré-charger : quand le pair ferme la connexion sans frame CLOSE (cas
    courant en fin d'exec), ce dernier lève une exception et **jette la sortie
    déjà reçue**. Ici on garde ce qui est arrivé.
    """
    data = getattr(response, "data", None)
    if data is not None:  # réponse déjà entièrement pré-chargée
        return str(data)
    deadline = time.monotonic() + timeout
    try:
        while response.is_open() and time.monotonic() < deadline:
            response.update(0.2)
    except Exception:  # flux coupé : la sortie accumulée reste lisible
        pass
    return str(response.read_all())


def _guarded(root: str, paths: Tuple[str, ...], script: str) -> str:
    """Restreint un script aux chemins sous `root`, liens symboliques compris.

    `_normalize_path` ne valide que la forme lexicale : un symlink planté dans
    le volume (l'élève a un shell dans son lab) pointe ailleurs, et `cat`, `>`
    ou un composant intermédiaire de chemin le suivent. `realpath -m` résout
    chaque composante — lien final, intermédiaire ou cassé — avant l'opération.
    ponytail: suppose GNU coreutils, comme `find -printf` plus bas ; une image
    sans `realpath -m` renvoie 400 au lieu de parcourir.
    """
    prologue = [
        f"_lod_root=$(realpath -m -- {shlex.quote(root)}) || exit {_GUARD_EXIT_CODE}"
    ]
    prologue += [
        f"_lod_p=$(realpath -m -- {shlex.quote(path)}) || exit {_GUARD_EXIT_CODE}; "
        f'case "$_lod_p" in "$_lod_root"|"$_lod_root"/*) ;; *) exit {_GUARD_EXIT_CODE} ;; esac'
        for path in paths
    ]
    return "; ".join(prologue) + "; " + script


def _run(
    core_v1: client.CoreV1Api,
    namespace: str,
    pod: str,
    container: Optional[str],
    root: str,
    paths: Tuple[str, ...],
    script: str,
    timeout: int = _EXEC_TIMEOUT,
) -> Tuple[int, str]:
    """Exécute un script shell one-shot et renvoie ``(code_de_sortie, sortie)``."""
    script = _guarded(root, paths, script)
    # Le script tourne dans un sous-shell : un `exit` interne ne court-circuite
    # pas l'écho du code de sortie.
    wrapped = f"( {script} )\nprintf '\\n{_EXIT_MARKER}%s' \"$?\""
    try:
        response = k8s_stream(
            core_v1.connect_get_namespaced_pod_exec,
            pod,
            namespace,
            container=container,
            command=["/bin/sh", "-c", wrapped],
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
            _preload_content=False,
            _request_timeout=timeout,
        )
    except client.exceptions.ApiException as e:
        raise_k8s_http(e)

    text = _collect_output(response, timeout)
    marker_at = text.rfind(_EXIT_MARKER)
    if marker_at == -1:
        raise HTTPException(status_code=502, detail="Réponse inattendue du pod")
    output = text[:marker_at].strip("\n")
    code = text[marker_at + len(_EXIT_MARKER):].strip()
    try:
        parsed = int(code)
    except ValueError:
        raise HTTPException(status_code=502, detail="Réponse inattendue du pod")
    if parsed == _GUARD_EXIT_CODE:
        raise HTTPException(status_code=400, detail="Chemin hors du volume persistant")
    return parsed, output


def _run_ok(
    core_v1: client.CoreV1Api,
    namespace: str,
    pod: str,
    container: Optional[str],
    root: str,
    paths: Tuple[str, ...],
    script: str,
    timeout: int = _EXEC_TIMEOUT,
) -> str:
    code, output = _run(core_v1, namespace, pod, container, root, paths, script, timeout)
    if code != 0:
        raise HTTPException(status_code=422, detail=output or f"Commande refusée (code {code})")
    return output


def _open_stream(
    core_v1: client.CoreV1Api,
    namespace: str,
    pod: str,
    container: Optional[str],
    root: str,
    paths: Tuple[str, ...],
    script: str,
):
    """Ouvre un exec en streaming binaire (stdout non bufferisé)."""
    try:
        return k8s_stream(
            core_v1.connect_get_namespaced_pod_exec,
            pod,
            namespace,
            container=container,
            command=["/bin/sh", "-c", _guarded(root, paths, script)],
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
            _preload_content=False,
            binary=True,
            _request_timeout=_STREAM_TIMEOUT,
        )
    except client.exceptions.ApiException as e:
        raise_k8s_http(e)


def _iter_stream(ws_client) -> Iterator[bytes]:
    sent = False
    try:
        while True:
            try:
                data = ws_client.read_channel(1, timeout=0.5)
            except Exception:
                # Fermeture brutale du pair : après le premier octet envoyé on
                # s'arrête sur le transfert déjà parti, sinon l'erreur remonte.
                if sent:
                    break
                raise
            if data:
                sent = True
                yield data
                continue
            if not ws_client.is_open():
                break
    finally:
        try:
            ws_client.close()
        except Exception:  # pragma: no cover - fermeture best effort
            pass


class _ChunkSink(io.RawIOBase):
    """File-like pour `zipfile` : chaque écriture devient un chunk téléchargeable."""

    def __init__(self) -> None:
        self.pending = bytearray()

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:
        self.pending += data
        return len(data)


class _ChunkReader(io.RawIOBase):
    """File-like en lecture au-dessus de l'itérateur de chunks du flux exec."""

    def __init__(self, source: Iterator[bytes]) -> None:
        self._source = source
        self._buffer = b""

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        while size < 0 or len(self._buffer) < size:
            chunk = next(self._source, None)
            if chunk is None:
                break
            self._buffer += chunk
        if size < 0:
            data, self._buffer = self._buffer, b""
            return data
        data, self._buffer = self._buffer[:size], self._buffer[size:]
        return data


def _zip_date(timestamp: float) -> Tuple[int, int, int, int, int, int]:
    """Date de fichier zip valide (le format ne va ni avant 1980 ni après 2107)."""
    try:
        fields = time.localtime(timestamp)[:6]
        if 1980 <= fields[0] <= 2107:
            return fields
    except (OSError, OverflowError, ValueError):
        pass
    return (1980, 1, 1, 0, 0, 0)


def _tar_to_zip(source: Iterator[bytes]) -> Iterator[bytes]:
    """Rejoue en streaming le tar du pod comme un zip complet.

    Le pod n'a pas forcément `zip` (php, mysql, busybox…) : la conversion se
    fait ici, chunk par chunk, sans tout charger en mémoire. ponytail: les
    liens sont stockés en convention Info-ZIP (mode 0120777) — restaurés par
    `ditto`/`unzip`, vus comme petits fichiers texte sous Windows.
    """
    sink = _ChunkSink()

    def drain() -> Iterator[bytes]:
        while sink.pending:
            chunk = bytes(sink.pending[:_CHUNK_SIZE])
            del sink.pending[:_CHUNK_SIZE]
            yield chunk

    with tarfile.open(fileobj=_ChunkReader(source), mode="r|*") as tar, \
            zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED) as archive:
        for member in tar:
            name = member.name[2:] if member.name.startswith("./") else member.name
            if not name:
                continue
            info = zipfile.ZipInfo(name, date_time=_zip_date(member.mtime))
            info.external_attr = (member.mode & 0xFFFF) << 16
            if member.isdir():
                info.filename = name.rstrip("/") + "/"
                info.external_attr |= 0x10
                archive.writestr(info, b"")
            elif member.issym() or member.islnk():
                info.external_attr = 0o120777 << 16
                archive.writestr(info, member.linkname)
            elif member.isfile():
                content = tar.extractfile(member)
                if content is None:
                    continue
                info.compress_type = zipfile.ZIP_DEFLATED
                info.file_size = member.size
                with content, archive.open(info, "w") as out:
                    shutil.copyfileobj(content, out, _CHUNK_SIZE)
            else:
                continue  # fifo, sockets, périphériques : hors périmètre d'un zip
            yield from drain()
    yield from drain()


def _content_disposition(filename: str, inline: bool = False) -> str:
    ascii_name = "".join(
        char if 32 <= ord(char) < 127 and char not in '"\\' else "_" for char in filename
    )
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _stream_headers(filename: str, inline: bool = False) -> dict:
    return {
        "Content-Disposition": _content_disposition(filename, inline),
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
    }


@router.get("/files", response_model=schemas.VolumeFileList)
def list_files(
    namespace: str,
    pod: Optional[str] = None,
    pvc: Optional[str] = None,
    container: Optional[str] = None,
    path: Optional[str] = None,
    include_hidden: bool = False,
    current_user: User = Depends(get_current_user),
):
    """Lister le contenu d'un dossier du volume persistant."""
    pod_name, container, root = _resolve_target(namespace, pod, pvc, container, current_user)
    target = _normalize_path(path, root)
    core_v1 = client.CoreV1Api()

    # ponytail: `find -printf` suppose findutils GNU (Debian/Ubuntu/Oracle Linux,
    # toutes les images du catalogue). Une image exotique renverra 422, ce qui
    # est visible et diagnosticable ; on ajoutera un fallback si ça arrive.
    script = f"find {shlex.quote(target)} -mindepth 1 -maxdepth 1 -printf '%y\\0%s\\0%T@\\0%f\\0'"
    code, output = _run(core_v1, namespace, pod_name, container, root, (target,), script)
    if code != 0:
        exists_code, exists = _run(
            core_v1, namespace, pod_name, container, root, (target,),
            f"if [ -d {shlex.quote(target)} ]; then echo yes; else echo no; fi",
        )
        if exists.strip() != "yes":
            raise HTTPException(status_code=404, detail="Dossier introuvable")
        raise HTTPException(status_code=422, detail=output or "Lecture impossible")

    fields = output.split("\x00")
    entries: list[schemas.VolumeFileEntry] = []
    for index in range(0, len(fields) - 3, 4):
        raw_type, raw_size, raw_mtime, name = fields[index:index + 4]
        if not name or (name.startswith(".") and not include_hidden):
            continue
        entry_type = {"d": "dir", "f": "file", "l": "link"}.get(raw_type, "other")
        try:
            size = int(raw_size)
        except ValueError:
            size = None
        try:
            modified_at = float(raw_mtime)
        except ValueError:
            modified_at = None
        entries.append(
            schemas.VolumeFileEntry(
                name=name,
                path=f"{target.rstrip('/')}/{name}",
                type=entry_type,
                size=None if entry_type == "dir" else size,
                modified_at=modified_at,
                preview=_preview_kind(name) if entry_type == "file" else None,
            )
        )

    entries.sort(key=lambda item: (item.type != "dir", item.name.lower()))
    return schemas.VolumeFileList(
        root=root,
        path=target,
        parent=None if target == root else os.path.dirname(target),
        entries=entries,
    )


@router.get("/files/download")
def download_file(
    namespace: str,
    path: str,
    pod: Optional[str] = None,
    pvc: Optional[str] = None,
    container: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """Télécharger un fichier, ou un dossier entier en zip."""
    pod_name, container, root = _resolve_target(namespace, pod, pvc, container, current_user)
    target = _normalize_path(path, root)
    core_v1 = client.CoreV1Api()

    kind_code, kind = _run(
        core_v1, namespace, pod_name, container, root, (target,),
        f"if [ -d {shlex.quote(target)} ]; then echo dir; elif [ -e {shlex.quote(target)} ]; then echo file; else echo missing; fi",
    )
    if kind_code != 0:
        raise HTTPException(status_code=422, detail=kind or "Lecture impossible")
    if kind == "missing":
        raise HTTPException(status_code=404, detail="Fichier introuvable")

    if kind == "dir":
        name = f"{os.path.basename(target) or 'volume'}.zip"
        parent = os.path.dirname(target)
        script = f"tar -cf - -C {shlex.quote(parent)} ./{shlex.quote(os.path.basename(target))}"
        headers = _stream_headers(name)
        return StreamingResponse(
            _tar_to_zip(
                _iter_stream(
                    _open_stream(core_v1, namespace, pod_name, container, root, (target,), script)
                )
            ),
            media_type="application/zip",
            headers=headers,
        )

    size_code, size_output = _run(
        core_v1, namespace, pod_name, container, root, (target,), f"stat -c %s {shlex.quote(target)}",
    )
    try:
        size = int(size_output)
    except ValueError:
        size = None
    audit_logger.info(
        "volume_file_downloaded",
        extra={
            "extra_fields": {
                "namespace": namespace,
                "pod": pod_name,
                "path": target,
                "user_id": getattr(current_user, "id", None),
            }
        },
    )
    headers = _stream_headers(os.path.basename(target))
    if size is not None:
        headers["Content-Length"] = str(size)
    script = f"cat -- {shlex.quote(target)}"
    return StreamingResponse(
        _iter_stream(_open_stream(core_v1, namespace, pod_name, container, root, (target,), script)),
        media_type="application/octet-stream",
        headers=headers,
    )


@router.get("/files/preview")
def preview_file(
    namespace: str,
    path: str,
    pod: Optional[str] = None,
    pvc: Optional[str] = None,
    container: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """Aperçu en ligne d'un fichier texte ou image (texte tronqué à 256 Kio)."""
    pod_name, container, root = _resolve_target(namespace, pod, pvc, container, current_user)
    target = _normalize_path(path, root)
    name = os.path.basename(target)
    kind = _preview_kind(name)
    if not kind:
        raise HTTPException(status_code=415, detail="Aperçu non disponible pour ce type de fichier")

    core_v1 = client.CoreV1Api()
    code, output = _run(
        core_v1, namespace, pod_name, container, root, (target,),
        f"if [ -f {shlex.quote(target)} ]; then stat -c %s {shlex.quote(target)}; else echo missing; fi",
    )
    if output == "missing":
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    try:
        size = int(output)
    except ValueError:
        size = 0

    headers = _stream_headers(name, inline=True)
    if kind == "image":
        headers["Content-Type"] = _IMAGE_MIME.get(_extension(name), "application/octet-stream")
        headers["Content-Length"] = str(size)
        script = f"cat -- {shlex.quote(target)}"
        return StreamingResponse(
            _iter_stream(_open_stream(core_v1, namespace, pod_name, container, root, (target,), script)),
            headers=headers,
        )

    truncated = size > _PREVIEW_MAX_BYTES
    headers["X-LabOnDemand-Truncated"] = "1" if truncated else "0"
    headers["Content-Length"] = str(min(size, _PREVIEW_MAX_BYTES))
    # Les fichiers HTML/SVG sont servis en texte brut : jamais exécutés dans
    # l'origine de l'application.
    script = f"head -c {_PREVIEW_MAX_BYTES} -- {shlex.quote(target)}"
    return StreamingResponse(
        _iter_stream(_open_stream(core_v1, namespace, pod_name, container, root, (target,), script)),
        media_type="text/plain; charset=utf-8",
        headers=headers,
    )


@router.post("/files/upload", response_model=schemas.VolumeFileEntry)
def upload_file(
    namespace: str = Form(...),
    path: str = Form(...),
    file: UploadFile = File(...),
    pod: Optional[str] = Form(None),
    pvc: Optional[str] = Form(None),
    container: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
):
    """Déposer un fichier dans un dossier du volume persistant."""
    pod_name, container, root = _resolve_target(namespace, pod, pvc, container, current_user)
    directory = _normalize_path(path, root)
    filename = _validate_entry_name(os.path.basename(file.filename or ""))
    destination = f"{directory.rstrip('/')}/{filename}"
    core_v1 = client.CoreV1Api()

    # Endpoint synchrone (thread du pool) : lecture directe du fichier spoolé,
    # équivalent à `await file.read()` sans passer par la boucle.
    total = file.size
    if total is None:  # pragma: no cover - Starlette fournit toujours .size
        content = file.file.read()
        total = len(content)
        chunks = [content]
    else:
        chunks = None

    try:
        ws_client = k8s_stream(
            core_v1.connect_get_namespaced_pod_exec,
            pod_name,
            namespace,
            container=container,
            # `head -c N` termine tout seul une fois N octets reçus : pas besoin
            # de signaler la fin de stdin (non supporté par le client Python).
            command=[
                "/bin/sh", "-c",
                _guarded(root, (destination,), f"head -c {total} > {shlex.quote(destination)}"),
            ],
            stderr=True,
            stdin=True,
            stdout=True,
            tty=False,
            _preload_content=False,
            binary=True,
            _request_timeout=_STREAM_TIMEOUT,
        )
    except client.exceptions.ApiException as e:
        raise_k8s_http(e)

    errors: bytes | str = b""
    code = 0
    try:
        if chunks is None:
            while True:
                chunk = file.file.read(_CHUNK_SIZE)
                if not chunk:
                    break
                ws_client.write_stdin(chunk)
        else:
            for chunk in chunks:
                ws_client.write_stdin(chunk)

        deadline = time.monotonic() + _EXEC_TIMEOUT
        while ws_client.is_open() and time.monotonic() < deadline:
            ws_client.update(0.2)
        if ws_client.is_open():
            raise HTTPException(status_code=504, detail="Dépôt interrompu (pod injoignable)")
        errors = ws_client.read_all()
        try:
            code = ws_client.returncode or 0
        except Exception:
            # Canal d'erreur vide (fermeture avant le statut) : on tranche plus
            # bas en comparant la taille réellement écrite.
            code = 0
    finally:
        try:
            ws_client.close()
        except Exception:  # pragma: no cover - fermeture best effort
            pass

    detail = errors.decode("utf-8", "replace").strip() if isinstance(errors, bytes) else str(errors)
    if code != 0:
        raise HTTPException(status_code=422, detail=detail or "Dépôt refusé par le pod")

    # Vérification d'intégrité : un dépôt tronqué ne doit jamais passer pour un succès.
    written = _run_ok(
        core_v1, namespace, pod_name, container, root, (destination,), f"stat -c %s {shlex.quote(destination)}",
    )
    try:
        written_size = int(written)
    except ValueError:
        written_size = -1
    if written_size != total:
        raise HTTPException(
            status_code=422,
            detail=detail or f"Dépôt incomplet ({written_size} octets écrits sur {total})",
        )

    audit_logger.info(
        "volume_file_uploaded",
        extra={
            "extra_fields": {
                "namespace": namespace,
                "pod": pod_name,
                "path": destination,
                "bytes": total,
                "user_id": getattr(current_user, "id", None),
            }
        },
    )
    return schemas.VolumeFileEntry(
        name=filename,
        path=destination,
        type="file",
        size=total,
        modified_at=time.time(),
        preview=_preview_kind(filename),
    )


@router.post("/files/mkdir", response_model=schemas.VolumeFileEntry)
def create_directory(
    payload: schemas.VolumeFileCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """Créer un dossier dans le volume persistant."""
    pod_name, container, root = _resolve_target(
        payload.namespace, payload.pod, payload.pvc, payload.container, current_user
    )
    directory = _normalize_path(payload.path, root)
    name = _validate_entry_name(payload.name)
    destination = f"{directory.rstrip('/')}/{name}"
    core_v1 = client.CoreV1Api()

    code, output = _run(
        core_v1, payload.namespace, pod_name, container, root, (destination,),
        f"if [ -e {shlex.quote(destination)} ]; then echo exists; exit 3; fi; mkdir -- {shlex.quote(destination)}",
    )
    if code == 3:
        raise HTTPException(status_code=409, detail="Un élément de ce nom existe déjà")
    if code != 0:
        raise HTTPException(status_code=422, detail=output or "Création impossible")

    audit_logger.info(
        "volume_directory_created",
        extra={
            "extra_fields": {
                "namespace": payload.namespace,
                "pod": pod_name,
                "path": destination,
                "user_id": getattr(current_user, "id", None),
            }
        },
    )
    return schemas.VolumeFileEntry(
        name=name, path=destination, type="dir", size=None, modified_at=time.time()
    )


@router.post("/files/rename", response_model=schemas.VolumeFileEntry)
def rename_entry(
    payload: schemas.VolumeFileRenameRequest,
    current_user: User = Depends(get_current_user),
):
    """Renommer un fichier ou un dossier du volume persistant."""
    pod_name, container, root = _resolve_target(
        payload.namespace, payload.pod, payload.pvc, payload.container, current_user
    )
    source = _normalize_path(payload.path, root)
    if source == root:
        raise HTTPException(status_code=400, detail="La racine du volume ne peut pas être renommée")
    name = _validate_entry_name(payload.new_name)
    destination = f"{os.path.dirname(source).rstrip('/')}/{name}"
    core_v1 = client.CoreV1Api()

    code, output = _run(
        core_v1, payload.namespace, pod_name, container, root, (source, destination),
        f"if [ ! -e {shlex.quote(source)} ]; then echo missing; exit 4; fi; "
        f"if [ -e {shlex.quote(destination)} ]; then echo exists; exit 3; fi; "
        f"mv -- {shlex.quote(source)} {shlex.quote(destination)}",
    )
    if code == 3:
        raise HTTPException(status_code=409, detail="Un élément de ce nom existe déjà")
    if code == 4:
        raise HTTPException(status_code=404, detail="Élément introuvable")
    if code != 0:
        raise HTTPException(status_code=422, detail=output or "Renommage impossible")

    audit_logger.info(
        "volume_entry_renamed",
        extra={
            "extra_fields": {
                "namespace": payload.namespace,
                "pod": pod_name,
                "path": source,
                "new_path": destination,
                "user_id": getattr(current_user, "id", None),
            }
        },
    )
    return schemas.VolumeFileEntry(
        name=name, path=destination, type="other", size=None, modified_at=time.time()
    )


@router.delete("/files")
def delete_entry(
    namespace: str,
    path: str,
    pod: Optional[str] = None,
    pvc: Optional[str] = None,
    container: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """Supprimer un fichier ou un dossier du volume persistant."""
    pod_name, container, root = _resolve_target(namespace, pod, pvc, container, current_user)
    target = _normalize_path(path, root)
    if target == root:
        raise HTTPException(status_code=400, detail="La racine du volume ne peut pas être supprimée")
    core_v1 = client.CoreV1Api()

    code, output = _run(
        core_v1, namespace, pod_name, container, root, (target,),
        f"if [ ! -e {shlex.quote(target)} ]; then echo missing; exit 4; fi; rm -rf -- {shlex.quote(target)}",
    )
    if code == 4:
        raise HTTPException(status_code=404, detail="Élément introuvable")
    if code != 0:
        raise HTTPException(status_code=422, detail=output or "Suppression impossible")

    audit_logger.info(
        "volume_entry_deleted",
        extra={
            "extra_fields": {
                "namespace": namespace,
                "pod": pod_name,
                "path": target,
                "user_id": getattr(current_user, "id", None),
            }
        },
    )
    return {"message": f"{os.path.basename(target)} supprimé", "path": target}
