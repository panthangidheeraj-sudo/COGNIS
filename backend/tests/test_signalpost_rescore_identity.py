"""Signalpost re-scoring: wrong-company website attribution (evaluator feedback on commit 408d9a4: 17 of 29 checked claims correct, 12 about another company).

The two exact failures reported by the evaluator and the class they belong to:

* VESTSIDEN HAGEBY IV BORETTSLAG (888078622) — https://www.gbbl.no/ is Grenland Boligbyggelag, the housing association that manages it;
* ALFHEIM 25-39 EIERSEKSJONSSAMEIE (891990472) — https://styrerommet.no/ is an OBOS board-portal platform.

The fixtures below are *synthetic* pages that reproduce the structure of those sites (a manager's / portal's identity, a list of the entities it administers, the
manager's shared contact details). They are not captures of the live sites: the live check has to be run from a machine with network access.

The class: a name, address, telephone number or e-mail address that appears somewhere on a page proves nothing about who owns the site. Only the site presenting itself
as the entity, the exact organisation number in its own identity, or the Norid domain-holder does.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from conftest import research

from app.competition.envelope import build_envelope
from app.config import Settings
from app.extraction.html import parse_html
from app.identity.match import audit_site, is_shared_management_entity
from app.identity.model import CanonicalIdentity
from app.testing.fixtures import FixtureNetwork, company_page, synthetic_entity, synthetic_roles

VESTSIDEN_ORG, VESTSIDEN_NAME = "888078622", "VESTSIDEN HAGEBY IV BORETTSLAG"
ALFHEIM_ORG, ALFHEIM_NAME = "891990472", "ALFHEIM 25-39 EIERSEKSJONSSAMEIE"
MANAGER_ORG = "974760673"  # a manager's own organisation number (checksum-valid stand-in)

OTHER_COOPS = ["SKIEN BOLIG BORETTSLAG", "FALKUM TERRASSE BORETTSLAG", "HERKULES BORETTSLAG", "BRATSBERG BORETTSLAG", "HEISTAD SAMEIE"]
MEMBER_LIST = "".join(f"<li>{n}</li>" for n in [VESTSIDEN_NAME, *OTHER_COOPS])
WEBSITE_DERIVED_FIELDS = {"official_website", "website_title", "website_description", "business_description", "contact_email", "contact_phone", "logo_url", "reported_employees",
                          "job_posting", "open_positions_count", "careers_page", "news_page", "about_page", "contact_page", "products_page", "team_page", "locations_page",
                          "investors_page", "sustainability_page", "news_item", "company_news"}


def manager_site(*, org_in_footer: bool = False) -> dict[str, str]:
    """Grenland Boligbyggelag-style housing association: its own identity, a list of its member cooperatives and its shared office address and telephone."""
    footer = "Grenland Boligbyggelag" + (f" · Org.nr. {MANAGER_ORG[:3]} {MANAGER_ORG[3:6]} {MANAGER_ORG[6:]}" if org_in_footer else "")
    links = [("/kontakt", "Kontakt"), ("/karriere", "Karriere"), ("/nyheter", "Nyheter")]
    return {
        "/": company_page("Grenland Boligbyggelag", f"<h1>Grenland Boligbyggelag</h1><p>Vi forvalter borettslag og sameier i Grenland. Våre borettslag:</p><ul>{MEMBER_LIST}</ul>",
                          footer=footer, links=links),
        "/kontakt": company_page("Kontakt Grenland Boligbyggelag", "<h1>Kontakt</h1><p>Storgata 117, 3721 Skien. Telefon 35 90 30 00. E-post <a href=\"mailto:post@gbbl.no\">post@gbbl.no</a></p>",
                                 footer=footer, links=links),
        "/karriere": company_page("Karriere", "<h1>Ledige stillinger</h1><p>Rådgiver forretningsfører — ledig nå.</p>", footer=footer, links=links),
        "/nyheter": company_page("Nyheter", "<article><time datetime=\"2026-10-01\">1. oktober 2026</time><h2>Nytt styreseminar i Skien</h2></article>", footer=footer, links=links),
    }


def portal_site() -> dict[str, str]:
    """Styrerommet-style board-portal platform: a product page naming the boards that use it, with the managing company's shared contact details."""
    names = "".join(f"<li>{n}</li>" for n in [ALFHEIM_NAME, "SOLBAKKEN SAMEIE", "LINDEBERG BORETTSLAG", "NORDSTRAND BORETTSLAG", "BJERKE EIERSEKSJONSSAMEIE"])
    links = [("/kontakt", "Kontakt"), ("/om-oss", "Om oss")]
    return {
        "/": company_page("Styrerommet – digitalt styrerom for borettslag og sameier", f"<h1>Styrerommet</h1><p>Det digitale styrerommet for styret. Styrer som bruker oss:</p><ul>{names}</ul>",
                          footer="Styrerommet — en tjeneste for borettslag og sameier", links=links),
        "/kontakt": company_page("Kontakt Styrerommet", "<h1>Kontakt</h1><p>Hammersborg torg 1, 0179 Oslo. Telefon 22 86 55 00.</p>", footer="Styrerommet", links=links),
        "/om-oss": company_page("Om Styrerommet", "<h1>Om oss</h1><p>Styrerommet er et styreverktøy for borettslag og sameier.</p>", footer="Styrerommet", links=links),
    }


