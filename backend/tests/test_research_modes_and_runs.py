"""Quick vs Deep, live progress, source failures and run history.

Deterministic: the fixture network and the fake language model stand in for every outside service, so these tests prove what the code does, not what
a live site happens to return.
"""
from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from conftest import run
from fastapi.testclient import TestClient

from app.agent import crosscheck
from app.agent.focus import focus_kinds
from app.agent.orchestrator import Orchestrator, ResearchOptions
from app.api.research_runs import STEP_DEFS, Run, RunManager, judge_outcome, plan_for
from app.core.util import now_iso
from app.evidence.gate import publish
from app.evidence.models import Observation
from app.extraction.html import parse_html
from app.net.http import HttpClient
from app.providers.fake_provider import FakeProvider
from app.runtime.budgets import BudgetLimits, RunBudget
from app.storage import run_history
from app.testing.fixtures import company_page, verified_site

AUTO = "810359862"
NAME = "AUTOBJØRN A/S"
ACCOUNT_COPIES = "/aarsregnskap/kopi/"


def rich_site(name: str = NAME, org: str = AUTO) -> dict[str, str]:
    """A company site with more pages than a Quick run reads: team, products, locations, investors and sustainability on top of the usual ones."""
    pages = verified_site(name, org, jobs=["Bilselger", "Mekaniker"])
    extra = [("/team", "Team"), ("/produkter", "Produkter"), ("/kontorer", "Kontorer"), ("/investor", "Investor relations"), ("/baerekraft", "Bærekraft")]
    anchors = "".join(f'<a href="{href}">{text}</a>' for href, text in extra)
    pages = {path: html.replace("<nav>", "<nav>" + anchors, 1) for path, html in pages.items()}
    footer = f"{name} · Org.nr. {org}"
    for path, title, body in (("/team", "Team", "Ledelsen i selskapet består av erfarne fagfolk."), ("/produkter", "Produkter", "Vi selger og vedlikeholder biler for private og bedrifter."),
                              ("/kontorer", "Kontorer", "Vi har kontorer i Oslo og Bergen."), ("/investor", "Investor relations", "Informasjon til investorer og långivere."),
                              ("/baerekraft", "Bærekraft", "Vi kutter utslipp fra egen drift hvert år og rapporterer åpent om fremdriften.")):
        pages[path] = company_page(f"{title} – {name}", f"<h1>{title}</h1><p>{body}</p>", footer=footer, links=[("/om-oss", "Om oss")] + extra)
    return pages


async def orchestrate(net: Any, *, mode: str, focus: str | None = None, provider: Any = None, step_keys: list[str] | None = None, events: list | None = None) -> dict[str, Any]:
    async with HttpClient(transport=net.transport(), sleep=lambda _s: asyncio.sleep(0)) as http:
        orch = Orchestrator(http=http, run_budget=RunBudget(BudgetLimits(max_requests=500)), provider=provider)
        sink = (lambda kind, data: events.append((kind, data))) if events is not None else None
        return await orch.research(AUTO, run_id="t", options=ResearchOptions(mode=mode, include_geo=False, focus=focus, step_keys=step_keys), on_event=sink)


