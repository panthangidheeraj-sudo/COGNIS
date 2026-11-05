"""V2.1 — which news candidates are fetched first, what counts as the same article, and how the company's request allowance is kept for article verification.

Everything runs against the offline ``FixtureNetwork``; nothing touches the real network."""
from __future__ import annotations

from datetime import date, timedelta

from test_news_article_verification import (
    HEADLINE,
    card,
    fetched,
    network,
    only_card,
    published,
    rejected,
    run,
    site,
)
from test_news_article_verification import (
    news as published_news,
)

from app.competition.batch import verification_summary
from app.competition.envelope import build_envelope
from app.config import Settings
from app.connectors import news_priority as npri
from app.connectors.newsroom import Candidate
from app.runtime.budgets import BudgetLimits, CompanyBudget, RunBudget, spend_purpose

LEGAL = "EQUINOR ASA"


def cand(title: str, url: str, when: str = "2026-10-28", kind: str = "newsroom_listing", feed: str | None = None) -> Candidate:
    return Candidate(title=title, url=url, summary="", page_kind="news", listing_date=None if feed else when, feed_date=feed, feed_date_source="rss_pubDate" if feed else None,
                     found_in=[{"kind": kind, "url": "https://www.equinor.com/news-and-media"}])


EVENT = cand("Equinor Q3 2026 results - analyst conference", "https://www.equinor.com/investors/q3-2026-analyst-conference")
PRESS_CONF = cand("Equinor Q3 2026 press conference", "https://www.equinor.com/news-and-media/q3-2026-press-conference")
SUPPLIER = cand("Equinor Supplier Day – OTD Bergen 2026", "https://www.equinor.com/about-us/supplier-day-otd-bergen-2026", "2026-10-14")
GENERIC = cand("All news", "https://www.equinor.com/news/archive")
DATED = cand("Aibel awarded contract for Wisting", "https://www.equinor.com/news/20261022-aibel-awarded-contract-for-wisting", "2026-10-22")
SLUG = cand("Equinor third quarter 2026 results", "https://www.equinor.com/news/equinor-third-quarter-2026-results")


# ============================================================================ ordering ==
def test_event_conference_and_generic_listing_pages_rank_below_likely_articles() -> None:
    ordered = npri.order([EVENT, PRESS_CONF, SUPPLIER, GENERIC, DATED, SLUG], LEGAL)
    articles = {ordered[0].url, ordered[1].url}
    assert articles == {DATED.url, SLUG.url}  # likely articles first, although the event pages are newer
    assert {c.url for c in ordered[2:]} == {EVENT.url, PRESS_CONF.url, SUPPLIER.url, GENERIC.url}
    assert all(npri.score(c, LEGAL) < 0 for c in (EVENT, PRESS_CONF, SUPPLIER, GENERIC))
    assert all(npri.score(c, LEGAL) > 0 for c in (DATED, SLUG))


def test_within_a_tier_the_newest_candidate_comes_first() -> None:
    older = cand("Equinor signs agreement with Eneco", "https://www.equinor.com/news/20260913-equinor-eneco-agreement", "2026-09-13")
    newer = cand("Equinor opens robotics centre at Karsto", "https://www.equinor.com/news/20261028-karsto-marine-robotics-centre", "2026-10-28")
    assert [c.url for c in npri.order([older, newer], LEGAL)] == [newer.url, older.url]


def test_a_feed_item_or_structured_article_data_counts_as_a_declared_article() -> None:
    plain = cand("Quarterly update from the company", "https://www.equinor.com/updates/quarterly-update-from-the-company")
    fed = cand("Quarterly update from the company", "https://www.equinor.com/updates/quarterly-update-from-the-company", kind="rss_item", feed="2026-10-28")
    assert npri.score(fed, LEGAL) > npri.score(plain, LEGAL)


def test_a_dated_news_page_about_an_event_is_an_announcement_not_the_event_page() -> None:
    announcement = cand("Equinor's Capital Markets Day 2026", "https://www.equinor.com/news/20260616-equinor-capital-markets-day-2026", "2026-06-16")
    event_page = cand("Equinor Capital Markets Day 2026", "https://www.equinor.com/investors/capital-markets-day-2026", "2026-06-16")
    assert npri.score(announcement, LEGAL) > npri.score(event_page, LEGAL)
    assert npri.order([event_page, announcement], LEGAL)[0].url == announcement.url


def test_a_headline_that_is_only_a_notice_title_ranks_lower_than_the_same_address_with_a_real_headline() -> None:
    short = cand("Notifiable trading – Equinor ASA", "https://www.equinor.com/news/20261028-notifiable-trading")
    real = cand("Equinor to commence fourth tranche of the share buy-back programme", "https://www.equinor.com/news/20261028-fourth-tranche-share-buy-back-programme")
    assert npri.score(short, LEGAL) < npri.score(real, LEGAL)