def housing_net(org: str, name: str, form: str, *, host: str, pages: dict[str, str], address: str, phone: str, email: str, registry_site: str | None = None,
                robots: str | None = None) -> FixtureNetwork:
    net = FixtureNetwork()
    net.load_brreg_probes()
    entity = synthetic_entity({"organisation_number": org, "name": name, "legal_form": form, "municipality": "Skien", "municipality_number": "4001"}, website=registry_site, email=email)
    entity["forretningsadresse"] = {"adresse": [address], "postnummer": "3721", "poststed": "SKIEN", "kommune": "SKIEN", "kommunenummer": "4001", "land": "Norge", "landkode": "NO"}
    entity["telefon"] = phone
    entity["organisasjonsform"] = {"kode": form, "beskrivelse": {"BRL": "Borettslag", "ESEK": "Eierseksjonssameie", "SAM": "Tingsrettslig sameie"}.get(form, form)}
    entity["erIKonsern"] = False
    net.register_company(org, entity=entity, roles=synthetic_roles(3), accounts=[], subunits={"_embedded": {"underenheter": []}, "page": {"totalElements": 0}})
    net.add_site(host, pages, robots=robots)
    return net


def run(net: FixtureNetwork, org: str) -> dict[str, Any]:
    return asyncio.run(research(net, org, provider=None))


def website_derived_claims(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in record["claims"] if c["availability"] == "available" and (c["field"] in WEBSITE_DERIVED_FIELDS or c["field"].startswith("social_profile_"))]


def assert_nothing_from_the_wrong_site(record: dict[str, Any], forbidden_host: str) -> None:
    assert not website_derived_claims(record), [c["field"] for c in website_derived_claims(record)]
    env = build_envelope(record, run_id="test")
    published = [c for c in env["claims"] if c.get("availability") == "available"]
    # the register's own e-mail address (post@gbbl.no) is a registry fact about the entity; every other published claim must be free of the wrong site
    about_site = [c for c in published if c["field"] != "registered_email"]
    assert forbidden_host not in json.dumps(about_site), "the wrong site appears in a published claim"
    assert forbidden_host not in json.dumps([e for e in env["evidence"] if any(e["id"] in (c.get("evidence_ids") or []) for c in about_site)])
    assert "registered_website" not in {c["field"] for c in published}
    assert record["website"] is None or not record["website"]["verified"]
    assert not [a for a in record["site_attempts"] if a["decision"] == "verified"]
    assert "official_website" not in {c["field"] for c in published}
    # no dependent social / news / jobs claim either
    assert not [c for c in published if c["field"].startswith(("social_profile", "news", "job_posting", "open_positions"))], [c["field"] for c in published]


