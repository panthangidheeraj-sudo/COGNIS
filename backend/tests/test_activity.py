"""Recent activity, end to end: official newsroom / investor relations / feeds first, press coverage second, registers last — ranked, de-duplicated and honest.

The research pipeline runs against an offline fixture network (no real requests). The regression this file exists for: a report called 52 of 60 events "major"
because routine establishment registrations counted as business developments, while real announcements could be missed or buried.
"""
from __future__ import annotations

import copy
import json
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import httpx
import pytest
from conftest import research as research_plain
from test_free_sources import AUTO

from app.api.profile_builder import build_profile
from app.api.research_runs import DEEP_KEYS, QUICK_KEYS, plan_for
from app.config import Settings
from app.connectors import news_discovery
from app.evidence.gate import check
from app.evidence.models import Observation
from app.extraction.html import parse_html
from app.identity.model import CanonicalIdentity
from app.testing.fixtures import FixtureNetwork, company_page, verified_site

NAME = "AUTOBJØRN A/S"
FOOTER = "AUTOBJØRN A/S · Org.nr. 810 359 862 · Oslo"
LINKS = [("/om-oss", "Om oss"), ("/kontakt", "Kontakt"), ("/karriere", "Karriere"), ("/nyheter", "Nyheter"), ("/investor", "Investor relations")]
TAVILY = "https://api.tavily.com/search"
CONTRACT = "AUTOBJØRN signerer rammeavtale verdt 120 millioner kroner med Statens vegvesen"
RESULTS = "AUTOBJØRN presenterer resultater for andre kvartal 2026: driftsinntekter økte 14 prosent"
WEBINAR = "Invitasjon til webinar om elbil for bedriftskunder"
OFFICE = "Vi åpner nytt kontor i Bergen og ansetter flere rådgivere"
CFO = "Ny finansdirektør i AUTOBJØRN"


def day(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def human(days_ago: int) -> str:
    d = date.today() - timedelta(days=days_ago)
    return f"{d.day}. {['januar', 'februar', 'mars', 'april', 'mai', 'juni', 'juli', 'august', 'september', 'oktober', 'november', 'desember'][d.month - 1]} {d.year}"


def article(days_ago: int, title: str, link: str, text: str = "") -> str:
    return f'<article><time datetime="{day(days_ago)}">{human(days_ago)}</time><h2><a href="{link}">{title}</a></h2><p>{text}</p></article>'


def feed(*items: tuple[int, str, str, str]) -> str:
    body = "".join(f"<item><title>{t}</title><link>{link}</link><pubDate>{format_datetime(datetime.combine(date.today() - timedelta(days=d), datetime.min.time(), UTC))}</pubDate>"
                   f"<description>{desc}</description></item>" for d, t, link, desc in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>AUTOBJØRN</title>{body}</channel></rss>'


def company_site(*, newsroom: str | None, investor: str | None = None, feed_xml: str | None = None) -> dict[str, str]:
    pages = verified_site(NAME, AUTO)
    pages["/"] = pages["/"].replace("</nav>", '<a href="/investor">Investor relations</a></nav>')
    if feed_xml:
        pages["/"] = pages["/"].replace("<head>", '<head><link rel="alternate" type="application/rss+xml" href="/feed.xml">')
        pages["/feed.xml"] = feed_xml
    if newsroom is None:
        pages.pop("/nyheter")
        pages = {path: html.replace('<a href="/nyheter">Nyheter</a>', "").replace('<a href="/investor">Investor relations</a>', "") for path, html in pages.items()}  # nothing links to a newsroom
    else:
        pages["/nyheter"] = company_page(f"Nyheter – {NAME}", newsroom, footer=FOOTER, links=LINKS)
    if investor is not None:
        pages["/investor"] = company_page(f"Investor relations – {NAME}", investor, footer=FOOTER, links=LINKS)
    return pages


def network(pages: dict[str, str] | None, *, robots: str | None = None) -> FixtureNetwork:
    net = FixtureNetwork()
    net.load_brreg_probes()
    if pages is not None:
        net.add_site("autobjorn.no", pages, robots=robots)
    return net


def run(net: FixtureNetwork, **kw: Any) -> dict[str, Any]:
    import asyncio

    return asyncio.run(research_plain(net, AUTO, **kw))


def activity(rec: dict[str, Any]) -> dict[str, Any]:
    return build_profile(rec)["activity"]


def titles(act: dict[str, Any], tier: str | None = None) -> list[str]:
    return [e["title"] for e in act["events"] if tier is None or e["significance"] == tier]


def full_site() -> dict[str, str]:
    news = article(20, CONTRACT, "/nyheter/kontrakt", "Avtalen gjelder leveranse av tjenestebiler i fire år.") + article(5, WEBINAR, "/nyheter/webinar") + article(40, OFFICE, "/nyheter/bergen")
    ir = f'<ul><li><a href="/investor/q2">{RESULTS}</a> <span>{date.fromisoformat(day(50)).strftime("%d.%m.%Y")}</span></li></ul>'
    rss = feed((20, CONTRACT, "https://www.autobjorn.no/nyheter/kontrakt", "Avtalen gjelder leveranse av tjenestebiler i fire år."),
               (12, CFO, "https://www.autobjorn.no/nyheter/cfo", "Kari Nordmann tiltrer som ny finansdirektør."))
    return company_site(newsroom=news, investor=ir, feed_xml=rss)


def tavily(hits: list[dict[str, str]], calls: list[dict[str, Any]]):  # noqa: ANN201
    def handle(request: httpx.Request) -> httpx.Response | None:
        if str(request.url) != TAVILY:
            return None
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [{"title": h.get("title", ""), "url": h["url"], "content": h.get("content", "")} for h in hits]})
    return handle


