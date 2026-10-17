"""Free hiring data: wrong-company jobs, stale listings, duplicate openings, NAV timeouts and missing hiring data.

Hiring comes from the company's own careers pages and linked job boards first; Tavily-suggested job pages are candidates that must be
verified; NAV is supplementary. Missing data is never read as "not hiring". No test touches the real network."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from conftest import research as research_plain
from test_free_sources import AUTO, NAV, research_with_db, run
from test_free_sources import network as ads_network  # offline NAV feed + register fixtures

from app.api.profile_builder import build_profile
from app.config import Settings
from app.connectors import job_discovery, nav
from app.connectors import jobs as jobs_conn
from app.connectors.jobs import JobItem, dedupe_jobs, jobs_from_jsonld, posting_state
from app.extraction.html import parse_html
from app.identity.model import CanonicalIdentity
from app.storage.db import Database
from app.testing.fixtures import FixtureNetwork, company_page, verified_site

FOOTER = "AUTOBJØRN A/S · Org.nr. 810 359 862 · Oslo"
LINKS = [("/om-oss", "Om oss"), ("/kontakt", "Kontakt"), ("/karriere", "Karriere"), ("/nyheter", "Nyheter")]
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
TAVILY = "https://api.tavily.com/search"


def posting(title: str, *, org: str | dict | None = "AUTOBJØRN A/S", posted: str | None = "2026-09-20", valid: str | None = "2099-01-31", url: str | None = None,
            city: str | None = "Oslo", modified: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"@context": "https://schema.org", "@type": "JobPosting", "title": title}
    if org:
        out["hiringOrganization"] = org if isinstance(org, dict) else {"@type": "Organization", "name": org}
    if city:
        out["jobLocation"] = {"@type": "Place", "address": {"addressLocality": city}}
    for key, value in (("datePosted", posted), ("validThrough", valid), ("url", url), ("dateModified", modified)):
        if value:
            out[key] = value
    return out


def site(postings: list[dict] | None = None, *, body: str = "<h1>Ledige stillinger</h1>", extra_links: list[tuple[str, str]] | None = None) -> dict[str, str]:
    pages = verified_site("AUTOBJØRN A/S", AUTO)
    pages["/karriere"] = company_page("Karriere – AUTOBJØRN A/S", body, footer=FOOTER, links=LINKS + (extra_links or []), jsonld=postings or [])
    return pages


def settings_with(settings: Settings, **update: Any) -> Settings:
    update.setdefault("enable_regulatory_discovery", False)  # likewise for the regulator-page search (tests/test_regulatory_and_chat.py)
    update.setdefault("enable_secondary_news", False)  # these tests are about job discovery; the press-coverage search has its own tests (test_activity.py)
    for key, value in update.items():
        setattr(settings, key, value)
    return settings


def doc(html_postings: list[dict], url: str = "https://autobjorn.no/karriere", text: str = "Ledige stillinger"):  # noqa: ANN201
    html = company_page("Karriere", f"<h1>{text}</h1>", jsonld=html_postings)
    return parse_html(url, url, html, content_sha256="x", retrieved_at="2026-10-09T08:00:00Z")


def item(title: str, **kw: Any) -> JobItem:
    base: dict[str, Any] = {"id": kw.pop("id", title), "title": title, "url": "https://autobjorn.no/karriere", "source_url": "https://autobjorn.no/karriere",
                            "source_host": "autobjorn.no", "method": "json_ld"}
    base.update(kw)
    return JobItem(**base)


def hiring(rec: dict[str, Any], **kw: Any) -> dict[str, Any]:
    return build_profile(rec, **kw)["hiring"]


@pytest.fixture
def quiet_nav(monkeypatch: pytest.MonkeyPatch) -> tuple[FixtureNetwork, list[str], list[Any]]:
    """A working NAV feed in which no ad belongs to the company: NAV was checked and has nothing."""
    import test_free_sources as t

    monkeypatch.setattr(t, "ADS", {"x-1": t._ad("x-1", "Sveiser", orgnr=t.OTHER_ORG, employer="Helt Annet AS"), "a-later-inactive": t.ADS["a-later-inactive"]})
    return ads_network()


def evidence_span(rec: dict[str, Any], claim: dict[str, Any]) -> str:
    by_id = {e["id"]: e for e in rec["evidence"]}
    return " | ".join(by_id[i]["claim_span"] for i in claim["evidence_ids"] if i in by_id)


def tavily_handler(hits: list[dict[str, str]], calls: list[dict]):  # noqa: ANN201
    def handle(request: httpx.Request) -> httpx.Response | None:
        if str(request.url) != TAVILY:
            return None
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [{"title": h.get("title", ""), "url": h["url"], "content": h.get("content", "")} for h in hits]})
    return handle


def research(net: FixtureNetwork, *, nav_index: bool = True, org: str = AUTO) -> dict[str, Any]:
    """One research run. With ``nav_index`` the NAV feed is synced first (as in production); without it NAV is not configured for the run."""
    if nav_index:
        return run(research_with_db(net, Database(":memory:"), org))
    return run(research_plain(net, org))


# ============================================================ wrong-company jobs ==
def test_posting_of_another_employer_on_the_company_site_is_dropped() -> None:
    d = doc([posting("Selger", org="Helt Annet Firma AS"), posting("Mekaniker")])
    titles = [j.title for j in jobs_from_jsonld(d, "AUTOBJØRN A/S", "Autobjørn", now=NOW)]
    assert titles == ["Mekaniker"]


def test_search_suggested_job_page_must_be_tied_to_this_exact_organisation(settings: Settings) -> None:
    """Tavily proposes three ATS pages: a similarly named company, an unverifiable page and the company's own (names the verified website)."""
    settings_with(settings, tavily_api_key="tvly-test-0000000000")
    calls: list[dict] = []
    host = "jobs.example-ats.teamtailor.com"
    hits = [{"url": f"https://{host}/jobs/1-selger-bergen", "title": "Autobjørn Bergen – Selger"},
            {"url": f"https://{host}/jobs/2-lagerjobb", "title": "Autobjørn lager"},
            {"url": f"https://{host}/jobs/3-bilselger", "title": "Autobjørn – Bilselger"}]
    pages = {
        "/jobs/1-selger-bergen": company_page("Selger Bergen", "<h1>Selger</h1>", jsonld=[posting("Selger Bergen", org="Autobjørn Bergen AS")]),  # similar name only
        "/jobs/2-lagerjobb": company_page("Lager", "<h1>Lager</h1>", jsonld=[posting("Lagerarbeider", org=None)]),  # no employer at all
        "/jobs/3-bilselger": company_page("Bilselger", "<h1>Bilselger</h1>", jsonld=[posting("Bilselger", org={"@type": "Organization", "name": "Autobjørn", "url": "https://www.autobjorn.no"})]),
    }
    net = FixtureNetwork()
    net.load_brreg_probes()
    net.handlers.append(tavily_handler(hits, calls))
    net.add_site("autobjorn.no", site())
    net.add_site(host, pages)
    rec = research(net, nav_index=False)

    # the search was restricted to the verified domain and known job boards, and asked once
    assert len(calls) == 1 and "autobjorn.no" in calls[0]["include_domains"] and "teamtailor.com" in calls[0]["include_domains"]
    assert "arbeidsplassen.nav.no" not in calls[0]["include_domains"]
    published = {c["value"]: c for c in rec["claims"] if c["field"] == "job_posting"}
    assert set(published) == {"Bilselger"}
    assert published["Bilselger"]["attributes"]["identity_basis"] == "hiring_organization_website" and published["Bilselger"]["attributes"]["discovered"] is True
    why = {c["title"]: c for c in rec["jobs"]["discovery_candidates"]}
    assert why["Selger Bergen"]["status"] == "wrong_company" and "Autobjørn Bergen AS" in why["Selger Bergen"]["reason"]
    assert why["Lagerarbeider"]["status"] == "unverified"
    # the rejected candidates never appear anywhere in the published record
    assert "Selger Bergen" not in json.dumps(rec["claims"], ensure_ascii=False) and "Lagerarbeider" not in json.dumps(rec["claims"], ensure_ascii=False)
    h = hiring(rec)
    assert h["outcome"] == "verified" and h["totalCurrent"] == 1