# --------------------------------------------------------------------------------------- the two exact failures, end to end through the pipeline --
def test_gbbl_is_not_published_as_vestsiden_hageby_iv_website(settings: Settings) -> None:
    """The registry lists www.gbbl.no for the cooperative and its registered address / telephone / e-mail are the manager's: still not the cooperative's website."""
    net = housing_net(VESTSIDEN_ORG, VESTSIDEN_NAME, "BRL", host="gbbl.no", pages=manager_site(), address="Storgata 117", phone="35903000", email="post@gbbl.no",
                      registry_site="www.gbbl.no")
    rec = run(net, VESTSIDEN_ORG)
    assert_nothing_from_the_wrong_site(rec, "gbbl.no")
    attempt = next(a for a in rec["site_attempts"] if a["domain"] == "gbbl.no")
    assert attempt["decision"] in ("ambiguous", "rejected")
    audit = rec["website"]["audit"]
    assert audit["scope"] == "manager" and audit["presents_entity"] is False and audit["risk"] == "shared_management_entity"
    assert {"registered_address_on_site", "registered_phone_on_site"} <= set(audit["shared_signals"])  # found, but not counted
    assert "registered_address_on_site" not in audit["signals"] and "registered_phone_on_site" not in audit["signals"]


def test_styrerommet_is_not_published_as_alfheim_website(settings: Settings) -> None:
    """The cooperative's registered e-mail is on the portal's domain (so the domain is proposed as a candidate): still the portal's website, not the sameie's."""
    net = housing_net(ALFHEIM_ORG, ALFHEIM_NAME, "ESEK", host="styrerommet.no", pages=portal_site(), address="Hammersborg torg 1", phone="22865500",
                      email="alfheim25-39@styrerommet.no")
    rec = run(net, ALFHEIM_ORG)
    assert_nothing_from_the_wrong_site(rec, "styrerommet.no")
    attempt = next(a for a in rec["site_attempts"] if a["domain"] == "styrerommet.no")
    assert attempt["decision"] in ("ambiguous", "rejected") and attempt["origin"] == "email_domain"
    assert rec["website"]["audit"]["scope"] == "manager"
    assert "registered_email_domain" in rec["website"]["audit"]["context_signals"] and "registered_email_domain" not in rec["website"]["audit"]["signals"]


def test_the_failed_sites_do_not_publish_even_when_the_manager_shows_its_own_organisation_number(settings: Settings) -> None:
    net = housing_net(VESTSIDEN_ORG, VESTSIDEN_NAME, "BRL", host="gbbl.no", pages=manager_site(org_in_footer=True), address="Storgata 117", phone="35903000", email="post@gbbl.no",
                      registry_site="www.gbbl.no")
    rec = run(net, VESTSIDEN_ORG)
    assert_nothing_from_the_wrong_site(rec, "gbbl.no")


def test_the_envelope_reports_the_website_as_unavailable_not_as_a_wrong_value(settings: Settings) -> None:
    net = housing_net(VESTSIDEN_ORG, VESTSIDEN_NAME, "BRL", host="gbbl.no", pages=manager_site(), address="Storgata 117", phone="35903000", email="post@gbbl.no", registry_site="www.gbbl.no")
    env = build_envelope(run(net, VESTSIDEN_ORG), run_id="test")
    site_claims = [c for c in env["claims"] if c["field"] == "official_website"]
    assert site_claims and all(c["availability"] != "available" and c.get("value") is None for c in site_claims)
    assert env["modules"]["website"]["state"] != "complete" or env["modules"]["website"]["availability"] != "available"
    assert env["website_attempts"] and all(a["decision"] != "verified" for a in env["website_attempts"])


