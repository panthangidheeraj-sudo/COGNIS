"""Social profiles linked from a verified website are candidates: agency/theme/parent-group/foreign-group links are rejected and kept in diagnostics."""
from __future__ import annotations

from app.identity.model import CanonicalIdentity
from app.identity.social import assess_social

IDENT = CanonicalIdentity(org_number="810359862", legal_name="AUTOBJØRN A/S", website="https://www.autobjorn.no")
RELATED = [{"name": "Bilgruppen ASA", "org": "999999999"}]


def verdict(network: str, handle: str, *, related=None, ident=IDENT, domain="autobjorn.no"):  # noqa: ANN001, ANN201
    return assess_social(ident, domain, network, handle, f"https://www.{network}.com/{handle}", "https://www.autobjorn.no/", related=related)


def test_a_handle_carrying_the_registered_name_is_accepted_even_when_the_nordic_letter_is_dropped() -> None:
    assert verdict("facebook", "autobjorn").decision == "accepted"
    v = verdict("linkedin", "autobj-rn-a-s")
    assert v.decision == "accepted" and v.basis == "name_in_handle"


def test_domain_brand_handle_is_accepted() -> None:
    ident = CanonicalIdentity(org_number="810359862", legal_name="Nordisk Biltjeneste AS")
    v = verdict("instagram", "nbtjeneste", ident=ident, domain="nbtjeneste.no")
    assert v.decision == "accepted" and v.basis == "domain_brand_in_handle"


def test_web_agency_and_theme_vendor_links_are_rejected() -> None:
    for handle in ("webdesignbyra", "themeforest", "wordpress", "elementor", "shopify"):
        v = verdict("facebook", handle)
        assert v.decision == "rejected" and "agency" in v.reasons[0], handle


def test_the_networks_own_pages_and_share_links_are_rejected() -> None:
    assert verdict("facebook", "sharer").decision == "rejected"
    assert verdict("linkedin", "company").decision == "rejected"


def test_parent_group_profile_is_rejected_not_published_as_the_companys() -> None:
    v = verdict("facebook", "bilgruppenasa", related=RELATED)
    assert v.decision == "rejected" and "parent group" in v.reasons[0]


def test_parent_name_inside_the_companys_own_handle_is_not_a_parent_profile() -> None:
    ident = CanonicalIdentity(org_number="810359862", legal_name="Bilgruppen Oslo AS")
    assert verdict("facebook", "bilgruppenoslo", related=RELATED, ident=ident).decision == "accepted"


def test_another_countrys_group_page_is_rejected() -> None:
    v = verdict("facebook", "autobjornsverige")
    assert v.decision == "rejected" and "another country" in v.reasons[0]


def test_unrelated_handle_stays_unverified_and_is_not_published() -> None:
    v = verdict("facebook", "kaffekompaniet")
    assert v.decision == "unverified" and v.basis is None and "not tied to this entity" in v.reasons[0]