def test_search_hits_on_other_platforms_are_never_fetched(settings: Settings) -> None:
    settings_with(settings, tavily_api_key="tvly-test-0000000000")
    net = FixtureNetwork()
    net.load_brreg_probes()
    hits = [{"url": "https://arbeidsplassen.nav.no/stillinger/stilling/abc", "title": "Autobjørn"}, {"url": "https://www.finn.no/job/ad/1", "title": "Autobjørn"},
            {"url": "https://www.linkedin.com/jobs/view/1", "title": "Autobjørn"}, {"url": "https://www.indeed.com/viewjob?jk=1", "title": "Autobjørn"}]
    net.handlers.append(tavily_handler(hits, []))
    net.add_site("autobjorn.no", site())
    rec = research(net, nav_index=False)
    fetched = [u for u in net.requests if any(h in u for h in ("arbeidsplassen.nav.no", "finn.no", "linkedin.com", "indeed.com"))]
    assert fetched == []  # not a single request to those platforms (the search hits were ignored, the site's own LinkedIn link is not fetched either)
    assert all(c["status"] == "ignored" for c in rec["jobs"]["discovery_candidates"])


def test_robots_txt_is_respected_for_search_suggested_pages(settings: Settings) -> None:
    settings_with(settings, tavily_api_key="tvly-test-0000000000")
    host = "autobjorn.teamtailor.com"
    net = FixtureNetwork()
    net.load_brreg_probes()
    net.handlers.append(tavily_handler([{"url": f"https://{host}/jobs/1-selger", "title": "Autobjørn selger"}], []))
    net.add_site("autobjorn.no", site())
    net.add_site(host, {"/jobs/1-selger": company_page("Selger", "<h1>Selger</h1>", jsonld=[posting("Selger")])}, robots="User-agent: *\nDisallow: /jobs/\n")
    rec = research(net, nav_index=False)
    cand = rec["jobs"]["discovery_candidates"][0]
    assert cand["status"] == "blocked" and "robots.txt" in cand["reason"]
    assert not [c for c in rec["claims"] if c["field"] == "job_posting"]
    assert not any(u.endswith("/jobs/1-selger") for u in net.requests)  # the page itself was never requested