# ------------------------------------------------------------------------------------------------------------ unit level: the identity decision --
def _page(title: str, body: str, *, footer: str = "", url: str = "https://example.no/", h1: str | None = None) -> Any:
    h = f"<h1>{h1}</h1>" if h1 else ""
    return parse_html(url, url, f"<html><head><title>{title}</title></head><body>{h}<main>{body}</main><footer>{footer}</footer></body></html>",
                      retrieved_at="2026-11-10T00:00:00Z", content_sha256="x")


def coop(form: str = "BRL", name: str = VESTSIDEN_NAME, org: str = VESTSIDEN_ORG, **kw: Any) -> CanonicalIdentity:
    return CanonicalIdentity(org_number=org, legal_name=name, legal_form=form, email=kw.get("email", "post@forvalter.no"), phone=kw.get("phone", "35903000"),
                             business_address={"adresse": [kw.get("address", "Storgata 117")], "postnummer": "3721"})


def test_a_shared_manager_address_and_telephone_cannot_establish_cooperative_ownership() -> None:
    """Name + address + telephone + e-mail all appear on the manager's contact page; the register-linked threshold used to be reached with name + address alone."""
    ident = coop()
    pages = [_page("Eiendomsforvalter AS", "<p>Vi forvalter borettslag.</p>", footer="Eiendomsforvalter AS", url="https://forvalter.no/"),
             _page("Kontakt", f"<p>{VESTSIDEN_NAME}, Storgata 117, 3721 Skien. Telefon 35 90 30 00. post@forvalter.no</p>", footer="Eiendomsforvalter AS", url="https://forvalter.no/kontakt")]
    audit = audit_site(ident, pages, "forvalter.no", registry_linked=True)
    assert audit.decision != "verified"
    assert not {"registered_address_on_site", "registered_phone_on_site", "registered_email_on_site"} & set(audit.signals)
    assert {"registered_address_on_site", "registered_phone_on_site", "registered_email_on_site"} <= set(audit.shared_signals)


@pytest.mark.parametrize("form,name,org", [("BRL", VESTSIDEN_NAME, VESTSIDEN_ORG), ("ESEK", ALFHEIM_NAME, ALFHEIM_ORG), ("SAM", "HEISTAD SAMEIE", "923609016")])
def test_housing_entities_need_the_organisation_number_or_the_domain_holder_not_contact_details(form: str, name: str, org: str) -> None:
    """Even the entity's own pages (name in the title and headings, registered address and telephone) are not enough for a cooperative / sameie."""
    ident = coop(form, name, org)
    pages = [_page(name, f"<p>Velkommen til {name}. Storgata 117, 3721 Skien. Telefon 35 90 30 00. post@forvalter.no</p>", footer=name, h1=name)]
    audit = audit_site(ident, pages, "example.no", registry_linked=True)
    assert audit.presents_entity and audit.decision == "ambiguous" and audit.risk == "shared_management_entity"
    assert "cannot be established" in " ".join(audit.reasons)


@pytest.mark.parametrize("form,name,org", [("BRL", VESTSIDEN_NAME, VESTSIDEN_ORG), ("ESEK", ALFHEIM_NAME, ALFHEIM_ORG)])
def test_a_genuine_housing_entity_site_with_exact_organisation_number_is_accepted(form: str, name: str, org: str) -> None:
    ident = coop(form, name, org)
    spaced = f"{org[:3]} {org[3:6]} {org[6:]}"
    pages = [_page(name, f"<p>Velkommen til {name}.</p>", footer=f"{name} · Org.nr. {spaced}", h1=name)]
    audit = audit_site(ident, pages, "example.no", registry_linked=True)
    assert audit.decision == "verified" and "org_number_on_site" in audit.signals and audit.scope == "company"