# ======================================================================== de-duplication ==
def test_address_variants_are_one_candidate() -> None:
    base = "Equinor opens robotics centre at Karsto"
    variants = [cand(base, "https://www.equinor.com/news/20261028-karsto"), cand(base, "http://equinor.com/news/20261028-karsto/"),
                cand(base, "https://www.equinor.com/news/20261028-karsto?utm_source=newsletter")]
    kept, merged = npri.merge_equivalents(variants, LEGAL)
    assert len(kept) == 1 and merged == 2


def test_the_same_headline_and_date_under_two_addresses_is_merged_and_the_better_address_kept() -> None:
    news_page = cand("Equinor's Capital Markets Day 2026", "https://www.equinor.com/news/20260616-equinor-capital-markets-day-2026", "2026-06-16")
    event_page = cand("Equinor Capital Markets Day 2026", "https://www.equinor.com/investors/capital-markets-day-2026", "2026-06-16")
    kept, merged = npri.merge_equivalents([event_page, news_page], LEGAL)
    assert merged == 1 and [c.url for c in kept] == [news_page.url]
    assert kept[0].found_in == [{"kind": "newsroom_listing", "url": "https://www.equinor.com/news-and-media"}]  # where it was found is kept, once


def test_the_same_headline_on_different_dates_is_not_merged() -> None:
    a = cand("Equinor publishes quarterly safety results", "https://www.equinor.com/news/20260710-safety-results", "2026-07-10")
    b = cand("Equinor publishes quarterly safety results", "https://www.equinor.com/news/20261021-safety-results", "2026-10-21")
    kept, merged = npri.merge_equivalents([a, b], LEGAL)
    assert len(kept) == 2 and merged == 0


def test_merging_keeps_a_feed_date_and_a_listing_date_from_either_twin() -> None:
    card_only = cand("Equinor opens robotics centre at Karsto", "https://www.equinor.com/news/20261028-karsto", "2026-10-28")
    fed = cand("Equinor opens robotics centre at Karsto", "http://www.equinor.com/news/20261028-karsto/", "2026-10-28", kind="rss_item", feed="2026-10-28")
    kept, _ = npri.merge_equivalents([card_only, fed], LEGAL)
    assert len(kept) == 1 and kept[0].feed_date == "2026-10-28" and kept[0].listing_date == "2026-10-28"
    assert {f["kind"] for f in kept[0].found_in} == {"newsroom_listing", "rss_item"}


# ===================================================================== fetch order, end to end ==
def _cards(spec: list[tuple[str, str, int]]) -> str:
    return "".join(card(title, link, days_ago) for title, link, days_ago in spec)


def test_with_a_tight_page_limit_articles_are_fetched_before_newer_event_pages(settings: Settings) -> None:
    settings.news_article_max_fetches = 2
    spec = [("Resultatpresentasjon for tredje kvartal 2026", "/nyheter/q3-2026-analyst-conference", 1), ("Pressekonferanse om kvartalsresultatet 2026", "/nyheter/q3-2026-press-conference", 2),
            ("Autobjørn signerer avtale med Posten Norge", "/nyheter/autobjorn-signerer-avtale-med-posten", 20), ("Autobjørn åpner nytt verksted i Drammen", "/nyheter/autobjorn-apner-nytt-verksted", 30)]
    pages = {link: published(days, headline=title) for title, link, days in spec}
    net = network(site(_cards(spec), pages))
    rec = run(net)
    assert {c["value"] for c in published_news(rec)} == {"Autobjørn signerer avtale med Posten Norge", "Autobjørn åpner nytt verksted i Drammen"}
    assert not fetched(net, "/nyheter/q3-2026-analyst-conference") and not fetched(net, "/nyheter/q3-2026-press-conference")
    assert {r["status"] for r in rejected(rec)} == {"not_checked"} and rec["news"]["newsroom"]["articles_fetched"] == 2


def test_event_pages_are_still_fetched_and_judged_when_the_allowance_lasts() -> None:
    spec = [("Resultatpresentasjon for tredje kvartal 2026", "/nyheter/q3-2026-analyst-conference", 1), ("Autobjørn signerer avtale med Posten Norge", "/nyheter/autobjorn-signerer-avtale-med-posten", 20)]
    net = network(site(_cards(spec), {link: published(days, headline=title) for title, link, days in spec}))
    rec = run(net)
    assert fetched(net, "/nyheter/q3-2026-analyst-conference") and len(published_news(rec)) == 2  # lower rank is not exclusion


