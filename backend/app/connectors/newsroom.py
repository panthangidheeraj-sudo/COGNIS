"""The company's own newsroom and investor-relations pages — the first place to look for what a company says it has done.

Runs only on an identity-verified website (``crawl.verified``). It reads, in this order:

1. newsroom / press / investor pages the site crawl already fetched (no second request);
2. further newsroom and investor-relations pages linked from the site, or listed in its sitemap, or — when the site links none — a few common paths;
3. RSS / Atom feeds the pages advertise.

Every request goes through the shared HTTP client: robots.txt is checked first (a disallowed page is recorded as *blocked* and never fetched), the SSRF policy,
per-host rate limits and request budgets apply, and only same-site URLs are followed. Pages are read as plain text; nothing is bypassed, no login is attempted.

Listing cards, JSON-LD on a listing and feed items are only **candidates** (stage A). A candidate is published only after its own article page has been fetched
and verified (stage B, ``news_article.py`` + ``news_validation.py``): a real article URL on the company's own verified domain, a headline and readable text on
the page, the exact legal entity named (organisation number or registered name; a conflicting organisation number is a rejection) and a publication date the
page (or the feed item's own ``pubDate`` / Atom ``published``) states as such. The evidence of a published item is the article page itself — its URL, title,
retrieval time, content hash and an excerpt from its text — never the listing it was found on. Every candidate that fails keeps its reason in ``rejected``.

What each page returned is written down (``sources``) so the report can say exactly what could and could not be read. A page that loads its items by script
yields no items — that is recorded as "no dated items could be read", never as "no news".
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, NamedTuple

from bs4 import BeautifulSoup

from ..core.util import clean_ws, date_only, fold, now_iso, truncate
from ..evidence.models import ModuleResult, Observation
from ..extraction.html import PageDoc, classify_link, jsonld_of_type
from ..extraction.web_facts import _page_base
from ..identity.model import CanonicalIdentity
from ..runtime.budgets import spend_purpose
from ..security.urls import canonical_url, host_of, registrable_domain
from . import news_article as na
from . import news_priority as npri
from . import news_validation as nv
from .base import ConnectorContext, not_run
from .website import FetchedPage, SiteCrawl, fetch_page, site_links, sitemap_links

MODULE = "news"
SOURCE_ID = "news"
SOURCE_NAME = "Company newsroom & investor relations"
NEWS_PAGE_KINDS = ("news", "investors")
COMMON_PATHS = ("/news", "/nyheter", "/press", "/presse", "/pressemeldinger", "/investors", "/investor-relations", "/en/news", "/en/investors", "/en/press")
MAX_PROBES = 4
MAX_REJECTED_EXAMPLES = 60  # candidates kept as examples in the record; ``NewsroomResult.rejected_total`` always holds the real count
KIND_OF_PAGE = {"news": "newsroom", "investors": "investor_relations"}
OUTCOME_NOTE = {
    "robots_disallowed": "robots.txt does not allow this page to be fetched, so it was not read",
    "blocked": "the site refused access",
    "not_found": "the page does not exist",
    "gone": "the page no longer exists",
    "budget_exhausted": "not read: the research budget for optional pages was used up",
    "timeout": "the site did not answer in time",
    "network": "the site could not be reached",
    "server_error": "the site returned a server error",
    "client_error": "the site refused the request",
    "too_large": "the page was too large to read",
    "invalid_content": "the page was not readable HTML",
    "rate_limited": "the site asked us to slow down (rate limited)",
}
STATUS_OF = {"robots_disallowed": "blocked", "blocked": "blocked", "rate_limited": "blocked", "budget_exhausted": "blocked", "not_found": "not_found", "gone": "not_found"}


@dataclass
class Candidate:
    """A possible article found on a listing page, in listing JSON-LD or in a feed. Nothing about it is evidence until its own page has been verified."""
    title: str  # as shown on the card / feed (a hint; the headline is read from the article page)
    url: str | None
    summary: str
    page_kind: str  # news | investors
    listing_date: str | None = None  # date on a listing card or in listing JSON-LD: a hint for ordering, never a publication date
    feed_date: str | None = None  # the feed item's own pubDate / Atom published
    feed_date_source: str | None = None  # rss_pubDate | atom_published
    found_in: list[dict[str, str]] = field(default_factory=list)  # [{"kind": newsroom_listing | json_ld | rss_item, "url": page or feed}]

    @property
    def hint_date(self) -> str | None:
        return self.feed_date or self.listing_date


@dataclass
class NewsroomResult:
    observations: list[Observation] = field(default_factory=list)
    module: ModuleResult | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)  # one entry per page or feed that was tried
    items: int = 0
    rejected: list[dict[str, Any]] = field(default_factory=list)  # candidates read but not published (status rejected | blocked | not_found | unreadable | not_checked), with the reason
    candidates: int = 0  # distinct article candidates found on listings and feeds
    articles_fetched: int = 0  # article pages requested (a page the site crawl already held, or the same URL from a listing and a feed, is not requested again)
    rejected_total: int = 0  # every candidate that was not published, counted even when only a limited number of examples is kept in ``rejected``
    rejected_by_status: dict[str, int] = field(default_factory=dict)  # rejected | blocked | not_found | unreadable | not_checked → count
    rejected_reasons: dict[str, int] = field(default_factory=dict)  # reason (first 90 characters) → count
    duplicates_merged: int = 0  # candidates that were the same article as another one and were merged before any page was requested


# ----------------------------------------------------------------------------- feeds --
class FeedRow(NamedTuple):
    title: str
    link: str | None
    day: str | None  # the item's own publication date (RSS pubDate / Atom published), ISO
    summary: str
    date_source: str | None  # rss_pubDate | atom_published, None when the item states no such date


def parse_feed(xml: str, base_url: str) -> list[FeedRow]:
    """One ``FeedRow`` per RSS ``item`` or Atom ``entry``. Only the item's own publication field is read: RSS ``pubDate`` or Atom ``published``. ``updated``,
    ``lastBuildDate`` and the generic ``<date>`` / ``dc:date`` fields are modification or unspecified dates and are never used as the publication date.
    Items without a title or a parseable date are skipped by the caller."""
    soup = BeautifulSoup(xml or "", "xml")
    rows: list[FeedRow] = []
    for node in soup.find_all(["item", "entry"]):
        title = clean_ws(node.find("title").get_text(" ")) if node.find("title") else ""
        link = None
        links = node.find_all("link")
        link_tag = next((t for t in links if (t.get("rel") or "alternate") == "alternate"), links[0] if links else None)  # an Atom entry may also link rel="self" / "edit"
        if link_tag is not None:
            href = link_tag.get("href") or clean_ws(link_tag.get_text(" "))
            if href:
                link = urllib.parse.urljoin(base_url, href)
        raw_date, source = "", None
        for tag, label in (("pubDate", "rss_pubDate"), ("published", "atom_published")):
            found = node.find(tag)
            if found is not None and clean_ws(found.get_text(" ")):
                raw_date, source = clean_ws(found.get_text(" ")), label
                break
        day = date_only(raw_date)
        if not day and raw_date:
            try:
                day = parsedate_to_datetime(raw_date).date().isoformat()
            except (TypeError, ValueError):
                day = None
        summary_tag = node.find("description") or node.find("summary") or node.find("content")
        summary = clean_ws(BeautifulSoup(summary_tag.get_text(" ") if summary_tag is not None else "", "lxml").get_text(" ")) if summary_tag is not None else ""
        rows.append(FeedRow(title, link, day, summary, source if day else None))
    return rows


# --------------------------------------------------------------------------- listings --
class Collector:
    """Candidates keyed by article URL: the same article seen in a listing and in a feed is one candidate (and so one fetch)."""

    def __init__(self) -> None:
        self.by_key: dict[str, Candidate] = {}

    def add(self, c: Candidate, found: dict[str, str]) -> None:
        key = canonical_url(c.url) if c.url else f"title:{fold(c.title)[:80]}|{c.hint_date or ''}"
        have = self.by_key.get(key)
        if have is None:
            c.found_in.append(found)
            self.by_key[key] = c
            return
        have.found_in.append(found)
        have.listing_date = have.listing_date or c.listing_date
        if c.feed_date and not have.feed_date:
            have.feed_date, have.feed_date_source = c.feed_date, c.feed_date_source
        have.summary = have.summary or c.summary

    def __len__(self) -> int:
        return len(self.by_key)


def _candidates_from_doc(doc: PageDoc, page_kind: str) -> list[tuple[Candidate, dict[str, str]]]:
    out: list[tuple[Candidate, dict[str, str]]] = []
    for it in doc.items:
        out.append((Candidate(title=it.title, url=it.url, summary=it.summary, page_kind=page_kind, listing_date=it.date), {"kind": "newsroom_listing", "url": doc.final_url}))
    for art in jsonld_of_type(doc, "NewsArticle", "Article", "BlogPosting", "PressRelease"):
        title = clean_ws(str(art.get("headline") or art.get("name") or ""))
        url = art.get("url") if isinstance(art.get("url"), str) else None
        if len(title) >= 12:  # the structured data on a listing is a candidate like any card: its date is a hint, the article page is fetched
            out.append((Candidate(title=title, url=urllib.parse.urljoin(doc.final_url, url) if url else None, summary=clean_ws(str(art.get("description") or ""))[:400], page_kind=page_kind,
                                  listing_date=date_only(str(art.get("datePublished") or "")) or None), {"kind": "json_ld", "url": doc.final_url}))
    return out


def seen_urls(crawl: SiteCrawl) -> list[str]:
    """Final URLs of the newsroom / investor-relations pages the crawl already holds."""
    return [p.doc.final_url for p in crawl.pages if p.doc is not None and p.kind in NEWS_PAGE_KINDS]


def _same_site(url: str, domain: str) -> bool:
    return registrable_domain(host_of(url)) == domain


# ------------------------------------------------------------------- stage B: verify --
def _observation(crawl: SiteCrawl, doc: PageDoc, article: na.Article, cand: Candidate, *, day: str, date_source: str, basis: str, details: dict[str, Any]) -> Observation:
    """The published claim: its source is the fetched article page (URL, title, retrieval time, content hash, excerpt from the article text), not the listing."""
    lead = article.lead or (truncate(article.paragraphs[0], na.EXCERPT_CHARS) if article.paragraphs and not article.nosnippet else "")
    span = truncate(f"{article.headline} — {lead}" if lead else article.headline, na.EXCERPT_CHARS)
    base = {**_page_base(crawl, doc), "module": MODULE}
    key = f"{day}|{fold(article.headline)[:80]}"
    return Observation(
        field="news_item", value=truncate(article.headline, 220), key_suffix=key, as_of=day, effective_from=day, claim_span=span, extraction_method="article_page",
        label="Company news" if cand.page_kind == "news" else "Investor relations", document_title=article.headline,
        attributes={"url": doc.final_url, "date": day, "date_source": date_source, "summary": lead or None, "page_kind": cand.page_kind,
                    "origin": "investor_relations" if cand.page_kind == "investors" else "company_newsroom", "feed": any(f["kind"] == "rss_item" for f in cand.found_in),
                    "identity_basis": basis, "organisation_numbers_on_page": details.get("organisation_numbers_on_page") or [],
                    "found_in": cand.found_in, "listing_title": cand.title if cand.title != article.headline else None, "listing_date_hint": cand.listing_date,
                    "feed_date": cand.feed_date, "article_requested": cand.url},
        **base)


async def verify_candidates(ctx: ConnectorContext, crawl: SiteCrawl, identity: CanonicalIdentity, related: list[dict], candidates: list[Candidate], *, today: date,
                            crawled_only: bool, result: NewsroomResult) -> int:
    """Stage B. Fetch each candidate's own article page (once per URL; pages the crawl already holds are not requested again) and publish it only when it passes every
    rule. Returns the number of requests made. A page that cannot be read is recorded with its real outcome; that is never evidence that there was no news."""
    s = ctx.settings
    legal = identity.legal_name
    oldest = (today - timedelta(days=s.news_max_age_days)).isoformat()
    latest = (today + timedelta(days=1)).isoformat()
    known = {canonical_url(p.doc.final_url): (p.result, p.doc) for p in crawl.pages if p.doc is not None}
    listings = [src["url"] for src in result.sources if src["kind"] in ("newsroom", "investor_relations", "feed")]
    accepted_urls: set[str] = set()
    accepted_heads: set[str] = set()
    requests = 0
    limit = 0 if crawled_only else s.news_article_max_fetches

    def reject(cand: Candidate, status: str, reason: str, **extra: Any) -> None:
        result.rejected_total += 1  # the true count: examples below are limited, the totals are not
        result.rejected_by_status[status] = result.rejected_by_status.get(status, 0) + 1
        short = re.sub(r"\d{4}-\d{2}-\d{2}", "<date>", reason)[:90]  # one key per kind of reason, not per date
        if short in result.rejected_reasons or len(result.rejected_reasons) < 40:
            result.rejected_reasons[short] = result.rejected_reasons.get(short, 0) + 1
        if len(result.rejected) < MAX_REJECTED_EXAMPLES:
            first = cand.found_in[0] if cand.found_in else {"kind": "", "url": ""}
            result.rejected.append({"title": truncate(cand.title, 140), "url": cand.url, "date": cand.hint_date, "source_page": first["url"], "method": first["kind"],
                                    "found_in": cand.found_in, "status": status, "reason": reason, **extra})

    # Equivalent candidates are one article (one request); likely articles are requested before event pages, conference pages and generic listings.
    legal_name = identity.legal_name
    unique, merged = npri.merge_equivalents(candidates, legal_name)
    result.duplicates_merged += merged
    ordered = npri.order(unique, legal_name)

    for cand in ordered:
        # -- the link itself: a real article URL on the company's own verified domain
        problem = next((p for p in (nv.url_problem(cand.url, listing_url=lu) for lu in [*listings, None]) if p), None)
        if problem:
            reject(cand, "rejected", problem)
            continue
        assert cand.url is not None
        host_domain = registrable_domain(host_of(cand.url))
        if host_domain != crawl.domain:
            reject(cand, "rejected", f"the link goes to another site ({host_domain or 'unknown host'}); only articles on the company's own verified domain ({crawl.domain}) are followed")
            continue
        hint = cand.hint_date
        if hint and (hint > latest or hint < oldest):
            where = "feed item" if cand.feed_date else "listing"
            reject(cand, "rejected", f"the {where} shows {hint}, which is {'in the future' if hint > latest else f'older than {s.news_max_age_days} days'}; the article page was not fetched")
            continue
        # -- the article page: requested once, through the shared client (robots.txt, SSRF policy, rate limits and budgets apply)
        key = canonical_url(cand.url)
        if key in known:
            res, doc = known[key]
        else:
            stop = requests_left(ctx, result.articles_fetched, limit)
            if stop is not None:
                reject(cand, "not_checked", stop)
                continue
            res, doc = await fetch_page(ctx, cand.url, connector="website", optional=True)
            requests += 0 if res.from_cache else 1 + res.retries + res.redirects
            result.articles_fetched += 1
            known[key] = (res, doc)
        if doc is None:
            cls = res.classification
            if cls == "budget_exhausted":  # the allowance ran out between the check above and the request: say which allowance
                reject(cand, "not_checked", budget_note(ctx) or OUTCOME_NOTE["budget_exhausted"], fetch=cls)
                continue
            reject(cand, {"blocked": "blocked", "not_found": "not_found"}.get(STATUS_OF.get(cls, ""), "unreadable"),
                   f"the article page could not be read: {OUTCOME_NOTE.get(cls, cls)}. This says nothing about whether the article is genuine.", fetch=cls, http_status=res.status or None)
            continue
        final = doc.final_url
        if registrable_domain(host_of(final)) != crawl.domain:
            reject(cand, "rejected", f"the link redirects to another site ({registrable_domain(host_of(final))}); not followed", article_url=final)
            continue
        problem = next((p for p in (nv.url_problem(final, listing_url=lu, article_page=True) for lu in [*listings, None]) if p), None)
        if problem:
            reject(cand, "rejected", f"after redirects, {problem}", article_url=final)
            continue
        # -- an article: a headline on the page, readable text
        article, why = na.read_article(doc, require_date=False)
        if article is None:
            reject(cand, "rejected", why or "the page is not an article", article_url=final)
            continue
        problem = nv.title_problem(article.headline, company_name=legal) or nv.body_problem(article.paragraphs)
        if problem:
            reject(cand, "rejected", problem, article_url=final)
            continue
        # -- about this exact legal entity (organisation number or registered name); a conflicting organisation number is a rejection
        basis, why, details = na.entity_basis(doc, article, identity, related)
        if basis is None:
            reject(cand, "rejected", why or "the article is not about this legal entity", article_url=final, organisation_numbers_on_page=details.get("organisation_numbers_on_page"))
            continue
        # -- a publication date the page itself states (JSON-LD datePublished, article:published_time, article-scoped <time itemprop="datePublished">);
        #    failing that, the feed item's own pubDate / Atom published. Never a listing-card date, a generic <time>, dateModified, dateCreated or the retrieval date.
        day, source = article.day, article.date_source
        if not day:
            if cand.feed_date and cand.feed_date_source:
                day, source = cand.feed_date, cand.feed_date_source
            else:
                extra = f" (the listing card shows {cand.listing_date}, which is not accepted as a publication date)" if cand.listing_date else ""
                reject(cand, "rejected", (article.date_why or "the page states no publication date") + extra, article_url=final, date_source=None)
                continue
        problem = nv.date_problem(day, source, today=today, max_age_days=s.news_max_age_days)
        if problem:
            reject(cand, "rejected", problem, article_url=final, date=day, date_source=source)
            continue
        head = f"{day}|{fold(article.headline)[:80]}"
        if canonical_url(final) in accepted_urls or head in accepted_heads:
            result.duplicates_merged += 1
            continue  # the same article reached by another link
        if len(accepted_heads) >= s.news_max_items:
            reject(cand, "not_checked", "enough items were already verified", article_url=final)
            continue
        accepted_urls.add(canonical_url(final))
        accepted_heads.add(head)
        result.observations.append(_observation(crawl, doc, article, cand, day=day, date_source=source or "", basis=basis, details=details))
    result.items = len(accepted_heads)
    return requests


def budget_note(ctx: ConnectorContext) -> str | None:
    """None while another optional request may be made, else the exact reason, so a company-level request cap is never described as a general budget."""
    budget = ctx.budget
    if budget is None:
        return None
    why = budget.why_not_optional() if hasattr(budget, "why_not_optional") else (None if not hasattr(budget, "can_optional") or budget.can_optional() else "run_budget")
    if why is None:
        return None
    cap = getattr(budget, "max_requests", None)
    return {
        "company_request_cap": f"not read: the company's request limit ({cap} requests) was reached; this item was not checked",
        "company_time": "not read: the company's time allowance was used up; this item was not checked",
        "run_time": "not read: the run's time allowance for optional pages was used up; this item was not checked",
        "run_budget": "not read: the run's request budget for optional pages was used up; this item was not checked",
    }.get(why, "not read: the allowance for optional pages was used up; this item was not checked")


def requests_left(ctx: ConnectorContext, fetched: int, limit: int) -> str | None:
    """None while another article page may be requested, else why not."""
    if limit <= 0:
        return "not read: article pages were not part of this research plan; this item was not checked"
    if fetched >= limit:
        return f"not read: the article-page limit for this company ({limit}) was reached; this item was not checked"
    return budget_note(ctx)


# ------------------------------------------------------------------------------- run --
async def discover_newsroom(ctx: ConnectorContext, crawl: SiteCrawl, *, identity: CanonicalIdentity, related: list[dict] | None = None, today: date | None = None,
                            crawled_only: bool = False) -> NewsroomResult:
    """The newsroom step. Its requests are charged to the ``news`` purpose, so the capacity held for it (``CompanyBudget.hold``) is available to it and only to it."""
    with spend_purpose("news"):
        return await _discover_newsroom(ctx, crawl, identity=identity, related=related, today=today, crawled_only=crawled_only)


async def _discover_newsroom(ctx: ConnectorContext, crawl: SiteCrawl, *, identity: CanonicalIdentity, related: list[dict] | None = None, today: date | None = None,
                             crawled_only: bool = False) -> NewsroomResult:
    s = ctx.settings
    today = today or date.today()
    if not getattr(s, "enable_news_discovery", True):
        return NewsroomResult(module=not_run(MODULE, source_id=SOURCE_ID, source_name=SOURCE_NAME, source_class="company_owned", state="not_applicable",
                                             note="Newsroom discovery is switched off by configuration."))
    if not crawl.verified or crawl.homepage is None:
        return NewsroomResult(module=not_run(MODULE, source_id=SOURCE_ID, source_name=SOURCE_NAME, source_class="company_owned", state="not_applicable",
                                             note="No identity-verified website, so no company newsroom or investor-relations page could be read."))
    result = NewsroomResult()
    seen: set[str] = set()
    found = Collector()
    requests = 0

    def record(kind: str, url: str, status: str, note: str, items: int | None = None, retrieved_at: str | None = None) -> None:
        result.sources.append({"kind": kind, "url": url, "status": status, "note": note, **({"items": items} if items is not None else {}),
                               **({"retrieved_at": retrieved_at} if retrieved_at else {})})

    def read_listing(doc: PageDoc, page_kind: str, url: str, probe: bool = False) -> None:
        items = _candidates_from_doc(doc, page_kind)
        for cand, where in items:
            found.add(cand, where)
        kind = KIND_OF_PAGE[page_kind]
        if items:
            record(kind, url, "read", f"{len(items)} item(s) listed; each is used only after its own article page has been read and checked" + (" (found by trying a common path)" if probe else ""),
                   len(items), doc.retrieved_at)
        else:
            record(kind, url, "no_dated_items", "the page was read but lists no dated items (it may load them by script, which COGNIS does not run); this is not evidence that there is no news",
                   0, doc.retrieved_at)

    # 1. pages the crawl already fetched
    for page in crawl.pages:
        if page.kind not in NEWS_PAGE_KINDS:
            continue
        url = page.doc.final_url if page.doc else page.result.url
        seen.add(canonical_url(url))
        if page.doc is not None:
            read_listing(page.doc, page.kind, url)
        else:
            cls = page.result.classification
            record(KIND_OF_PAGE[page.kind], url, STATUS_OF.get(cls, "failed"), OUTCOME_NOTE.get(cls, f"the page could not be read ({cls})"))

    # 2. more newsroom / investor pages: linked from any fetched page, then the sitemap, then a few common paths
    #    (``crawled_only``: the run's plan left company news out, so nothing beyond the pages the crawl already holds is requested)
    pending: list[tuple[str, str]] = []
    listing_paths = [urllib.parse.urlsplit(u).path.rstrip("/") for u in seen_urls(crawl)]
    article_urls = {k for k, c in found.by_key.items() if c.url}

    def is_article(url: str) -> bool:  # a link under a listing page, or one the listing itself shows as an item, is an article, not another newsroom
        path = urllib.parse.urlsplit(url).path.rstrip("/")
        return canonical_url(url) in article_urls or any(lp and path.startswith(lp + "/") for lp in listing_paths)

    for page in crawl.pages:
        if page.doc is None or page.kind in NEWS_PAGE_KINDS:
            continue
        for kind, links in site_links(page.doc, crawl.domain).items():
            if kind in NEWS_PAGE_KINDS:
                for link in links[:3]:
                    if canonical_url(link.url) not in seen and not is_article(link.url) and all(link.url != u for _k, u in pending):
                        pending.append((kind, link.url))
    if crawled_only:
        pending = []
    if not crawled_only and not pending and not any(src["kind"] in ("newsroom", "investor_relations") for src in result.sources):
        try:
            for link in await sitemap_links(ctx, crawl.homepage, crawl.domain):
                kind = classify_link(link.url, link.text)
                if kind in NEWS_PAGE_KINDS and canonical_url(link.url) not in seen and len(pending) < s.news_discovery_max_pages:
                    pending.append((kind, link.url))
        except Exception:  # a sitemap problem never stops the rest
            pass
    origin = f"{urllib.parse.urlsplit(crawl.homepage.final_url).scheme}://{urllib.parse.urlsplit(crawl.homepage.final_url).netloc}"
    probes = False
    if not crawled_only and not pending and not any(src["kind"] in ("newsroom", "investor_relations") for src in result.sources):
        pending = [("news" if "invest" not in p and p not in ("/en/investors",) else "investors", origin + p) for p in COMMON_PATHS]
        probes = True
    fetched = 0
    probed = 0
    got_probe_hit = False
    for kind, url in pending:
        key = canonical_url(url)
        if key in seen or not _same_site(url, crawl.domain):
            continue
        if probes and (probed >= MAX_PROBES or got_probe_hit):
            break
        if fetched >= s.news_discovery_max_pages:
            record(KIND_OF_PAGE[kind], url, "not_checked", f"not read: the page limit for newsroom discovery ({s.news_discovery_max_pages}) was reached")
            continue
        stop = budget_note(ctx)
        if stop is not None:
            record(KIND_OF_PAGE[kind], url, "not_checked", stop.replace("this item was not checked", "this page was not checked"))
            continue
        seen.add(key)
        res, doc = await fetch_page(ctx, url, connector="website", optional=True)
        requests += 0 if res.from_cache else 1 + res.retries + res.redirects
        fetched += 1
        probed += 1 if probes else 0
        if doc is None:
            if probes and res.classification in ("not_found", "gone"):
                continue  # a guessed path that does not exist says nothing
            cls = res.classification
            record(KIND_OF_PAGE[kind], url, STATUS_OF.get(cls, "failed"), OUTCOME_NOTE.get(cls, f"the page could not be read ({cls})"))
            continue
        crawl.pages.append(FetchedPage(kind, res, doc))
        read_listing(doc, kind, doc.final_url, probe=probes)
        got_probe_hit = got_probe_hit or probes
    if probes and not any(src["kind"] in ("newsroom", "investor_relations") for src in result.sources):
        record("newsroom", origin + "/", "not_found", "no newsroom or investor-relations page is linked from the site, and none was found at common paths")

    # 3. feeds advertised by the pages that were read
    feeds: list[tuple[str, str]] = []
    for doc in crawl.docs():
        for f in doc.feeds:
            if _same_site(f, crawl.domain) and all(f != x[1] for x in feeds):
                feeds.append((doc.final_url, f))
    for _page, feed_url in (feeds[:2] if not crawled_only else []):
        stop = budget_note(ctx)
        if stop is not None:
            record("feed", feed_url, "not_checked", stop.replace("this item was not checked", "this feed was not checked"))
            continue
        res = await ctx.fetch(feed_url, connector="website", optional=True, accept="application/rss+xml,application/atom+xml,application/xml,text/xml;q=0.9,*/*;q=0.5", check_robots=True,
                              max_bytes=1_500_000, cache_ttl=s.cache_ttl_web_seconds)
        requests += 0 if res.from_cache else 1 + res.retries + res.redirects
        if not res.ok:
            cls = res.classification
            record("feed", feed_url, STATUS_OF.get(cls, "failed"), OUTCOME_NOTE.get(cls, f"the feed could not be read ({cls})"))
            continue
        rows = [r for r in parse_feed(res.text(), res.final_url) if len(r.title) >= 12]
        for row in rows:
            found.add(Candidate(title=row.title, url=row.link, summary=row.summary[:400], page_kind="news", feed_date=row.day, feed_date_source=row.date_source),
                      {"kind": "rss_item", "url": res.final_url})
        record("feed", feed_url, "read" if rows else "no_dated_items", f"{len(rows)} item(s) listed; each is used only after its own article page has been read and checked" if rows else "the feed lists no items",
               len(rows), res.retrieved_at)

    # stage B: every candidate is judged on its own article page
    result.candidates = len(found)
    requests += await verify_candidates(ctx, crawl, identity, related or [], list(found.by_key.values()), today=today, crawled_only=crawled_only, result=result)
    read = [x for x in result.sources if x["status"] == "read"]
    state = ("available" if read else "blocked" if result.sources and all(x["status"] == "blocked" for x in result.sources) else
             "available" if any(x["status"] == "no_dated_items" for x in result.sources) else "not_available" if (not result.sources or all(x["status"] == "not_found" for x in result.sources))
             else "failed")
    if read:
        note = (f"{result.items} article(s) verified on their own pages ({result.candidates} candidate(s) found on {len(read)} listing page(s)/feed(s) on {crawl.domain}, "
                f"{result.articles_fetched} article page(s) requested)")
        unchecked = sum(result.rejected_by_status.get(k, 0) for k in ("blocked", "not_found", "unreadable", "not_checked"))
        if unchecked:
            note += f"; {unchecked} candidate(s) could not be checked because the article page was unavailable or a request limit was reached (this is not evidence that there was no such news)"
        used = result.rejected_by_status.get("rejected", 0)
        if used:
            first = next((r for r in result.rejected if r["status"] == "rejected"), None)
            note += f"; {used} not used" + (f" (e.g. {first['reason']})" if first else "")
    elif crawled_only and not result.sources:
        state = "not_applicable"
        note = "Company news was not part of this research plan, and the website crawl reached no newsroom or investor-relations page."
    else:
        note = "; ".join(f"{x['kind'].replace('_', ' ')} {x['url']}: {x['note']}" for x in result.sources[:4]) or "no newsroom page found"
    result.module = ModuleResult(module=MODULE, source_id=SOURCE_ID, source_name=SOURCE_NAME, source_class=crawl.source_class, state=state, url=crawl.homepage.final_url,  # type: ignore[arg-type]
                                 retrieved_at=now_iso(), note=note, requests=requests, tier="B", value={"sources": result.sources, "items": result.items, "candidates": result.candidates, "articles_fetched": result.articles_fetched,
                                                                                       "rejected": result.rejected[:20], "rejected_total": result.rejected_total,
                                                                                       "rejected_by_status": result.rejected_by_status, "duplicates_merged": result.duplicates_merged})
    return result
