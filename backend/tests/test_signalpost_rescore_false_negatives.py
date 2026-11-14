"""Signalpost re-scoring: the false-negative side. The stricter website-identity rules must keep accepting legitimate company-owned sites.

``test_signalpost_rescore_identity.py`` proves the wrong sites are not published. This module pins the other direction on synthetic pages (no live site was contacted):
the evidence that genuinely shows a site belongs to the entity still verifies it, for companies (AS) and for BRL / ESEK / SAM entities, and the cases that stay
ambiguous are written down so any later change in coverage is a deliberate one. It also adds adversarial cases (a portal or parent that links to the entity).

Measured against the previous matcher (commit ea05bf8) on the same synthetic pages, the only company case whose decision changed is a site that shows the legal name and the
registered address only in a body paragraph (the member-list pattern); every other case below behaves as before.
"""
from __future__ import annotations

import pytest
from test_signalpost_rescore_identity import ALFHEIM_NAME, ALFHEIM_ORG, VESTSIDEN_NAME, VESTSIDEN_ORG, _page, coop, housing_net, run

from app.extraction.html import parse_html
from app.identity.match import audit_site
from app.identity.model import CanonicalIdentity

NAME, ORG = "AUTOBJØRN A/S", "810359862"
HOUSING = [("BRL", VESTSIDEN_NAME, VESTSIDEN_ORG), ("ESEK", ALFHEIM_NAME, ALFHEIM_ORG), ("SAM", "HEISTAD SAMEIE", "923609016")]


def company(**kw: str) -> CanonicalIdentity:
    address = kw.get("address")
    return CanonicalIdentity(org_number=ORG, legal_name=NAME, legal_form="AS", email=kw.get("email"), phone=kw.get("phone"),
                             business_address={"adresse": [address], "postnummer": "1153"} if address else None)


def site(title: str, body: str, footer: str = "", h1: str = "") -> list:
    return [_page(title, body, footer=footer, h1=h1, url="https://autobjorn.no/")]


# ------------------------------------------------------------------------------------------------ legitimate company sites are still verified --
@pytest.mark.parametrize("label,pages,ident", [
    ("exact name in the title + the registered address", site(NAME, "<p>Cecilie Thoresens vei 5-7, 1153 Oslo</p>"), company(address="Cecilie Thoresens vei 5-7")),
    ("exact name in the main heading + the registered address", site("Forside", "<p>Cecilie Thoresens vei 5-7</p>", h1=NAME), company(address="Cecilie Thoresens vei 5-7")),
    ("exact name in the footer + the registered telephone", site("Forside", "<p>Ring 22 33 44 55</p>", footer=f"© 2026 {NAME}"), company(phone="22334455")),
    ("exact name in the title + the registered e-mail address", site(NAME, "<p>Kontakt post@autobjorn.no</p>"), company(email="post@autobjorn.no")),
])
def test_company_sites_that_present_the_entity_with_registry_corroboration_are_verified(label: str, pages: list, ident: CanonicalIdentity) -> None:
    audit = audit_site(ident, pages, "autobjorn.no", registry_linked=True)
    assert audit.decision == "verified" and audit.scope == "company" and audit.presents_entity, (label, audit.reasons)


def test_a_site_whose_structured_data_names_the_company_and_shows_its_address_is_verified() -> None:
    html = ('<html><head><title>Forside</title><script type="application/ld+json">{"@type":"Organization","name":"AUTOBJØRN A/S",'
            '"address":{"streetAddress":"Cecilie Thoresens vei 5-7"}}</script></head><body><p>Cecilie Thoresens vei 5-7</p></body></html>')
    page = parse_html("https://autobjorn.no/", "https://autobjorn.no/", html, retrieved_at="2026-11-10T00:00:00Z", content_sha256="x")
    assert audit_site(company(address="Cecilie Thoresens vei 5-7"), [page], "autobjorn.no", registry_linked=True).decision == "verified"


def test_a_legitimate_site_with_different_contact_details_is_verified_by_its_organisation_number() -> None:
    """The register's address / telephone are often out of date or the head office's: the organisation number in the site's own footer is enough."""
    ident = company(address="Gammel gate 1", phone="99999999")
    pages = site("Forside", "<p>Besøk oss i Nygata 5.</p>", footer=f"{NAME} · Org.nr. 810 359 862")
    audit = audit_site(ident, pages, "autobjorn.no", registry_linked=True)
    assert audit.decision == "verified" and "org_number_on_site" in audit.signals and not audit.conflicts