def test_a_genuine_housing_entity_site_with_a_norid_domain_holder_match_is_accepted() -> None:
    ident = coop()
    pages = [_page(VESTSIDEN_NAME, f"<p>{VESTSIDEN_NAME}</p>", footer=VESTSIDEN_NAME, h1=VESTSIDEN_NAME)]
    audit = audit_site(ident, pages, "vestsiden4.no", norid_holder_org=VESTSIDEN_ORG)
    assert audit.decision == "verified" and "norid_holder_match" in audit.signals


def test_a_norid_domain_holder_naming_the_manager_rejects_the_site() -> None:
    ident = coop()
    pages = [_page("Grenland Boligbyggelag", f"<ul><li>{VESTSIDEN_NAME}</li></ul>", footer="Grenland Boligbyggelag", url="https://gbbl.no/")]
    audit = audit_site(ident, pages, "gbbl.no", registry_linked=True, norid_holder_org=MANAGER_ORG)
    assert audit.decision == "rejected" and any("domain holder is organisation" in c for c in audit.conflicts)


def test_an_organisation_number_inside_a_member_list_is_not_ownership() -> None:
    """A manager that lists only this one cooperative with its organisation number (no group listing) is still not the cooperative's site."""
    ident = coop()
    pages = [_page("Grenland Boligbyggelag", f"<table><tr><td>{VESTSIDEN_NAME}</td><td>Org.nr. 888 078 622</td></tr></table>", footer="Grenland Boligbyggelag", url="https://gbbl.no/")]
    audit = audit_site(ident, pages, "gbbl.no", registry_linked=True)
    assert audit.decision != "verified" and "org_number_on_site" not in audit.signals and "org_number_on_site" in audit.shared_signals


@pytest.mark.parametrize("title,footer", [
    ("Nordmann Forretningsførsel AS", "Nordmann Forretningsførsel AS"),   # property-management firm
    ("Boligbygg Vest", "Boligbygg Vest — boligbyggelag"),                 # housing association
    ("Min side – beboerportal", "Beboerportal for borettslag"),           # resident portal
    ("Styreportalen", "Styreportalen — digitalt styrerom"),               # board-management platform
])
def test_manager_portal_and_platform_sites_are_never_the_cooperatives(title: str, footer: str) -> None:
    ident = coop()
    pages = [_page(title, f"<p>Kontakt: Storgata 117, 3721 Skien, telefon 35 90 30 00. {VESTSIDEN_NAME} er blant våre kunder.</p>", footer=footer, url="https://manager.no/")]
    audit = audit_site(ident, pages, "manager.no", registry_linked=True)
    assert audit.decision != "verified" and audit.scope in ("manager", "unknown", "company")  # never published
    assert audit.decision in ("ambiguous", "rejected") and not audit.presents_entity


def test_a_member_list_of_several_housing_entities_marks_the_site_as_a_manager() -> None:
    ident = coop()
    listing = "".join(f"<li>{n}</li>" for n in [VESTSIDEN_NAME, *OTHER_COOPS])
    pages = [_page("Velkommen", f"<p>Våre kunder:</p><ul>{listing}</ul><p>Storgata 117, 3721 Skien</p>", footer="Velkommen", url="https://kundeliste.no/")]
    audit = audit_site(ident, pages, "kundeliste.no", registry_linked=True)
    assert audit.scope == "manager" and audit.decision != "verified" and "member / customer list" in " ".join(audit.conflicts)


def test_property_management_firm_for_an_ordinary_company_does_not_prove_ownership_either() -> None:
    """The same weakness for an AS: a management / group page that lists the company with its contact details does not make the page the company's website."""
    ident = CanonicalIdentity(org_number="810359862", legal_name="AUTOBJØRN A/S", email="post@gruppe.no", phone="22334455", business_address={"adresse": ["Cecilie Thoresens vei 5-7"]})
    pages = [_page("Bilgruppen Drift AS", "<p>Selskaper vi drifter: AUTOBJØRN A/S, Cecilie Thoresens vei 5-7, 1153 Oslo. Telefon 22 33 44 55. post@gruppe.no</p>", footer="Bilgruppen Drift AS",
                   url="https://gruppe.no/")]
    audit = audit_site(ident, pages, "gruppe.no", registry_linked=True)
    assert audit.decision != "verified" and not audit.presents_entity
    assert {"registered_address_on_site", "registered_phone_on_site", "registered_email_on_site"} <= set(audit.shared_signals)


