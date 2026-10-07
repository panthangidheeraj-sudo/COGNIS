"""Exact-entity identity, the publication gate, conflicts and LLM output validation."""
from __future__ import annotations

import asyncio

from app.agent import llm_tasks
from app.evidence.gate import absences, check, publish
from app.evidence.models import ModuleResult, Observation
from app.extraction.html import parse_html
from app.identity.match import audit_site
from app.identity.model import CanonicalIdentity
from app.identity.normalization import find_org_numbers, org_checksum_ok
from app.providers.fake_provider import FakeProvider

IDENT = CanonicalIdentity(org_number="810359862", legal_name="AUTOBJØRN A/S", website="https://www.autobjorn.no", website_raw="www.autobjorn.no",
                          business_address={"adresse": ["Cecilie Thoresens vei 5-7"], "postnummer": "1153", "kommune": "OSLO"})


def _doc(body: str, url: str = "https://www.autobjorn.no/") -> object:
    return parse_html(url, url, f"<html><head><title>Autobjørn</title></head><body>{body}</body></html>", retrieved_at="2026-10-01T00:00:00Z", content_sha256="abc")


def test_org_number_checksum() -> None:
    assert org_checksum_ok("810359862") and org_checksum_ok("923609016")
    assert not org_checksum_ok("810359863")
    nums = find_org_numbers("Org.nr. 810 359 862 MVA · ring 22 33 44 55")
    assert ("810359862", True) in nums


def test_org_number_on_site_verifies() -> None:
    audit = audit_site(IDENT, [_doc("<footer>AUTOBJØRN A/S · Org.nr. 810 359 862</footer>")], "autobjorn.no")
    assert audit.decision == "verified" and "org_number_on_site" in audit.signals


def test_conflicting_org_number_vetoes_even_with_same_name() -> None:
    """Same-name company: the site shows another organisation number → never verified."""
    audit = audit_site(IDENT, [_doc("<footer>AUTOBJØRN A/S · Org.nr. 923 609 016</footer>")], "autobjorn.no")
    assert audit.decision != "verified" and audit.conflicts


def test_name_only_is_not_enough() -> None:
    audit = audit_site(IDENT, [_doc("<p>Velkommen til AUTOBJØRN A/S</p>", "https://autobjorn-shop.no/")], "autobjorn-shop.no")
    assert audit.decision != "verified"


def test_registry_listed_plus_name_verifies() -> None:
    audit = audit_site(IDENT, [_doc("<p>Velkommen til AUTOBJØRN A/S – din bilforhandler</p>")], "autobjorn.no", registry_linked=True)
    assert audit.decision == "verified"


def test_parked_domain_rejected() -> None:
    audit = audit_site(IDENT, [_doc("This domain is for sale")], "autobjorn.no", registry_linked=True, parked=True)
    assert audit.decision != "verified"


def _obs(**kw) -> Observation:  # noqa: ANN003
    base = dict(field="revenue", value=100.0, module="financials", source_id="accounts", source_name="Regnskapsregisteret", source_class="official_annual_accounts",
                source_url="https://data.brreg.no/regnskapsregisteret/regnskap/810359862", retrieved_at="2026-10-01T00:00:00Z", content_sha256="abc",
                claim_span="sumDriftsinntekter = 100", extraction_method="structured_api", reporting_period="2025-01-01/2025-12-31", numeric=True)
    base.update(kw)
    return Observation(**base)


def test_gate_rules() -> None:
    assert check(_obs()) is None
    assert check(_obs(value=0.0)) is None  # a stated zero is a real value
    assert "period" in check(_obs(reporting_period=None))
    assert "source URL" in check(_obs(source_url=None))
    assert "evidence span" in check(_obs(claim_span=" "))
    assert "candidates" in check(_obs(source_class="search_result", tier="C"))
    assert "identity" in check(_obs(field="official_website", value="https://x.no", source_class="company_owned_discovered", identity_score=0.3, numeric=False,
                                    reporting_period=None))
    assert "quote" in check(_obs(field="business_description", value="We sell cars", extraction_method="llm_quote_verified", numeric=False, reporting_period=None))
    assert "numeric" in check(_obs(value="lots"))


def test_conflict_live_beats_bulk_and_is_recorded() -> None:
    live = _obs(field="registered_employees", value=12, module="registry_live", source_id="brreg", source_class="official_registry_live", reporting_period=None,
                claim_span="antallAnsatte = 12")
    bulk = _obs(field="registered_employees", value=9, module="registry", source_id="brreg", source_class="official_registry_bulk", reporting_period=None,
                claim_span="antallAnsatte = 9", source_url="https://data.brreg.no/enhetsregisteret/api/enheter/lastned")
    claims, _ = publish([bulk, live], "810359862")
    assert len(claims) == 1 and claims[0].value == 12 and claims[0].conflict and claims[0].conflict["resolution"] == "official_registry_live"


