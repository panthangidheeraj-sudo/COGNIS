"""Website identity, version 2: a registry listing or a name-shaped domain is only where a candidate came from. A site is published as the company's own
only when the site (or the domain registry) shows it belongs to this exact legal entity — never a parent group's corporate site."""
from __future__ import annotations

import asyncio
from typing import Any

from conftest import research
from test_free_sources import AUTO

from app.config import Settings, override_settings
from app.connectors.domain_discovery import candidate_domains
from app.identity.model import CanonicalIdentity
from app.testing.fixtures import FixtureNetwork, company_page, verified_site

NAME = "AUTOBJØRN A/S"


def run(net: FixtureNetwork, **kw: Any) -> dict[str, Any]:
    return asyncio.run(research(net, AUTO, provider=None, **kw))


def net_with(host: str, pages: dict[str, str], *, robots: str | None = None) -> FixtureNetwork:
    net = FixtureNetwork()
    net.load_brreg_probes()
    net.add_site(host, pages, robots=robots)
    return net


def website_claim(rec: dict[str, Any]) -> dict[str, Any] | None:
    return next((c for c in rec["claims"] if c["field"] == "official_website" and c["availability"] == "available"), None)


def attempts(rec: dict[str, Any], origin: str | None = None) -> list[dict[str, Any]]:
    return [a for a in rec["site_attempts"] if origin is None or a["origin"] == origin]


def test_a_registry_listed_site_that_only_repeats_the_name_is_not_published(settings: Settings) -> None:
    pages = {"/": company_page("Velkommen", "<h1>Velkommen til AUTOBJØRN A/S</h1><p>Din lokale bilforhandler med bredt utvalg av nye og brukte biler, verksted og delelager. "
                                                  "Vi har solgt biler til privatkunder og bedrifter i over tretti år og tar oss av hele prosessen fra finansiering til levering.</p>",
                                  links=[("/kontakt", "Kontakt")]),
             "/kontakt": company_page("Kontakt", "<p>Ta kontakt med oss for en uforpliktende prat om bil, finansiering og service. Vi svarer innen en arbeidsdag.</p>")}
    rec = run(net_with("autobjorn.no", pages))
    assert website_claim(rec) is None
    a = attempts(rec, "registry")[0]
    assert a["decision"] == "ambiguous" and a["signals"] in (["legal_name_on_site"], ["legal_name_on_site", "brand_tokens_on_site"])
    assert rec["modules"]["website"]["state"] == "ambiguous"
    assert rec["website"]["audit"]["context_signals"] and "registry_listed_website" in rec["website"]["audit"]["context_signals"]
    assert "not enough evidence" in " ".join(rec["website"]["audit"]["reasons"])


def test_a_site_with_the_organisation_number_is_published_and_the_signals_are_stored(settings: Settings) -> None:
    rec = run(net_with("autobjorn.no", verified_site(NAME, AUTO)))
    claim = website_claim(rec)
    assert claim is not None
    audit = rec["website"]["audit"]
    assert audit["decision"] == "verified" and "org_number_on_site" in audit["signals"] and audit["evidence"]["org_number_on_site"]


def test_a_group_website_listing_several_legal_entities_is_not_published_as_the_companys_own(settings: Settings) -> None:
    footer = "AUTOBJØRN A/S Org.nr. 810 359 862 · Bilutleie AS Org.nr. 923 609 016 · Lager Drammen AS Org.nr. 914 778 271"
    pages = {"/": company_page("Bilgruppen", "<h1>Bilgruppen</h1><p>Våre selskaper.</p>", footer=footer, links=[("/kontakt", "Kontakt")]),
             "/kontakt": company_page("Kontakt", "<p>Hovedkontor</p>", footer=footer)}
    rec = run(net_with("autobjorn.no", pages))
    assert website_claim(rec) is None
    audit = rec["website"]["audit"]
    assert audit["scope"] == "group" and audit["decision"] == "ambiguous"
    assert any("group website" in c for c in audit["conflicts"]) and "multi-entity" in " ".join(audit["reasons"])


def test_a_site_showing_another_organisation_number_is_rejected_with_the_reason_kept(settings: Settings) -> None:
    pages = {"/": company_page("AUTOBJØRN", "<h1>AUTOBJØRN A/S</h1>", footer="AUTOBJØRN A/S · Org.nr. 923 609 016", links=[("/kontakt", "Kontakt")]),
             "/kontakt": company_page("Kontakt", "<p>Org.nr. 923 609 016</p>")}
    rec = run(net_with("autobjorn.no", pages))
    assert website_claim(rec) is None
    a = attempts(rec, "registry")[0]
    assert a["decision"] != "verified" and any("different organisation number" in c for c in a["conflicts"])


def test_name_derived_candidates_are_proposed_for_generic_names_never() -> None:
    ident = CanonicalIdentity(org_number="810359862", legal_name="AUTOBJØRN A/S")
    cands = candidate_domains(ident)
    assert cands[0] == "autobjorn.no" and "autobjorn.com" in cands and len(cands) <= 4
    assert candidate_domains(ident, exclude={"autobjorn.no"})[0] != "autobjorn.no"
    assert candidate_domains(CanonicalIdentity(org_number="1", legal_name="Norsk Bygg AS")) == []
    assert candidate_domains(CanonicalIdentity(org_number="1", legal_name=None)) == []


def test_keyless_discovery_finds_and_verifies_the_real_site_when_the_registry_one_is_dead(settings: Settings) -> None:
    net = net_with("autobjorn.com", verified_site(NAME, AUTO))  # registry-listed autobjorn.no does not exist on this network
    rec = run(net)
    claim = website_claim(rec)
    assert claim is not None and claim["value"].rstrip("/") in ("https://www.autobjorn.com", "https://autobjorn.com")
    found = [a for a in attempts(rec, "name_derived") if a["decision"] == "verified"]
    assert found and "org_number_on_site" in found[0]["signals"]
    assert not [u for u in net.requests if "tavily" in u]


def test_a_name_shaped_domain_that_belongs_to_someone_else_is_rejected_not_published(settings: Settings) -> None:
    other = verified_site("AUTOBJØRN BERGEN A/S", "923609016")  # a different legal entity on the guessed domain
    rec = run(net_with("autobjorn.com", other))
    assert website_claim(rec) is None
    guessed = [a for a in attempts(rec, "name_derived") if a["domain"] == "autobjorn.com"]
    assert guessed and guessed[0]["decision"] in ("rejected", "ambiguous") and guessed[0]["conflicts"]


def test_guessed_domains_respect_robots_txt(settings: Settings) -> None:
    net = net_with("autobjorn.com", verified_site(NAME, AUTO), robots="User-agent: *\nDisallow: /")
    rec = run(net)
    assert website_claim(rec) is None
    assert not [u for u in net.requests if u.startswith("https://autobjorn.com/") and not u.endswith("robots.txt")]
    assert not [u for u in net.requests if u.startswith("https://www.autobjorn.com/") and not u.endswith("robots.txt")]


def test_an_unreachable_guess_is_a_diagnostic_never_the_website_module(settings: Settings) -> None:
    rec = run(net_with("unrelated.example", verified_site("Annen AS", "923609016")))
    assert website_claim(rec) is None
    assert all(a["decision"] != "verified" for a in rec["site_attempts"])
    assert "name-derived domain(s) were tried and none could be read" in (rec["modules"]["website"].get("note") or "") or rec["modules"]["website"]["state"] in ("failed", "blocked", "not_available", "ambiguous")