def test_directories_and_registers_are_rejected_even_with_the_organisation_number() -> None:
    ident = CanonicalIdentity(org_number="810359862", legal_name="AUTOBJØRN A/S")
    pages = [_page("AUTOBJØRN A/S - Proff", "<p>AUTOBJØRN A/S Org.nr. 810 359 862</p>", footer="Proff", url="https://www.proff.no/selskap/autobjorn", h1="AUTOBJØRN A/S")]
    audit = audit_site(ident, pages, "proff.no")
    assert audit.decision == "rejected" and audit.scope == "directory"


def test_the_parent_groups_corporate_site_still_is_not_published() -> None:
    ident = CanonicalIdentity(org_number="810359862", legal_name="AUTOBJØRN A/S", business_address={"adresse": ["Cecilie Thoresens vei 5-7"]})
    page = _page("Bilgruppen ASA", "<p>Datterselskap: AUTOBJØRN A/S. Cecilie Thoresens vei 5-7</p>", footer="Bilgruppen ASA", url="https://group.no/", h1="Bilgruppen ASA")
    audit = audit_site(ident, [page], "group.no", registry_linked=True, related=[{"name": "Bilgruppen ASA", "org": "999999999"}])
    assert audit.decision == "ambiguous" and audit.scope == "group"


# ------------------------------------------------------------------------------------------- coverage is preserved where genuine evidence exists --
def test_a_corporate_site_that_presents_the_company_with_its_registered_address_is_still_accepted() -> None:
    ident = CanonicalIdentity(org_number="810359862", legal_name="AUTOBJØRN A/S", business_address={"adresse": ["Cecilie Thoresens vei 5-7"], "postnummer": "1153"})
    page = _page("Autobjørn", "<p>AUTOBJØRN A/S – Cecilie Thoresens vei 5-7, 1153 Oslo</p>", footer="AUTOBJØRN A/S", url="https://www.autobjorn.no/", h1="Autobjørn")
    audit = audit_site(ident, [page], "autobjorn.no", registry_linked=True)
    assert audit.decision == "verified" and audit.presents_entity and "registered_address_on_site" in audit.signals


def test_a_corporate_site_with_the_organisation_number_in_its_footer_is_accepted_with_no_registry_link() -> None:
    ident = CanonicalIdentity(org_number="810359862", legal_name="AUTOBJØRN A/S")
    page = _page("Forside", "<p>Velkommen</p>", footer="AUTOBJØRN A/S · Org.nr. 810 359 862", url="https://autobjorn.no/")
    assert audit_site(ident, [page], "autobjorn.no").decision == "verified"


def test_a_corporate_site_whose_structured_data_names_the_company_counts_as_presenting_it() -> None:
    ident = CanonicalIdentity(org_number="810359862", legal_name="AUTOBJØRN A/S", phone="22334455")
    html = ('<html><head><title>Forside</title><script type="application/ld+json">{"@type":"Organization","name":"Autobjørn AS","telephone":"+47 22 33 44 55"}</script></head>'
            "<body><p>Ring oss på 22 33 44 55</p></body></html>")
    page = parse_html("https://autobjorn.no/", "https://autobjorn.no/", html, retrieved_at="2026-11-10T00:00:00Z", content_sha256="x")
    audit = audit_site(ident, [page], "autobjorn.no", registry_linked=True)
    assert audit.presents_entity and "registered_phone_on_site" in audit.signals


