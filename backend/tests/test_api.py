"""Frontend contract (API_CONTRACT.md) against the offline network."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.testing.fixtures import verified_site

AUTO = "810359862"


@pytest.fixture
def client(net, settings):  # noqa: ANN001, ANN201
    from app.api.main import create_app
    from app.api.services import Services
    from app.providers.fake_provider import FakeProvider
    from app.storage.db import Database

    net.add_site("autobjorn.no", verified_site("AUTOBJØRN A/S", AUTO, jobs=["Bilselger", "Mekaniker"]))
    svc = Services(settings, db=Database(":memory:"), transport=net.transport(), provider=FakeProvider(), use_provider=True)
    with TestClient(create_app(svc)) as c:
        yield c


def _run(client: TestClient, body: dict) -> tuple[dict, list[dict]]:  # noqa: ANN001
    run = client.post("/api/research/runs", json=body).json()
    events = []
    with client.stream("GET", f"/api/research/runs/{run['id']}/events?lastSeq=0") as stream:
        for line in stream.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
                if events[-1]["type"] in ("run.completed", "run.failed"):
                    break
    return run, events


def test_status_and_errors(client: TestClient) -> None:
    st = client.get("/api/status").json()
    assert st["mode"] == "live" and st["capabilities"]["discoverFilters"]
    r = client.get("/api/companies/123")
    assert r.status_code == 400 and r.json()["code"] == "invalid"
    r = client.get("/api/companies/923609016")
    assert r.status_code == 404 and r.json() == {"code": "not_found", "message": r.json()["message"]}


def test_profile_registry_then_research(client: TestClient) -> None:
    p = client.get(f"/api/companies/{AUTO}").json()
    assert p["company"]["researchState"] == "not_researched" and p["website"]["status"] == "pending"
    assert p["financials"]["series"] and p["identity"]["legalName"]["evidence"]
    run, events = _run(client, {"query": AUTO, "mode": "quick"})
    types = [e["type"] for e in events]
    assert types[0] == "run.started" and types[-1] == "run.completed"
    assert [e["seq"] for e in events] == sorted({e["seq"] for e in events})
    started = {e["stepId"] for e in events if e["type"] == "step.started"}
    assert started == {s["id"] for s in run["plan"]["steps"]}  # every planned step reports, nothing invented
    assert any(e["type"] == "fact.confirmed" for e in events)
    done = events[-1]
    assert done["artifactId"] == f"art-{AUTO}" and done["summary"]["factsVerified"] > 0
    p = client.get(f"/api/companies/{AUTO}").json()
    assert p["company"]["researchState"] == "researched" and p["website"]["status"] == "available" and p["hiring"]["totalCurrent"] == 2
    replay = []
    with client.stream("GET", f"/api/research/runs/{run['id']}/events?lastSeq={events[-3]['seq']}") as stream:
        for line in stream.iter_lines():
            if line.startswith("data: "):
                replay.append(json.loads(line[6:]))
    assert [e["seq"] for e in replay] == [e["seq"] for e in events[-2:]]


def test_deep_run_requires_confirmation(client: TestClient) -> None:
    run = client.post("/api/research/runs", json={"query": AUTO, "mode": "deep"}).json()
    assert run["status"] == "awaiting_confirmation" and run["plan"]["requiresConfirmation"]
    keys = [s["key"] for s in run["plan"]["steps"] if s["key"] != "filings"]
    confirmed = client.post(f"/api/research/runs/{run['id']}/confirm", json={"stepKeys": keys}).json()
    assert confirmed["status"] == "running" and "filings" not in [s["key"] for s in confirmed["plan"]["steps"]]


def test_brief_explain_ask_compare_library(client: TestClient) -> None:
    _run(client, {"query": AUTO, "mode": "quick"})
    brief = client.get(f"/api/companies/{AUTO}/brief").json()
    assert {s["id"] for s in brief["sections"]} == {"what", "scale", "financials", "leadership", "locations", "hiring", "changes"}
    ex = client.post(f"/api/companies/{AUTO}/explain", json={"subject": {"kind": "metric", "metric": "revenue", "fromPeriod": "FY2024", "toPeriod": "FY2025"}}).json()
    assert ex["observed"] and ex["origin"] == "saved_evidence"
    ans = client.post("/api/research/ask", json={"orgNumber": AUTO, "question": "Who is the CEO?", "fresh": False}).json()
    assert ans["blocks"] and all(b["citations"] for b in ans["blocks"])
    cmp_ = client.get(f"/api/compare?orgs={AUTO},810363142").json()
    assert [r["key"] for r in cmp_["summary"]] == ["revenue", "employees", "hiring", "locations", "filing"] and len(cmp_["companies"]) == 2
    lib = client.get("/api/library").json()
    assert lib["facets"]["company"] >= 1 and lib["items"][0]["type"] == "company"
    art = client.get(f"/api/library/art-{AUTO}").json()
    assert art["versions"][0]["isCurrent"] and art["profile"]["company"]["orgNumber"] == AUTO
    assert client.get("/api/library/by-org/810363142").json() is None
    patched = client.patch(f"/api/library/art-{AUTO}", json={"tags": ["prospect"], "pinned": True}).json()
    assert patched["tags"] == ["prospect"] and patched["pinned"]
    report = client.post("/api/reports", json={"orgNumber": AUTO, "kind": "company_brief", "sections": ["summary"]}).json()
    assert client.get(f"/api/library/{report['id']}").json()["type"] == "report"


def test_sheet_with_ai_column(client: TestClient) -> None:
    sheet = client.post("/api/sheets", json={"title": "Autos", "criteria": [], "text": "AUTOBJ"}).json()
    assert sheet["rowCount"] >= 1
    preview = client.post(f"/api/sheets/{sheet['id']}/columns/preview", json={"instruction": "Who is the CEO?"}).json()
    assert preview["supported"] and preview["valueType"] == "person"
    unsupported = client.post(f"/api/sheets/{sheet['id']}/columns/preview", json={"instruction": "Their ESG score"}).json()
    assert not unsupported["supported"]
    col = client.post(f"/api/sheets/{sheet['id']}/columns", json={"instruction": "Who is the CEO?"}).json()
    client.post(f"/api/sheets/{sheet['id']}/research", json={"columnIds": [col["id"]]})
    last = None
    with client.stream("GET", f"/api/sheets/{sheet['id']}/events") as stream:
        for line in stream.iter_lines():
            if line.startswith("data: "):
                last = json.loads(line[6:])
                if last["type"] == "batch.completed":
                    break
    assert last and last["batch"]["done"] >= 1
    data = client.get(f"/api/sheets/{sheet['id']}").json()
    cell = data["rows"][0]["cells"][col["id"]]
    assert cell["status"] == "verified" and cell["evidence"] and "field" not in data["columns"][-1]


def test_exports_and_watchlist(client: TestClient) -> None:
    _run(client, {"query": AUTO, "mode": "quick"})
    for fmt in ("csv", "json", "xlsx"):
        res = client.post("/api/exports", json={"target": {"type": "company", "id": AUTO}, "format": fmt,
                                                 "options": {"sourceLinks": True, "evidence": True, "retrievalDates": True, "reportingPeriods": True, "changes": True}}).json()
        assert res["status"] == "ready"
        assert client.get(res["url"]).status_code == 200
    wl = client.post("/api/watchlist/items", json={"orgNumber": AUTO}).json()
    assert wl["items"][0]["company"]["orgNumber"] == AUTO
    assert client.post("/api/watchlist/checked").json()["changedCount"] == 0


def test_competition_endpoint_returns_contract_envelope(client: TestClient) -> None:
    env = client.post("/api/research/company", json={"organisation_number": AUTO}).json()
    assert env["organisation_number"] == AUTO and env["run"]["terminal_status"] == "completed"
    assert any(c["field"] == "official_website" and c["availability"] == "available" for c in env["claims"])