def test_a_verified_norid_domain_holder_verifies_even_when_the_pages_do_not_show_the_name() -> None:
    audit = audit_site(company(), site("Bilsalg", "<p>Biler til salgs</p>"), "autobjorn.no", norid_holder_org=ORG)
    assert audit.decision == "verified" and "norid_holder_match" in audit.signals


def test_a_normal_site_template_that_repeats_the_company_name_in_navigation_is_not_mistaken_for_a_member_list() -> None:
    pages = [_page(NAME, f"<nav><a href='/om'>Om oss</a><a href='/kontakt'>Kontakt</a></nav><p>{NAME} selger og leaser biler. Cecilie Thoresens vei 5-7.</p>", footer=NAME,
                   url="https://autobjorn.no/")]
    audit = audit_site(company(address="Cecilie Thoresens vei 5-7"), pages, "autobjorn.no", registry_linked=True)
    assert audit.decision == "verified" and audit.scope == "company"


# --------------------------------------------------------------- housing entities (BRL / ESEK / SAM): accepted with the right evidence, never without --
@pytest.mark.parametrize("form,name,org", HOUSING)
def test_housing_entity_with_the_organisation_number_in_its_footer_is_verified_even_with_different_contact_details(form: str, name: str, org: str) -> None:
    ident = coop(form, name, org, address="Annen gate 5", phone="99999999")
    pages = [_page(name, "<p>Velkommen. Storgata 1.</p>", footer=f"{name} · Org.nr. {org[:3]} {org[3:6]} {org[6:]}", h1=name, url="https://example.no/")]
    assert audit_site(ident, pages, "example.no", registry_linked=True).decision == "verified"


@pytest.mark.parametrize("form,name,org", HOUSING)
def test_housing_entity_with_an_organisation_number_line_on_its_own_page_is_verified(form: str, name: str, org: str) -> None:
    pages = [_page(name, f"<p>Org.nr. {org}</p>", footer=name, h1=name, url="https://example.no/")]
    assert audit_site(coop(form, name, org), pages, "example.no", registry_linked=True).decision == "verified"


@pytest.mark.parametrize("form,name,org", HOUSING)
def test_housing_entity_with_a_norid_holder_match_is_verified(form: str, name: str, org: str) -> None:
    pages = [_page(name, f"<p>{name}</p>", footer=name, h1=name, url="https://example.no/")]
    assert audit_site(coop(form, name, org), pages, "example.no", norid_holder_org=org).decision == "verified"


@pytest.mark.parametrize("form,name,org", HOUSING)
def test_housing_entity_that_shows_only_its_name_and_the_registered_contact_details_stays_ambiguous_by_design(form: str, name: str, org: str) -> None:
    """The documented coverage trade-off: contact details are routinely the manager's, so a cooperative site needs its organisation number or the domain holder."""
    pages = [_page(name, "<p>Storgata 117, 3721 Skien. Telefon 35 90 30 00</p>", footer=name, h1=name, url="https://example.no/")]
    audit = audit_site(coop(form, name, org), pages, "example.no", registry_linked=True)
    assert audit.decision == "ambiguous" and audit.presents_entity and not audit.conflicts


# ------------------------------------------------------------------------------- documented limits: name-only company sites stay ambiguous --
@pytest.mark.parametrize("pages", [
    site(NAME, "<p>Velkommen</p>"),
    site("Forside", "<p>Hei</p>", footer=NAME, h1=NAME),
])
def test_a_company_site_that_shows_only_the_legal_name_stays_ambiguous_as_before(pages: list) -> None:
    """Unchanged from the previous matcher: a name alone (0.35 + brand 0.20) is below the 0.65 threshold. It is a coverage limit, not a regression."""
    audit = audit_site(company(), pages, "autobjorn.no", registry_linked=True)
    assert audit.decision == "ambiguous" and not audit.conflicts