def workflows(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {w["key"]: w for w in record["effort"]["workflows"]}


# ---------------------------------------------------------------------------------------------------------------- Quick vs Deep --
def test_deep_runs_the_additional_workflows_that_quick_does_not(net) -> None:  # noqa: ANN001
    net.add_site("autobjorn.no", rich_site())
    quick = run(orchestrate(net, mode="quick", provider=FakeProvider()))
    quick_requests = list(net.requests)
    net.requests.clear()
    deep = run(orchestrate(net, mode="deep", provider=FakeProvider()))
    deep_requests = list(net.requests)

    # What was asked of the outside world differs: the multi-year filing history is requested by Deep only.
    assert not any(ACCOUNT_COPIES in u for u in quick_requests)
    assert any(ACCOUNT_COPIES in u for u in deep_requests)
    assert len(deep_requests) > len(quick_requests)

    q, d = workflows(quick), workflows(deep)
    assert q["filings"]["status"] == "skipped" and "Deep" in q["filings"]["detail"]
    assert d["filings"]["status"] == "ran"
    assert q["crosscheck"]["status"] == "skipped" and d["crosscheck"]["status"] == "ran"
    assert q["extract"]["status"] == "skipped" and d["extract"]["status"] == "ran"
    assert q["site_search"]["status"] == "skipped" and "Quick" in q["site_search"]["detail"]
    assert q["press"]["status"] == "skipped" and "Quick" in q["press"]["detail"]
    # Deep reads more of the company's own site than Quick does.
    assert deep["effort"]["pagesRead"] > quick["effort"]["pagesRead"]
    assert deep["effort"]["requests"] > quick["effort"]["requests"]
    # Quick stayed lean: one language-model call at most, no cross-check object.
    assert quick["effort"]["llmCalls"] <= 1 and quick["effort"]["crosscheck"] is None
    assert deep["effort"]["crosscheck"]["checked"] > 0


def test_press_search_explains_why_it_did_not_run_when_search_is_not_configured(net) -> None:  # noqa: ANN001
    net.add_site("autobjorn.no", rich_site())
    deep = run(orchestrate(net, mode="deep", provider=FakeProvider()))
    press = workflows(deep)["press"]
    assert press["status"] == "skipped" and "TAVILY_API_KEY" in press["detail"]  # visible, instead of silently looking like a thinner run
    site_search = workflows(deep)["site_search"]
    assert site_search["status"] == "skipped"  # the register-listed or derived site verified, so no search was needed


def test_deep_follow_up_reads_the_pages_about_the_question_first_and_quick_ignores_it(net) -> None:  # noqa: ANN001
    net.add_site("autobjorn.no", rich_site())
    question = "What are their sustainability initiatives?"
    assert focus_kinds(question) == ["sustainability"] and focus_kinds("Company brief") == [] and focus_kinds(None) == []

    def followed(record: dict[str, Any]) -> list[str]:
        return [t["kind"] for t in record["trace"] if t.get("tool") == "fetch_page"]

    plain = run(orchestrate(net, mode="deep"))
    guided = run(orchestrate(net, mode="deep", focus=question))
    quick = run(orchestrate(net, mode="quick", focus=question))
    assert "sustainability" not in followed(plain)  # not one of the generic follow-up kinds
    assert followed(guided)[0] == "sustainability"  # the page the question is about is read first
    assert "sustainability" not in followed(quick)  # Quick keeps its fixed, lean rule
    assert "your focus" in workflows(guided)["followup"]["detail"]
    assert guided["effort"]["pagesRead"] > plain["effort"]["pagesRead"]


def test_cross_check_reports_the_agreement_between_sources_and_never_changes_the_facts(net) -> None:  # noqa: ANN001
    net.add_site("autobjorn.no", rich_site())
    with_check = run(orchestrate(net, mode="deep"))
    keys = [k for k in STEP_DEFS if k not in ("crosscheck", "extract")]
    without = run(orchestrate(net, mode="deep", step_keys=keys + ["geo"]))
    facts = lambda r: sorted((c["key"], json.dumps(c["value"], sort_keys=True)) for c in r["claims"])  # noqa: E731
    assert facts(with_check) == facts(without)  # reporting agreement adds, removes and upgrades nothing
    assert workflows(without)["crosscheck"]["status"] == "skipped"
    cc = with_check["effort"]["crosscheck"]
    assert cc["checked"] == cc["corroborated"] + cc["singleSource"] + cc["conflicts"]
    assert cc["checked"] > 0


def _obs(field: str, value: Any, source_id: str, source_class: str, name: str) -> Observation:
    return Observation(field=field, value=value, module=source_id, source_id=source_id, source_name=name, source_class=source_class, source_url=f"https://{source_id}.example/",
                       retrieved_at=now_iso(), content_sha256=None, claim_span=str(value), extraction_method="json_field", identity_score=1.0)


def test_cross_check_counts_confirmations_single_sources_and_disagreements() -> None:
    claims, _ = publish([
        _obs("official_website", "https://auto.no", "brreg", "official_registry_live", "Enhetsregisteret"),
        _obs("official_website", "https://auto.no", "site", "company_owned", "Company website"),  # a second, independent source agrees
        _obs("industry_label", "Detaljhandel med biler", "brreg", "official_registry_live", "Enhetsregisteret"),  # single source
        _obs("legal_name", "Autobjørn AS", "brreg", "official_registry_live", "Enhetsregisteret"),
        _obs("legal_name", "Auto Bjørn AS", "site", "company_owned", "Company website"),  # the sources disagree
    ], AUTO)
    cc = crosscheck.analyse(claims)
    assert (cc["checked"], cc["corroborated"], cc["singleSource"], cc["conflicts"]) == (3, 1, 1, 1)
    assert cc["conflictFacts"][0]["field"] == "legal_name"
    assert {c["source"] for c in cc["conflictFacts"][0]["candidates"]} == {"Enhetsregisteret", "Company website"}
    assert "1 of 3 facts are confirmed by two or more independent sources" in crosscheck.describe(cc)
    assert crosscheck.analyse([])["checked"] == 0  # nothing to cross-check is a result, not an error


def test_deep_plan_lists_its_extra_steps_and_quick_does_not() -> None:
    quick = [s["key"] for s in plan_for("quick", None, llm=True)["steps"]]
    deep = [s["key"] for s in plan_for("deep", None, llm=True)["steps"]]
    assert {"filings", "followup", "extract", "crosscheck"} <= set(deep) and not {"filings", "followup", "extract", "crosscheck"} & set(quick)
    assert "extract" not in [s["key"] for s in plan_for("deep", None, llm=False)["steps"]]  # no model configured → not offered


# ----------------------------------------------------------------------------------------------------- description boilerplate --
MENU = "Hjem Om oss Tjenester Karriere Kontakt Personvern Nyheter Investor Bærekraft Les mer Søk Logg inn"


def test_navigation_menus_never_become_the_company_description() -> None:
    html = (f'<html><head><title>Aker</title><meta name="description" content="{MENU}"></head><body>'
            f"<header><nav><ul><li>{MENU}</li></ul></nav></header><main><p>{MENU}</p>"
            "<p>Vi utvikler og driver olje- og gassfelt på norsk sokkel med fokus på lav kostnad og lave utslipp.</p></main>"
            f"<footer><p>{MENU} Alle rettigheter forbeholdt</p></footer></body></html>")
    doc = parse_html("https://aker.no/", "https://aker.no/", html)
    assert doc.paragraphs == ["Vi utvikler og driver olje- og gassfelt på norsk sokkel med fokus på lav kostnad og lave utslipp."]


def test_a_menu_meta_description_is_not_published_as_a_website_description(net) -> None:  # noqa: ANN001
    pages = verified_site(NAME, AUTO)
    pages["/"] = pages["/"].replace(pages["/"].split('content="')[1].split('"')[0], MENU, 1)
    net.add_site("autobjorn.no", pages)
    record = run(orchestrate(net, mode="quick"))
    assert not [c for c in record["claims"] if c["field"] in ("website_description", "business_description") and MENU[:20] in str(c["value"])]
    assert not any("Hjem Om oss" in json.dumps(c["value"]) for c in record["claims"])


# ----------------------------------------------------------------------------------------------------------------- the stream --
def test_events_emitted_while_the_stream_is_sending_are_delivered_at_once() -> None:
    """Regression: clearing the 'changed' signal after collecting events swallowed any event emitted while the previous one was being sent, so progress
    reached the browser in bursts, up to the 15 s keep-alive late."""
    async def scenario() -> list[float]:
        mgr = RunManager(SimpleNamespace(provider=None))
        r = Run(id="run-x", query="x", mode="quick", prompt=None, status="running", plan=plan_for("quick", None, llm=False), started_at=now_iso(), org=AUTO)
        mgr.runs[r.id] = r
        mgr._emit(r, "run.started")
        gen = mgr.events(r.id, 0)
        await anext(gen)  # the first event is out; the stream is now suspended inside its send loop
        waits = []
        for i in range(3):
            mgr._emit(r, "step.started", stepId=r.plan["steps"][i]["id"], sourceName="src")
            t0 = time.monotonic()
            chunk = await asyncio.wait_for(anext(gen), timeout=2)  # old behaviour: nothing for 15 s
            waits.append(time.monotonic() - t0)
            assert f'"seq": {i + 2}' in chunk or f'"seq":{i + 2}' in chunk
        await gen.aclose()
        return waits

    assert max(run(scenario())) < 0.5


# --------------------------------------------------------------------------------------------------------- API-level run tests --
class SlowTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport, delay: float) -> None:
        self.inner, self.delay = inner, delay

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(self.delay)
        return await self.inner.handle_async_request(request)


