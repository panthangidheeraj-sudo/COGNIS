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


# ------------------------------------------------------------- V2.1 stricter verification --
import asyncio  # noqa: E402

from app.connectors.website import FetchedPage, SiteCrawl, collect_links_and_social  # noqa: E402
from app.evidence import gate  # noqa: E402
from app.extraction import web_facts  # noqa: E402
from app.extraction.html import declared_same_as, parse_html  # noqa: E402
from app.identity.match import IdentityAudit  # noqa: E402
from app.identity.social import declaration_confidence  # noqa: E402

EQ = CanonicalIdentity(org_number="923609016", legal_name="EQUINOR ASA", website="https://www.equinor.com")


def test_a_name_fragment_inside_a_longer_handle_is_rejected() -> None:
    for handle in ("equinorfans", "equinor-recruiting-scam", "equinorsupporters", "myequinor"):
        v = verdict("facebook", handle, ident=EQ, domain="equinor.com")
        assert v.decision == "rejected" and "inside a longer one" in v.reasons[0], handle
        assert v.confidence is None and v.verification is None


def test_the_name_alone_or_with_a_plain_affix_is_accepted() -> None:
    exact = verdict("linkedin", "equinor", ident=EQ, domain="equinor.com")
    affix = verdict("facebook", "equinornorge", ident=EQ, domain="equinor.com")
    assert (exact.decision, exact.match) == ("accepted", "exact") and (affix.decision, affix.match) == ("accepted", "affix")


def test_a_brand_fragment_is_no_longer_accepted() -> None:
    ident = CanonicalIdentity(org_number="810359862", legal_name="Nordisk Biltjeneste AS")
    assert verdict("instagram", "nbtjenesteoslo", ident=ident, domain="nbtjeneste.no").decision == "rejected"
    assert verdict("instagram", "nbtjenesteno", ident=ident, domain="nbtjeneste.no").decision == "accepted"


def test_an_accepted_profile_is_linked_from_the_site_and_never_platform_verified() -> None:
    v = verdict("linkedin", "equinor", ident=EQ, domain="equinor.com")
    assert v.verification == "linked_from_company_site" and v.platform_verified is False
    assert "not verified on the platform" in v.reasons[-1]
    assert v.profile()["platform_verified"] is False and v.profile()["verification"] == "linked_from_company_site"


def test_confidence_follows_how_the_company_declared_the_profile() -> None:
    conf = {how: declaration_confidence(how, "exact", 1.0) for how in ("jsonld_sameAs", "footer", "header", "page_body")}
    assert conf["jsonld_sameAs"] > conf["footer"] > conf["header"] > conf["page_body"]
    assert declaration_confidence("footer", "affix", 1.0) < conf["footer"]  # name + affix is weaker than the name itself


def test_a_weakly_verified_website_lowers_the_confidence_of_its_profiles() -> None:
    strong, weak = declaration_confidence("footer", "exact", 1.0), declaration_confidence("footer", "exact", 0.62)
    assert weak < strong < 0.88  # never the old flat 0.88, and never above what the site's own identity supports


def _crawl(html: str, *, score: float = 0.9, domain: str = "equinor.com") -> SiteCrawl:
    doc = parse_html(f"https://www.{domain}/", f"https://www.{domain}/", html, content_sha256="abc", retrieved_at="2026-11-05T10:00:00Z")
    crawl = SiteCrawl(start_url=f"https://www.{domain}/", source_class="company_owned", origin="registry", domain=domain)
    crawl.pages.append(FetchedPage("home", None, doc))  # type: ignore[arg-type]
    crawl.audit = IdentityAudit(domain=domain, score=score, decision="verified", signals=["registered_phone_on_site"])
    return crawl


def _collect(crawl: SiteCrawl) -> dict[tuple[str, str], dict]:
    asyncio.run(collect_links_and_social(None, crawl, EQ, None))  # type: ignore[arg-type]
    return {(c["network"], c["handle"]): c for c in crawl.social_candidates}