# ============================================================== stale listings ==
def test_postings_past_their_end_or_without_recent_dates_are_stale() -> None:
    assert posting_state("2026-10-08", "2026-09-01", None, NOW, 180) == "stale"  # ended yesterday
    assert posting_state("2026-10-09", "2026-09-01", None, NOW, 180) == "current"  # a date-only end date is inclusive: open all of that day
    assert posting_state(None, "2026-01-01", None, NOW, 180) == "stale"  # no end date, posted over 180 days ago
    assert posting_state(None, "2026-01-01", "2026-10-01", NOW, 180) == "current"  # recently updated
    assert posting_state(None, "2026-09-20", None, NOW, 180) == "current"
    d = doc([posting("Gammel stilling", valid=None, posted="2025-01-01"), posting("Utløpt", valid="2026-06-30"), posting("Åpen")])
    states = {j.title: j.state for j in jobs_from_jsonld(d, "AUTOBJØRN A/S", "Autobjørn", now=NOW)}
    assert states == {"Gammel stilling": "stale", "Utløpt": "stale", "Åpen": "current"}


def test_stale_postings_are_not_counted_and_are_shown_as_stale() -> None:
    net = FixtureNetwork()
    net.load_brreg_probes()
    net.add_site("autobjorn.no", site([posting("Utløpt stilling", valid="2026-01-31"), posting("Åpen stilling")]))
    rec = research(net, nav_index=False)
    h = hiring(rec)
    assert h["totalCurrent"] == 1 and h["outcome"] == "verified"
    states = {j["title"]: j["state"] for j in h["jobs"]}
    assert states == {"Utløpt stilling": "stale", "Åpen stilling": "current"}
    stale = next(j for j in h["jobs"] if j["title"] == "Utløpt stilling")
    assert stale["validThrough"] == "2026-01-31" and stale["postedAt"] == "2026-09-20" and stale["url"].startswith("https://")


