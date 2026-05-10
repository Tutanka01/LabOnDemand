"""
i18n léger pour LabOnDemand.
Charge les fichiers JSON depuis backend/translations/{fr,en}.json.
Expose t(key, locale, **vars) et get_locale(request).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

logger = logging.getLogger("labondemand.i18n")

_TRANSLATIONS_DIR = Path(__file__).parent / "translations"
_DEFAULT_LOCALE = "fr"
_SUPPORTED = ("fr", "en")

TRANSLATIONS: dict[str, dict[str, str]] = {}


def _load() -> None:
    for lang in _SUPPORTED:
        path = _TRANSLATIONS_DIR / f"{lang}.json"
        if path.exists():
            try:
                TRANSLATIONS[lang] = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("i18n_load_failed", extra={"extra_fields": {"lang": lang, "error": str(exc)}})
        else:
            TRANSLATIONS[lang] = {}
            logger.warning("i18n_file_missing", extra={"extra_fields": {"path": str(path)}})


_load()


def get_locale(request: Request) -> str:
    lang = request.query_params.get("lang")
    if lang and lang in _SUPPORTED:
        return lang
    cookie_lang = request.cookies.get("lang")
    if cookie_lang and cookie_lang in _SUPPORTED:
        return cookie_lang
    accept = request.headers.get("Accept-Language", "")
    for part in accept.split(","):
        code = part.strip().split(";")[0].split("-")[0].lower()
        if code in _SUPPORTED:
            return code
    return _DEFAULT_LOCALE


def t(key: str, locale: str = _DEFAULT_LOCALE, **vars: Any) -> str:
    msg = TRANSLATIONS.get(locale, {}).get(key)
    if msg is None:
        msg = TRANSLATIONS.get(_DEFAULT_LOCALE, {}).get(key)
    if msg is None:
        return key
    for k, v in vars.items():
        msg = msg.replace(f"{{{k}}}", str(v))
    return msg


def http_error(request: Request, status_code: int, key: str, **vars: Any) -> HTTPException:
    locale = get_locale(request)
    return HTTPException(status_code=status_code, detail=t(key, locale, **vars))