# ------------------------------------------------------------------------------------------------------------------------- adversarial cases --
def test_a_parent_company_portal_that_links_to_the_entity_does_not_verify_it() -> None:
    page = _page("Bilgruppen ASA", f"<p>Datterselskap: <a href='https://autobjorn.no/'>{NAME}</a>, Cecilie Thoresens vei 5-7, 1153 Oslo. Org.nr. 810 359 862</p>",
                 footer="Bilgruppen ASA", url="https://bilgruppen.no/")
    audit = audit_site(company(address="Cecilie Thoresens vei 5-7"), [page], "bilgruppen.no", registry_linked=True)
    assert audit.decision != "verified" and not audit.presents_entity and "org_number_on_site" not in audit.signals


def test_an_organisation_number_in_a_customer_table_of_an_ordinary_company_site_is_not_ownership() -> None:
    page = _page("Regnskapsbyrå Nord AS", f"<table><tr><td>{NAME}</td><td>Org.nr. 810 359 862</td></tr><tr><td>Annen Kunde AS</td><td>Org.nr. 923 609 016</td></tr></table>",
                 footer="Regnskapsbyrå Nord AS", url="https://regnskap.no/")
    audit = audit_site(company(), [page], "regnskap.no", registry_linked=True)
    assert audit.decision != "verified" and "org_number_on_site" not in audit.signals


def test_a_portal_that_names_the_cooperative_with_its_organisation_number_in_a_list_item_is_not_ownership() -> None:
    page = _page("Styreportalen", f"<ul><li>{VESTSIDEN_NAME} (org.nr. {VESTSIDEN_ORG})</li><li>SOLBAKKEN SAMEIE</li></ul>", footer="Styreportalen — digitalt styrerom", url="https://portal.no/")
    audit = audit_site(coop(), [page], "portal.no", registry_linked=True)
    assert audit.decision != "verified" and "org_number_on_site" not in audit.signals


def test_a_registry_listed_url_held_by_another_organisation_is_rejected() -> None:
    page = _page(NAME, "<p>Cecilie Thoresens vei 5-7</p>", footer=NAME, url="https://autobjorn.no/")
    audit = audit_site(company(address="Cecilie Thoresens vei 5-7"), [page], "autobjorn.no", registry_linked=True, norid_holder_org="974760673")
    assert audit.decision == "rejected"


# ---------------------------------------------------------------------------------------- end to end: a genuine cooperative site is still published --
def test_a_genuine_cooperative_site_with_its_organisation_number_is_published_through_the_pipeline() -> None:
    pages = {"/": f"<html><head><title>{VESTSIDEN_NAME}</title></head><body><h1>{VESTSIDEN_NAME}</h1><main><p>Velkommen til oss.</p></main>"
                  f"<footer>{VESTSIDEN_NAME} · Org.nr. 888 078 622</footer></body></html>"}
    net = housing_net(VESTSIDEN_ORG, VESTSIDEN_NAME, "BRL", host="vestsiden4.no", pages=pages, address="Storgata 117", phone="35903000", email="post@forvalter.no",
                      registry_site="https://vestsiden4.no/")
    record = run(net, VESTSIDEN_ORG)
    assert record["website"] and record["website"]["verified"], record["site_attempts"]
    assert any(a["decision"] == "verified" for a in record["site_attempts"])


# ------------------------------------------------------------------------------------------------ the registry e-mail is a labelled registry fact --
def test_the_registered_e_mail_is_labelled_as_a_registry_contact_and_never_as_a_verified_company_e_mail() -> None:
    from test_signalpost_rescore_identity import manager_site

    from app.competition.envelope import build_envelope
    net = housing_net(VESTSIDEN_ORG, VESTSIDEN_NAME, "BRL", host="gbbl.no", pages=manager_site(), address="Storgata 117", phone="35903000", email="post@gbbl.no",
                      registry_site="https://www.gbbl.no/")
    env = build_envelope(run(net, VESTSIDEN_ORG), run_id="test")
    claims = [c for c in env["claims"] if c["field"] == "registered_email" and c["availability"] == "available"]
    assert claims and all(c["label"] == "Registered e-mail" for c in claims)
    sources = {e["source_name"] for e in env["evidence"] if any(e["id"] in c["evidence_ids"] for c in claims)}
    assert sources == {"Brønnøysundregistrene — Enhetsregisteret"}
    assert "contact_email" not in {c["field"] for c in env["claims"] if c["availability"] == "available"}