def news_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The press-coverage searches (job discovery uses the same search API for its own query)."""
    return [c for c in calls if c.get("topic") == "news"]


def press_page(title: str, days_ago: int, body: str, *, extra_head: str = "") -> str:
    ld = json.dumps({"@context": "https://schema.org", "@type": "NewsArticle", "headline": title, "datePublished": day(days_ago)})
    return (f'<html lang="nb"><head><title>{title} | E24</title><script type="application/ld+json">{ld}</script>{extra_head}</head>'
            f"<body><article><h1>{title}</h1><p>{body}</p></article></body></html>")


# ================================================================== the actual issue ==
def test_company_announcements_outrank_routine_register_entries() -> None:
    rec = run(network(full_site()))
    act = activity(rec)
    by_title = {e["title"]: e for e in act["events"]}
    assert by_title[CONTRACT]["significance"] == "major" and by_title[RESULTS]["significance"] == "major" and by_title[CFO]["significance"] == "major"
    assert by_title[WEBINAR]["significance"] == "routine" and by_title[OFFICE]["significance"] == "relevant"
    registry = [e for e in act["events"] if e["sourceType"] == "official_registry"]
    assert registry and all(e["significance"] == "routine" for e in registry)  # still available, never major
    ranked = sorted(act["events"], key=lambda e: e["rank"])
    assert [e["significance"] for e in ranked] == sorted((e["significance"] for e in ranked), key=["major", "relevant", "routine"].index)  # tiers never interleave
    assert {e["title"] for e in ranked[:3]} == {CONTRACT, RESULTS, CFO}
    assert act["counts"] == {"major": 3, "relevant": 1, "routine": len(act["events"]) - 4}


def test_the_default_fixture_newsroom_item_is_relevant_not_major() -> None:
    act = activity(run(network(verified_site(NAME, AUTO))))
    office = next(e for e in act["events"] if e["title"].startswith("Vi åpner nytt kontor i Bergen"))
    assert office["significance"] == "relevant" and office["sourceType"] == "company_newsroom"
    assert act["counts"]["major"] == 0


def test_dozens_of_establishment_registrations_stay_available_but_are_not_major() -> None:
    rec = run(network(full_site()))
    est = next(c for c in rec["claims"] if c["field"] == "registered_establishment")
    for i in range(52):
        clone = copy.deepcopy(est)
        clone["key_suffix"] = f"synthetic-{i}"
        clone["key"] = f"{AUTO}|registered_establishment|synthetic-{i}|"
        clone["value"] = f"9{i:08d}"
        clone["effective_from"] = day(30 + i * 7)
        clone["attributes"] = {**(clone.get("attributes") or {}), "name": f"AUTOBJØRN AVD {i}"}
        rec["claims"].append(clone)
    act = activity(rec)
    registry = [e for e in act["events"] if e["sourceType"] == "official_registry"]
    assert len(registry) >= 52
    assert all(e["significance"] == "routine" for e in registry)
    assert act["counts"]["major"] == 3  # the three real announcements, not 52 registrations
    assert max(e["rank"] for e in act["events"] if e["significance"] == "major") < min(e["rank"] for e in registry)


def test_the_same_announcement_in_the_newsroom_and_the_feed_is_one_event_with_both_sources() -> None:
    act = activity(run(network(full_site())))
    contract = [e for e in act["events"] if e["title"] == CONTRACT]
    assert len(contract) == 1
    event = contract[0]
    urls = {s["url"] for s in event["sources"]}
    assert "https://www.autobjorn.no/feed.xml" in urls and any(u.endswith("/nyheter") for u in urls)
    assert len(event["evidence"]) == 2 and event["url"].endswith("/nyheter/kontrakt")
    assert any("2 places" in r for r in event["reasons"])


def test_every_event_has_date_description_source_url_source_type_and_evidence() -> None:
    act = activity(run(network(full_site())))
    for e in act["events"]:
        assert e["date"] and e["title"] and e["sourceType"] in ("investor_relations", "company_newsroom", "public_procurement", "official_registry", "secondary_news")
        assert e["evidence"] and all(ev.get("url") and ev.get("excerpt") for ev in e["evidence"])
        assert e["sources"] and e["reasons"] and isinstance(e["score"], int)
    contract = next(e for e in act["events"] if e["title"] == CONTRACT)
    assert contract["description"].startswith("Avtalen gjelder") and contract["sourceType"] == "company_newsroom"
    assert next(e for e in act["events"] if e["title"] == RESULTS)["sourceType"] == "investor_relations"


def test_existing_saved_research_is_reclassified_without_researching_again() -> None:
    rec = run(network(full_site()))
    legacy = copy.deepcopy(rec)
    legacy.pop("news")  # a record saved before newsroom discovery existed
    act = activity(legacy)
    assert act["counts"]["major"] >= 1 and all(e["significance"] in ("major", "relevant", "routine") for e in act["events"])
    assert next(c for c in act["sourcesChecked"] if c["kind"] == "newsroom")["status"] == "read"


# ============================================================ source limitations ==
def test_a_newsroom_blocked_by_robots_txt_is_a_limitation_and_is_never_fetched() -> None:
    net = network(full_site(), robots="User-agent: *\nDisallow: /nyheter\nDisallow: /investor\nDisallow: /feed.xml")
    rec = run(net)
    assert not [u for u in net.requests if "/nyheter" in u or "/investor" in u or "feed.xml" in u]  # robots.txt respected, not worked around
    act = activity(rec)
    assert CONTRACT not in titles(act) and RESULTS not in titles(act)
    blocked = [c for c in act["sourcesChecked"] if c["status"] == "blocked"]
    assert blocked and all(c["kind"] in ("newsroom", "investor_relations", "feed") for c in blocked)
    assert act["status"] == "partial" and "not evidence" in act["message"] and "robots.txt" in act["message"]
    assert act["counts"]["major"] == 0  # and nothing was invented to fill the gap


def test_an_unreachable_newsroom_is_reported_as_unread_not_as_no_news() -> None:
    net = network(full_site())
    net.fail("https://www.autobjorn.no/nyheter", "timeout")
    act = activity(run(net))
    assert next(c for c in act["sourcesChecked"] if c["kind"] == "newsroom" and c["url"].endswith("/nyheter"))["status"] in ("failed", "blocked")
    assert "not evidence" in act["message"] or "may be missing" in act["message"]
    assert RESULTS in titles(act)  # what could be read is still shown


def test_a_site_without_a_newsroom_does_not_claim_there_was_no_news() -> None:
    act = activity(run(network(company_site(newsroom=None))))
    newsroom = next(c for c in act["sourcesChecked"] if c["kind"] == "newsroom")
    assert newsroom["status"] == "not_found" and "none was found" in newsroom["note"]
    assert act["status"] == "partial" and "not evidence that none were made" in act["message"]
    assert act["counts"]["major"] == 0 and all(e["sourceType"] == "official_registry" for e in act["events"])


def test_a_script_rendered_newsroom_yields_no_events_and_says_so() -> None:
    act = activity(run(network(company_site(newsroom='<div id="app"></div><script src="/app.js"></script>'))))
    check_ = next(c for c in act["sourcesChecked"] if c["kind"] == "newsroom")
    assert check_["status"] == "no_dated_items" and "not evidence that there is no news" in check_["note"]


def test_without_a_verified_website_the_newsroom_is_not_checked_and_the_report_says_why() -> None:
    act = activity(run(network(None)))
    newsroom = next(c for c in act["sourcesChecked"] if c["kind"] == "newsroom")
    assert newsroom["status"] == "not_run" and "identity-verified website" in newsroom["note"]
    assert act["status"] in ("partial", "not_available") and "not" in act["message"].lower()


def test_no_events_at_all_never_reads_as_proof_that_nothing_happened(settings: Settings) -> None:
    rec = run(network(None))
    rec["claims"] = [c for c in rec["claims"] if c["field"] not in ("registration_date", "founded_date", "registered_establishment", "parent_company", "subsidiary", "former_name")]
    act = activity(rec)
    assert act["events"] == [] and act["status"] in ("not_available", "blocked")
    assert "does not mean that nothing happened" in act["message"]


def test_a_missing_search_key_is_a_stated_limitation(settings: Settings) -> None:
    rec = run(network(full_site()))
    search = next(c for c in activity(rec)["sourcesChecked"] if c["kind"] == "news_search")
    assert search["status"] == "not_run" and "TAVILY_API_KEY" in search["note"]


# =========================================================== press coverage search ==
def configured(settings: Settings, **update: Any) -> None:
    settings.tavily_api_key = "tvly-test-0000000000"
    for k, v in update.items():
        setattr(settings, k, v)


def press_network(hits: list[dict[str, str]], outlets: dict[str, dict[str, str]], calls: list[dict[str, Any]], *, robots: dict[str, str] | None = None) -> FixtureNetwork:
    net = network(full_site())
    net.handlers.append(tavily(hits, calls))
    for host, pages in outlets.items():
        net.add_site(host, pages, robots=(robots or {}).get(host))
    return net


def test_verified_press_coverage_is_added_with_a_short_verbatim_excerpt(settings: Settings) -> None:
    configured(settings)
    calls: list[dict[str, Any]] = []
    head = "Autobjørn kjøper konkurrent for 300 millioner kroner"
    lead = "Bilforhandleren Autobjørn har inngått avtale om å kjøpe konkurrenten Biler Nord for 300 millioner kroner, opplyser selskapet. " * 3
    net = press_network([{"url": "https://e24.no/naeringsliv/kjop", "title": head}], {"e24.no": {"/naeringsliv/kjop": press_page(head, 3, lead)}}, calls)
    rec = run(net)
    sent = news_calls(calls)
    assert len(sent) == 1 and set(sent[0]["include_domains"]) >= {"e24.no", "dn.no", "reuters.com"}  # restricted to reputable outlets
    act = activity(rec)
    event = next(e for e in act["events"] if e["title"] == head)
    assert event["sourceType"] == "secondary_news" and event["type"] == "acquisition" and event["significance"] == "major"
    assert event["url"] == "https://e24.no/naeringsliv/kjop" and event["sourceIds"][0].startswith("news-") and "e24.no" in event["sourceIds"][0]
    excerpt = event["evidence"][0]["excerpt"]
    assert excerpt.startswith(head) and len(excerpt) <= 300  # headline + short lead only, never the article
    assert next(c for c in act["sourcesChecked"] if c["kind"] == "news_search")["status"] == "read"
    profile = build_profile(rec)
    assert profile["sourceIndex"][event["sourceIds"][0]]["kind"] == "news" and profile["sourceIndex"][event["sourceIds"][0]]["official"] is False


def test_press_coverage_that_cannot_be_tied_to_this_exact_company_is_not_used(settings: Settings) -> None:
    configured(settings)
    calls: list[dict[str, Any]] = []
    other = "Autobjørn Bergen AS får ny sjef"
    wrong_number = "Autobjørn kjøper lagerbygg i Drammen"
    stale = "Autobjørn vant stor kontrakt for lenge siden"
    future = "Autobjørn vil kjøpe konkurrent neste år"
    undated = "Autobjørn uten publiseringsdato"
    hits = [{"url": f"https://dn.no/a{i}", "title": t} for i, t in enumerate([other, wrong_number, stale, future, undated, "Autobjørn blogg"])]
    hits.append({"url": "https://randomblog.example/autobjorn", "title": "Autobjørn blog"})
    outlets = {"dn.no": {"/a0": press_page(other, 2, "Autobjørn Bergen AS er et annet selskap enn morselskapet."),
                         "/a1": press_page(wrong_number, 2, "Eiendommen kjøpes av Autobjørn. Selger: Lager Drammen AS, org.nr. 923 609 016."),
                         "/a2": press_page(stale, 3000, "Autobjørn vant for mange år siden en kontrakt verdt 50 millioner kroner."),
                         "/a3": press_page(future, -90, "Autobjørn planlegger oppkjøp i fremtiden, ifølge selskapet selv."),
                         "/a4": f"<html><head><title>{undated}</title></head><body><h1>{undated}</h1><p>{'Tekst uten dato. ' * 12}</p></body></html>",
                         "/a5": press_page("Autobjørn blogg", 2, "Autobjørn")},
               "randomblog.example": {"/autobjorn": press_page("Autobjørn blog", 2, "x" * 100)}}
    net = press_network(hits, outlets, calls)
    rec = run(net)
    act = activity(rec)
    shown = titles(act)
    assert not {other, wrong_number, stale, future, undated} & set(shown)
    assert not [u for u in net.requests if "randomblog" in u]  # an outlet outside the allowlist is never fetched
    status = {c["url"].rsplit("/", 1)[-1]: c["status"] for c in rec["news"]["search"]["candidates"]}
    assert status["a0"] == "unverified" and status["a1"] == "unverified" and status["a2"] == "rejected" and status["a3"] == "rejected" and status["a4"] == "unverified"
    assert status["autobjorn"] == "ignored"
    reasons = {c["url"].rsplit("/", 1)[-1]: c["reason"] for c in rec["news"]["search"]["candidates"]}
    assert "exact organisation" in reasons["a0"] and "different organisation number" in reasons["a1"] and "no publication date" in reasons["a4"]
    assert next(c for c in act["sourcesChecked"] if c["kind"] == "news_search")["status"] == "read"  # the search ran; nothing qualified


def test_press_coverage_respects_robots_txt(settings: Settings) -> None:
    configured(settings)
    calls: list[dict[str, Any]] = []
    head = "Autobjørn kjøper konkurrent for 300 millioner kroner"
    net = press_network([{"url": "https://finansavisen.no/kjop", "title": head}], {"finansavisen.no": {"/kjop": press_page(head, 3, "Autobjørn " * 20)}}, calls,
                        robots={"finansavisen.no": "User-agent: *\nDisallow: /"})
    rec = run(net)
    assert not [u for u in net.requests if u.startswith("https://finansavisen.no/kjop")]
    assert rec["news"]["search"]["candidates"][0]["status"] == "blocked" and "robots.txt" in rec["news"]["search"]["candidates"][0]["reason"]
    assert head not in titles(activity(rec))


def test_a_failing_search_is_a_limitation_not_a_finding(settings: Settings) -> None:
    configured(settings)
    net = network(full_site())
    net.fail(TAVILY, "503")
    act = activity(run(net))
    search = next(c for c in act["sourcesChecked"] if c["kind"] == "news_search")
    assert search["status"] in ("failed", "blocked") and "not evidence" in search["note"]
    assert CONTRACT in titles(act)  # the company's own announcements are unaffected


def test_press_and_newsroom_reports_of_the_same_announcement_are_consolidated(settings: Settings) -> None:
    configured(settings)
    calls: list[dict[str, Any]] = []
    head = "AUTOBJØRN signerer rammeavtale verdt 120 millioner kroner med Statens vegvesen"
    net = press_network([{"url": "https://e24.no/avtale", "title": head}], {"e24.no": {"/avtale": press_page(head, 19, "AUTOBJØRN AS har signert en rammeavtale verdt 120 millioner kroner med Statens vegvesen. " * 2)}}, calls)
    act = activity(run(net))
    events = [e for e in act["events"] if "rammeavtale" in e["title"]]
    assert len(events) == 1 and events[0]["sourceType"] == "company_newsroom"  # the company's own wording is the primary source
    assert {s["sourceType"] for s in events[0]["sources"]} == {"company_newsroom", "secondary_news"} and len(events[0]["sources"]) >= 3
    assert act["consolidated"] >= 1


def test_press_search_can_be_switched_off(settings: Settings) -> None:
    configured(settings, enable_secondary_news=False)
    calls: list[dict[str, Any]] = []
    act = activity(run(press_network([], {}, calls)))
    assert news_calls(calls) == [] and next(c for c in act["sourcesChecked"] if c["kind"] == "news_search")["status"] == "not_run"


def test_press_search_is_not_run_in_quick_research(settings: Settings) -> None:
    configured(settings)
    calls: list[dict[str, Any]] = []
    run(press_network([], {}, calls), mode="quick")
    assert news_calls(calls) == []


def test_a_generic_company_name_is_not_searched_in_the_press(settings: Settings) -> None:
    import asyncio

    from app.connectors.base import ConnectorContext
    from app.net.http import HttpClient

    configured(settings)
    calls: list[dict[str, Any]] = []
    net = FixtureNetwork()
    net.handlers.append(tavily([], calls))

    async def go() -> news_discovery.NewsSearchResult:
        async with HttpClient(transport=net.transport(), sleep=lambda _s: asyncio.sleep(0)) as http:
            ctx = ConnectorContext(org_number="923609016", http=http, budget=None, settings=settings)
            return await news_discovery.discover_news(ctx, None, CanonicalIdentity(org_number="923609016", legal_name="Norsk Bygg AS"))

    res = asyncio.run(go())
    assert calls == [] and res.module.state == "not_applicable" and "too generic" in res.module.note  # a shared word proves nothing, so nothing is searched


# ============================================================== reading one article ==
def doc_of(html: str, url: str = "https://e24.no/a"):  # noqa: ANN201
    return parse_html(url, url, html, content_sha256="x", retrieved_at="2026-10-12T08:00:00Z")


def test_an_article_page_needs_a_headline_and_a_publication_date() -> None:
    article_, why = news_discovery.read_article(doc_of(press_page("Autobjørn vinner stor kontrakt med Forsvaret", 4, "Tekst om kontrakten. " * 8)))
    assert why is None and article_.headline == "Autobjørn vinner stor kontrakt med Forsvaret" and article_.day == day(4)
    assert len(article_.lead) <= 300 and article_.lead.startswith("Tekst om kontrakten")
    none, why = news_discovery.read_article(doc_of("<html><head><title>Autobjørn vinner kontrakt</title></head><body><h1>Autobjørn vinner kontrakt</h1><p>" + "x " * 50 + "</p></body></html>"))
    assert none is None and "no publication date" in why


def test_nosnippet_pages_keep_only_the_headline() -> None:
    page = press_page("Autobjørn vinner stor kontrakt med Forsvaret", 4, "Tekst om kontrakten. " * 8, extra_head='<meta name="robots" content="nosnippet">')
    article_, _ = news_discovery.read_article(doc_of(page))
    assert article_.nosnippet and article_.lead == ""


def test_a_section_page_listing_several_articles_is_not_one_article() -> None:
    ld = [json.dumps({"@type": "NewsArticle", "headline": f"Overskrift nummer {i} om noe", "datePublished": day(i + 1), "url": f"https://e24.no/{i}"}) for i in range(3)]
    html = "<html><head><title>Næringsliv</title>" + "".join(f'<script type="application/ld+json">{x}</script>' for x in ld) + "</head><body><h1>Næringsliv</h1></body></html>"
    none, why = news_discovery.read_article(doc_of(html, "https://e24.no/naeringsliv"))
    assert none is None and "several articles" in why


@pytest.mark.parametrize("headline,expected", [
    ("Autobjørn Bergen AS får ny sjef", True),
    ("Autobjørn Group AS åpner", True),
    ("Nordic Autobjørn AS vinner", True),
    ("Autobjørn kjøper konkurrent for 300 millioner kroner", False),
    ("Autobjørn AS kjøper Biler Nord AS", False),
    ("AUTOBJØRN A/S signerer avtale", False),
])
def test_a_name_that_continues_into_a_longer_company_name_is_a_different_company(headline: str, expected: bool) -> None:
    assert news_discovery.continues_into_longer_name(headline, "AUTOBJØRN AS") is expected


# ================================================================ publication gate ==
def news_obs(**kw: Any) -> Observation:
    base: dict[str, Any] = dict(field="news_item", value="Autobjørn kjøper konkurrent for 300 millioner kroner", key_suffix=f"{day(3)}|x", as_of=day(3), effective_from=day(3), module="news_discovery",
                                source_id="news-e24.no", source_name="e24.no", source_class="secondary_news", source_url="https://e24.no/a", retrieved_at="2026-10-12T08:00:00Z",
                                content_sha256="abc", claim_span="Autobjørn kjøper konkurrent for 300 millioner kroner — Bilforhandleren …", extraction_method="secondary_article", tier="B",
                                identity_score=0.95, attributes={"identity_basis": "exact_legal_name_in_headline", "origin": "secondary_news"})
    base.update(kw)
    return Observation(**base)


def test_the_gate_publishes_a_verified_press_item_and_refuses_unsupported_ones() -> None:
    assert check(news_obs()) is None
    assert check(news_obs(attributes={"origin": "secondary_news"})) == "third-party record not resolved to this exact organisation"  # no identity basis
    assert check(news_obs(identity_score=0.5)) == "third-party record not resolved to this exact organisation"
    assert check(news_obs(source_url=None)) == "no source URL"
    assert check(news_obs(claim_span="  ")) == "no evidence span"
    assert check(news_obs(retrieved_at=None)) == "no retrieval time"
    assert "candidates, not evidence" in (check(news_obs(source_class="search_snippet")) or "")
    assert "candidates, not evidence" in (check(news_obs(tier="C")) or "")
    llm = news_obs(source_class="company_owned", extraction_method="llm_quote", attributes={"quote_verified": False}, identity_score=0.9)
    assert check(llm) == "LLM extraction whose quote was not found verbatim on the page"


def test_a_published_event_whose_evidence_does_not_contain_its_headline_is_excluded() -> None:
    rec = run(network(full_site()))
    claim = next(c for c in rec["claims"] if c["field"] == "news_item" and c["value"] == CONTRACT)
    evidence = {e["id"]: e for e in rec["evidence"]}
    for ev_id in claim["evidence_ids"]:
        evidence[ev_id]["claim_span"] = "Cookie-innstillinger og personvern"
    act = activity(rec)
    assert CONTRACT not in titles(act)
    assert act["excluded"]["count"] >= 1 and any("headline" in x["reason"] for x in act["excluded"]["items"])


def test_a_published_event_without_a_valid_date_or_source_url_is_excluded() -> None:
    rec = run(network(full_site()))
    news = [c for c in rec["claims"] if c["field"] == "news_item"]
    news[0]["as_of"] = "2026-99-99"
    news[0]["attributes"] = {**news[0].get("attributes", {}), "date": None}
    evidence = {e["id"]: e for e in rec["evidence"]}
    for ev_id in news[1]["evidence_ids"]:
        evidence[ev_id]["source_url"] = None
    news[1]["attributes"] = {**news[1].get("attributes", {}), "url": None}
    act = activity(rec)
    assert {news[0]["value"], news[1]["value"]}.isdisjoint(titles(act))
    reasons = " | ".join(x["reason"] for x in act["excluded"]["items"])
    assert "no valid date" in reasons and "no source URL" in reasons


# ====================================================================== plan & config ==
def test_company_news_is_part_of_the_research_plan() -> None:
    assert "news" in QUICK_KEYS and "news" in DEEP_KEYS
    for mode in ("quick", "deep"):
        assert "news" in [s["key"] for s in plan_for(mode, None, llm=True)["steps"]]


def test_newsroom_discovery_can_be_switched_off_and_falls_back_to_crawled_pages(settings: Settings) -> None:
    settings.enable_news_discovery = False
    rec = run(network(verified_site(NAME, AUTO)))
    assert rec["news"]["newsroom"]["state"] == "not_applicable"
    assert any(c["field"] == "news_item" for c in rec["claims"])  # the previous behaviour: items on pages the crawl already read
    assert next(c for c in activity(rec)["sourcesChecked"] if c["kind"] == "newsroom")["status"] == "not_run"


def test_a_plan_without_company_news_makes_no_extra_requests(settings: Settings) -> None:
    import asyncio

    from app.agent.orchestrator import Orchestrator, ResearchOptions
    from app.net.http import HttpClient
    from app.providers.fake_provider import FakeProvider
    from app.runtime.budgets import BudgetLimits, RunBudget

    net = network(full_site())

    async def go() -> dict[str, Any]:
        async with HttpClient(transport=net.transport(), sleep=lambda _s: asyncio.sleep(0)) as http:
            orch = Orchestrator(http=http, run_budget=RunBudget(BudgetLimits(max_requests=500)), provider=FakeProvider())
            return await orch.research(AUTO, run_id="t", options=ResearchOptions(mode="quick", include_geo=False, step_keys=["registry", "accounts", "roles", "website"]))

    rec = asyncio.run(go())
    assert not [u for u in net.requests if "feed.xml" in u]  # no feed, sitemap or guessed path was requested
    assert rec["news"]["search"]["state"] == "not_applicable"
