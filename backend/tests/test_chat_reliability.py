"""AI Chat reliability: the six observed chat failures, financial comparison, citation de-duplication, temporal checks, source audits, company switching,
research triggering, and durable conversation threads. No test touches the real network; the model and the register are fakes (these are offline tests,
not live integration tests)."""
from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import chat, fincompare
from app.api.chat import Item, canonical_url, salvage_supported, tidy_citations
from app.api.chat_intent import capitalised_names, classify, event_status
from app.api.chat_threads import make_title
from app.api.question_router import route_question
from app.config import Settings
from app.testing.fixtures import FixtureNetwork
from tests.test_regulatory_and_chat import AUTO, CapturingProvider, make_client

TODAY = date(2026, 10, 14)


# ===================================================================================== intent ==
@pytest.mark.parametrize(
    ("question", "kind"),
    [
        ("Which sources did you actually check for patents, ownership, and regulatory issues?", "source_audit"),
        ("Which financial figures changed most between the two latest reporting periods? Include both periods, the calculation and sources.", "financial_comparison"),
        ("Compare its latest results with the previous year.", "financial_comparison"),
        ("What was Equinor ASA's exact actual revenue in 2035?", "future_actual"),
        ("What is the revenue forecast for 2028?", "forecast"),
        ("What happened recently?", "recent"),
        ("What was the revenue in 2023?", "general"),
        ("Who runs this company?", "general"),
    ],
)
def test_intent_classification(question: str, kind: str) -> None:
    assert classify(question, today=TODAY).kind == kind


def test_future_years_are_detected_against_the_calendar_not_the_answer() -> None:
    assert classify("exact revenue in 2035", today=TODAY).future_years == [2035]
    assert classify("exact revenue in 2026", today=TODAY).future_years == [2026]  # the year is not over: its accounts do not exist
    assert classify("revenue in 2025", today=TODAY).future_years == []
    assert classify("What was the revenue in FY2031?", today=TODAY).kind == "future_actual"


def test_a_ranking_question_for_amounts_is_not_ranked_by_percent() -> None:
    assert classify("Which figure changed most in money terms?", today=TODAY).rank_by == "amount"
    assert classify("Which figure changed most?", today=TODAY).rank_by == "percent"


def test_event_status_never_promotes_an_intention_to_an_outcome() -> None:
    assert event_status("Equinor makes oil discovery near Johan Sverdrup")[0] == "discovery_announced"
    assert event_status("Equinor signs agreement to sell its stake in the field")[0] == "agreement_signed"
    assert event_status("Equinor completes the sale of its stake")[0] == "transfer_completed"
    assert event_status("The board proposes a quarterly dividend of USD 0.37")[0] == "dividend_announced"
    assert event_status("Equinor has paid the dividend of USD 0.37 per share")[0] == "dividend_paid"
    assert event_status("Equinor plans to submit a development plan")[0] in ("investment_decision", "planned")
    assert event_status("Production starts at the new field")[0] == "production_started"


def test_capitalised_names_find_company_candidates_not_question_words() -> None:
    assert capitalised_names("What about DNB Bank's revenue?")[0].startswith("DNB")
    assert capitalised_names("What is its revenue?") == []


# =============================================================================== comparison math ==
def _record(rows: dict[str, list[tuple[str, float]]], currency: str = "USD", account_type: str = "SELSKAP") -> dict[str, Any]:
    claims, evidence = [], []
    for field, pts in rows.items():
        for year, value in pts:
            eid = f"ev-{field}-{year}"
            evidence.append({"id": eid, "source_url": "https://data.brreg.no/regnskapsregisteret/regnskap/111111118", "retrieved_at": "2026-10-01T00:00:00Z", "claim_span": f"regnskapstype {account_type}"})
            claims.append({"field": field, "value": value, "currency": currency, "reporting_period": f"{year}-01-01/{year}-12-31", "period_label": f"FY{year}", "evidence_ids": [eid], "attributes": {"account_type": account_type}})
    return {"claims": claims, "evidence": evidence}