def test_json_ld_same_as_is_read_for_organisations_only() -> None:
    doc = parse_html("https://a.no/", "https://a.no/", '<script type="application/ld+json">{"@graph":[{"@type":"Organization","sameAs":["https://www.linkedin.com/company/equinor"]},'
                     '{"@type":"Person","sameAs":["https://www.linkedin.com/in/someone"]},{"@type":"Article","sameAs":["https://www.facebook.com/other"]}]}</script>')
    assert declared_same_as(doc) == ["https://www.linkedin.com/company/equinor"]


def test_same_as_footer_and_content_links_are_tagged_with_how_they_were_declared() -> None:
    crawl = _crawl('<html><body><main><a href="https://x.com/equinor">follow</a></main><footer><a href="https://www.instagram.com/equinor">ig</a></footer>'
                   '<script type="application/ld+json">{"@type":"Organization","sameAs":["https://www.linkedin.com/company/equinor"]}</script></body></html>')
    got = _collect(crawl)
    assert got[("linkedin", "equinor")]["declared_by"] == "jsonld_sameAs"
    assert got[("instagram", "equinor")]["declared_by"] == "footer"
    assert got[("x", "equinor")]["declared_by"] == "page_body"
    assert got[("linkedin", "equinor")]["confidence"] > got[("instagram", "equinor")]["confidence"] > got[("x", "equinor")]["confidence"]


def test_a_profile_declared_two_ways_keeps_the_stronger_declaration() -> None:
    crawl = _crawl('<html><body><main><a href="https://www.facebook.com/equinor">fb</a></main><footer><a href="https://www.facebook.com/equinor">fb</a></footer></body></html>')
    assert _collect(crawl)[("facebook", "equinor")]["declared_by"] == "footer"


def test_a_content_only_profile_is_not_published_beside_a_declared_one_for_the_same_network() -> None:
    crawl = _crawl('<html><body><main><a href="https://www.facebook.com/equinornorge">other page</a></main><footer><a href="https://www.facebook.com/equinor">fb</a></footer></body></html>')
    got = _collect(crawl)
    assert got[("facebook", "equinor")]["decision"] == "accepted"
    demoted = got[("facebook", "equinornorge")]
    assert demoted["decision"] == "unverified" and "declares a different facebook profile" in " ".join(demoted["reasons"])
    assert [p["handle"] for p in crawl.social] == ["equinor"]


def test_a_content_only_profile_is_published_when_nothing_better_is_declared() -> None:
    crawl = _crawl('<html><body><main><a href="https://www.facebook.com/equinor">fb</a></main></body></html>')
    _collect(crawl)
    assert [p["handle"] for p in crawl.social] == ["equinor"] and crawl.social[0]["declared_by"] == "page_body"


def test_the_published_claim_says_linked_not_verified_and_is_capped_below_the_old_flat_confidence() -> None:
    crawl = _crawl('<html><head><title>Equinor</title></head><body><footer><a href="https://www.linkedin.com/company/equinor">in</a></footer></body></html>', score=0.65)
    _collect(crawl)
    obs = [o for o in web_facts.website_observations(crawl) if o.field.startswith("social_profile_")]
    assert len(obs) == 1 and "footer link on" in obs[0].claim_span and "not verified on the platform" in obs[0].claim_span
    assert obs[0].attributes["platform_verified"] is False and obs[0].attributes["verification"] == "linked_from_company_site"
    claims, _ = gate.publish(obs, "923609016")
    assert claims and claims[0].confidence < 0.88 and claims[0].confidence == obs[0].attributes["confidence_ceiling"]


def test_a_better_verified_website_gives_its_profiles_more_confidence() -> None:
    def conf(score: float) -> float:
        crawl = _crawl('<html><body><footer><a href="https://www.linkedin.com/company/equinor">in</a></footer></body></html>', score=score)
        _collect(crawl)
        obs = [o for o in web_facts.website_observations(crawl) if o.field.startswith("social_profile_")]
        return gate.publish(obs, "923609016")[0][0].confidence

    assert conf(0.95) > conf(0.62)