def test_the_same_article_under_two_addresses_costs_one_request() -> None:
    twin = "Autobjørn signerer rammeavtale med Statens vegvesen"
    spec = [(twin, "/nyheter/20260901-rammeavtale-statens-vegvesen", 10), (twin, "/aktuelt/rammeavtale-vegvesen", 10)]
    pages = {"/nyheter/20260901-rammeavtale-statens-vegvesen": published(10), "/aktuelt/rammeavtale-vegvesen": published(10)}
    net = network(site(_cards(spec), pages))
    rec = run(net)
    nr = rec["news"]["newsroom"]
    assert len(published_news(rec)) == 1 and nr["articles_fetched"] == 1 and nr["duplicates_merged"] == 1
    assert fetched(net, "/nyheter/20260901-rammeavtale-statens-vegvesen") and not fetched(net, "/aktuelt/rammeavtale-vegvesen")  # the better-ranked address is the one requested


# ============================================================================ true totals ==
def _future_cards(n: int) -> str:
    out = []
    for i in range(n):
        d = date.today() + timedelta(days=30 + i)
        out.append(f'<article><time datetime="{d.isoformat()}">{d.day}.{d.month}.{d.year}</time><h2><a href="/nyheter/arrangement-nummer-{i}-i-fremtiden">Arrangement nummer {i} senere i kalenderen til selskapet</a></h2>'
                   f"<p>Kortfattet sammendrag av arrangementet som står på nyhetssiden.</p></article>")
    return "".join(out)


def test_the_true_number_of_unusable_candidates_survives_the_stored_example_limit() -> None:
    rec = run(network(site(_future_cards(70) + card(HEADLINE, "/nyheter/rammeavtale", 10), {"/nyheter/rammeavtale": published(10)})))
    nr = rec["news"]["newsroom"]
    assert len(published_news(rec)) == 1
    assert nr["rejected_total"] == 70 and nr["rejected_by_status"] == {"rejected": 70}
    assert len(nr["rejected"]) == 60  # examples are limited; the total is not
    assert sum(nr["rejected_reasons"].values()) == 70 and len(nr["rejected_reasons"]) == 1  # 70 different dates, one kind of reason


def test_the_envelope_and_the_batch_summary_report_the_true_total_not_the_example_count(settings: Settings) -> None:
    rec = run(network(site(_future_cards(70) + card(HEADLINE, "/nyheter/rammeavtale", 10), {"/nyheter/rammeavtale": published(10)})))
    env = build_envelope(rec, run_id="t")
    diag = env["diagnostics"]
    assert diag["news_rejected_total"] == 70 and len(diag["news_rejected"]) == 60 and diag["news_rejected_by_status"] == {"rejected": 70}
    summary = verification_summary(["x"], [env], {}, settings, {"passed": True}, 0)["news"]
    assert summary["candidates_rejected_or_unusable"] == 70 and summary["rejected_examples_stored"] == 60
    assert sum(summary["rejection_reasons"].values()) == 70


def test_an_envelope_without_totals_still_summarises_from_its_examples(settings: Settings) -> None:
    rec = run(only_card("/nyheter/finnes-ikke", None, days_ago=3))
    env = build_envelope(rec, run_id="t")
    assert "news_rejected_total" in env.get("diagnostics", {}) or not env.get("diagnostics", {}).get("news_rejected")
    env.setdefault("diagnostics", {}).pop("news_rejected_total", None)
    env["diagnostics"].pop("news_rejected_reasons", None)
    env["diagnostics"]["news_rejected"] = [{"reason": "a reason"}] * 3
    assert verification_summary(["x"], [env], {}, settings, {"passed": True}, 0)["news"]["candidates_rejected_or_unusable"] == 3


# ============================================================== accurate exhaustion reasons ==
def _eight_articles() -> tuple[str, dict[str, str]]:
    cards = "".join(card(f"Sak nummer {i} fra nyhetssiden til selskapet", f"/nyheter/l{i}", 3 + i) for i in range(8))
    return cards, {f"/nyheter/l{i}": published(3 + i, headline=f"Sak nummer {i} fra nyhetssiden til selskapet") for i in range(8)}


def test_company_request_cap_exhaustion_is_reported_as_the_company_cap(settings: Settings) -> None:
    settings.per_company_max_requests = 14
    rec = run(network(site(*_eight_articles())))
    unchecked = [r for r in rejected(rec) if r["status"] == "not_checked"]
    assert unchecked and rec["operations"]["requests"] <= 14
    for r in unchecked:
        assert "company's request limit (14 requests)" in r["reason"] and "optional pages" not in r["reason"] and "research budget" not in r["reason"]
    assert rec["news"]["newsroom"]["rejected_by_status"]["not_checked"] == len(unchecked)


