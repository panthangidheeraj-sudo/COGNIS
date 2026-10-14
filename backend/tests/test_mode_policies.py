"""Quick and Deep are different research modes — in what they are allowed to spend and in what they actually do — and the evidence standard is the same.

Every outside service is replaced by the fixture network and the fake language model, so these tests prove what the code does, not what a live site returns.

* Budgets: each mode is held to its own request / time / search / model-call / page budget, and the report of that budget is read back from the object that enforced it.
* Execution paths: the requests that really leave the process differ (filing history, further pages, search discovery), and optional discovery that the
  selected focus does not need is skipped in Quick.
* Evidence: nothing in the publication gate or the identity checks knows the mode; Deep never publishes what its sources do not support, and when there is
  nothing more to find it reports that instead of finding more.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import run
from fastapi.testclient import TestClient
from test_hiring_data import hiring, posting, settings_with, site, tavily_handler
from test_research_modes_and_runs import ACCOUNT_COPIES, AUTO, NAME, build, orchestrate, rich_site, stream, workflows

from app.agent import orchestrator as orch_mod
from app.agent.modes import QUICK_SITE_PAGES, policy_for
from app.api.research_runs import DEEP_KEYS, QUICK_KEYS
from app.config import Settings
from app.evidence import gate
from app.providers.fake_provider import FakeProvider
from app.runtime.budgets import CompanyBudget
from app.testing.fixtures import FixtureNetwork, verified_site

TAVILY_KEY = "tvly-test-0000000000"
BUDGET_AXES = ("max_requests", "max_seconds", "max_searches", "max_llm_calls", "max_site_pages", "follow_up_rounds")
COPIES_LIST = f"https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{AUTO}/aar"


def claim_set(record: dict[str, Any]) -> set[tuple[str, str]]:
    return {(c["field"], json.dumps(c["value"], sort_keys=True, default=str)) for c in record["claims"]}


def website_paths(net: FixtureNetwork) -> list[str]:
    return [re.sub(r"^https?://[^/]+", "", u) or "/" for u in net.requests if "autobjorn.no" in u and not u.endswith("/robots.txt")]


# ------------------------------------------------------------------------------------------------------------------- the budgets --
def test_quick_has_a_smaller_budget_than_deep_on_every_axis(settings: Settings) -> None:
    quick, deep = policy_for(settings, "quick"), policy_for(settings, "deep")
    for axis in BUDGET_AXES:
        assert getattr(quick, axis) < getattr(deep, axis), axis
    assert (quick.job_page_search, deep.job_page_search) == (False, True)
    assert quick.max_site_pages == QUICK_SITE_PAGES


def test_deep_and_batch_runs_keep_the_full_per_company_budget_and_registry_lookups_make_no_model_calls(settings: Settings) -> None:
    for mode in ("deep", "competition"):
        full = policy_for(settings, mode)
        assert (full.max_requests, full.max_seconds, full.max_searches, full.max_llm_calls, full.max_site_pages, full.follow_up_rounds) == (
            settings.per_company_max_requests, settings.per_company_max_seconds, settings.max_searches_per_company, settings.max_llm_calls_per_company,
            settings.max_pages_per_site, settings.max_research_rounds)
    assert policy_for(settings, "registry").max_llm_calls == 0


def test_quick_can_never_be_configured_larger_than_deep(settings: Settings) -> None:
    settings_with(settings, quick_max_requests=500, quick_max_seconds=9999.0, quick_max_searches=50, max_pages_per_site=2)
    quick, deep = policy_for(settings, "quick"), policy_for(settings, "deep")
    for axis in BUDGET_AXES:
        assert getattr(quick, axis) <= getattr(deep, axis), axis


def test_the_shipped_quick_budget_and_how_to_change_it(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("QUICK_MAX_REQUESTS", "QUICK_MAX_SECONDS", "QUICK_MAX_SEARCHES"):
        monkeypatch.delenv(name, raising=False)
    shipped = Settings(_env_file=None)
    assert (shipped.quick_max_requests, shipped.quick_max_seconds, shipped.quick_max_searches) == (20, 60.0, 1)  # as documented in .env.example
    monkeypatch.setenv("QUICK_MAX_REQUESTS", "7")
    monkeypatch.setenv("QUICK_MAX_SECONDS", "33")
    monkeypatch.setenv("QUICK_MAX_SEARCHES", "0")
    tuned = Settings(_env_file=None)
    assert (tuned.quick_max_requests, tuned.quick_max_seconds, tuned.quick_max_searches) == (7, 33.0, 0)


def test_each_mode_is_held_to_its_own_budget_and_the_report_shows_the_budget_that_was_enforced(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[dict[str, Any]] = []

    class SpyBudget(CompanyBudget):
        def __init__(self, run_budget: Any, **limits: Any) -> None:
            built.append(limits)
            super().__init__(run_budget, **limits)

    monkeypatch.setattr(orch_mod, "CompanyBudget", SpyBudget)
    net.add_site("autobjorn.no", rich_site())
    quick = run(orchestrate(net, mode="quick", provider=FakeProvider()))
    deep = run(orchestrate(net, mode="deep", provider=FakeProvider()))
    q, d = built
    assert (q["max_requests"], q["max_seconds"], q["max_searches"], q["max_llm_calls"]) == (20, 60.0, 1, 1)
    assert (d["max_requests"], d["max_seconds"], d["max_searches"], d["max_llm_calls"]) == (30, 120.0, 3, 4)
    for axis in ("max_requests", "max_seconds", "max_searches", "max_llm_calls"):
        assert q[axis] < d[axis], axis
    # the effort report carries the limits of the policy object that built those budgets
    assert quick["effort"]["budget"] == policy_for(settings, "quick").limits() and deep["effort"]["budget"] == policy_for(settings, "deep").limits()
    assert quick["effort"]["budget"]["maxRequests"] < deep["effort"]["budget"]["maxRequests"]
    # and the work stayed inside it
    assert quick["effort"]["llmCalls"] <= q["max_llm_calls"] and deep["effort"]["llmCalls"] <= d["max_llm_calls"]
    assert quick["operations"]["requests"] <= q["max_requests"] and deep["operations"]["requests"] <= d["max_requests"]


def test_the_hard_time_limit_follows_the_mode(net: FixtureNetwork, monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    real_wait_for = asyncio.wait_for

    async def spy(awaitable: Any, timeout: float | None = None) -> Any:
        waits.append(timeout or 0.0)
        return await real_wait_for(awaitable, timeout=timeout)

    class Aio:  # only the orchestrator's view of asyncio is replaced; everything else is delegated
        wait_for = staticmethod(spy)

        def __getattr__(self, name: str) -> Any:
            return getattr(asyncio, name)

    monkeypatch.setattr(orch_mod, "asyncio", Aio())
    net.add_site("autobjorn.no", rich_site())
    run(orchestrate(net, mode="quick", provider=FakeProvider()))
    quick_cap, waits[:] = max(waits), []
    run(orchestrate(net, mode="deep", provider=FakeProvider()))
    deep_cap = max(waits)
    assert quick_cap == 60.0 + 15 and deep_cap == 120.0 + 15


def test_a_small_quick_budget_stops_optional_lookups_but_never_the_registers(net: FixtureNetwork, settings: Settings) -> None:
    net.add_site("autobjorn.no", rich_site())
    normal = run(orchestrate(net, mode="quick", provider=FakeProvider()))
    settings_with(settings, quick_max_requests=6)
    capped = run(orchestrate(net, mode="quick", provider=FakeProvider()))
    # identity, roles and the annual accounts are essential: they are published whatever the cap
    essential = {"legal_name", "ceo", "operating_result", "annual_result", "registered_employees"}
    assert essential <= {c["field"] for c in capped["claims"]}
    # what was optional is cut, visibly: the blocked lookups are counted and the site was read less
    assert capped["operations"]["blocked_by_budget"].get("website", 0) > 0
    assert capped["effort"]["pagesRead"] < normal["effort"]["pagesRead"]
    assert normal["operations"]["blocked_by_budget"] == {}


# ----------------------------------------------------------------------------------------------- what leaves the process --
def test_quick_reads_the_pages_its_limit_allows_and_deep_reads_more_of_the_same_site(net: FixtureNetwork, settings: Settings) -> None:
    net.add_site("autobjorn.no", rich_site())
    quick = run(orchestrate(net, mode="quick", provider=FakeProvider()))
    quick_paths, quick_requests = website_paths(net), list(net.requests)
    net.requests.clear()
    deep = run(orchestrate(net, mode="deep", provider=FakeProvider()))
    deep_paths, deep_requests = website_paths(net), list(net.requests)
    policy = policy_for(settings, "quick")
    # homepage + the page limit + one follow-up round of at most two pages
    assert quick["effort"]["pagesRead"] <= 1 + policy.max_site_pages + 2 * policy.follow_up_rounds
    assert deep["effort"]["pagesRead"] > quick["effort"]["pagesRead"]
    assert len(set(deep_paths)) > len(set(quick_paths))
    assert set(quick_paths) <= set(deep_paths)  # Deep does what Quick does, and more
    assert not any(ACCOUNT_COPIES in u for u in quick_requests) and any(ACCOUNT_COPIES in u for u in deep_requests)  # the multi-year filing history: Deep only
    assert len(deep_requests) > len(quick_requests)


def test_quick_skips_the_search_for_job_pages_unless_the_focus_is_hiring_and_deep_always_runs_it(settings: Settings) -> None:
    settings_with(settings, tavily_api_key=TAVILY_KEY)
    outcomes: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    for label, mode, focus in (("quick", "quick", None), ("quick-financials", "quick", "Latest financials"), ("quick-hiring", "quick", "Are they hiring?"), ("deep", "deep", None)):
        net, calls = FixtureNetwork(), []
        net.load_brreg_probes()
        net.add_site("autobjorn.no", site())  # a careers page with no opening, so search discovery is the only way to look further
        net.handlers.append(tavily_handler([], calls))
        outcomes[label] = (run(orchestrate(net, mode=mode, focus=focus, provider=FakeProvider())), calls)

    assert outcomes["quick"][1] == [] and outcomes["quick-financials"][1] == []  # optional discovery the focus does not need
    assert len(outcomes["quick-hiring"][1]) == 1 and len(outcomes["deep"][1]) == 1
    assert "autobjorn.no" in outcomes["quick-hiring"][1][0]["include_domains"]
    skipped = workflows(outcomes["quick"][0])["job_search"]
    assert skipped["status"] == "skipped" and "unless the focus is about hiring" in skipped["detail"] and "careers pages and NAV were still checked" in skipped["detail"]
    for label in ("quick-hiring", "deep"):
        assert workflows(outcomes[label][0])["job_search"]["status"] == "ran"
    assert outcomes["quick"][0]["operations"]["searches"] == 0
    assert outcomes["quick-hiring"][0]["operations"]["searches"] == 1 <= policy_for(settings, "quick").max_searches


def test_quick_still_reads_the_companys_own_careers_page_and_a_skipped_search_is_never_read_as_no_openings(settings: Settings) -> None:
    settings_with(settings, tavily_api_key=TAVILY_KEY)

    def quick_run(pages: dict[str, str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        net, calls = FixtureNetwork(), []
        net.load_brreg_probes()
        net.add_site("autobjorn.no", pages)
        net.handlers.append(tavily_handler([], calls))
        return run(orchestrate(net, mode="quick", provider=FakeProvider())), calls

    with_opening, calls = quick_run(site([posting("Bilselger")]))
    assert calls == [] and hiring(with_opening)["outcome"] == "verified" and hiring(with_opening)["totalCurrent"] == 1  # the essential source needs no search

    quiet, calls = quick_run(site())
    h = hiring(quiet)
    assert calls == [] and h["outcome"] != "verified"
    assert re.search(r"not evidence|does not mean", h["message"])  # silence is not a conclusion
    assert not [c for c in quiet["claims"] if c["field"] == "open_positions_count" and c["value"] == 0]


# ----------------------------------------------------------------------------------------------- the evidence standard --
def test_the_publication_gate_and_identity_checks_never_look_at_the_mode() -> None:
    root = Path(orch_mod.__file__).resolve().parents[1]
    for package in ("evidence", "identity", "extraction"):
        files = list((root / package).rglob("*.py"))
        assert files, package
        for path in files:
            assert not re.search(r"\b(quick|deep)\b", path.read_text(encoding="utf-8"), re.I), f"{package}/{path.name} must not depend on the research mode"
    assert "mode" not in inspect.signature(gate.publish).parameters


def test_register_facts_are_identical_in_both_modes_and_every_published_fact_is_evidenced(net: FixtureNetwork) -> None:
    net.add_site("autobjorn.no", rich_site())
    quick = run(orchestrate(net, mode="quick", provider=FakeProvider()))
    deep = run(orchestrate(net, mode="deep", provider=FakeProvider()))

    def official(record: dict[str, Any]) -> set[tuple[str, str]]:
        return {(c["field"], json.dumps(c["value"], sort_keys=True, default=str)) for c in record["claims"] if c["source_class"].startswith("official_")}

    assert official(quick) and official(quick) <= official(deep)  # what the registers say does not depend on how hard we looked
    for record in (quick, deep):
        evidence = {e["id"]: e for e in record["evidence"]}
        for claim in record["claims"]:
            assert claim["evidence_ids"], claim["field"]
            for eid in claim["evidence_ids"]:
                e = evidence[eid]
                assert e["source_url"] and e["retrieved_at"] and e["claim_span"], (claim["field"], eid)  # same minimum in Quick and Deep


def test_everything_deep_adds_comes_from_work_only_deep_does(net: FixtureNetwork) -> None:
    net.add_site("autobjorn.no", rich_site())
    quick = run(orchestrate(net, mode="quick", provider=FakeProvider()))
    deep = run(orchestrate(net, mode="deep", provider=FakeProvider()))
    extra = claim_set(deep) - claim_set(quick)
    assert extra  # this site has more to find, and Deep found it
    extra_fields = {f for f, _ in extra}
    classes = {c["source_class"] for c in deep["claims"] if c["field"] in extra_fields}
    assert classes <= {"official_annual_account_copies", "company_owned"}  # the filing history and the further pages / AI-read quotes of the verified site


def test_ai_reading_cannot_publish_a_statement_the_page_does_not_contain(net: FixtureNetwork) -> None:
    net.add_site("autobjorn.no", rich_site())
    made_up = {"business_description": {"text": "Verdens største leverandør av romfartøy.", "quote": "Selskapet er verdens største leverandør av romfartøy og kvantedatamaskiner.",
                                        "page": "https://www.autobjorn.no/"},
               "products_services": [{"name": "Romfartøy", "quote": "Vi bygger og selger romfartøy til hele verden", "page": "https://www.autobjorn.no/"}]}
    lying = run(orchestrate(net, mode="deep", provider=FakeProvider(script={"extract_website": json.dumps(made_up)})))
    blob = json.dumps(lying["claims"], ensure_ascii=False).lower()
    assert "romfartøy" not in blob and "kvantedatamaskiner" not in blob
    assert workflows(lying)["extract"]["status"] == "ran" and workflows(lying)["extract"]["detail"] == "No quote-verified statements were extracted."
    assert not [c for c in lying["claims"] if c["extraction_method"] == "llm_quote_verified"]
    honest = run(orchestrate(net, mode="deep", provider=FakeProvider()))
    assert [c for c in honest["claims"] if c["extraction_method"] == "llm_quote_verified"]  # a statement that IS on the page is published, with its quote


def test_an_unrelated_company_site_is_not_verified_in_either_mode_and_deeper_search_does_not_relax_the_check(settings: Settings) -> None:
    settings_with(settings, tavily_api_key=TAVILY_KEY)
    runs: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    for mode in ("quick", "deep"):
        net, calls = FixtureNetwork(), []
        net.load_brreg_probes()
        net.add_site("autobjorn.no", verified_site("Helt Annet AS", "914552108"))  # the register's website belongs to a different company
        net.add_site("autobjorn-bergen.no", verified_site("Autobjørn Bergen AS", "914552108"))  # and the search offers a look-alike
        net.handlers.append(tavily_handler([{"url": "https://autobjorn-bergen.no/", "title": "Autobjørn Bergen AS", "content": "Autobjørn Bergen AS bilforhandler"}], calls))
        runs[mode] = (run(orchestrate(net, mode=mode, provider=FakeProvider())), calls)
    (quick, quick_calls), (deep, deep_calls) = runs["quick"], runs["deep"]
    assert quick_calls == [] and len(deep_calls) == 1  # Deep looked wider ...
    assert any(a["domain"] == "autobjorn-bergen.no" for a in deep["site_attempts"])
    assert quick["site_attempts"][0]["decision"] == deep["site_attempts"][0]["decision"] != "verified"  # ... and the register's site is judged the same way
    for record in (quick, deep):
        assert all(a["decision"] != "verified" for a in record["site_attempts"])  # ... and nothing it found was accepted
        assert not [c for c in record["claims"] if c["source_class"] == "company_owned"]
        assert not [e for e in record["evidence"] if "autobjorn-bergen.no" in e["source_url"] or "helt" in e["source_url"].lower()]


def test_deep_reports_its_work_but_adds_no_findings_when_the_sources_have_nothing_more(net: FixtureNetwork) -> None:
    net.add_site("autobjorn.no", {"/": verified_site(NAME, AUTO)["/"]})  # a verified site with a homepage and nothing linked from it
    net.add_json(COPIES_LIST, [])  # no filed annual-account copies are listed
    nothing = json.dumps({"business_description": None, "products_services": []})
    quick = run(orchestrate(net, mode="quick", provider=FakeProvider(script={"extract_website": nothing})))
    deep = run(orchestrate(net, mode="deep", provider=FakeProvider(script={"extract_website": nothing})))
    assert claim_set(deep) == claim_set(quick)  # not a single extra finding, and none removed
    assert deep["effort"]["pagesRead"] == quick["effort"]["pagesRead"] == 1
    w = workflows(deep)
    assert w["filings"]["status"] == "ran" and "No filed annual-account copies" in w["filings"]["detail"]
    assert w["followup"]["status"] == "ran" and "No further relevant pages" in w["followup"]["detail"]
    assert w["extract"]["status"] == "ran" and w["extract"]["detail"] == "No quote-verified statements were extracted."
    assert w["crosscheck"]["status"] == "ran"  # the extra verification still happened, and it too changed nothing
    assert deep["effort"]["requests"] > quick["effort"]["requests"]  # it did try harder; the report says so


# ----------------------------------------------------------------------------------- frontend → API → orchestrator → record --
@pytest.fixture
def api(net: FixtureNetwork, settings: Settings):  # noqa: ANN201
    svc, app = build(net, settings)
    with TestClient(app) as client:
        yield SimpleNamespace(svc=svc, client=client, net=net)


def test_the_selected_mode_travels_from_the_api_to_the_orchestrator_and_into_the_saved_run(api: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []
    original = api.svc.research

    async def spy(org: str, **kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs)
        return await original(org, **kwargs)

    monkeypatch.setattr(api.svc, "research", spy)

    quick = api.client.post("/api/research/runs", json={"query": AUTO, "mode": "quick"}).json()
    quick_events = stream(api.client, quick["id"])
    deep = api.client.post("/api/research/runs", json={"query": AUTO, "mode": "deep"}).json()
    assert deep["status"] == "awaiting_confirmation" and quick["status"] == "running"  # Deep shows its plan first, Quick starts at once
    api.client.post(f"/api/research/runs/{deep['id']}/confirm", json={"stepKeys": [s["key"] for s in deep["plan"]["steps"]]})
    deep_events = stream(api.client, deep["id"])
    unknown = api.client.post("/api/research/runs", json={"query": AUTO, "mode": "turbo"}).json()  # anything but "deep" is Quick
    stream(api.client, unknown["id"])
    assert unknown["mode"] == "quick"

    researched = [kw for kw in seen if kw["mode"] != "registry"]  # (the first lookup of an unknown company is a registry-only call)
    assert [kw["mode"] for kw in researched] == ["quick", "deep", "quick"]
    assert researched[0]["step_keys"] == [*QUICK_KEYS, "geo"] and researched[1]["step_keys"] == [*DEEP_KEYS, "geo"]
    assert not {"filings", "followup", "extract", "crosscheck"} & set(researched[0]["step_keys"])
    assert {"filings", "followup", "extract", "crosscheck"} <= set(researched[1]["step_keys"])

    q, d = quick_events[-1]["summary"]["effort"], deep_events[-1]["summary"]["effort"]
    assert (q["mode"], d["mode"]) == ("quick", "deep")
    assert q["budget"]["maxRequests"] == 20 < d["budget"]["maxRequests"] == 30
    assert q["budget"]["maxSeconds"] < d["budget"]["maxSeconds"] and q["budget"]["maxSearches"] < d["budget"]["maxSearches"]
    saved = {r["id"]: r for r in api.client.get(f"/api/library/art-{AUTO}").json()["runs"]}  # the run history keeps each run's mode and the budget it had
    assert (saved[quick["id"]]["mode"], saved[deep["id"]]["mode"]) == ("quick", "deep")
    assert saved[quick["id"]]["effort"]["budget"] == q["budget"] and saved[deep["id"]]["effort"]["budget"] == d["budget"]
