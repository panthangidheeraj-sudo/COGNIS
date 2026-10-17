"""Unit tests for the chat's targeted lookup (``app/api/chat_lookup.py``): the query it sends, the passages it keeps, the identity check every page must
pass, the permitted domains, and the honest outcome it reports. Offline."""
from __future__ import annotations

from typing import Any

import pytest

from app.api import chat_lookup as cl
from app.config import Settings
from app.extraction.html import parse_html
from app.identity.model import CanonicalIdentity
from app.testing.fixtures import FixtureNetwork, company_page
from tests.test_regulatory_and_chat import AUTO, HOST, CapturingProvider, make_client, official, tavily

EQUINOR = CanonicalIdentity(org_number="923609016", legal_name="EQUINOR ASA", website="www.equinor.com")
Q = ("Summarise Equinor ASA's latest annual financial results. Include the reporting period, revenue, net income, and source links. "
     "Clearly distinguish consolidated group accounts from company-only accounts, and identify anything you cannot verify.")


def doc(url: str, body: str, title: str = "Page") -> Any:
    return parse_html(url, url, company_page(title, body), retrieved_at="2026-10-16T10:00:00Z")


def test_the_query_names_the_company_and_what_is_asked_not_the_instructions() -> None:
    q = cl.build_query(Q, "EQUINOR ASA", ["financials"], [])
    assert q.startswith('"EQUINOR"') and "annual report" in q and "revenue" in q and "net income" in q
    for word in ("summarise", "include", "clearly", "identify", "links", "verify"):
        assert word not in q.lower().split()
    assert len(q) <= 380
    assert "2025" in cl.build_query("What was revenue in 2025?", "EQUINOR ASA", ["financials"], [2025])


def test_only_passages_that_bear_on_the_question_are_kept_verbatim() -> None:
    page = doc("https://www.equinor.com/news/annual-results", (
        "<p>We use cookies to improve your experience on this site, read our privacy policy.</p>"
        "<p>Equinor reported total revenues and other income of USD 103.8 billion for the full year 2025, and net income of USD 9.1 billion.</p>"
        "<p>The company sponsors a local football team and an art prize every year.</p>"))
    got = cl.relevant_passages(page, Q, "EQUINOR ASA", ["financials"])
    assert got == ["Equinor reported total revenues and other income of USD 103.8 billion for the full year 2025, and net income of USD 9.1 billion."]


def test_identity_check_accepts_own_site_and_exact_name_and_rejects_everything_else() -> None:
    own = {"equinor.com"}
    assert cl.ties_to_company(doc("https://www.equinor.com/x", "<p>Results</p>"), EQUINOR, own)[0] == "the company's own website"
    assert cl.ties_to_company(doc("https://e24.no/a", "<p>Equinor ASA la fram tall i dag.</p>"), EQUINOR, own)[0]
    assert cl.ties_to_company(doc("https://e24.no/b", "<p>Org.nr. 923 609 016: kvartalstall</p>"), EQUINOR, own)[0] == "organisation number on the page"
    basis, why = cl.ties_to_company(doc("https://e24.no/c", "<p>Equinor Energy AS (org.nr. 990 888 213) melder om nye funn.</p>"), EQUINOR, own)
    assert basis is None and "different organisation number" in why
    basis, why = cl.ties_to_company(doc("https://e24.no/d", "<p>Statoil-arven og oljeprisen.</p>"), EQUINOR, own)
    assert basis is None and why


def test_own_domains_come_from_the_verified_site_and_the_register() -> None:
    assert cl.own_domains({"website": {"domain": "equinor.com", "verified": True}}, EQUINOR) == {"equinor.com"}
    assert cl.own_domains({}, CanonicalIdentity(org_number="1", legal_name="X AS")) == set()
    assert cl.own_domains({"website": {"domain": "lookalike.no", "verified": False}}, CanonicalIdentity(org_number="1", legal_name="X AS")) == set()


@pytest.mark.parametrize(("checked", "searches", "web_note", "failed", "state", "phrase"), [
    ([], 1, None, False, "no_results", "found nothing that answers"),
    ([{"name": "Regnskapsregisteret (filed annual accounts)", "kind": "official", "state": "unavailable", "reason": "HTTP 503"}], 0,
     "Web search is not configured here (no Tavily key, or search is switched off), so only official registers could be checked.", False, "unavailable", "could not be read (HTTP 503)"),
    ([], 1, "Web search was unavailable (limit) — no paid fallback is used; this is not evidence that nothing exists.", True, "unavailable", "no paid fallback"),
])
def test_the_outcome_says_exactly_why_nothing_was_found(checked: list, searches: int, web_note: str | None, failed: bool, state: str, phrase: str) -> None:
    out = cl.Lookup("no_results", "", checked=checked, searches=searches)
    cl.finish(out, Settings(_env_file=None, app_env="test", tavily_api_key="tvly-x"), web_note, failed)
    assert out.state == state and phrase in out.note and not out.found


def test_a_regulatory_question_searches_the_regulator_allowlist_and_labels_the_stage(net: FixtureNetwork, settings: Settings) -> None:
    settings.tavily_api_key = "tvly-test"
    net.add_site(HOST, {"/vedtak": official("Vedtak om overtredelsesgebyr", "Konkurransetilsynet har vedtatt å ilegge Autobjørn AS (org.nr. 810 359 862) et gebyr.", "2026-08-20")})
    calls: list[dict] = []
    net.handlers.append(tavily([f"https://{HOST}/vedtak"], calls))
    client, _svc = make_client(net, settings, CapturingProvider(None))
    with client as c:
        c.get(f"/api/companies/{AUTO}")
        body = c.post(f"/api/companies/{AUTO}/chat", json={"question": "Has a regulator made any decision about it?"}).json()
    assert calls and "konkurransetilsynet.no" in calls[0]["include_domains"]
    src = [s for s in body["citations"] if s["url"] == f"https://{HOST}/vedtak"]
    assert src and src[0]["sourceClass"] == "government_regulator" and src[0]["publishedAt"] == "2026-08-20" and src[0]["origin"] == "fresh"