def test_entity_type_detection() -> None:
    assert is_shared_management_entity(CanonicalIdentity(org_number="1", legal_name="X BORETTSLAG", legal_form="BRL"))
    assert is_shared_management_entity(CanonicalIdentity(org_number="1", legal_name="ALFHEIM 25-39 EIERSEKSJONSSAMEIE"))
    assert is_shared_management_entity(CanonicalIdentity(org_number="1", legal_name="Rolighet Boligsameie", legal_form=None))
    assert not is_shared_management_entity(CanonicalIdentity(org_number="1", legal_name="AUTOBJØRN A/S", legal_form="AS"))


# ----------------------------------------------------------------------------------------------- false-positive audit (accepted / rejected / ambiguous) --
def test_false_positive_audit_counts_every_candidate_and_never_accepts_a_wrong_one(settings: Settings) -> None:
    """The audit a reviewer reads: each candidate with its verdict and the reason. Only the genuine one is accepted."""
    cases = {
        "gbbl.no (manager of the cooperative)": ("manager", audit_site(coop(), [_page("Grenland Boligbyggelag", f"<ul><li>{VESTSIDEN_NAME}</li></ul><p>Storgata 117, 3721 Skien. 35 90 30 00</p>",
                                                                                          footer="Grenland Boligbyggelag", url="https://gbbl.no/")], "gbbl.no", registry_linked=True)),
        "styrerommet.no (portal)": ("manager", audit_site(coop("ESEK", ALFHEIM_NAME, ALFHEIM_ORG), [_page("Styrerommet", f"<ul><li>{ALFHEIM_NAME}</li></ul>", footer="Styrerommet",
                                                                                                       url="https://styrerommet.no/")], "styrerommet.no")),
        "proff.no (directory)": ("directory", audit_site(coop(), [_page(VESTSIDEN_NAME, "Org.nr. 888 078 622", footer="Proff", url="https://proff.no/x", h1=VESTSIDEN_NAME)], "proff.no")),
        "vestsiden4.no (the cooperative's own site)": ("company", audit_site(coop(), [_page(VESTSIDEN_NAME, "", footer=f"{VESTSIDEN_NAME} Org.nr. 888 078 622", h1=VESTSIDEN_NAME,
                                                                                            url="https://vestsiden4.no/")], "vestsiden4.no")),
    }
    table = {label: (audit.decision, audit.scope, audit.reasons[0]) for label, (_scope, audit) in cases.items()}
    accepted = [label for label, (decision, _s, _r) in table.items() if decision == "verified"]
    assert accepted == ["vestsiden4.no (the cooperative's own site)"], table
    assert all(reason for (_d, _s, reason) in table.values())
    for label, (expected_scope, audit) in cases.items():
        assert audit.scope == expected_scope, (label, audit.scope)


def test_the_profile_and_module_value_do_not_present_the_manager_site_as_the_companys(settings: Settings) -> None:
    """The profile JSON must not carry the manager's address or content in the website section either; the diagnosis stays in the envelope diagnostics."""
    from app.api.profile_builder import build_profile  # noqa: PLC0415

    net = housing_net(VESTSIDEN_ORG, VESTSIDEN_NAME, "BRL", host="gbbl.no", pages=manager_site(), address="Storgata 117", phone="35903000", email="post@gbbl.no", registry_site="www.gbbl.no")
    rec = run(net, VESTSIDEN_ORG)
    mod_value = rec["modules"]["website"]["value"]
    assert mod_value["verified"] is False and "title" not in mod_value and "description" not in mod_value and "pages" not in mod_value and "social_links" not in mod_value
    profile = build_profile(rec)
    site = profile["website"]
    assert site["status"] == "not_available" and "url" not in site and "domain" not in site and "gbbl.no" not in json.dumps(site)
    assert "gbbl.no" not in json.dumps(profile.get("identity", {}).get("website", ""))
