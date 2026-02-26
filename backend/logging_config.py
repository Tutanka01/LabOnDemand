"""
Logging configuration for LabOnDemand backend.
Provides structured JSON logs and correlation helpers.
"""

from __future__ import annotations

import contextvars
import json
import logging
import logging.config
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .config import settings

_request_id_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "labondemand_request_id", default=None
)
_configured = False


def get_request_id() -> Optional[str]:
    """Return the current request identifier if any."""
    return _request_id_ctx.get()


def set_request_id(request_id: str) -> contextvars.Token:
    """Bind the request identifier into the context and return the token."""
    return _request_id_ctx.set(request_id)


def reset_request_id(token: contextvars.Token) -> None:
    """Reset the request identifier using the provided token."""
    try:
        _request_id_ctx.reset(token)
    except Exception:
        # Silently ignore reset errors; logging must not fail request processing.
        pass


def shorten_token(token: Optional[str], visible: int = 8) -> Optional[str]:
    """Return a shortened preview of a sensitive token for logging purposes."""
    if not token:
        return None
    if len(token) <= visible:
        return token
    return f"{token[:visible]}..."


class JsonFormatter(logging.Formatter):
    """Formatter that emits structured JSON logs."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        if timestamp.endswith("+00:00"):
            timestamp = timestamp[:-6] + "Z"

        payload: Dict[str, Any] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = record.stack_info

        extra_fields = getattr(record, "extra_fields", None)
        if isinstance(extra_fields, dict):
            try:
                payload.update(extra_fields)
            except Exception:
                payload["extra_fields_error"] = "unserializable"

        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def setup_logging() -> None:
    """Configure application-wide logging once."""
    global _configured
    if _configured:
        return

    log_dir = Path(settings.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Ensure log files exist so tailing agents pick them up even before first entry
    for fname in ("app.log", "audit.log", "access.log"):
        path = log_dir / fname
        if not path.exists():
            path.touch()

    root_handlers: list[str] = ["app_file"]
    handlers: Dict[str, Dict[str, Any]] = {
        "app_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "json",
            "filename": str(log_dir / "app.log"),
            "maxBytes": settings.LOG_MAX_BYTES,
            "backupCount": settings.LOG_BACKUP_COUNT,
            "encoding": "utf-8",
        },
        "audit_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "json",
            "filename": str(log_dir / "audit.log"),
            "maxBytes": settings.AUDIT_LOG_MAX_BYTES,
            "backupCount": settings.AUDIT_LOG_BACKUP_COUNT,
            "encoding": "utf-8",
        },
        "access_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "json",
            "filename": str(log_dir / "access.log"),
            "maxBytes": settings.LOG_MAX_BYTES,
            "backupCount": settings.LOG_BACKUP_COUNT,
            "encoding": "utf-8",
        },
    }

    if settings.LOG_ENABLE_CONSOLE:
        handlers["console"] = {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "level": settings.LOG_LEVEL,
        }
        root_handlers.append("console")

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                "datefmt": "%Y-%m-%dT%H:%M:%S",
            },
            "json": {
                "()": "backend.logging_config.JsonFormatter",
            },
        },
        "handlers": handlers,
        "loggers": {
            "labondemand": {
                "level": settings.LOG_LEVEL,
                "propagate": True,
            },
            "labondemand.audit": {
                "level": "INFO",
                "handlers": ["audit_file"]
                + (["console"] if settings.LOG_ENABLE_CONSOLE else []),
                "propagate": False,
            },
            "labondemand.access": {
                "level": "INFO",
                "handlers": ["access_file"]
                + (["console"] if settings.LOG_ENABLE_CONSOLE else []),
                "propagate": False,
            },
            "uvicorn.error": {
                "level": settings.LOG_LEVEL,
                "handlers": root_handlers,
                "propagate": False,
            },
            "uvicorn.access": {
                "level": "INFO",
                "handlers": ["access_file"]
                + (["console"] if settings.LOG_ENABLE_CONSOLE else []),
                "propagate": False,
            },
        },
        "root": {
            "level": settings.LOG_LEVEL,
            "handlers": root_handlers,
        },
    }

    logging.config.dictConfig(logging_config)
    logging.captureWarnings(True)

    logging.getLogger("labondemand").info(
        "logging_initialized",
        extra={
            "extra_fields": {
                "log_dir": str(log_dir),
                "level": settings.LOG_LEVEL,
                "max_bytes": settings.LOG_MAX_BYTES,
                "backup_count": settings.LOG_BACKUP_COUNT,
                "audit_max_bytes": settings.AUDIT_LOG_MAX_BYTES,
                "audit_backup_count": settings.AUDIT_LOG_BACKUP_COUNT,
                "console_enabled": settings.LOG_ENABLE_CONSOLE,
            }
        },
    )

    _configured = True


__all__ = [
    "get_request_id",
    "set_request_id",
    "reset_request_id",
    "setup_logging",
    "shorten_token",
]
