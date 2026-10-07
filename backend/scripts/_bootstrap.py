"""Shared CLI bootstrap: import path, logging, configuration check."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def bootstrap(*, quiet: bool = False) -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles/pipes default to a legacy code page
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    from app.config import ConfigurationError, get_settings, validate_configuration
    from app.logging_setup import configure_logging

    configure_logging(quiet=quiet)
    try:
        for warning in validate_configuration(get_settings()):
            print(f"[config] {warning}", file=sys.stderr)
    except ConfigurationError as exc:
        print(f"[config] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
