"""Can this installation produce the Full Research Report (PDF)? Answered WITHOUT importing ReportLab.

The status endpoint, the startup checks and the export menu ask this question. Importing ``report_pdf`` to answer it would make them fail with
``ModuleNotFoundError`` on an installation where ReportLab is missing (an environment created before it was added to requirements.txt), and the
whole backend would then look offline. Here the packages are only *located* (``importlib.util.find_spec``), so a missing optional export
dependency turns PDF export off with a precise reason while everything else keeps working.
"""
from __future__ import annotations

import ast
import importlib.util
from functools import lru_cache
from pathlib import Path

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONT_FILES = {"Cognis": "LiberationSans-Regular.ttf", "Cognis-Bold": "LiberationSans-Bold.ttf", "Cognis-Italic": "LiberationSans-Italic.ttf",
              "Cognis-BoldItalic": "LiberationSans-BoldItalic.ttf", "CognisSerif-Bold": "LiberationSerif-Bold.ttf"}
# import name → the requirements.txt distribution that provides it (ReportLab needs Pillow and charset-normalizer at run time)
REQUIRED_MODULES = {"reportlab": "reportlab", "PIL": "pillow", "charset_normalizer": "charset-normalizer"}
INSTALL_HINT = "Run `python -m pip install -r requirements.txt` in the backend folder (with its virtual environment active) and restart the backend."


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):  # a broken or half-removed package
        return False


def missing_packages() -> list[str]:
    """The requirements.txt packages the PDF report needs that this Python environment does not have."""
    return [dist for module, dist in REQUIRED_MODULES.items() if not _installed(module)]


def fonts_available() -> bool:
    return all((FONT_DIR / f).is_file() for f in FONT_FILES.values())


def pdf_status() -> dict[str, object]:
    """``{"available": bool, "reason": str | None, "missing": [...]}`` — the reason says exactly what is missing and how to fix it."""
    missing = missing_packages()
    if missing:
        names = ", ".join(f"'{m}'" for m in missing)
        plural = "s" if len(missing) > 1 else ""
        return {"available": False, "missing": missing,
                "reason": f"PDF reports are turned off: the Python package{plural} {names} {'are' if plural else 'is'} not installed in this backend environment. {INSTALL_HINT}"}
    if not fonts_available():
        return {"available": False, "missing": [],
                "reason": f"PDF reports are turned off: the report fonts are missing from {FONT_DIR}. Re-install the backend files (restore backend/app/assets/fonts)."}
    return {"available": True, "missing": [], "reason": None}


def pdf_available() -> bool:
    return bool(pdf_status()["available"])


@lru_cache(maxsize=1)
def report_module_imports() -> frozenset[str]:
    """Top-level third-party packages ``report_pdf`` imports (read from its source, not by importing it). Tests use this to make sure every one of
    them is checked above, so the check can never fall behind the module."""
    tree = ast.parse((Path(__file__).with_name("report_pdf.py")).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return frozenset(names)