def test_only_stale_postings_never_give_a_count_or_a_zero(quiet_nav: Any) -> None:
    net, _calls, _ = quiet_nav
    net.add_site("autobjorn.no", site([posting("Utløpt stilling", valid="2026-01-31")]))
    rec = research(net)
    h = hiring(rec)
    assert h["totalCurrent"] is None and h["outcome"] == "none_found"
    assert not [c for c in rec["claims"] if c["field"] == "open_positions_count"]


def test_closed_notice_on_a_job_board_page_makes_the_posting_closed(settings: Settings) -> None:
    host = "autobjorn.teamtailor.com"
    net = FixtureNetwork()
    net.load_brreg_probes()
    board = company_page("Jobber", '<h1>Jobber</h1><a href="/jobs/1-selger">Selger</a>', jsonld=[])
    detail = company_page("Selger", "<h1>Selger</h1><p>Søknadsfristen er utløpt.</p>", jsonld=[posting("Selger")])
    net.add_site(host, {"/jobs": board, "/jobs/1-selger": detail})
    net.add_site("autobjorn.no", site(extra_links=[(f"https://{host}/jobs", "Se alle stillinger")]))
    rec = research(net, nav_index=False)
    h = hiring(rec)
    assert [j["state"] for j in h["jobs"]] == ["closed"] and h["totalCurrent"] is None
    assert not [c for c in rec["claims"] if c["field"] == "open_positions_count"]


def test_search_found_posting_without_any_date_is_not_current(settings: Settings) -> None:
    settings_with(settings, tavily_api_key="tvly-test-0000000000")
    host = "autobjorn.teamtailor.com"
    net = FixtureNetwork()
    net.load_brreg_probes()
    net.handlers.append(tavily_handler([{"url": f"https://{host}/jobs/1-selger", "title": "Autobjørn selger"}], []))
    net.add_site("autobjorn.no", site())
    net.add_site(host, {"/jobs/1-selger": company_page("Selger", "<h1>Selger</h1>", jsonld=[posting("Selger", posted=None, valid=None,
                                                                                                    org={"name": "Autobjørn", "url": "https://autobjorn.no"})])})
    rec = research(net, nav_index=False)
    assert not [c for c in rec["claims"] if c["field"] == "job_posting"]
    assert rec["jobs"]["discovery_candidates"][0]["status"] == "stale" and "not shown to be current" in rec["jobs"]["discovery_candidates"][0]["reason"]


