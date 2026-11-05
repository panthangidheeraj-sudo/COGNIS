"""V2.1 — a news item is published only after its own article page has been fetched and verified.

A newsroom card, a listing's JSON-LD or a feed item is a *candidate*. It is published only when the linked page is a real article on the company's own verified
domain, has a headline and readable text, names the exact legal entity (organisation number or registered name), carries no conflicting organisation number
and states a genuine publication date. The evidence of a published item is the article page itself — never the listing or feed it was found on. Every candidate
that fails keeps its reason. Everything runs against the offline ``FixtureNetwork``; nothing touches the real network.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from typing import Any

from conftest import research as research_plain
from test_free_sources import AUTO

from app.config import Settings
from app.connectors import news_article as na
from app.connectors import news_validation as nv
from app.connectors.newsroom import parse_feed
from app.extraction.html import parse_html
from app.identity.model import CanonicalIdentity
from app.testing.fixtures import FixtureNetwork, verified_site

NAME = "AUTOBJØRN A/S"
FOOTER = "AUTOBJØRN A/S · Org.nr. 810 359 862 · Oslo"
HOST = "https://www.autobjorn.no"
HEADLINE = "AUTOBJØRN signerer rammeavtale med Statens vegvesen"
LEAD = "AUTOBJØRN A/S har inngått en rammeavtale om leveranse av tjenestebiler til Statens vegvesen, opplyser selskapet i dag."
MORE = "Avtalen gjelder i fire år og omfatter service og vedlikehold av hele bilparken, med mulighet for forlengelse."
IDENT = CanonicalIdentity(org_number=AUTO, legal_name=NAME)


def day(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


# ------------------------------------------------------------------------------ pages --
def page(headline: str, *, paragraphs: tuple[str, ...] = (LEAD, MORE), head: str = "", before: str = "", footer: str = FOOTER, ld: dict[str, Any] | None = None) -> str:
    """One article page. ``ld`` is JSON-LD for the article (``None`` = no structured data); ``head`` / ``before`` add meta tags or markup ahead of the text."""
    script = f'<script type="application/ld+json">{json.dumps({"@context": "https://schema.org", "@type": "NewsArticle", "headline": headline, **ld}, ensure_ascii=False)}</script>' if ld is not None else ""
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    return (f'<!doctype html><html lang="nb"><head><title>{headline} – AUTOBJØRN</title>{head}{script}</head><body><nav><a href="/nyheter">Nyheter</a></nav>'
            f"<main><article>{before}<h1>{headline}</h1>{body}</article></main><footer>{footer}</footer></body></html>")


def published(days_ago: int = 10, **kw: Any) -> str:
    return page(kw.pop("headline", HEADLINE), ld={"datePublished": day(days_ago)}, **kw)


def card(title: str, link: str | None, days_ago: int = 10, note: str = "Kortfattet sammendrag av saken som står på nyhetssiden til selskapet.") -> str:
    d = date.today() - timedelta(days=days_ago)
    anchor = f'<a href="{link}">{title}</a>' if link else title
    return f'<article><time datetime="{d.isoformat()}">{d.day}.{d.month}.{d.year}</time><h2>{anchor}</h2><p>{note}</p></article>'


def rss(*items: tuple[str, str, str]) -> str:
    """(title, link, date_markup) — date_markup is the raw child element(s) that carry the item's dates."""
    body = "".join(f"<item><title>{t}</title><link>{link}</link>{dates}<description>Kort beskrivelse av saken.</description></item>" for t, link, dates in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>AUTOBJØRN</title>{body}</channel></rss>'


def pub_date(days_ago: int) -> str:
    return f"<pubDate>{format_datetime(datetime.combine(date.today() - timedelta(days=days_ago), datetime.min.time(), UTC))}</pubDate>"


def site(cards: str = "", pages: dict[str, str] | None = None, feed_xml: str | None = None) -> dict[str, str]:
    out = verified_site(NAME, AUTO)
    out["/nyheter"] = out["/nyheter"].replace("<main>", "<main>" + cards).replace(
        '<article><time datetime="2026-08-14">14. august 2026</time><h2><a href="/nyheter/vi-apner-nytt-kontor-i-bergen">Vi åpner nytt kontor i Bergen og ansetter flere rådgivere</a></h2></article>', "")
    out.pop("/nyheter/vi-apner-nytt-kontor-i-bergen", None)
    if feed_xml:
        out["/"] = out["/"].replace("<head>", '<head><link rel="alternate" type="application/rss+xml" href="/feed.xml">')
        out["/feed.xml"] = feed_xml
    out.update(pages or {})
    return out


def network(pages: dict[str, str], *, robots: str | None = None) -> FixtureNetwork:
    net = FixtureNetwork()
    net.load_brreg_probes()
    net.add_site("autobjorn.no", pages, robots=robots)
    return net


def run(net: FixtureNetwork) -> dict[str, Any]:
    return asyncio.run(research_plain(net, AUTO))


def news(rec: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in rec["claims"] if c["field"] == "news_item" and c["availability"] == "available"]


def rejected(rec: dict[str, Any]) -> list[dict[str, Any]]:
    return rec["news"]["newsroom"]["rejected"]


def reason_for(rec: dict[str, Any], path: str) -> dict[str, Any]:
    return next(r for r in rejected(rec) if (r["url"] or "").endswith(path))


def fetched(net: FixtureNetwork, path: str) -> list[str]:
    return [u for u in net.requests if u.split("?")[0].endswith(path)]


def only_card(link: str, article_html: str | None, *, days_ago: int = 10, title: str = HEADLINE) -> FixtureNetwork:
    pages = {link: article_html} if article_html is not None else {}
    return network(site(card(title, link, days_ago), pages))


# =============================================================== 1 / 13: the accepted case ==
def test_a_genuine_dated_article_about_the_exact_company_is_published_with_the_article_page_as_evidence() -> None:
    rec = run(only_card("/nyheter/rammeavtale", published(10)))
    claim, = news(rec)
    assert claim["value"] == HEADLINE and claim["as_of"] == day(10)
    attrs = claim["attributes"]
    assert attrs["url"] == f"{HOST}/nyheter/rammeavtale" and attrs["date_source"] == "datePublished" and attrs["identity_basis"] in ("exact_legal_name_in_headline", "exact_legal_name_in_article_text")
    ev = next(e for e in rec["evidence"] if e["id"] == claim["evidence_ids"][0])
    assert ev["source_url"] == f"{HOST}/nyheter/rammeavtale"  # the article, not the /nyheter listing
    assert ev["document_title"] == HEADLINE and ev["retrieved_at"] and ev["content_sha256"]
    assert ev["claim_span"].startswith(HEADLINE) and "rammeavtale" in ev["claim_span"] and "Kortfattet sammendrag" not in ev["claim_span"]  # from the article text, not the card
    assert rec["news"]["newsroom"]["published"] == 1 and rec["news"]["newsroom"]["articles_fetched"] == 1


def test_the_exact_name_spelled_as_or_a_s_and_the_organisation_number_each_identify_the_entity() -> None:
    for legal_spelling, paragraphs in (("AUTOBJØRN AS", (f"{'AUTOBJØRN AS'} har inngått en rammeavtale om leveranse av tjenestebiler til Statens vegvesen.", MORE)),
                                       ("number", ("Selskapet har inngått en rammeavtale om leveranse av tjenestebiler til Statens vegvesen (org.nr. 810 359 862).", MORE))):
        headline = "Ny rammeavtale for tjenestebiler" if legal_spelling == "number" else HEADLINE.replace("AUTOBJØRN ", "Ny avtale for ")
        rec = run(only_card("/nyheter/a", page(headline, ld={"datePublished": day(5)}, paragraphs=paragraphs), title=headline))
        claim, = news(rec)
        assert claim["attributes"]["identity_basis"] == ("organisation_number_in_article" if legal_spelling == "number" else "exact_legal_name_in_article_text"), legal_spelling


# ================================================================ 2: listings are not articles ==
def test_a_newsroom_listing_or_section_page_is_never_published_as_an_article() -> None:
    cards = "".join(card(f"Oversikt over saker og meldinger fra selskapet {i}", link) for i, link in enumerate(["/nyheter", "/nyheter/page/2", "/tag/elbil", "/arkiv", "/"]))
    net = network(site(cards))
    rec = run(net)
    assert news(rec) == []
    reasons = [r["reason"] for r in rejected(rec)]
    assert len(reasons) == 5 and all(("listing" in x or "section" in x or "bare domain" in x or "tag" in x) for x in reasons)
    assert len(fetched(net, "/nyheter/page/2")) == 0 and len(fetched(net, "/tag/elbil")) == 0  # rejected from the URL alone, nothing was requested


# ============================================================ 3: link to an article that is missing ==
def test_a_card_linking_to_a_missing_article_is_rejected_and_kept_in_diagnostics() -> None:
    rec = run(only_card("/nyheter/finnes-ikke", None))
    assert news(rec) == []
    r = reason_for(rec, "/nyheter/finnes-ikke")
    assert r["status"] == "not_found" and r["fetch"] == "not_found" and "does not exist" in r["reason"] and "says nothing about whether the article is genuine" in r["reason"]
    assert r["title"] == HEADLINE and r["source_page"].endswith("/nyheter") and r["found_in"][0]["kind"] == "newsroom_listing"


# ================================================================== 4: product / navigation pages ==
def test_product_and_navigation_pages_linked_from_the_newsroom_are_rejected() -> None:
    product = page("Tjenestebiler for bedrifter – våre leasingløsninger", ld=None, before='<time datetime="2026-10-01">1. oktober 2026</time>',
                   paragraphs=("AUTOBJØRN A/S tilbyr fleksible leasingløsninger for bedrifter med behov for mange biler.", "Kontakt oss for tilbud på langtidsleie, service og forsikring av hele bilparken."))
    net = network(site(card("Våre leasingløsninger for bedrifter", "/produkter") + card("Tjenestebiler for bedrifter – våre løsninger", "/produkter/tjenestebiler", 12),
                       {"/produkter/tjenestebiler": product}))
    rec = run(net)
    assert news(rec) == []
    assert "product" in reason_for(rec, "/produkter")["reason"]  # the one-segment product page is refused from its URL alone ...
    assert rec["news"]["newsroom"]["articles_fetched"] == 0  # ... and the deeper one was already read by the site crawl, so it is judged without a second request
    deep = reason_for(rec, "/produkter/tjenestebiler")
    assert deep["status"] == "rejected" and "publication date" in deep["reason"]  # fetched, but a product page states no publication date


# ============================================================================ 5-8: dates ==
def test_a_page_with_only_a_modification_date_is_not_published() -> None:
    rec = run(only_card("/nyheter/m", page(HEADLINE, ld={"dateModified": day(3)})))
    assert news(rec) == [] and "only a modification date" in reason_for(rec, "/nyheter/m")["reason"]


def test_a_page_with_only_a_creation_date_is_not_published() -> None:
    rec = run(only_card("/nyheter/c", page(HEADLINE, ld={"dateCreated": day(3)})))
    assert news(rec) == [] and "only a modification date" in reason_for(rec, "/nyheter/c")["reason"]  # created/modified: neither says when it was published


def test_a_generic_time_element_and_a_card_date_do_not_date_an_article() -> None:
    generic = page(HEADLINE, before=f'<time datetime="{day(10)}">{day(10)}</time>')
    rec = run(only_card("/nyheter/g", generic, days_ago=10))
    assert news(rec) == []
    why = reason_for(rec, "/nyheter/g")["reason"]
    assert "no publication date" in why and "generic <time>" in why and "listing card shows" in why  # the card's own date is named and refused


def test_an_rss_updated_date_is_not_a_publication_date() -> None:
    feed = rss((HEADLINE, f"{HOST}/nyheter/u", f"<updated>{day(2)}T08:00:00Z</updated>"))
    rec = run(network(site(pages={"/nyheter/u": page(HEADLINE)}, feed_xml=feed)))
    assert news(rec) == []
    r = reason_for(rec, "/nyheter/u")
    assert "publication date" in r["reason"] and r["found_in"][0]["kind"] == "rss_item"


def test_feed_fields_other_than_pubdate_and_atom_published_are_never_publication_dates() -> None:
    xml = ('<?xml version="1.0"?><rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>'
           f"<item><title>Første sak i strømmen fra selskapet</title><link>{HOST}/a</link><dc:date>{day(5)}</dc:date></item>"
           f"<item><title>Andre sak i strømmen fra selskapet</title><link>{HOST}/b</link><date>{day(5)}</date><lastBuildDate>{day(1)}</lastBuildDate></item>"
           f"<item><title>Tredje sak i strømmen fra selskapet</title><link>{HOST}/c</link>{pub_date(6)}</item></channel></rss>")
    atom = (f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Fjerde sak i strømmen fra selskapet</title><link rel="self" href="{HOST}/self"/><link rel="alternate" href="{HOST}/d"/>'
            f"<updated>{day(1)}T00:00:00Z</updated><published>{day(7)}T09:00:00Z</published></entry></feed>")
    rows = parse_feed(xml, f"{HOST}/feed.xml")
    assert [(r.day, r.date_source) for r in rows] == [(None, None), (None, None), (day(6), "rss_pubDate")]
    entry, = parse_feed(atom, f"{HOST}/atom.xml")
    assert entry.link == f"{HOST}/d" and (entry.day, entry.date_source) == (day(7), "atom_published")


# ================================================== 9: RSS pubDate supplies the date, the page is still checked ==
def test_an_rss_pubdate_can_supply_the_date_but_the_article_page_is_still_fetched_and_verified() -> None:
    undated = page(HEADLINE)  # names the company, states no date of its own
    feed = rss((HEADLINE, f"{HOST}/nyheter/f1", pub_date(4)))
    net = network(site(pages={"/nyheter/f1": undated}, feed_xml=feed))
    rec = run(net)
    claim, = news(rec)
    assert claim["attributes"]["date_source"] == "rss_pubDate" and claim["as_of"] == day(4)
    assert fetched(net, "/nyheter/f1")  # the linked page was requested and judged
    ev = next(e for e in rec["evidence"] if e["id"] == claim["evidence_ids"][0])
    assert ev["source_url"] == f"{HOST}/nyheter/f1"  # the article page, not feed.xml


def test_an_rss_item_with_a_pubdate_is_still_rejected_when_its_article_is_about_someone_else() -> None:
    other = page("Autobjørn Bergen AS får ny daglig leder", paragraphs=("Autobjørn Bergen AS har ansatt ny daglig leder, opplyser selskapet i en pressemelding i dag.", MORE))
    feed = rss(("Autobjørn Bergen AS får ny daglig leder", f"{HOST}/nyheter/f2", pub_date(4)))
    net = network(site(pages={"/nyheter/f2": other}, feed_xml=feed))
    rec = run(net)
    assert news(rec) == [] and fetched(net, "/nyheter/f2")
    assert "continues into, or could belong to, another company" in reason_for(rec, "/nyheter/f2")["reason"]


def test_a_feed_date_never_overrides_the_date_the_article_page_states() -> None:
    feed = rss((HEADLINE, f"{HOST}/nyheter/f3", pub_date(2)))
    rec = run(network(site(pages={"/nyheter/f3": published(9)}, feed_xml=feed)))
    claim, = news(rec)
    assert claim["as_of"] == day(9) and claim["attributes"]["date_source"] == "datePublished" and claim["attributes"]["feed_date"] == day(2)


# ================================================================ 10-12: exact legal entity ==
def test_an_article_about_the_parent_group_alone_is_not_attributed_to_the_subsidiary() -> None:
    group = page("Bilgruppen AS kjøper konkurrent for 300 millioner kroner", ld={"datePublished": day(6)},
                 paragraphs=("Bilgruppen AS har inngått avtale om å kjøpe konkurrenten Biler Nord for 300 millioner kroner, opplyser konsernet.", "Oppkjøpet er et ledd i konsernets strategi for vekst i hele landet."))
    rec = run(only_card("/nyheter/gruppen", group, title="Bilgruppen AS kjøper konkurrent for 300 millioner kroner"))
    assert news(rec) == []
    assert "does not name this legal entity" in reason_for(rec, "/nyheter/gruppen")["reason"]


def test_the_parent_group_is_named_as_the_reason_when_the_register_lists_it() -> None:
    doc = parse_html(f"{HOST}/x", f"{HOST}/x", page("Bilgruppen AS kjøper konkurrent for 300 millioner kroner", ld={"datePublished": day(6)}, footer="",
                                                    paragraphs=("Bilgruppen AS har inngått avtale om å kjøpe konkurrenten Biler Nord for 300 millioner kroner, opplyser konsernet.", MORE)))
    art, _ = na.read_article(doc)
    assert art is not None
    basis, why, _ = na.entity_basis(doc, art, IDENT, related=[{"name": "Bilgruppen AS", "org": "923609016"}])
    assert basis is None and "parent group (Bilgruppen AS)" in why


def test_an_article_about_another_subsidiary_is_rejected() -> None:
    sister = page("AUTOBJØRN BERGEN A/S får ny daglig leder", ld={"datePublished": day(6)},
                  paragraphs=("AUTOBJØRN BERGEN A/S har ansatt ny daglig leder fra årsskiftet, opplyser selskapet i en pressemelding.", MORE))
    rec = run(only_card("/nyheter/bergen", sister, title="AUTOBJØRN BERGEN A/S får ny daglig leder"))
    assert news(rec) == []
    assert "name" in reason_for(rec, "/nyheter/bergen")["reason"]
    numbered = page("Selskap i konsernet får ny leder", ld={"datePublished": day(6)}, footer="Org.nr. 923 609 016",
                    paragraphs=("Lager Drammen AS, org.nr. 923 609 016, har ansatt ny daglig leder fra årsskiftet, opplyser selskapet.", MORE))
    rec = run(only_card("/nyheter/lager", numbered, title="Selskap i konsernet får ny leder"))
    assert news(rec) == [] and "different organisation number (923609016)" in reason_for(rec, "/nyheter/lager")["reason"]


def test_an_article_with_a_conflicting_organisation_number_is_rejected() -> None:
    # the page carries another organisation's number next to ours, and its headline does not name this entity
    mixed = page("Rammeavtale for tjenestebiler signert", ld={"datePublished": day(6)},
                 paragraphs=("Avtalen er inngått mellom Statens vegvesen og leverandøren Lager Drammen AS, org.nr. 923 609 016, opplyser partene i dag.", MORE))
    rec = run(only_card("/nyheter/mixed", mixed, title="Rammeavtale for tjenestebiler signert"))
    assert news(rec) == [] and "several organisation numbers" in reason_for(rec, "/nyheter/mixed")["reason"]


def test_an_article_naming_this_entity_in_its_headline_is_not_lost_because_it_mentions_a_counterparty_number() -> None:
    counterparty = page("AUTOBJØRN kjøper lagerbygg i Drammen", ld={"datePublished": day(6)},
                        paragraphs=("AUTOBJØRN A/S kjøper lagerbygget i Drammen. Selger er Lager Drammen AS, org.nr. 923 609 016, opplyser partene i dag.", MORE))
    rec = run(only_card("/nyheter/lager2", counterparty, title="AUTOBJØRN kjøper lagerbygg i Drammen"))
    assert len(news(rec)) == 1 and news(rec)[0]["attributes"]["identity_basis"] == "exact_legal_name_in_headline"


def test_the_site_footer_alone_does_not_make_an_article_about_the_entity() -> None:
    generic = page("Rammeavtale for tjenestebiler signert", ld={"datePublished": day(6)}, paragraphs=("Avtalen gjelder leveranse av tjenestebiler til det offentlige, og den løper over fire år.", MORE))
    rec = run(only_card("/nyheter/generisk", generic, title="Rammeavtale for tjenestebiler signert"))
    assert news(rec) == [] and "only the site footer carries the organisation number" in reason_for(rec, "/nyheter/generisk")["reason"]


def test_a_longer_company_name_or_a_shared_brand_word_is_not_a_match() -> None:
    for headline, text in (("Autobjørn Gruppen kjøper konkurrent for 300 millioner kroner", "Autobjørn Gruppen har inngått avtale om oppkjøp av konkurrenten, opplyser konsernet i dag."),
                           ("Autobjørn Norge åpner nytt anlegg i Stavanger", "Autobjørn Norge åpner nytt anlegg i Stavanger i løpet av våren, opplyser selskapet i dag.")):
        doc = parse_html(f"{HOST}/x", f"{HOST}/x", page(headline, ld={"datePublished": day(6)}, paragraphs=(text, MORE), footer=""))
        art, _ = na.read_article(doc)
        basis, why, _ = na.entity_basis(doc, art, IDENT)  # type: ignore[arg-type]
        assert basis is None, headline


# ======================================================================== 14: unavailable pages ==
def test_blocked_and_unavailable_article_pages_leave_diagnostics_but_no_published_news() -> None:
    cards = "".join(card(f"Sak nummer {i} fra nyhetssiden til selskapet", f"/nyheter/u{i}", 10 + i) for i in range(5))
    pages = {f"/nyheter/u{i}": published(10 + i) for i in range(5)}
    net = network(site(cards, pages), robots="User-agent: *\nDisallow: /nyheter/u0")
    net.fail(f"{HOST}/nyheter/u1", "timeout")
    net.fail(f"{HOST}/nyheter/u2", "404")
    net.fail(f"{HOST}/nyheter/u3", "503")
    net.fail(f"{HOST}/nyheter/u4", "403")
    rec = run(net)
    assert news(rec) == []
    status = {r["url"].rsplit("/", 1)[-1]: (r["status"], r.get("fetch")) for r in rejected(rec)}
    assert status["u0"] == ("blocked", "robots_disallowed") and status["u1"][0] == "unreadable" and status["u2"] == ("not_found", "not_found")
    assert status["u3"][0] == "unreadable" and status["u4"][0] == "blocked"
    assert not [u for u in net.requests if u.endswith("/nyheter/u0")]  # robots.txt respected
    note = rec["news"]["newsroom"]["note"]
    assert "not evidence that there was no such news" in note and rec["news"]["newsroom"]["state"] == "available"  # the listing was read; the articles could not be


# ==================================================================== 15: provenance, end to end ==
def test_every_published_item_cites_its_article_page_and_never_the_listing_or_the_feed() -> None:
    cards = card(HEADLINE, "/nyheter/a1", 10) + card("Ny finansdirektør i AUTOBJØRN", "/nyheter/a2", 8)
    pages = {"/nyheter/a1": published(10), "/nyheter/a2": page("Ny finansdirektør i AUTOBJØRN", ld={"datePublished": day(8)},
                                                              paragraphs=("Kari Nordmann tiltrer som ny finansdirektør i AUTOBJØRN A/S fra første januar, opplyser selskapet.", MORE))}
    feed = rss(("Ny finansdirektør i AUTOBJØRN", f"{HOST}/nyheter/a2", pub_date(8)))
    rec = run(network(site(cards, pages, feed)))
    items = news(rec)
    assert len(items) == 2
    by_id = {e["id"]: e for e in rec["evidence"]}
    for claim in items:
        urls = {by_id[i]["source_url"] for i in claim["evidence_ids"]}
        assert urls == {claim["attributes"]["url"]} and not any(u.endswith(("/nyheter", "/feed.xml")) for u in urls)
        ev = by_id[claim["evidence_ids"][0]]
        assert ev["document_title"] == claim["value"] and ev["claim_span"] and ev["extraction_method"] == "article_page"
    finance = next(c for c in items if "finansdirektør" in c["value"])
    assert {f["kind"] for f in finance["attributes"]["found_in"]} == {"newsroom_listing", "rss_item"}


# ================================================================ 16: one fetch per article URL ==
def test_the_same_article_listed_and_fed_is_fetched_once() -> None:
    cards = card(HEADLINE, "/nyheter/dup", 10) + card(HEADLINE, "/nyheter/dup/", 10)
    feed = rss((HEADLINE, f"{HOST}/nyheter/dup", pub_date(10)), (HEADLINE, f"{HOST}/nyheter/dup/", pub_date(10)))
    net = network(site(cards, {"/nyheter/dup": published(10)}, feed))
    rec = run(net)
    assert len(news(rec)) == 1
    assert len([u for u in net.requests if u.rstrip("/").endswith("/nyheter/dup")]) == 1
    assert rec["news"]["newsroom"]["articles_fetched"] == 1 and rec["news"]["newsroom"]["candidates"] == 1


# ===================================================================== extra rules and limits ==
def test_links_to_other_sites_are_not_followed() -> None:
    net = network(site(card("Vi omtales i E24 etter den store kontrakten", "https://e24.no/naeringsliv/autobjorn-kontrakt", 5)))
    net.add_site("e24.no", {"/naeringsliv/autobjorn-kontrakt": published(5)})
    rec = run(net)
    assert news(rec) == [] and "another site (e24.no)" in reason_for(rec, "/naeringsliv/autobjorn-kontrakt")["reason"]
    assert not [u for u in net.requests if "e24.no" in u]


def test_publication_dates_that_say_what_they_are_are_accepted_and_labelled() -> None:
    meta = page(HEADLINE, head=f'<meta property="article:published_time" content="{day(7)}T08:00:00+01:00">')
    scoped = page(HEADLINE, before=f'<time itemprop="datePublished" datetime="{day(6)}">{day(6)}</time>')
    rec = run(network(site(card(HEADLINE, "/nyheter/meta", 7) + card("Andre sak med dato i artikkelen", "/nyheter/itemprop", 6), {"/nyheter/meta": meta, "/nyheter/itemprop": scoped})))
    sources = {c["attributes"]["url"].rsplit("/", 1)[-1]: c["attributes"]["date_source"] for c in news(rec)}
    assert sources == {"meta": "published_time", "itemprop": "time_itemprop_datePublished"}
    outside = page(HEADLINE).replace("<main>", f'<main><time itemprop="datePublished" datetime="{day(6)}">x</time>')  # not inside the article: no publication semantics
    rec = run(only_card("/nyheter/out", outside, days_ago=6))
    assert news(rec) == []


def test_a_page_listing_several_publication_dates_is_not_one_article() -> None:
    many = page(HEADLINE, before=(f'<time itemprop="datePublished" datetime="{day(5)}">a</time><time itemprop="datePublished" datetime="{day(9)}">b</time>'))
    rec = run(only_card("/nyheter/arkiv-side", many))
    assert news(rec) == [] and "several publication dates" in reason_for(rec, "/nyheter/arkiv-side")["reason"]


def test_a_page_without_readable_article_text_is_rejected() -> None:
    thin = page(HEADLINE, ld={"datePublished": day(4)}, paragraphs=("Se bildet.",))
    rec = run(only_card("/nyheter/tynn", thin))
    assert news(rec) == [] and "no readable article text" in reason_for(rec, "/nyheter/tynn")["reason"]


def test_the_article_page_limit_is_respected_and_unchecked_items_say_so(settings: Settings) -> None:
    settings.news_article_max_fetches = 2
    cards = "".join(card(f"Sak nummer {i} fra nyhetssiden til selskapet", f"/nyheter/l{i}", 3 + i) for i in range(5))
    net = network(site(cards, {f"/nyheter/l{i}": published(3 + i, headline=f"Sak nummer {i} fra nyhetssiden til selskapet") for i in range(5)}))
    rec = run(net)
    assert len(news(rec)) == 2 and rec["news"]["newsroom"]["articles_fetched"] == 2
    unchecked = [r for r in rejected(rec) if r["status"] == "not_checked"]
    assert len(unchecked) == 3 and all("was not checked" in r["reason"] for r in unchecked)
    assert not [u for u in net.requests if u.endswith(("/nyheter/l2", "/nyheter/l3", "/nyheter/l4"))]


def test_a_listing_card_alone_is_never_enough_even_with_a_dated_card() -> None:
    rec = run(only_card("/nyheter/finnes-ikke-heller", None, days_ago=2))
    assert news(rec) == []  # a dated card, a link, a meaningful title — and no article page behind it


def test_press_search_without_a_key_is_a_limitation_not_a_finding() -> None:
    rec = run(only_card("/nyheter/a", published(5)))
    search = rec["news"]["search"]
    assert search["state"] == "not_applicable" and "TAVILY_API_KEY" in search["note"]
    assert [c for c in news(rec)] and not [c for c in rec["claims"] if c.get("source_class") == "secondary_news"]


def test_validation_rules_name_publication_sources_only() -> None:
    assert nv.PUBLICATION_DATE_SOURCES == {"datePublished", "published_time", "time_itemprop_datePublished", "rss_pubDate", "atom_published"}
    for source in ("generic_time_element", "listing_card_date", "dc_date", "time_element", "printed_date", "feed_date_field"):
        assert nv.date_problem(day(3), source, today=date.today(), max_age_days=365), source