def test_absence_states_distinguish_checked_from_unchecked() -> None:
    mods = {"roles": ModuleResult(module="roles", source_id="roles", source_name="r", source_class="official_roles", state="available"),
            "website": ModuleResult(module="website", source_id="website", source_name="w", source_class="company_owned", state="blocked", note="disallowed by robots.txt"),
            "group": ModuleResult(module="group", source_id="group", source_name="g", source_class="official_group_structure", state="not_applicable", note="erIKonsern=false")}
    ab = {a.field: a for a in absences([], mods)}
    assert ab["ceo"].availability == "not_available"  # checked, none registered
    assert ab["official_website"].availability == "blocked"
    assert ab["parent_company"].availability == "not_applicable"


def test_llm_quote_must_exist_on_page() -> None:
    from app.connectors.website import FetchedPage, SiteCrawl
    from app.identity.match import IdentityAudit
    from app.net.http import FetchResult

    doc = _doc("<p>AUTOBJØRN A/S selger og reparerer biler i Oslo og har gjort det siden 1968.</p>", "https://www.autobjorn.no/om-oss")
    crawl = SiteCrawl(start_url="https://www.autobjorn.no", source_class="company_owned", origin="registry", domain="autobjorn.no",
                      pages=[FetchedPage("about", FetchResult("u", "u", 200, "ok"), doc)], audit=IdentityAudit(domain="autobjorn.no", score=1.2, decision="verified"))
    invented = FakeProvider(script={"extract_website": '{"business_description": {"text": "Leading EV maker", "quote": "We build electric aircraft.", "page": "https://www.autobjorn.no/om-oss"}}'})
    assert asyncio.run(llm_tasks.extract_website_facts(llm_tasks.LLMRunner(invented), crawl, IDENT)) == []
    real = FakeProvider(script={"extract_website": '{"business_description": {"text": "Sells and repairs cars in Oslo since 1968.", "quote": "AUTOBJØRN A/S selger og reparerer biler i Oslo og har gjort det siden 1968.", "page": "https://www.autobjorn.no/om-oss"}, "products_services": [{"name": "Flying cars", "quote": "AUTOBJØRN A/S selger og reparerer biler", "page": "x"}]}'})
    obs = asyncio.run(llm_tasks.extract_website_facts(llm_tasks.LLMRunner(real), crawl, IDENT))
    assert [o.field for o in obs] == ["business_description"]  # the invented product name is dropped
    assert obs[0].attributes["quote_verified"] and check(obs[0]) is None


def test_synthesis_rejects_ungrounded_numbers() -> None:
    facts = [("Revenue FY2025: NOK 21.8M", "ev-1"), ("Employees registered: 12", "ev-2")]
    bad = FakeProvider(script={"synthesis": '{"summary": "The company has 250 employees and revenue of NOK 21.8M in FY2025."}'})
    text, method = asyncio.run(llm_tasks.synthesize(llm_tasks.LLMRunner(bad), IDENT, facts))
    assert text is None and method == "rejected"
    good = FakeProvider(script={"synthesis": '{"summary": "AUTOBJØRN A/S reported revenue of NOK 21.8M in FY2025 and has 12 registered employees."}'})
    text, method = asyncio.run(llm_tasks.synthesize(llm_tasks.LLMRunner(good), IDENT, facts))
    assert method == "llm_grounded" and "21.8M" in text


def test_malformed_llm_output_falls_back() -> None:
    runner = llm_tasks.LLMRunner(FakeProvider(malformed=True))
    text, method = asyncio.run(llm_tasks.synthesize(runner, IDENT, [("Revenue FY2025: NOK 21.8M", "ev-1")]))
    assert text is None and runner.errors


def test_planner_only_accepts_offered_actions() -> None:
    sneaky = FakeProvider(script={"plan": '{"actions": [{"tool": "fetch_page", "arg": "http://169.254.169.254/", "reason": "x"}, {"tool": "fetch_page", "arg": "https://www.autobjorn.no/karriere", "reason": "jobs"}]}'})
    chosen = asyncio.run(llm_tasks.plan_actions(llm_tasks.LLMRunner(sneaky), IDENT, [], ["careers"],
                                                [{"tool": "fetch_page", "arg": "https://www.autobjorn.no/karriere", "hint": "careers"}], "10 requests", 2))
    assert chosen == [{"tool": "fetch_page", "arg": "https://www.autobjorn.no/karriere", "reason": "jobs"}]