# ============================================================= duplicate openings ==
def test_same_opening_on_several_sources_is_merged_and_keeps_every_listing() -> None:
    company = item("Bilselger", id="c1", url="https://autobjorn.no/karriere/bilselger", location="Oslo", posted_at="2026-09-20", valid_through="2026-12-31")
    board = item("Bilselger (m/k)", id="b1", url="https://autobjorn.teamtailor.com/jobs/1-bilselger", source_host="autobjorn.teamtailor.com", method="ats_link", location="Oslo")
    navjob = item("Bilselger", id="nav-1", url="https://arbeidsplassen.nav.no/stillinger/stilling/x", source_url="https://arbeidsplassen.nav.no/stillinger/stilling/x",
                  source_host="arbeidsplassen.nav.no", method="nav_feed", source="nav", location="Oslo", posted_at="2026-09-25",
                  details={"nav_uuid": "x", "updated_at": "2026-09-30T08:00:00", "original_source_url": "https://autobjorn.no/karriere/bilselger"})
    other_place = item("Bilselger", id="c2", url="https://autobjorn.no/karriere/bilselger-bergen", location="Bergen")
    merged = dedupe_jobs([navjob, board, company, other_place])
    assert [(j.id, j.location) for j in merged] == [("c1", "Oslo"), ("c2", "Bergen")]  # same title in another city is another opening
    rep = merged[0]
    assert {m["id"] for m in rep.details["merged"]} == {"b1", "nav-1"}
    assert {m["url"] for m in rep.details["merged"]} >= {"https://autobjorn.teamtailor.com/jobs/1-bilselger", "https://arbeidsplassen.nav.no/stillinger/stilling/x"}
    nav_listing = next(m for m in rep.details["merged"] if m["id"] == "nav-1")
    assert nav_listing["posted_at"] == "2026-09-25" and nav_listing["updated_at"].startswith("2026-09-30") and nav_listing["state"] == "current"
    assert (rep.posted_at, rep.valid_through) == ("2026-09-20", "2026-12-31")


def test_merged_opening_takes_the_most_cautious_status() -> None:
    company = item("Selger", id="c1", url="https://autobjorn.no/karriere/selger", state="current")
    stale = item("Selger", id="b1", url="https://autobjorn.no/karriere/selger", method="ats_link", state="stale")
    (rep,) = dedupe_jobs([company, stale])
    assert rep.state == "stale" and "stale" in rep.details["state_conflict"]


def test_distinct_openings_with_a_shared_application_page_are_not_merged() -> None:
    a = item("Mekaniker", id="n1", source="nav", method="nav_feed", url="https://arbeidsplassen.nav.no/stillinger/stilling/a", source_url="https://arbeidsplassen.nav.no/stillinger/stilling/a",
             details={"application_url": "https://apply.example/x"}, location="Oslo")
    b = item("Lagerarbeider", id="n2", source="nav", method="nav_feed", url="https://arbeidsplassen.nav.no/stillinger/stilling/b", source_url="https://arbeidsplassen.nav.no/stillinger/stilling/b",
             details={"application_url": "https://apply.example/x"}, location="Oslo")
    assert len(dedupe_jobs([a, b])) == 2


def test_duplicate_listings_across_careers_page_board_and_nav_count_once(settings: Settings) -> None:
    """End to end: the careers page lists Bilselger twice (structured data + link) and NAV has the same opening; one more NAV ad is different."""
    net, _calls, _ = ads_network()
    net.add_site("autobjorn.no", site([posting("Bilselger", url="https://autobjorn.no/karriere/bilselger")],
                                      body='<h1>Ledige stillinger</h1><ul><li><a href="/jobs/bilselger">Bilselger</a></li></ul>'))
    net.sites["autobjorn.no"]["/jobs/bilselger"] = site()["/karriere"]
    rec = research(net)
    h = hiring(rec)
    titles = sorted(j["title"] for j in h["jobs"] if j["state"] == "current")
    assert titles.count("Bilselger") == 1  # not 3
    assert h["totalCurrent"] == len(titles) == 3  # Bilselger (company + link + NAV, once), Mekaniker, Lagermedarbeider (NAV)
    bilselger = next(j for j in h["jobs"] if j["title"] == "Bilselger")
    assert bilselger["url"] and bilselger["postedAt"] and bilselger["alsoListed"]
    count = next(c for c in rec["claims"] if c["field"] == "open_positions_count")
    assert count["value"] == 3 and "merged and counted once" in evidence_span(rec, count)
    assert {"jobs", "nav"} <= {e["source_id"] for e in rec["evidence"] if e["id"] in count["evidence_ids"]}
    # the merged opening keeps the evidence of both listings
    assert {e["sourceId"] for e in bilselger["evidence"]} >= {"nav"} and len(bilselger["evidence"]) >= 2


