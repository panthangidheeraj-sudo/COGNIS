"""Research focus quality: each focus chip and common phrasing returns what it is about, and the financial caveats stay attached.

* Leadership focus → the registered people (CEO first), not a generic "other" answer.
* Latest financials focus → figures with their reporting period AND the accounting-scope caveat (company-only accounts are never presented as group figures).
* Recent activity focus → dated, relevant announcements, most significant first; menus, undated items and register entries never appear.
"""
from __future__ import annotations

import pytest
from test_custom_questions import ORG, TODAY, ago, announcements, ask, ev, event, profile, texts

from app.agent.focus import focus_kinds
from app.api.question_router import route_question


def person(i: int, name: str, role: str) -> dict:
    fact = {"id": f"{ORG}:people.{i}", "field": "people.ceo", "label": role, "status": "verified", "value": name,
            "evidence": [ev(f"e-p{i}", "https://data.brreg.no/enhetsregisteret/api/roller", f"{role}: {name}", "brreg")]}
    return {"id": f"{ORG}-p{i}", "name": name, "role": role, "roleGroup": "management", "current": True, "fact": fact}


def with_people(p: dict) -> dict:
    p["people"] = {"status": "available", "people": [person(0, "Ingrid Solberg", "CEO"), person(1, "Kari Nordmann", "Chair of the board"), person(2, "Ola Hansen", "Board member")]}
    return p


@pytest.mark.parametrize("question", ["Leadership", "Who runs it?", "Who leads the company?", "Who is in charge?", "Who is the managing director?", "Who are the directors?",
                                      "CFO and CTO", "Management team", "Executive team and board", "Head of the company", "Board of directors"])
def test_leadership_wordings_are_routed_to_the_people_evidence(question: str) -> None:
    assert route_question(question).kinds == ["people"]


@pytest.mark.parametrize("question", ["Who runs it?", "Leadership", "Who leads the company?"])
def test_a_leadership_focus_returns_leadership_information_with_citations(question: str) -> None:
    a = ask(with_people(profile()), question)
    t = texts(a)
    assert t.startswith("Ingrid Solberg — CEO.") and "Kari Nordmann — Chair of the board." in t
    assert all(b["citations"] for b in a["blocks"]), "every person is cited to the register"
    assert not a.get("limitation") and "does not address" not in json_text(a)


def test_a_leadership_focus_with_no_registered_roles_says_so_instead_of_guessing() -> None:
    p = profile()
    p["people"] = {"status": "not_available", "people": [], "message": "No registered roles were found."}
    a = ask(p, "Leadership")
    assert not a["blocks"] and any("No registered roles" in g for g in a["gaps"])


def test_the_leadership_focus_reads_the_pages_where_people_are_listed() -> None:
    assert focus_kinds("Leadership") == ["team", "about"]
    assert focus_kinds("Who leads the company?") == ["team", "about"]


def test_the_latest_financials_focus_keeps_period_currency_and_the_company_only_caveat() -> None:
    a = ask(profile(), "Latest financials")
    t = texts(a)
    assert "Revenue: USD 68.0M for FY2024 (reporting period 2024-01-01 to 2024-12-31) — company-only (parent) annual accounts." in t
    assert "Operating result" in t and "Annual result" in t
    assert any("company's own (non-consolidated) accounts" in g and "not inferred" in g for g in a["gaps"]), "the scope caveat stays visible"
    assert all(b["citations"] and b.get("reportingPeriod") for b in a["blocks"])


def test_the_latest_financials_focus_never_shows_company_only_accounts_as_group_figures() -> None:
    a = ask(profile(), "Latest financials")
    assert "consolidated (group)" not in texts(a)


def test_the_recent_activity_focus_lists_dated_relevant_announcements_most_significant_first() -> None:
    items = [*announcements(),
             event("u1", "Unrelated routine greeting", 15, "announcement", rank=6, tier="routine"),
             event("m1", "Acquires a majority stake in a Danish service company", 55, "acquisition", rank=0)]
    undated = event("x1", "Announcement without a usable date", 5, "contract", rank=0)
    undated["date"] = "not a date"
    a = ask(profile([*items, undated]), "Recent activity")
    t = texts(a)
    titles = [b["text"] for b in a["blocks"]]
    assert "majority stake" in titles[0] and ago(55).split("-")[0] in titles[0], "the most significant announcement comes first, with its date"
    assert "framework agreement" in t and "autonomous vessels" in t
    assert "Hopp til hovedinnhold" not in t, "website navigation is never an announcement"
    assert "Establishment opened" not in t and "greeting" not in t and "webinar" not in t
    assert "without a usable date" not in t, "an item without a valid date is excluded"
    assert all(b["citations"] for b in a["blocks"]) and TODAY.isoformat()[:4] in "".join(titles)


def json_text(a: dict) -> str:
    import json

    return json.dumps(a)