# ------------------------------------------------------------------------------------- old (ea05bf8) vs new matrix, pinned as the intended outcomes --
def _p(title: str, body: str = "<p>Velkommen</p>", footer: str = "", h1: str = "", ld: str = "") -> object:
    heading = f"<h1>{h1}</h1>" if h1 else ""
    script = f'<script type="application/ld+json">{ld}</script>' if ld else ""
    html = f"<html><head><title>{title}</title>{script}</head><body>{heading}<main>{body}</main><footer>{footer}</footer></body></html>"
    return parse_html("https://example.no/", "https://example.no/", html, retrieved_at="2026-11-10T00:00:00Z", content_sha256="x")


_ADDR = {"adresse": ["Cecilie Thoresens vei 5-7"], "postnummer": "1153"}
_LD = '{"@type":"Organization","name":"AUTOBJØRN A/S"}'
# (label, identity, pages, decision with the previous matcher, decision now)
MATRIX = [
    ("name in title only", company(), [_p(NAME)], "ambiguous", "ambiguous"),
    ("name in heading only", company(), [_p("Forside", h1=NAME)], "ambiguous", "ambiguous"),
    ("name in footer only", company(), [_p("Forside", footer=NAME)], "ambiguous", "ambiguous"),
    ("name in JSON-LD only", company(), [_p("Forside", ld=_LD)], "ambiguous", "ambiguous"),
    ("name + registered address", company(address="Cecilie Thoresens vei 5-7"), [_p(NAME, "<p>Cecilie Thoresens vei 5-7, 1153 Oslo</p>")], "verified", "verified"),
    ("name + registered telephone", company(phone="22334455"), [_p(NAME, "<p>Tlf 22 33 44 55</p>")], "verified", "verified"),
    ("name + different contact details", company(address="Cecilie Thoresens vei 5-7", phone="22334455"), [_p(NAME, "<p>Nygata 5. Tlf 99 88 77 66</p>")], "ambiguous", "ambiguous"),
    ("JSON-LD name + registered address", company(address="Cecilie Thoresens vei 5-7"), [_p("Forside", "<p>Cecilie Thoresens vei 5-7</p>", ld=_LD)], "ambiguous", "verified"),
    ("manager lists the cooperative with shared contact details", coop(),
     [_p("Grenland Boligbyggelag", "<ul><li>VESTSIDEN HAGEBY IV BORETTSLAG</li><li>SKIEN BOLIG BORETTSLAG</li><li>HERKULES BORETTSLAG</li><li>BRATSBERG BORETTSLAG</li></ul>"
         "<p>Storgata 117, 3721 Skien. Tlf 35 90 30 00. post@forvalter.no</p>", footer="Grenland Boligbyggelag")], "verified", "ambiguous"),
    ("cooperative page: name + shared contact, no organisation number", coop(),
     [_p(VESTSIDEN_NAME, "<p>Storgata 117, 3721 Skien. Tlf 35 90 30 00</p>", footer=VESTSIDEN_NAME, h1=VESTSIDEN_NAME)], "verified", "ambiguous"),
    ("similar-named entity with the address", company(address="Cecilie Thoresens vei 5-7"), [_p("Autobjørn Bil AS", "<p>Cecilie Thoresens vei 5-7</p>", footer="Autobjørn Bil AS")],
     "ambiguous", "ambiguous"),
    ("organisation number in another company's customer table", company(),
     [_p("Regnskap Nord AS", "<table><tr><td>AUTOBJØRN A/S</td><td>Org.nr. 810 359 862</td></tr></table>", footer="Regnskap Nord AS")], "verified", "ambiguous"),
    ("organisation number in the footer", company(), [_p("Forside", footer=f"{NAME} Org.nr. 810 359 862")], "verified", "verified"),
]


@pytest.mark.parametrize("label,ident,pages,old,new", MATRIX, ids=[m[0] for m in MATRIX])
def test_old_versus_new_decision_matrix(label: str, ident: CanonicalIdentity, pages: list, old: str, new: str) -> None:
    """``old`` is the decision of the matcher at ea05bf8 on the same page (recorded when this audit was run); ``new`` is what must hold now. Every change from verified
    to ambiguous is a wrong-company pattern or a documented coverage trade-off; the one change from ambiguous to verified rests on the entity's own structured data."""
    assert audit_site(ident, pages, "example.no", registry_linked=True).decision == new, (label, old)