# ================================================================== NAV timeouts ==
def test_nav_timeout_does_not_break_research_or_remove_company_openings() -> None:
    net, _calls, _ = ads_network()
    net.add_site("autobjorn.no", site([posting("Bilselger"), posting("Selger")]))
    # sync the index first, then NAV starts timing out while the ads are read
    rec = run(_research_after_sync(net, fail=f"{NAV}/api/v1/feedentry"))
    nav_mod = rec["modules"]["nav_jobs"]
    assert nav_mod["state"] == "failed" and "could not be checked" in nav_mod["note"] and "not evidence" in nav_mod["note"]
    assert rec["terminal_status"] == "completed"
    h = hiring(rec)
    assert h["totalCurrent"] == 2 and h["outcome"] == "verified"
    assert "NAV Arbeidsplassen" in h["message"] and "further openings" in h["message"]  # the caveat: NAV could not be checked
    assert {c["id"]: c["state"] for c in h["checks"]}["nav"] == "unavailable"
    assert "nav" not in h["searchedSourceIds"]


def test_nav_timeout_with_no_company_openings_is_source_unavailable_not_zero() -> None:
    net, _calls, _ = ads_network()
    net.add_site("autobjorn.no", site(body="<h1>Ledige stillinger</h1><p>Vi har ingen ledige stillinger akkurat nå.</p>"))
    rec = run(_research_after_sync(net, fail=f"{NAV}/api/v1/feedentry"))
    h = hiring(rec)
    assert h["outcome"] == "source_unavailable" and h["totalCurrent"] is None  # the careers page said "no openings", but NAV was down: no zero is shown
    assert "NAV Arbeidsplassen" in h["message"] and "not evidence" in h["message"]
    assert not [c for c in rec["claims"] if c["field"] == "open_positions_count"]
    assert h["status"] == "partial"


def test_nav_unreachable_stops_after_two_failures_and_token_timeout_is_unavailable() -> None:
    net, _calls, _ = ads_network()
    net.add_site("autobjorn.no", site())
    rec = run(_research_after_sync(net, fail=f"{NAV}/api/v1/feedentry"))
    entry_calls = [u for u in net.requests if "/api/v1/feedentry/" in u]
    assert len(entry_calls) <= 2 * 4  # two candidates (each with a few retries), then the rest are not requested
    skipped = [c for c in rec["jobs"]["nav"]["candidates"] if "stopped responding" in c["reason"]]
    assert skipped and all(c["status"] == "not_checked" for c in skipped)

    # the token endpoint itself timing out is "unreachable", not "access refused"
    net2, _c, _b = ads_network()
    net2.add_site("autobjorn.no", site())
    rec2 = run(_research_after_sync(net2, fail=f"{NAV}/api/publicToken", reset_token=True))
    assert rec2["modules"]["nav_jobs"]["state"] == "failed"
    assert hiring(rec2)["outcome"] == "source_unavailable"