def test_revenue_change_is_calculated_exactly_with_its_formula() -> None:
    cmp = fincompare.compare_periods(_record({"revenue": [(2024, 72_540_000_000), (2025, 67_960_000_000)]}))
    (row,) = cmp.rows
    assert row.absolute == -4_580_000_000
    assert round(row.percent or 0, 2) == -6.31
    assert row.formula.startswith("USD 67.96B − USD 72.54B = −USD 4.58B")
    assert "−6.31%" in row.formula and cmp.periods == ("FY2024", "FY2025")


def test_ranking_names_its_criterion_and_percent_and_amount_orders_differ() -> None:
    rec = _record({"revenue": [(2024, 100_000_000), (2025, 110_000_000)], "annual_result": [(2024, 1_000_000), (2025, 3_000_000)], "equity": [(2024, 50_000_000), (2025, 40_000_000)]})
    by_pct = fincompare.compare_periods(rec, rank_by="percent")
    by_amt = fincompare.compare_periods(rec, rank_by="amount")
    assert [r.key for r in by_pct.ranked()][0] == "annual_result"  # +200%
    assert [r.key for r in by_amt.ranked()][0] == "revenue"  # +10M is the largest amount (equity −10M ties in size, revenue first by input order)
    assert "percentage" in by_pct.criterion and "absolute" in by_amt.criterion


def test_incomparable_figures_are_left_out_with_a_reason() -> None:
    rec = _record({"revenue": [(2024, 100.0), (2025, 120.0)]})
    rec["claims"].append({"field": "equity", "value": 5.0, "currency": "NOK", "reporting_period": "2025-01-01/2025-12-31", "period_label": "FY2025", "evidence_ids": [], "attributes": {}})
    rec["claims"].append({"field": "equity", "value": 4.0, "currency": "USD", "reporting_period": "2024-01-01/2024-12-31", "period_label": "FY2024", "evidence_ids": [], "attributes": {}})
    rec["claims"].append({"field": "total_liabilities", "value": 9.0, "currency": "USD", "reporting_period": "2025-01-01/2025-12-31", "period_label": "FY2025", "evidence_ids": [], "attributes": {}})
    cmp = fincompare.compare_periods(rec)
    assert [r.key for r in cmp.rows] == ["revenue"]
    text = " ".join(cmp.omitted)
    assert "different currencies" in text and "only 1 reporting period" in text


def test_company_only_and_consolidated_are_never_mixed() -> None:
    rec = _record({"revenue": [(2024, 100.0), (2025, 110.0)]})
    cons = _record({"consolidated_revenue": [(2024, 900.0), (2025, 990.0)]}, account_type="KONSERN")
    rec["claims"] += cons["claims"]
    rec["evidence"] += cons["evidence"]
    cmp = fincompare.compare_periods(rec)
    scopes = {(r.key, r.scope): (r.previous.value, r.latest.value) for r in cmp.rows}
    assert scopes == {("revenue", "company"): (100.0, 110.0), ("revenue", "group"): (900.0, 990.0)}
    assert cmp.scope_note and "each is compared only with itself" in cmp.scope_note


def test_zero_or_sign_changing_previous_values_have_no_percentage() -> None:
    cmp = fincompare.compare_periods(_record({"annual_result": [(2024, -10.0), (2025, 5.0)], "total_liabilities": [(2024, 0.0), (2025, 5.0)]}))
    assert all(r.percent is None for r in cmp.rows)
    assert all("not meaningful" in r.formula for r in cmp.rows)


# ========================================================================= citations and evidence ==
def test_canonical_url_treats_spelling_variants_as_one_source() -> None:
    a = canonical_url("https://www.Example.com/news/?utm_source=x#top")
    assert a == canonical_url("http://example.com/news") == canonical_url("https://example.com/news/")
    assert canonical_url("https://example.com/a?id=1") != canonical_url("https://example.com/a?id=2")


def test_citation_markers_are_tidied_not_stacked() -> None:
    assert tidy_citations("Revenue rose [1][1][1][2] in the year. It fell [2][2].") == "Revenue rose [1][2] in the year. It fell [2]."
    assert tidy_citations("A [3][1][2][4][5] claim.") == "A [1][2][3] claim."


