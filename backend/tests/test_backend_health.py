"""Backend health must not depend on an optional export package.

Regression for ``ModuleNotFoundError: No module named 'reportlab'`` raised from ``app/api/report_pdf.py``: the status endpoint imported the PDF
module only to ask whether PDFs are possible, so an environment without ReportLab (created before it was added to requirements.txt) answered
/status with a server error and the app showed "Backend offline". ReportLab is made unimportable here exactly the way a missing package is —
``import reportlab`` raises ``ModuleNotFoundError: No module named 'reportlab'`` — without touching the real installation.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_report_export import AUTO, _download, _export, _research

import app.api as api_pkg
from app.api import pdf_support
from app.config import Settings, validate_configuration
from app.testing.fixtures import FixtureNetwork, verified_site

BACKEND = Path(__file__).resolve().parents[1]


class _MissingPackage:
    """A meta-path finder that behaves as if the named top-level packages were not installed."""

    def __init__(self, *names: str) -> None:
        self.names = set(names)

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> None:
        top = fullname.split(".")[0]
        if top in self.names:
            raise ModuleNotFoundError(f"No module named '{top}'", name=top)
        return None


@pytest.fixture
def without_reportlab(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [m for m in sys.modules if m == "reportlab" or m.startswith("reportlab.") or m == "app.api.report_pdf"]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.delattr(api_pkg, "report_pdf", raising=False)  # `from . import report_pdf` would otherwise reuse the loaded attribute
    monkeypatch.setattr(sys, "meta_path", [_MissingPackage("reportlab"), *sys.meta_path])


@pytest.fixture
def app_client(net: FixtureNetwork, settings: Settings):  # noqa: ANN201
    from app.api.main import create_app
    from app.api.services import Services
    from app.providers.fake_provider import FakeProvider
    from app.storage.db import Database

    net.add_site("autobjorn.no", verified_site("AUTOBJØRN A/S", AUTO, jobs=["Bilselger"]))
    svc = Services(settings, db=Database(":memory:"), transport=net.transport(), provider=FakeProvider(), use_provider=True)
    with TestClient(create_app(svc)) as client:
        yield client


# ------------------------------------------------------------------------------------------------------------ the original failure --
def test_the_original_failure_is_reproduced_by_the_missing_package(without_reportlab: None) -> None:
    with pytest.raises(ModuleNotFoundError, match="No module named 'reportlab'"):
        importlib.import_module("app.api.report_pdf")


# --------------------------------------------------------------------------------------------------- status without ReportLab --
def test_status_and_health_answer_without_reportlab_and_say_why_pdf_is_off(without_reportlab: None, app_client: TestClient) -> None:
    health = app_client.get("/api/health")
    assert health.status_code == 200 and health.json()["status"] == "ok"
    res = app_client.get("/api/status")
    assert res.status_code == 200, res.text  # was a 500, which the app showed as "Backend offline"
    status = res.json()
    assert status["backend"] == "connected" and status["research"] == "online"
    caps = status["capabilities"]
    assert caps["pdfReports"] is False and "report" not in caps["exportKinds"] and "pdf" not in caps["exports"]
    assert "evidence" in caps["exportKinds"] and "csv" in caps["exports"]  # the other exports are unaffected
    assert "'reportlab'" in caps["pdfReportsNote"] and "pip install -r requirements.txt" in caps["pdfReportsNote"]
    assert "app.api.report_pdf" not in sys.modules  # answering never even tried to import the PDF module


def test_the_evidence_export_works_and_the_pdf_export_explains_itself_without_reportlab(without_reportlab: None, app_client: TestClient) -> None:
    _research(app_client)
    evidence = _export(app_client, "evidence", "csv")
    assert evidence["status"] == "ready"  # used to fail too: the export imported the PDF module for every kind
    assert _download(app_client, evidence).decode("utf-8-sig").startswith("org_number")
    pdf = _export(app_client, "report", "pdf")
    assert pdf["status"] == "failed" and "'reportlab'" in pdf["message"] and "requirements.txt" in pdf["message"]


def test_a_missing_pdf_dependency_is_a_startup_warning_not_a_crash(without_reportlab: None, settings: Settings) -> None:
    warnings = validate_configuration(settings)
    assert any("'reportlab'" in w and "Full Research Report (PDF)" in w for w in warnings)


def test_the_check_names_every_missing_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "meta_path", [_MissingPackage("reportlab", "PIL"), *sys.meta_path])
    for name in [m for m in sys.modules if m.split(".")[0] in ("reportlab", "PIL")]:
        monkeypatch.delitem(sys.modules, name)
    status = pdf_support.pdf_status()
    assert status["available"] is False and status["missing"] == ["reportlab", "pillow"]
    assert "'reportlab', 'pillow' are not installed" in str(status["reason"])


# ------------------------------------------------------------------------------------------------------------- the dependencies --
def test_every_package_the_pdf_module_imports_is_checked_and_pinned_in_requirements() -> None:
    third_party = {m for m in pdf_support.report_module_imports() if m not in sys.stdlib_module_names and m not in ("__future__", "app")}
    assert third_party and third_party <= set(pdf_support.REQUIRED_MODULES)
    pins = {}
    for line in (BACKEND / "requirements.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)==([0-9][^\s#]*)", line.strip())
        if m:
            pins[m.group(1).lower()] = m.group(2)
    for dist in pdf_support.REQUIRED_MODULES.values():
        assert dist in pins, f"{dist} must be pinned in requirements.txt"
    dev = (BACKEND / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "-r requirements.txt" in dev  # the development install includes the runtime packages


def test_this_environment_has_the_pdf_dependencies_and_a_real_pdf_is_produced(app_client: TestClient) -> None:
    assert pdf_support.missing_packages() == [] and pdf_support.pdf_available()
    status = app_client.get("/api/status").json()
    assert status["capabilities"]["pdfReports"] is True and "pdfReportsNote" not in status["capabilities"]
    _research(app_client)
    data = _download(app_client, _export(app_client, "report", "pdf"))
    assert data.startswith(b"%PDF-") and len(data) > 10_000
