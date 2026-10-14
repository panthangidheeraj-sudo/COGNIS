"""Custom questions are answered from the evidence that is about them (Test #3).

1. "latest revenue, operating profit and reporting period" -> those figures with their period, currency and accounting scope — nothing else.
2. "contracts, discoveries and partnerships announced in the last 12 months" -> dated announcements inside the window, never a website menu or unrelated facts.
3. "confidential future contracts" -> a plain statement of what public sources can and cannot verify, not saved evidence repeated.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.api.briefs import answer
from app.api.question_router import route_question, time_window
from app.events.timeline import Candidate, unsupported_reason
from app.extraction.boilerplate import is_boilerplate
from app.extraction.web_facts import description_observation

TODAY = date(2026, 10, 12)
MENU = "Hopp til hovedinnhold Hjem Om oss Tjenester Prosjekter Karriere Kontakt Personvern Meny Søk"
ORG = "810359862"


def ago(days: int) -> str:
    return (TODAY - timedelta(days=days)).isoformat()


def ev(eid: str, url: str, excerpt: str, source: str = "web-1") -> dict:
    return {"id": eid, "sourceId": source, "url": url, "retrievedAt": "2026-10-01T10:00:00Z", "excerpt": excerpt}


def money(key: str, label: str, value: float, currency: str | None, period: str, year: int, scope: str = "SELSKAP") -> dict:
    cur = f" {currency}" if currency else ""
    fact = {"id": f"{ORG}:financials.{key}.{year}", "field": f"financials.{key}.{year}", "label": label, "status": "verified", "value": value, "currency": currency,
            "displayValue": f"{currency} {value / 1e6:.2f}M" if currency else f"{value / 1e6:.2f}M", "reportingPeriod": f"{year}-01-01/{year}-12-31",
            "evidence": [ev(f"e-{key}-{year}", "https://data.brreg.no/regnskapsregisteret", f"{key} = {value:.0f}{cur} (regnskapsperiode {year}-01-01–{year}-12-31, regnskapstype {scope})", "accounts")]}
    return {"period": period, "year": year, "fact": fact}


def event(eid: str, title: str, days: int, etype: str, *, rank: int, tier: str = "major", source: str = "company_newsroom", desc: str | None = None) -> dict:
    url = f"https://www.firma.no/nyheter/{eid}"
    return {"id": eid, "date": ago(days), "type": etype, "title": title, "description": desc, "significance": tier, "score": 70, "rank": rank, "sourceType": source,
            "url": url, "evidence": [ev(f"ev-{eid}", url, title)]}


def profile(events: list[dict] | None = None, *, currency: str | None = "USD", description: str | None = MENU, activity_extra: dict | None = None) -> dict:
    series = [{"key": "revenue", "label": "Revenue", "points": [money("revenue", "Revenue", 72_540_000, currency, "FY2023", 2023), money("revenue", "Revenue", 67_960_000, currency, "FY2024", 2024)]},
              {"key": "operating_result", "label": "Operating result", "points": [money("operating_result", "Operating result", 9_100_000, currency, "FY2024", 2024)]},
              {"key": "annual_result", "label": "Annual result", "points": [money("annual_result", "Annual result", 6_400_000, currency, "FY2024", 2024)]}]
    desc = {"id": f"{ORG}:overview.description", "field": "overview.description", "label": "What the company does", "status": "verified", "value": description,
            "evidence": [ev("e-desc", "https://www.firma.no/", description or "", "web-1")]} if description else None
    emp = {"id": f"{ORG}:overview.employees", "field": "overview.employees", "label": "Employees", "status": "verified", "value": 214, "evidence": [ev("e-emp", "https://data.brreg.no", "antall ansatte 214", "brreg")]}
    p = {"company": {"legalName": "Firma AS", "orgNumber": ORG}, "identity": {}, "keyMetrics": [emp], "financials": {"series": series, "latestPeriod": "FY2024"},
         "people": {"people": []}, "locations": {"locations": []}, "hiring": {"totalCurrent": None, "jobs": []}, "changes": {"changes": []}, "knowns": [],
         "sourceIndex": {"web-1": {"name": "Firma newsroom"}, "accounts": {"name": "Regnskapsregisteret"}, "brreg": {"name": "Enhetsregisteret"}},
         "activity": {"status": "available", "events": events or [], **(activity_extra or {})}}
    if desc:
        p["description"] = desc
    return p


def ask(p: dict, question: str, origin: str = "saved_evidence") -> dict:
    return asyncio.run(answer(p, question, None, origin=origin, today=TODAY))


def texts(a: dict) -> str:
    return " ".join(b["text"] for b in a["blocks"])


# ------------------------------------------------------------ 1. financial question --
Q1 = "What is the latest revenue, operating profit and reporting period?"


def test_a_financial_question_gets_the_requested_figures_with_period_currency_and_scope() -> None:
    a = ask(profile(), Q1)
    t = texts(a)
    assert "Revenue: USD 68.0M for FY2024 (reporting period 2024-01-01 to 2024-12-31) — company-only (parent) annual accounts." in t
    assert "Operating result: USD 9.1M for FY2024" in t
    assert any(b["text"].startswith("Reporting period: 2024-01-01 to 2024-12-31") for b in a["blocks"])
    assert "Annual result" not in t and "FY2023" not in t, "only what was asked: no net result and no prior year"
    assert "NOK" not in json.dumps(a), "the currency is the filing's own (USD here), never assumed"
    assert all(b["citations"] for b in a["blocks"]), "every figure keeps its citation"
    assert not a.get("limitation")


def test_company_only_accounts_are_never_presented_as_consolidated() -> None:
    a = ask(profile(), "What is the consolidated group revenue?")
    assert "company-only" in texts(a) and "consolidated (group)" not in texts(a)
    assert any("never inferred" in g for g in a["gaps"])


def test_a_figure_without_a_stated_currency_says_so() -> None:
    a = ask(profile(currency=None), Q1)
    assert "does not state a currency" in texts(a) and "NOK" not in json.dumps(a)


def test_the_filing_scope_is_used_as_stated_not_guessed() -> None:
    p = profile()
    for s in p["financials"]["series"]:
        for pt in s["points"]:
            pt["fact"]["evidence"][0]["excerpt"] = pt["fact"]["evidence"][0]["excerpt"].replace("SELSKAP", "KONSERN")
    assert "consolidated (group) annual accounts" in texts(ask(p, Q1))
    for s in p["financials"]["series"]:
        for pt in s["points"]:
            pt["fact"]["evidence"][0]["excerpt"] = "revenue = 1"
    assert "accounting scope not stated by the source" in texts(ask(p, Q1))


def test_missing_accounts_are_reported_not_replaced_by_other_facts() -> None:
    p = profile()
    p["financials"] = {"series": [], "message": "No filed annual accounts were found for this company."}
    a = ask(p, Q1)
    assert not a["blocks"] and any("No filed annual accounts" in g for g in a["gaps"])


# ------------------------------------------------------- 2. recent announcements --
Q2 = "Which contracts, discoveries and partnerships were announced in the last 12 months?"


def announcements() -> list[dict]:
    return [
        event("c1", "Signs framework agreement worth 400 million with the Defence Materiel Agency", 40, "contract", rank=1),
        event("p1", "Strategic partnership to develop autonomous vessels", 120, "partnership", rank=2, desc="Joint development with a research institute."),
        event("c0", "Wins vehicle supply contract from a municipality", 700, "contract", rank=3),  # outside the window
        event("r1", "Establishment opened: AVD 3", 30, "location", rank=9, tier="routine", source="official_registry"),
        event("n1", MENU, 20, "announcement", rank=8),  # a scraped menu mistaken for a headline
        event("w1", "Invitation to webinar", 10, "announcement", rank=7, tier="routine"),
    ]


def test_recent_announcements_come_from_dated_events_inside_the_window() -> None:
    a = ask(profile(announcements()), Q2)
    t = texts(a)
    assert "framework agreement worth 400 million" in t and "autonomous vessels" in t
    assert ago(40).split("-")[0] in t  # dated
    assert "Source: the company's newsroom." in t
    first = a["blocks"][0]
    assert first["detail"] == "https://www.firma.no/nyheter/c1" and first["citations"] and first["citations"][0]["evidence"]["excerpt"]
    assert "vehicle supply contract" not in t, "outside the requested 12 months"
    assert "Establishment opened" not in t and "webinar" not in t, "register entries and routine notices are not announcements"
    assert any("No discoveries announcement dated within the last 12 months" in g for g in a["gaps"])


def test_website_navigation_and_unrelated_saved_facts_are_never_an_answer() -> None:
    a = ask(profile(announcements()), Q2)
    blob = json.dumps(a, ensure_ascii=False)
    for junk in ("Hopp til hovedinnhold", "Personvern", "Karriere", "214", "Revenue", "employees"):
        assert junk not in blob, junk


def test_without_matching_announcements_the_answer_says_so_and_offers_live_research() -> None:
    a = ask(profile([]), Q2)
    assert not a["blocks"]
    assert "No contracts / discoveries / partnerships dated within the last 12 months" in a["limitation"]
    assert "not evidence that none were made" in a["limitation"] and "Research more (live sources)" in a["limitation"]
    assert "Hopp til hovedinnhold" not in json.dumps(a, ensure_ascii=False) and "214" not in json.dumps(a)


def test_a_fresh_answer_does_not_offer_the_live_option_it_already_used() -> None:
    a = ask(profile([]), Q2, origin="fresh_research")
    assert "Research more" not in a["limitation"] and "Live sources were queried" in a["limitation"]


def test_unreadable_sources_are_listed_so_missing_news_is_not_read_as_no_news() -> None:
    extra = {"status": "partial", "message": "No company announcements could be read.", "sourcesChecked": [{"name": "Company newsroom", "status": "blocked", "note": "robots.txt"}]}
    a = ask(profile([], activity_extra=extra), Q2)
    assert any("Company newsroom (blocked: robots.txt)" in g for g in a["gaps"])


def test_the_requested_window_is_honoured() -> None:
    a = ask(profile(announcements()), "Which contracts were announced in the last 3 years?")
    assert "vehicle supply contract" in texts(a)
    assert "autonomous vessels" not in texts(a), "partnerships were not asked for"


# ---------------------------------------------------- 3. unanswerable questions --
Q3 = "What confidential future contracts is the company going to win?"


def test_confidential_or_future_questions_state_the_limit_instead_of_repeating_saved_evidence() -> None:
    a = ask(profile(announcements()), Q3)
    assert a["blocks"] == []
    assert a["limitation"].startswith("This cannot be answered from public sources")
    assert "will not infer or guess" in a["limitation"] and "Research more (live sources)" in a["limitation"]
    blob = json.dumps(a, ensure_ascii=False)
    for junk in ("Hopp til hovedinnhold", "Revenue", "214", "framework agreement", "USD"):
        assert junk not in blob, junk


def test_the_limit_after_live_research_says_live_sources_cannot_verify_it_either() -> None:
    a = ask(profile(), "Tell me about their unannounced future contracts", origin="fresh_research")
    assert a["blocks"] == [] and "cannot verify this either" in a["limitation"]


def test_a_question_nothing_on_record_addresses_is_not_answered_with_generic_facts() -> None:
    a = ask(profile(announcements()), "Does the company sponsor any football clubs?")
    assert a["blocks"] == [] and "does not address this question" in a["limitation"]


# ------------------------------------------------------------------- routing --
@pytest.mark.parametrize("question,kinds", [
    (Q1, ["financial"]), (Q2, ["announcements"]), (Q3, ["limitation"]), ("What are the latest financials?", ["financial"]), ("Recent activity", ["announcements"]),
    ("Who runs the company?", ["people"]), ("Is it hiring?", ["hiring"]), ("Where does it operate internationally?", ["locations"]),
    ("What changed recently?", ["changes"]), ("Company brief", ["overview"]), ("What do we still not know?", ["gaps"]), ("Does the company sponsor football?", ["other"]),
])
def test_questions_are_routed_to_the_evidence_they_are_about(question: str, kinds: list[str]) -> None:
    assert route_question(question).kinds == kinds


def test_operating_profit_means_the_operating_result_and_plain_profit_the_annual_result() -> None:
    assert route_question(Q1).metrics == ["revenue", "operating_result"]
    assert route_question("What was the net profit last year?").metrics == ["annual_result"]


def test_time_windows_are_read_from_the_question() -> None:
    assert time_window("in the last 12 months") == (365, "the last 12 months")
    assert time_window("over the past two years")[0] == 730
    assert time_window("siste 6 måneder")[0] == 183
    assert time_window("anything new?") == (None, None)


# --------------------------------------------------------------- boilerplate --
@pytest.mark.parametrize("text", [MENU, "Hjem | Om oss | Tjenester | Nyheter | Karriere | Kontakt | English", "Vi bruker informasjonskapsler for å gi deg en bedre opplevelse.",
                                  "Home About Us Services Products News Contact Careers Login", "Skip to main content"])
def test_navigation_menus_and_cookie_text_are_boilerplate(text: str) -> None:
    assert is_boilerplate(text)


@pytest.mark.parametrize("text", ["Kongsberg signs framework agreement worth NOK 400 million with the Defence Materiel Agency.", "Nordic Wins Major Contract With Defence Materiel Agency",
                                  "We deliver services, solutions and products to customers and partners across Norway.",
                                  "AUTOBJØRN AS selger og vedlikeholder biler og leverer tjenester, produkter og løsninger til kunder og partnere i hele landet."])
def test_real_sentences_and_headlines_are_not_boilerplate(text: str) -> None:
    assert not is_boilerplate(text)


def test_a_menu_is_not_extracted_as_the_company_description() -> None:
    doc = SimpleNamespace(paragraphs=[MENU * 1], title="Firma", description=None, og={})
    crawl = SimpleNamespace(verified=True, docs=lambda *kinds: [doc] if kinds == ("about",) else [], homepage=SimpleNamespace(description=MENU + " Søk Meny Logg inn", og={}, title="Firma"))
    assert description_observation(crawl) is None


def test_a_menu_is_not_accepted_as_an_announcement_headline() -> None:
    c = Candidate(id="m", date=ago(5), title=MENU, origin="company_newsroom", evidence=[ev("x", "https://www.firma.no/nyheter", MENU)], url="https://www.firma.no/nyheter")
    assert "navigation or boilerplate" in (unsupported_reason(c, TODAY) or "")
    ok = Candidate(id="o", date=ago(5), title="Signs framework agreement with the Defence Materiel Agency", origin="company_newsroom",
                   evidence=[ev("y", "https://www.firma.no/nyheter/1", "Signs framework agreement with the Defence Materiel Agency")], url="https://www.firma.no/nyheter/1")
    assert unsupported_reason(ok, TODAY) is None


# ------------------------------------------------------------ through the API --
def test_the_ask_endpoint_uses_the_router(net, settings) -> None:  # noqa: ANN001
    from fastapi.testclient import TestClient

    from app.api.main import create_app
    from app.api.services import Services
    from app.providers.fake_provider import FakeProvider
    from app.storage.db import Database
    from app.testing.fixtures import verified_site

    net.add_site("autobjorn.no", verified_site("AUTOBJØRN A/S", ORG, jobs=["Bilselger", "Mekaniker"]))
    svc = Services(settings, db=Database(":memory:"), transport=net.transport(), provider=FakeProvider(), use_provider=True)
    with TestClient(create_app(svc)) as c:
        assert c.get(f"/api/companies/{ORG}").status_code == 200
        res = c.post("/api/research/ask", json={"orgNumber": ORG, "question": Q3}).json()
        assert res["blocks"] == [] and res["limitation"].startswith("This cannot be answered from public sources") and res["origin"] == "saved_evidence"
        res = c.post("/api/research/ask", json={"orgNumber": ORG, "question": Q2}).json()
        assert "Hopp til hovedinnhold" not in json.dumps(res, ensure_ascii=False)
        assert res["blocks"] == [] or all(b["detail"].startswith("http") for b in res["blocks"])
        res = c.post("/api/research/ask", json={"orgNumber": ORG, "question": "Does the company sponsor any football clubs?"}).json()
        assert res["blocks"] == [] and "does not address this question" in res["limitation"]