def build(net: Any, settings: Any, *, delay: float = 0.0, provider: Any = "fake"):  # noqa: ANN202
    from app.api.main import create_app
    from app.api.services import Services
    from app.storage.db import Database

    net.add_site("autobjorn.no", rich_site())
    transport = net.transport() if not delay else SlowTransport(net.transport(), delay)
    svc = Services(settings, db=Database(":memory:"), transport=transport, provider=FakeProvider() if provider == "fake" else provider, use_provider=provider == "fake")
    return svc, create_app(svc)


@pytest.fixture
def ctx(net, settings):  # noqa: ANN001, ANN201
    svc, app = build(net, settings)
    with TestClient(app) as client:
        yield SimpleNamespace(svc=svc, client=client, net=net)


def stream(client: TestClient, run_id: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with client.stream("GET", f"/api/research/runs/{run_id}/events?lastSeq=0") as s:
        for line in s.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
                if events[-1]["type"] in ("run.completed", "run.failed"):
                    break
    return events


def research(c: Any, mode: str = "quick", prompt: str | None = None, keys: list[str] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    body: dict[str, Any] = {"query": AUTO, "mode": mode}
    if prompt:
        body["prompt"] = prompt
    r = c.client.post("/api/research/runs", json=body).json()
    if r["status"] == "awaiting_confirmation":
        r = c.client.post(f"/api/research/runs/{r['id']}/confirm", json={"stepKeys": keys or [s["key"] for s in r["plan"]["steps"]]}).json()
    return r, stream(c.client, r["id"])


def terminal_types(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        if e["type"].startswith("step."):
            by.setdefault(e["stepId"], []).append(e)
    return by


def test_each_planned_source_reports_in_order_and_unused_steps_are_skipped_with_a_reason(ctx) -> None:  # noqa: ANN001
    ctx.net.add_site("autobjorn.no", {"/": "<html><body>no site</body></html>"})  # a site that cannot be verified: its dependent steps never run
    run_, events = research(ctx)
    by_step = terminal_types(events)
    assert set(by_step) == {s["id"] for s in run_["plan"]["steps"]}  # every planned step reports exactly its own states
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(set(seqs))
    for sid, evs in by_step.items():
        kinds = [e["type"] for e in evs]
        terminal = [k for k in kinds if k in ("step.completed", "step.failed", "step.blocked", "step.skipped", "step.cancelled")]
        assert len(terminal) == 1, (sid, kinds)  # one end state per step
        if "step.started" in kinds:
            assert kinds[0] == "step.started" and kinds.index(terminal[0]) > 0
            assert all(k == "step.progress" for k in kinds[1:kinds.index(terminal[0])])  # only progress may happen while it runs
        else:
            assert kinds == ["step.skipped"]  # never started → never claimed to have run
            assert evs[0]["message"]  # and the reason is stated
    assert events[-1]["type"] == "run.completed"


def test_progress_updates_arrive_while_a_source_runs(ctx) -> None:  # noqa: ANN001
    run_, events = research(ctx, "deep", prompt="What are their sustainability initiatives?")
    ids = {s["key"]: s["id"] for s in run_["plan"]["steps"]}
    progress = [e for e in events if e["type"] == "step.progress"]
    assert any(e["stepId"] == ids["website"] and "autobjorn.no" in e["message"] for e in progress)
    follow = [e for e in progress if e["stepId"] == ids["followup"]]
    assert follow and all(e["message"].startswith("Reading /") for e in follow)
    start = next(e["seq"] for e in events if e["type"] == "step.started" and e["stepId"] == ids["followup"])
    end = next(e["seq"] for e in events if e["type"] == "step.completed" and e["stepId"] == ids["followup"])
    assert all(start < e["seq"] < end for e in follow)  # shown only between the backend starting and finishing that work
    cross = next(e for e in events if e["type"] == "step.completed" and e["stepId"] == ids["crosscheck"])
    assert "confirmed by two or more independent sources" in cross["message"] and cross["evidenceCount"] > 0


def test_deep_run_reports_its_extra_effort_and_does_not_have_to_find_more_facts(ctx) -> None:  # noqa: ANN001
    _, quick = research(ctx, "quick")
    _, deep = research(ctx, "deep")
    q, d = quick[-1]["summary"], deep[-1]["summary"]
    assert {w["key"]: w["status"] for w in d["effort"]["workflows"]}["filings"] == "ran"
    assert {w["key"]: w["status"] for w in q["effort"]["workflows"]}["filings"] == "skipped"
    assert d["effort"]["pagesRead"] > q["effort"]["pagesRead"]
    assert d["effort"]["crosscheck"]["checked"] > 0
    # The effort is visible whatever the number of facts is; nothing makes Deep report a bigger number.
    assert d["factsVerified"] >= 1 and q["factsVerified"] >= 1


def test_a_source_failure_is_shown_and_the_run_is_not_labelled_completed(ctx) -> None:  # noqa: ANN001
    ctx.net.fail(f"https://data.brreg.no/regnskapsregisteret/regnskap/{AUTO}", "503")
    run_, events = research(ctx)
    ids = {s["key"]: s["id"] for s in run_["plan"]["steps"]}
    failed = [e for e in events if e["type"] == "step.failed"]
    assert any(e["stepId"] == ids["accounts"] and e["message"] for e in failed)  # which source, and why
    done = events[-1]
    assert done["type"] == "run.completed" and done["outcome"] == "partial"
    assert done["summary"]["failedSources"] >= 1 and any("could not be reached" in i for i in done["issues"])
    runs = ctx.client.get(f"/api/library/art-{AUTO}").json()["runs"]
    assert runs[0]["id"] == run_["id"] and runs[0]["status"] == "partial"  # saved as partial, never "completed"
    assert any(s["key"] == "accounts" and s["status"] == "failed" for s in runs[0]["steps"])


def test_a_run_that_fails_is_kept_in_the_history_without_a_report(ctx, monkeypatch) -> None:  # noqa: ANN001
    research(ctx)  # a good run first: the card exists
    from app.errors import ApiError

    async def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise ApiError("unavailable", "The company register did not respond.", status=503)

    monkeypatch.setattr(ctx.svc, "research", boom)
    run_, events = research(ctx)
    assert events[-1]["type"] == "run.failed"
    runs = ctx.client.get(f"/api/library/art-{AUTO}").json()["runs"]
    assert [r["status"] for r in runs] == ["failed", "completed"]
    failed = runs[0]
    assert failed["id"] == run_["id"] and failed["hasReport"] is False and failed["versionId"] is None and failed["isLatestReport"] is False
    assert failed["issues"] == ["The company register did not respond."]
    assert runs[1]["isLatestReport"] is True  # the earlier good report is still the latest one


def test_cancelling_stops_running_sources_and_is_recorded(net, settings) -> None:  # noqa: ANN001
    svc, app = build(net, settings, delay=0.05)
    with TestClient(app) as client:
        r = client.post("/api/research/runs", json={"query": AUTO, "mode": "quick"}).json()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            live = client.get(f"/api/research/runs/{r['id']}").json()
            if any(s["status"] == "running" for s in live["plan"]["steps"]):
                break
            time.sleep(0.02)
        else:
            pytest.fail("no source ever started")
        assert client.post(f"/api/research/runs/{r['id']}/cancel").json()["status"] == "cancelled"
        final = client.get(f"/api/research/runs/{r['id']}").json()
        statuses = [s["status"] for s in final["plan"]["steps"]]
        assert "running" not in statuses and "pending" not in statuses  # nothing is left looking busy or waiting
        assert "cancelled" in statuses or "skipped" in statuses
        events = svc.runs.runs[r["id"]].events
        assert events[-1]["type"] == "run.failed" and events[-1]["cancelled"] is True
        assert "Nothing from this run was saved" in events[-1]["message"]
        saved = run_history.runs_for_org(svc.db, AUTO)
        assert [x["status"] for x in saved] == ["cancelled"] and saved[0]["profileVersionId"] is None


def test_time_limit_marks_unfinished_sources_failed_and_unreached_ones_skipped() -> None:
    mgr = RunManager(SimpleNamespace(provider=None))
    r = Run(id="run-t", query="x", mode="quick", prompt=None, status="running", plan=plan_for("quick", None, llm=False), started_at=now_iso(), org=AUTO)
    mgr.runs[r.id] = r
    first, second = r.plan["steps"][0], r.plan["steps"][1]
    mgr._emit(r, "step.started", stepId=first["id"], sourceName="Brønnøysundregistrene")
    mgr._emit(r, "step.completed", stepId=first["id"], sourceName="Brønnøysundregistrene", factCount=2, evidenceCount=2, durationMs=40, outcome="verified")
    mgr._emit(r, "step.started", stepId=second["id"], sourceName="Regnskapsregisteret")  # still running when the limit hit
    mgr._settle_steps(r, {"modules": {}}, {"timedOut": True, "workflows": []}, True)
    states = {s["key"]: s for s in r.plan["steps"]}
    assert states[first["key"]]["status"] == "done"
    assert states[second["key"]]["status"] == "failed" and "time limit" in states[second["key"]]["message"]
    others = [s for s in r.plan["steps"][2:]]
    assert others and all(s["status"] == "skipped" and "time limit" in s["message"] for s in others)
    assert r.counts["failed"] == 1


def test_outcome_is_completed_only_when_everything_was_verified_and_reachable() -> None:
    full = {"complete": 5, "total": 5, "areas": [{"area": a, "status": "complete"} for a in ("company_record", "financials", "people_locations", "website", "hiring_activity")]}
    assert judge_outcome(full, blocked=0, failed=0, timed_out=False) == ("completed", [])
    gaps = {"complete": 3, "total": 5, "areas": [{"area": "company_record", "status": "complete"}, {"area": "website", "status": "blocked"}, {"area": "hiring_activity", "status": "unavailable"}]}
    outcome, issues = judge_outcome(gaps, blocked=1, failed=1, timed_out=True)
    assert outcome == "partial"
    assert any("time limit" in i for i in issues) and any("1 source could not be reached" in i for i in issues) and any("Company website, Hiring & public activity" in i for i in issues)
    assert judge_outcome(None, blocked=0, failed=0, timed_out=False)[0] == "partial"  # no coverage reported → completeness cannot be claimed


# ------------------------------------------------------------------------------------------------------------- run history --
def test_every_run_is_kept_under_the_one_company_card(ctx) -> None:  # noqa: ANN001
    first, _ = research(ctx, "quick")
    second, _ = research(ctx, "quick", prompt="Which contracts were announced recently?")
    third, _ = research(ctx, "deep")
    lib = ctx.client.get("/api/library").json()
    assert len([i for i in lib["items"] if i["type"] == "company" and i["orgNumber"] == AUTO]) == 1  # still one card

    art = ctx.client.get(f"/api/library/art-{AUTO}").json()
    runs = art["runs"]
    assert [r["id"] for r in runs] == [third["id"], second["id"], first["id"]]  # newest first
    assert [r["mode"] for r in runs] == ["deep", "quick", "quick"]
    assert runs[1]["prompt"] == "Which contracts were announced recently?" and runs[2]["prompt"] in (None, "")
    assert all(r["status"] in ("completed", "partial") and r["hasReport"] for r in runs)
    assert [r["isLatestReport"] for r in runs] == [True, False, False]  # exactly one is "the latest report"
    assert all(r["finishedAt"] and r["startedAt"] for r in runs)
    assert runs[0]["effort"]["workflows"] and runs[0]["steps"] and runs[0]["summary"]["factsVerified"] >= 1
    assert runs[1]["answer"] is not None  # the answer to that run's question is kept with it

    # Each run's report is still reachable through its own version, and the current version is the newest run's.
    version_ids = {v["id"] for v in art["versions"]}
    assert all(r["versionId"] in version_ids for r in runs)
    assert runs[0]["versionId"] == art["versions"][0]["id"] == art["versionId"]
    for r in runs:
        view = ctx.client.get(f"/api/library/art-{AUTO}/versions/{r['versionId']}").json()
        assert view["versionId"] == r["versionId"] and view["profile"]["company"]["orgNumber"] == AUTO


def test_a_run_that_finds_the_same_facts_says_so_and_does_not_hide_the_earlier_report(ctx) -> None:  # noqa: ANN001
    _, e1 = research(ctx, "quick")
    _, e2 = research(ctx, "quick")
    assert e1[-1]["summary"]["report"]["factsChanged"] is True  # nothing was on record before
    assert e2[-1]["summary"]["report"]["factsChanged"] is False  # same facts as the run before
    runs = ctx.client.get(f"/api/library/art-{AUTO}").json()["runs"]
    assert runs[0]["evidenceChanged"] is False and runs[1]["evidenceChanged"] is True
    assert len(runs) == 2 and runs[0]["versionId"] != runs[1]["versionId"]  # each run keeps its own report version


def test_the_current_report_follows_the_newest_run_even_when_its_evidence_matches_an_older_version(ctx) -> None:  # noqa: ANN001
    from app.api.library import ensure_company_artifact

    research(ctx, "quick")
    art = ctx.client.get(f"/api/library/art-{AUTO}").json()
    old = art["versions"][-1]
    record = {"organisation_number": AUTO, "identity": {"legal_name": NAME}, "completed_at": "2099-01-01T00:00:00Z"}
    # A later run whose evidence hashes to the existing version (identical content) must make that version current again.
    ensure_company_artifact(ctx.svc, record, ctx.svc.db.one("SELECT profile_version_id AS p FROM artifact_versions WHERE id = ?", (old["id"],))["p"], "Update")
    again = ctx.client.get(f"/api/library/art-{AUTO}").json()
    assert again["versions"][0]["id"] == old["id"] and again["versions"][0]["createdAt"].startswith("2099")


def test_runs_of_one_company_do_not_appear_on_another(ctx) -> None:  # noqa: ANN001
    research(ctx, "quick")
    assert run_history.runs_for_org(ctx.svc.db, "810363142") == []
