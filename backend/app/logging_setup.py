"""Structured JSON logging with secret redaction.

Every record is one JSON object. Context (run_id, organisation number,
connector …) is passed through ``extra={"ctx": {...}}`` or via ``log_event``.
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

from .core.util import now_iso
from .security.redaction import redact

_CONFIGURED = False


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": now_iso(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        ctx = getattr(record, "ctx", None)
        if isinstance(ctx, dict):
            for key, value in ctx.items():
                payload[key] = redact(value) if isinstance(value, str) else value
        if record.exc_info:
            payload["error"] = redact(self.formatException(record.exc_info).splitlines()[-1])
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", *, quiet: bool = False) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("cognis")
    root.handlers[:] = [handler]
    root.setLevel(logging.WARNING if quiet else getattr(logging, level.upper(), logging.INFO))
    root.propagate = False
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"cognis.{name}")


def log_event(logger: logging.Logger, msg: str, level: int = logging.INFO, **ctx: Any) -> None:
    logger.log(level, msg, extra={"ctx": ctx})