def test_the_article_page_limit_is_named_as_such(settings: Settings) -> None:
    settings.news_article_max_fetches = 2
    rec = run(network(site(*_eight_articles())))
    unchecked = [r for r in rejected(rec) if r["status"] == "not_checked"]
    assert unchecked and all("article-page limit for this company (2)" in r["reason"] for r in unchecked)


def test_a_run_wide_request_budget_is_named_as_the_run_budget(settings: Settings) -> None:
    import asyncio

    from conftest import research
    net = network(site(*_eight_articles()))
    rec = asyncio.run(research(net, "810359862", max_requests=14))  # the run allows 14 requests (12 for optional pages); the company's own cap of 30 is not the limit
    unchecked = [r for r in rejected(rec) if r["status"] == "not_checked"]
    assert unchecked and all("run's request budget for optional pages" in r["reason"] for r in unchecked)


def test_news_not_in_the_plan_says_so_rather_than_naming_a_budget(settings: Settings) -> None:
    from app.connectors.newsroom import requests_left

    class Ctx:
        budget = None

    assert "not part of this research plan" in requests_left(Ctx(), 0, 0)  # type: ignore[arg-type]


# ============================================================================ the reserve ==
def _budget(max_requests: int = 10) -> CompanyBudget:
    return CompanyBudget(RunBudget(BudgetLimits(max_requests=1000)), max_requests=max_requests, max_seconds=100, max_llm_calls=0, max_searches=0)


def test_held_capacity_is_invisible_to_other_optional_requests_and_usable_by_its_purpose() -> None:
    b = _budget(10)
    assert b.hold("news", 4) == 4
    spent = sum(1 for _ in range(10) if b.reserve(connector="website"))
    assert spent == 6 and not b.can_optional() and b.why_not_optional() == "company_request_cap"  # other steps stop at 6 of 10
    with spend_purpose("news"):
        assert b.can_optional()
        assert [b.reserve(connector="website") for _ in range(5)] == [True, True, True, True, False]  # the held four, then the company cap
    assert b.requests == 10 and b.held("news") == 0


def test_mandatory_requests_ignore_holds() -> None:
    b = _budget(10)
    b.hold("news", 8)
    assert all(b.reserve(connector="brreg", optional=False) for _ in range(9))  # identity requests are never starved by a hold


def test_a_released_hold_returns_the_capacity_to_everyone() -> None:
    b = _budget(10)
    b.hold("news", 5)
    assert sum(1 for _ in range(10) if b.reserve(connector="website")) == 5
    b.release("news")
    assert b.can_optional() and b.reserve(connector="website")


def test_a_hold_is_never_larger_than_what_is_left_and_a_refund_gives_held_capacity_back() -> None:
    b = _budget(10)
    for _ in range(8):
        b.reserve(connector="website")
    assert b.hold("news", 5) == 2  # only two requests of the allowance are left
    with spend_purpose("news"):
        assert b.reserve(connector="website") and b.held("news") == 1
        b.refund(connector="website")
        assert b.held("news") == 2


def test_the_purpose_belongs_to_the_task_that_set_it() -> None:
    import asyncio

    async def scenario() -> tuple[bool, bool]:
        b = _budget(10)
        b.hold("news", 5)
        for _ in range(5):
            b.reserve(connector="website")

        async def news_task() -> bool:
            with spend_purpose("news"):
                await asyncio.sleep(0)
                return b.can_optional()

        async def other_task() -> bool:
            await asyncio.sleep(0)
            return b.can_optional()

        return tuple(await asyncio.gather(news_task(), other_task()))  # type: ignore[return-value]

    assert asyncio.run(scenario()) == (True, False)


def test_why_not_optional_names_the_limit_that_applies() -> None:
    assert _budget(10).why_not_optional() is None
    full = _budget(2)
    full.reserve(connector="website")
    full.reserve(connector="website")
    assert full.why_not_optional() == "company_request_cap"
    slow = CompanyBudget(RunBudget(BudgetLimits(max_requests=1000)), max_requests=10, max_seconds=0.5, max_llm_calls=0, max_searches=0)
    assert slow.why_not_optional() == "company_time"
    tight = CompanyBudget(RunBudget(BudgetLimits(max_requests=10)), max_requests=30, max_seconds=100, max_llm_calls=0, max_searches=0)
    for _ in range(9):
        tight.run.reserve(connector="x")
    assert tight.why_not_optional() == "run_budget"


def test_with_a_small_allowance_the_reserve_lets_the_newsroom_verify_more_articles(settings: Settings) -> None:
    settings.per_company_max_requests = 12

    def verified(reserved: int) -> int:
        settings.news_article_reserved_requests = reserved
        return run(network(site(*_eight_articles())))["news"]["newsroom"]["articles_fetched"]

    without, with_reserve = verified(0), verified(10)
    assert with_reserve > without  # crawling no longer takes the requests that article pages need