def test_salvage_keeps_only_sentences_the_evidence_supports() -> None:
    items = [Item(1, "fact", "Revenue: NOK 72.54M (FY2023) (value: 72540000)", "Accounts", "https://data.brreg.no/x", None, None, "official_register", period="FY2023")]
    kept, dropped = salvage_supported("Revenue was NOK 72.54M in FY2023 [1]. It also won a giant contract [1].", items, question="revenue?", history=[])
    assert "72.54M" in kept and "contract" not in kept and dropped == 1


@pytest.fixture
def api(net: FixtureNetwork, settings: Settings):  # noqa: ANN201
    provider = CapturingProvider(None)
    client, svc = make_client(net, settings, provider)
    with client as c:
        c.get(f"/api/companies/{AUTO}")
        yield c, provider, svc


def ask(c: TestClient, q: str, **kw: Any) -> dict[str, Any]:
    r = c.post(f"/api/companies/{AUTO}/chat", json={"question": q, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_filing_is_one_citation_no_matter_how_many_figures_come_from_it(api) -> None:  # noqa: ANN001
    c, _, svc = api
    from app.storage import repository as repo

    record = repo.latest_record(svc.db, AUTO)
    profile = svc.profile_for(record)
    items = chat.build_evidence(profile, record, route_question("What is the revenue and profit?"), "What is the revenue and profit?", limit=24, origin="saved")
    keys = [(canonical_url(i.url), i.period, i.scope) for i in items if i.kind == "fact"]
    assert len(keys) == len(set(keys)), "the same source record was numbered twice"
    periods = [i.period for i in items if i.kind == "fact" and i.period]
    assert len(periods) == len(set(periods)) and len(periods) >= 2  # different reporting periods stay different records
    multi = [i for i in items if i.period and len(i.parts) > 1]
    assert multi, "several figures of one filing share one citation"
    assert all("not independently verify" in (i.uncertainty or "") for i in items if i.period)  # a filing is not an independent verification


def test_financial_citations_point_to_the_filing_of_that_period_when_the_register_lists_it(api) -> None:  # noqa: ANN001
    c, _, svc = api
    from app.storage import repository as repo

    record = repo.latest_record(svc.db, AUTO)
    record["claims"].append({"field": "annual_accounts_filed", "value": "2025", "attributes": {"document_url": f"https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{AUTO}/2025"}})
    profile = svc.profile_for(record)
    items = chat.build_evidence(profile, record, route_question("What is the revenue?"), "What is the revenue?", limit=24, origin="saved")
    fy25 = next(i for i in items if i.period == "FY2025")
    assert fy25.url.endswith(f"/aarsregnskap/kopi/{AUTO}/2025") and fy25.document and "FY2025" in fy25.document
    fy24 = next(i for i in items if i.period == "FY2024")
    assert fy24.url.endswith(AUTO)  # no per-year copy listed: the register's accounts endpoint is cited, not a made-up document


# =================================================================================== Test 2 · comparison ==
def test_comparison_question_is_calculated_not_asked_of_the_model(api) -> None:  # noqa: ANN001
    c, provider, _ = api
    before = provider.calls
    body = ask(c, "Which financial figures changed most between the latest two reporting periods? Include both periods, the calculation and sources.")
    assert body["kind"] == "comparison" and provider.calls == before
    cmp = body["comparison"]
    assert cmp["periods"] == ["FY2024", "FY2025"] and cmp["rankedBy"] == "percent"
    rev = next(r for r in cmp["rows"] if r["metric"] == "revenue")
    assert rev["previous"] == {"period": "FY2024", "value": 26480515.0} and rev["latest"] == {"period": "FY2025", "value": 21789260.0}
    assert round(rev["percentChange"], 2) == round((21789260 - 26480515) / 26480515 * 100, 2)
    assert len(cmp["rows"]) >= 4, "operating result, net result, assets, equity ... are compared too, not only revenue"
    assert "Ranked by percentage change" in body["answer"] and "Calculation:" in body["answer"] and "FY2024" in body["answer"]
    assert body["citations"] and all(s["reportingPeriod"] in ("FY2024", "FY2025") for s in body["citations"])
    assert len({s["reportingPeriod"] for s in body["citations"]}) == 2 and len(body["citations"]) == 2  # one citation per filing, not one per figure


def test_a_named_year_pair_compares_exactly_those_years(api) -> None:  # noqa: ANN001
    c, _, _ = api
    body = ask(c, "Compare revenue between 2023 and 2024")
    assert body["comparison"]["periods"] == ["FY2023", "FY2024"]


def test_amount_ranking_is_labelled_as_such(api) -> None:  # noqa: ANN001
    c, _, _ = api
    body = ask(c, "Which figure changed most in absolute money terms between the two latest years?")
    assert body["comparison"]["rankedBy"] == "amount" and "absolute monetary change" in body["answer"]


# ===================================================================== Test 4 · future-year actuals ==
def test_future_year_actual_is_never_answered_with_another_year(api) -> None:  # noqa: ANN001
    c, provider, _ = api
    before = provider.calls
    body = ask(c, "What is the exact actual revenue in 2035?")
    assert body["kind"] == "future_actual" and provider.calls == before
    assert "does not exist yet" in body["answer"] and "2035" in body["answer"]
    assert "not the requested value" in body["answer"]  # historical context, explicitly separate
    ctx_cites = body["citations"]
    assert all(s["reportingPeriod"] in ("FY2025", "FY2024", "FY2023") for s in ctx_cites)


def test_forecast_question_without_evidence_says_so_and_estimates_nothing(api) -> None:  # noqa: ANN001
    c, _, _ = api
    body = ask(c, "What is the revenue forecast for 2028?")
    assert body["kind"] == "forecast" and "No published forecast" in body["answer"] and "no actual result exists" in body["answer"]
    assert body["citations"] == []


# ===================================================================== Test 6 · source-audit questions ==
def test_source_audit_returns_status_records_not_company_facts(api) -> None:  # noqa: ANN001
    c, provider, _ = api
    before = provider.calls
    body = ask(c, "Which sources did you actually check for patents, ownership, and regulatory issues?")
    assert body["kind"] == "source_audit" and provider.calls == before
    ans = body["answer"]
    for word in ("Patentstyret", "Shareholders", "Regulators"):
        assert word in ans
    assert "UNAVAILABLE" in ans and "NOT checked" in ans
    assert "not evidence that nothing exists" in ans
    assert "Revenue" not in ans and "NOK" not in ans  # no unrelated financial facts
    rows = {r["area"]: r for r in body["checked"]}
    assert rows["ip"]["status"] == "unavailable" and rows["ip"]["relevant"] and rows["regulatory"]["status"] == "not_checked"
    assert all(r["status"] in chat.STATUS for r in body["checked"])


def test_patent_question_never_implies_none_when_the_source_is_unavailable(api) -> None:  # noqa: ANN001
    c, provider, _ = api
    provider.reply = {"answer": "It holds no patents [1].", "cited": [1]}
    body = ask(c, "Which patents does it hold?")
    low = body["answer"].lower()
    assert "patentstyret" in low and "unknown" in low or "unavailable" in low
    assert "holds no patents" not in low and "has no patents" not in low
    assert "NOK" not in body["answer"] and body["citations"] == []


def test_ownership_question_gets_the_limitation_not_the_accounts(api) -> None:  # noqa: ANN001
    c, _, _ = api
    body = ask(c, "Who owns this company?")
    assert "Shareholders" in body["answer"] or "ownership" in body["answer"].lower()
    assert "revenue" not in body["answer"].lower()


# ============================================================== pipeline: no unrelated evidence dumps ==
def test_a_rejected_model_answer_is_replaced_by_a_relevant_limitation_not_unrelated_facts(api) -> None:  # noqa: ANN001
    c, provider, _ = api
    provider.reply = {"answer": "The CEO is Jane Doe [1].", "cited": [1]}
    body = ask(c, "Does it have any regulatory issues?")
    assert body["kind"] in ("limitation", "evidence_only")
    assert "NOK" not in body["answer"] and "revenue" not in body["answer"].lower()


def test_model_is_given_one_corrective_attempt_before_the_answer_is_cut_down(api) -> None:  # noqa: ANN001
    c, provider, _ = api
    first = ask(c, "What is the revenue?")
    n = next(s["n"] for s in first["sources"] if s["reportingPeriod"])
    src = next(s for s in first["sources"] if s["n"] == n)
    good = f"The register lists {src['excerpt'].split(' (value')[0].split(';')[0]} [{n}]."
    replies = [{"answer": "Revenue was NOK 999 billion [1].", "cited": [1]}, {"answer": good, "cited": [n]}]
    provider.calls = 0
    orig = provider.chat

    async def seq(messages, **kw):  # noqa: ANN001, ANN202
        provider.reply = replies[min(provider.calls, len(replies) - 1)]
        return await orig(messages, **kw)

    provider.chat = seq  # type: ignore[method-assign]
    body = ask(c, "What was the latest revenue?")
    assert provider.calls == 2 and body["kind"] == "model" and "999" not in body["answer"]


# ================================================================================ Test 5 · identity ==
SECOND = "810034882"  # SANDNES ELEKTRISKE AS — a second company in the offline register fixtures


def _resolver(svc: Any, monkeypatch: pytest.MonkeyPatch, mapping: dict[str, str]) -> None:
    async def resolve(query: str, auto_pick: bool = True):  # noqa: ANN202
        for key, org in mapping.items():
            if key.lower() in query.lower():
                return org, []
        return None, []

    monkeypatch.setattr(svc, "resolve_query", resolve)


def test_naming_another_company_switches_explicitly_and_carries_nothing_over(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CapturingProvider(None)
    client, svc = make_client(net, settings, provider)
    with client as c:
        c.get(f"/api/companies/{AUTO}")
        _resolver(svc, monkeypatch, {"Sandnes": SECOND})
        body = ask(c, "What about Sandnes Elektriske AS revenue? Use AUTOBJØRN's sources for it.")
    assert body["contextSwitch"]["to"]["orgNumber"] == SECOND and body["contextSwitch"]["from"]["orgNumber"] == AUTO
    assert "nothing from" in body["contextSwitch"]["message"] and "not done" in body["contextSwitch"]["message"]
    assert body["company"]["orgNumber"] == SECOND and "SANDNES" in body["company"]["legalName"]
    blob = json.dumps([body["answer"], body["citations"], body["sources"]])
    assert AUTO not in blob and "AUTOBJ" not in blob  # none of the previous company's facts, figures, sources or citations
    assert all(f"/{AUTO}" not in (s_["url"] or "") for s_ in body["sources"])


def test_an_ambiguous_second_company_asks_for_clarification(api, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    c, _, svc = api

    async def resolve(query: str, auto_pick: bool = True):  # noqa: ANN202
        return None, [{"orgNumber": "923609016", "legalName": "NORDVIK AS"}, {"orgNumber": "810359862", "legalName": "NORDVIK HOLDING AS"}]

    monkeypatch.setattr(svc, "resolve_query", resolve)
    body = ask(c, "And what about Nordvik AS?")
    assert body["kind"] == "clarification" and body["company"]["orgNumber"] == AUTO and body["candidates"] and body["citations"] == []
    assert "guessed" in body["answer"]


def test_comparing_two_companies_in_one_chat_is_refused_not_mixed(api) -> None:  # noqa: ANN001
    c, _, _ = api
    body = ask(c, "Compare AUTOBJØRN A/S with Polarlys Medtech AS")
    assert body["kind"] == "clarification" and "never mixes" in body["answer"] and body["citations"] == []


# ===================================================================== research is triggered by chat ==
def test_chat_checks_current_sources_only_when_the_question_needs_it_and_never_runs_the_research_pipeline(net: FixtureNetwork, settings: Settings,
                                                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_regulatory_and_chat import tavily

    settings.tavily_api_key = "tvly-test"
    searches: list[dict] = []
    net.handlers.append(tavily([], searches))
    client, svc = make_client(net, settings, CapturingProvider({"answer": "x [1]", "cited": [1]}))
    calls: list[str] = []
    with client as c:
        c.get(f"/api/companies/{AUTO}")
        orig = svc.research

        async def spy(org: str, **kw: Any):  # noqa: ANN202
            calls.append(kw.get("mode", ""))
            return await orig(org, **kw)

        monkeypatch.setattr(svc, "research", spy)
        ask(c, "What is the latest revenue?")  # filed accounts are on record: nothing is looked up
        assert searches == []
        ask(c, "What happened recently? Any new announcements?")  # announcements were not checked: ONE targeted search, not a research run
        assert 1 <= len(searches) <= settings.chat_max_searches and calls == []  # (a second, broader search only because the first found nothing)
        with c.stream("POST", f"/api/companies/{AUTO}/chat/stream", json={"question": "What happened recently?"}) as r:
            text = "".join(r.iter_text())
    assert calls == []  # chat never starts the deep research pipeline
    events = [line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("event: ")]
    assert "progress" in events and events[-1] == "result"
    assert "Understanding your question" in text and "Checking company register" in text and "Checking current sources for this question" in text


def test_a_slow_live_source_never_looks_successful(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from app.connectors import search

    settings.tavily_api_key = "tvly-test"
    settings.chat_fresh_timeout_seconds = 0.05  # the lower of this and CHAT_LOOKUP_TIMEOUT_SECONDS applies (never below half a second)
    client, svc = make_client(net, settings, CapturingProvider(None))

    async def slow(*a: Any, **k: Any):  # noqa: ANN202
        await asyncio.sleep(5)
        return None, []

    with client as c:
        c.get(f"/api/companies/{AUTO}")
        monkeypatch.setattr(search, "web_search", slow)
        body = ask(c, "What are the latest announcements?")
    assert body["search"]["state"] == "timeout" and "Nothing from it is part of this answer" in body["search"]["note"]
    assert body["origin"] == "saved" and all(s["origin"] == "saved" for s in body["sources"])


# ================================================================================ Test 3 · recent events ==
def test_recent_developments_carry_date_status_significance_and_source_and_never_overstate() -> None:
    base = {"company": {"orgNumber": AUTO, "legalName": "TESTCO ASA"}}
    def ev(date_: str, body: str, tier: str) -> Item:
        _k, label = event_status(body)
        it = Item(0, "event", f"{date_} — {body} [status: {label}]", "Newsroom", f"https://testco.example/news/{date_}", date_, "2026-10-01T00:00:00Z", "company_disclosure", status=label, significance=tier)
        return it
    items = [ev("2026-09-30", "TESTCO makes discovery in the North Sea.", "Major — a new discovery"), ev("2026-09-12", "TESTCO signs agreement to sell its stake in the field.", "Major — transaction"),
             ev("2026-09-02", "The board proposes a dividend of USD 0.37 per share.", "Relevant — shareholder return")]
    for i, it in enumerate(items, 1):
        it.n = i
    ans = chat.answer_recent(base, items, [], {"state": "not_used", "note": ""}, "saved")
    assert ans is not None and ans["kind"] == "recent"
    text = ans["answer"]
    assert "Status: Discovery announced (not a field development or production)" in text
    assert "Status: Agreement signed (transfer or closing not yet confirmed)" in text
    assert "Status: Dividend announced or proposed (not yet paid)" in text
    assert "Significance: Major" in text and "published 2026-09-30" in text and "Company disclosure" in text
    assert [s["url"] for s in ans["sources"]] == [i.url for i in items]
    assert chat.answer_recent(base, [], [], {}, "saved") is None  # nothing found: the caller says so, nothing is invented


# =============================================================================== threads: persistence ==
@pytest.fixture
def threads(api):  # noqa: ANN001, ANN201
    c, provider, svc = api
    return c, provider, svc


def test_thread_lifecycle_create_ask_reload_rename_delete(threads) -> None:  # noqa: ANN001
    c, provider, svc = threads
    tid = "thread-aaaa-0001"
    assert c.get("/api/chat/threads").json() == {"threads": []}
    made = c.post("/api/chat/threads", json={"id": tid, "orgNumber": AUTO}).json()
    assert made["id"] == tid and made["company"]["orgNumber"] == AUTO and made["title"] == "New chat"
    assert c.post("/api/chat/threads", json={"id": tid, "orgNumber": AUTO}).json()["id"] == tid  # retry: same thread
    assert len(c.get("/api/chat/threads").json()["threads"]) == 1

    r = c.post(f"/api/chat/threads/{tid}/ask", json={"question": "What is the latest revenue?", "messageId": "msg-aaaa-0001"}).json()
    assert r["assistantMessage"]["role"] == "assistant" and r["assistantMessage"]["payload"]["citations"]
    again = c.post(f"/api/chat/threads/{tid}/ask", json={"question": "What is the latest revenue?", "messageId": "msg-aaaa-0001"}).json()
    assert again["assistantMessage"]["id"] == r["assistantMessage"]["id"]  # a retry replays, it does not duplicate

    # "reload the app": a brand-new service object over the same database still has the conversation, with citations and statuses
    from app.api.chat_threads import ChatThreads

    reopened = ChatThreads(svc).get(tid)
    assert [m["role"] for m in reopened["messages"]] == ["user", "assistant"]
    assert reopened["title"].lower().startswith("latest revenue") or "revenue" in reopened["title"].lower()
    payload = reopened["messages"][1]["payload"]
    assert payload["citations"] and payload["coverage"] and payload["search"] and payload["company"]["orgNumber"] == AUTO

    renamed = c.patch(f"/api/chat/threads/{tid}", json={"title": "Revenue check"}).json()
    assert renamed["title"] == "Revenue check" and renamed["titleEdited"] is True
    c.post(f"/api/chat/threads/{tid}/ask", json={"question": "Who runs this company?"})
    assert c.get(f"/api/chat/threads/{tid}").json()["title"] == "Revenue check"  # an edited title is never overwritten

    assert c.delete(f"/api/chat/threads/{tid}").json() == {"deleted": True}
    assert c.get(f"/api/chat/threads/{tid}").status_code == 404
    assert svc.db.one("SELECT COUNT(*) AS n FROM chat_messages WHERE thread_id = ?", (tid,))["n"] == 0  # really gone from storage
    assert c.delete(f"/api/chat/threads/{tid}").status_code == 404


def test_history_comes_from_the_thread_not_the_browser_and_threads_never_mix(threads) -> None:  # noqa: ANN001
    c, provider, _ = threads
    for tid in ("thread-bbbb-0001", "thread-bbbb-0002"):
        c.post("/api/chat/threads", json={"id": tid, "orgNumber": AUTO})
    provider.reply = {"answer": "x [1]", "cited": [1]}
    c.post("/api/chat/threads/thread-bbbb-0001/ask", json={"question": "What was the revenue last year?"})
    c.post("/api/chat/threads/thread-bbbb-0002/ask", json={"question": "Who runs this company?"})
    c.post("/api/chat/threads/thread-bbbb-0001/ask", json={"question": "And the year before?"})
    sent = " ".join(m["content"] for m in provider.messages)
    assert "revenue last year" in sent and "Who runs this company" not in sent
    a = c.get("/api/chat/threads/thread-bbbb-0001").json()["messages"]
    b = c.get("/api/chat/threads/thread-bbbb-0002").json()["messages"]
    assert {m["id"] for m in a}.isdisjoint({m["id"] for m in b})
    assert not any("runs this company" in m["content"] for m in a)


def test_a_thread_without_a_company_asks_which_one_and_does_not_guess(threads, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    c, _, svc = threads
    c.post("/api/chat/threads", json={"id": "thread-cccc-0001"})
    r = c.post("/api/chat/threads/thread-cccc-0001/ask", json={"question": "What is its latest revenue?", "messageId": "msg-cccc-0001"}).json()
    assert r["assistantMessage"]["kind"] == "clarification" and r["thread"]["company"] is None
    # the user names the company by organisation number → the SAME question is answered, once
    r2 = c.post("/api/chat/threads/thread-cccc-0001/ask", json={"question": "", "retryOf": "msg-cccc-0001", "orgNumber": AUTO}).json()
    assert r2["assistantMessage"]["kind"] != "clarification" and r2["thread"]["company"]["orgNumber"] == AUTO
    msgs = c.get("/api/chat/threads/thread-cccc-0001").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert c.get("/api/chat/threads/thread-cccc-0001").json()["title"] == "What is its latest revenue"


def test_switching_company_opens_a_new_thread_and_leaves_the_old_one_clean(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    client, svc = make_client(net, settings, CapturingProvider(None))
    with client as c:
        c.get(f"/api/companies/{AUTO}")
        c.post("/api/chat/threads", json={"id": "thread-dddd-0001", "orgNumber": AUTO})
        c.post("/api/chat/threads/thread-dddd-0001/ask", json={"question": "What is the latest revenue?"})
        _resolver(svc, monkeypatch, {"Sandnes": SECOND})
        r = c.post("/api/chat/threads/thread-dddd-0001/ask", json={"question": "What about Sandnes Elektriske AS?"}).json()
        new_id = r["threadId"]
        assert new_id != "thread-dddd-0001" and r["switchedFromThreadId"] == "thread-dddd-0001"
        assert r["thread"]["company"]["orgNumber"] == SECOND
        old = c.get("/api/chat/threads/thread-dddd-0001").json()
        new = c.get(f"/api/chat/threads/{new_id}").json()
        assert old["company"]["orgNumber"] == AUTO and old["messages"][-1]["kind"] == "context_notice"
        assert all(SECOND not in json.dumps(m.get("payload", {}).get("citations", [])) for m in old["messages"])
        assert [m["role"] for m in new["messages"]] == ["user", "assistant"] and new["messages"][1]["payload"]["company"]["orgNumber"] == SECOND
        assert all(AUTO not in json.dumps(m.get("payload", {}).get("sources", [])) for m in new["messages"])
        # a follow-up in the old thread is still about the old company and never sees the moved question
        c.post("/api/chat/threads/thread-dddd-0001/ask", json={"question": "And the year before?"})
        assert "Sandnes" not in " ".join(m["content"] for m in svc.provider.messages)
        ids = [t["id"] for t in c.get("/api/chat/threads").json()["threads"]]
        assert set(ids) == {"thread-dddd-0001", new_id}


def test_titles_are_short_and_meaningful() -> None:
    assert make_title("Please tell me what is the revenue of Equinor in 2024?") == "What is the revenue of Equinor in 2024"
    assert len(make_title("x" * 300)) <= 56 + 1
    assert make_title("hi", "Equinor ASA") == "About Equinor ASA"


def test_invalid_ids_and_empty_questions_are_rejected_cleanly(threads) -> None:  # noqa: ANN001
    c, _, _ = threads
    assert c.post("/api/chat/threads", json={"id": "bad id!"}).status_code == 400
    c.post("/api/chat/threads", json={"id": "thread-eeee-0001", "orgNumber": AUTO})
    assert c.post("/api/chat/threads/thread-eeee-0001/ask", json={"question": "  "}).status_code == 400
    assert c.get("/api/chat/threads/thread-zzzz-9999").status_code == 404


def test_no_credential_ever_appears_in_stored_threads(threads) -> None:  # noqa: ANN001
    c, _, svc = threads
    svc.settings.tavily_api_key = "tvly-SECRET-VALUE"
    c.post("/api/chat/threads", json={"id": "thread-ffff-0001", "orgNumber": AUTO})
    c.post("/api/chat/threads/thread-ffff-0001/ask", json={"question": "What is the latest revenue?"})
    assert "SECRET" not in json.dumps(c.get("/api/chat/threads/thread-ffff-0001").json())