def test_nav_step_has_a_hard_time_limit(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_with(settings, nav_step_timeout_seconds=0.05)

    async def never_answers(*_a: Any, **_k: Any) -> Any:
        await asyncio.sleep(5)

    monkeypatch.setattr(nav, "nav_jobs", never_answers)
    net, _calls, _ = ads_network()
    net.add_site("autobjorn.no", site([posting("Bilselger")]))
    rec = research(net)
    assert rec["modules"]["nav_jobs"]["state"] == "failed" and "did not answer within" in rec["modules"]["nav_jobs"]["note"]
    h = hiring(rec)
    assert h["totalCurrent"] == 1 and h["outcome"] == "verified"


def test_nav_internal_error_is_contained(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(nav, "nav_jobs", boom)
    net, _calls, _ = ads_network()
    net.add_site("autobjorn.no", site([posting("Bilselger")]))
    rec = research(net)
    assert rec["modules"]["nav_jobs"]["state"] == "failed" and "RuntimeError" in rec["modules"]["nav_jobs"]["note"]
    assert hiring(rec)["totalCurrent"] == 1


async def _research_after_sync(net: FixtureNetwork, *, fail: str, reset_token: bool = False) -> dict[str, Any]:
    """Build the NAV index while NAV works, then make NAV fail (the case that matters: the research itself meets the timeout)."""
    from app.agent.orchestrator import Orchestrator, ResearchOptions
    from app.config import get_settings
    from app.net.http import HttpClient
    from app.providers.fake_provider import FakeProvider
    from app.runtime.budgets import BudgetLimits, RunBudget

    db = Database(":memory:")
    async with HttpClient(transport=net.transport(), sleep=lambda _s: asyncio.sleep(0)) as http:
        await nav.sync_feed(http, db, get_settings())
        if reset_token:
            nav.TOKEN.public = None
        net.fail(fail, "timeout")
        orch = Orchestrator(http=http, run_budget=RunBudget(BudgetLimits(max_requests=500)), provider=FakeProvider(), db=db)
        return await orch.research(AUTO, run_id="test", options=ResearchOptions(mode="deep", include_geo=False))


# ============================================================ missing hiring data ==
def test_no_careers_page_and_no_nav_match_is_none_found_not_zero(quiet_nav: Any) -> None:
    net, _calls, _ = quiet_nav
    pages = verified_site("AUTOBJØRN A/S", AUTO)
    pages.pop("/karriere")
    pages["/"] = pages["/"].replace('<a href="/karriere">Karriere</a>', "")
    net.add_site("autobjorn.no", pages)
    rec = research(net)
    h = hiring(rec)
    assert h["totalCurrent"] is None and h["outcome"] == "none_found"
    assert "does not mean the company is not hiring" in h["message"]
    assert {c["id"]: c["state"] for c in h["checks"]} == {"careers": "checked", "nav": "checked"}
    assert not [c for c in rec["claims"] if c["field"] == "open_positions_count"]  # absence is not a zero


def test_careers_page_that_cannot_be_fetched_is_unavailable_not_absent(quiet_nav: Any) -> None:
    net, _calls, _ = quiet_nav
    net.add_site("autobjorn.no", site())
    net.fail("https://www.autobjorn.no/karriere", "timeout")
    rec = research(net)
    h = hiring(rec)
    assert h["outcome"] == "source_unavailable" and h["totalCurrent"] is None
    assert "Company careers" in h["message"] and "timed out" in h["message"]
    assert "No careers page" not in (rec["jobs"]["note"] or "")


def test_unverified_website_means_incomplete_research() -> None:
    net = FixtureNetwork()
    net.load_brreg_probes()  # no website for the company is served: nothing to verify
    rec = research(net, nav_index=False)
    h = hiring(rec)
    assert h["outcome"] == "incomplete" and h["totalCurrent"] is None
    assert "not evidence" in h["message"] and "No identity-verified company website" in h["message"]
    assert not [c for c in rec["claims"] if c["field"] == "open_positions_count"]


def test_explicit_no_openings_statement_is_the_only_zero(quiet_nav: Any) -> None:
    net, _calls, _ = quiet_nav
    net.add_site("autobjorn.no", site(body="<h1>Ledige stillinger</h1><p>Vi har ingen ledige stillinger akkurat nå.</p>"))
    rec = research(net)
    h = hiring(rec)
    assert h["totalCurrent"] == 0 and h["outcome"] == "none_found" and "states that it has no open positions" in h["message"]
    zero = next(c for c in rec["claims"] if c["field"] == "open_positions_count")
    assert zero["value"] == 0 and "ingen ledige stillinger" in evidence_span(rec, zero).casefold()


def test_nothing_is_inferred_for_an_old_record_without_an_outcome() -> None:
    net = FixtureNetwork()
    net.load_brreg_probes()
    net.add_site("autobjorn.no", site())
    rec = research(net, nav_index=False)
    rec["jobs"].pop("outcome", None)  # records stored before the outcome existed
    h = hiring(rec)
    assert h["totalCurrent"] is None and "outcome" not in h and h["status"] != "available" and h["message"]  # still no count, still no zero


# ======================================================== status / configuration ==
def test_fakt_is_not_integrated_and_listed_as_not_used(settings: Settings) -> None:
    from app.api.compare_export import system_status

    class S:  # the parts of the service object the status endpoint reads
        db = Database(":memory:")

    S.settings = settings  # type: ignore[attr-defined]
    sources = {s["name"]: s for s in system_status(S)["sources"]}
    assert sources["Fakt.no"]["status"] == "not_used" and "paid" in sources["Fakt.no"]["note"]
    assert not any("fakt" in field.lower() for field in Settings.model_fields)  # no Fakt API key setting exists
    assert sources["Company careers pages and linked job boards"]["status"] == "available"
    assert "never reports" in sources["NAV Arbeidsplassen job ads"]["note"]


def test_discovery_is_skipped_when_company_pages_already_show_an_opening(settings: Settings) -> None:
    settings_with(settings, tavily_api_key="tvly-test-0000000000")
    calls: list[dict] = []
    net = FixtureNetwork()
    net.load_brreg_probes()
    net.handlers.append(tavily_handler([], calls))
    net.add_site("autobjorn.no", site([posting("Bilselger")]))
    rec = research(net, nav_index=False)
    assert calls == [] and hiring(rec)["totalCurrent"] == 1
    assert rec["modules"].get("job_discovery") is None


def test_job_discovery_can_be_switched_off(settings: Settings) -> None:
    settings_with(settings, tavily_api_key="tvly-test-0000000000", enable_job_discovery=False)
    calls: list[dict] = []
    net = FixtureNetwork()
    net.load_brreg_probes()
    net.handlers.append(tavily_handler([], calls))
    net.add_site("autobjorn.no", site())
    research(net, nav_index=False)
    assert calls == []


def test_employer_basis_rules() -> None:
    ident = CanonicalIdentity(org_number=AUTO, legal_name="AUTOBJØRN A/S", legal_form="AS")
    page_on_board = doc([], url="https://x.teamtailor.com/jobs/1")
    on_site = doc([], url="https://autobjorn.no/jobs/1")
    job = item("Selger", raw={"hiring_org": {"name": "Autobjørn Bergen AS", "urls": []}})
    assert job_discovery.employer_basis(on_site, job, ident, "autobjorn.no") == "verified_domain"
    assert job_discovery.employer_basis(page_on_board, job, ident, "autobjorn.no") is None  # a similar name proves nothing
    assert job_discovery.employer_basis(page_on_board, item("Selger", raw={"hiring_org": {"name": "X", "urls": ["https://www.autobjorn.no/om"]}}), ident,
                                        "autobjorn.no") == "hiring_organization_website"
    with_number = doc([], url="https://x.teamtailor.com/jobs/2", text="Org.nr 810 359 862")
    assert job_discovery.employer_basis(with_number, job, ident, "autobjorn.no") == "organisation_number_on_page"
    other_number = doc([], url="https://x.teamtailor.com/jobs/3", text="Org.nr 923 609 016")
    assert job_discovery.employer_basis(other_number, job, ident, "autobjorn.no") is None
    assert jobs_conn.is_nav_host("https://arbeidsplassen.nav.no/x") and not jobs_conn.is_nav_host("https://autobjorn.no/x")
