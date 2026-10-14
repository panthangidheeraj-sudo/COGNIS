"""The company's own newsroom and investor-relations pages — the first place to look for what a company says it has done.

Runs only on an identity-verified website (``crawl.verified``). It reads, in this order:

1. newsroom / press / investor pages the site crawl already fetched (no second request);
2. further newsroom and investor-relations pages linked from the site, or listed in its sitemap, or — when the site links none — a few common paths;
3. RSS / Atom feeds the pages advertise.

Every request goes through the shared HTTP client: robots.txt is checked first (a disallowed page is recorded as *blocked* and never fetched), the SSRF policy,
per-host rate limits and request budgets apply, and only same-site URLs are followed. Pages are read as plain text; nothing is bypassed, no login is attempted.

What each page returned is written down (``sources``) so the report can say exactly what could and could not be read. A page that loads its items by script
yields no items — that is recorded as "no dated items could be read", never as "no news".
"""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

from bs4 import BeautifulSoup

from ..core.util import clean_ws, date_only, fold, now_iso, truncate
from ..evidence.models import ModuleResult, Observation
from ..extraction.html import PageDoc, classify_link, jsonld_of_type
from ..extraction.web_facts import _page_base
from ..security.urls import canonical_url, host_of, registrable_domain
from .base import ConnectorContext, not_run
from .website import FetchedPage, SiteCrawl, fetch_page, site_links, sitemap_links

MODULE = "news"
SOURCE_ID = "news"
SOURCE_NAME = "Company newsroom & investor relations"
NEWS_PAGE_KINDS = ("news", "investors")
COMMON_PATHS = ("/news", "/nyheter", "/press", "/presse", "/pressemeldinger", "/investors", "/investor-relations", "/en/news", "/en/investors", "/en/press")
MAX_PROBES = 4
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
class NewsItem:
    title: str
    date: str
    url: str | None
    summary: str
    span: str  # exact wording the item was read from
    method: str
    page_kind: str  # news | investors
    page_url: str
    doc: PageDoc | None = None
    feed: bool = False
    retrieved_at: str | None = None
    content_sha256: str | None = None


@dataclass
class NewsroomResult:
    observations: list[Observation] = field(default_factory=list)
    module: ModuleResult | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)  # one entry per page or feed that was tried
    items: int = 0


# ----------------------------------------------------------------------------- feeds --
def parse_feed(xml: str, base_url: str) -> list[tuple[str, str | None, str | None, str]]:
    """(title, link, ISO date, summary) for each RSS ``item`` or Atom ``entry``. Items without a title or a parseable date are skipped by the caller."""
    soup = BeautifulSoup(xml or "", "xml")
    rows: list[tuple[str, str | None, str | None, str]] = []
    for node in soup.find_all(["item", "entry"]):
        title = clean_ws(node.find("title").get_text(" ")) if node.find("title") else ""
        link = None
        link_tag = node.find("link")
        if link_tag is not None:
            href = link_tag.get("href") or clean_ws(link_tag.get_text(" "))
            if href:
                link = urllib.parse.urljoin(base_url, href)
        raw_date = ""
        for tag in ("pubDate", "published", "updated", "date", "dc:date"):
            found = node.find(tag)
            if found is not None and clean_ws(found.get_text(" ")):
                raw_date = clean_ws(found.get_text(" "))
                break
        day = date_only(raw_date)
        if not day and raw_date:
            try:
                day = parsedate_to_datetime(raw_date).date().isoformat()
            except (TypeError, ValueError):
                day = None
        summary_tag = node.find("description") or node.find("summary") or node.find("content")
        summary = clean_ws(BeautifulSoup(summary_tag.get_text(" ") if summary_tag is not None else "", "lxml").get_text(" ")) if summary_tag is not None else ""
        rows.append((title, link, day, summary))
    return rows


# --------------------------------------------------------------------------- listings --
def _items_from_doc(doc: PageDoc, page_kind: str) -> list[NewsItem]:
    out: dict[str, NewsItem] = {}

    def put(item: NewsItem) -> None:
        out.setdefault(f"{item.date}|{fold(item.title)[:80]}", item)

    base = {"page_kind": page_kind, "page_url": doc.final_url, "doc": doc, "retrieved_at": doc.retrieved_at, "content_sha256": doc.content_sha256}
    for it in doc.items:
        put(NewsItem(title=it.title, date=it.date, url=it.url, summary=it.summary, span=truncate(it.context, 300), method="newsroom_listing", **base))
    for art in jsonld_of_type(doc, "NewsArticle", "Article", "BlogPosting", "PressRelease"):
        title = clean_ws(str(art.get("headline") or art.get("name") or ""))
        day = date_only(str(art.get("datePublished") or art.get("dateCreated") or ""))
        if len(title) >= 12 and day:
            url = art.get("url") if isinstance(art.get("url"), str) else None
            desc = clean_ws(str(art.get("description") or ""))[:400]
            put(NewsItem(title=title, date=day, url=url, summary=desc, span=truncate(f'{art.get("@type")} "{title}" datePublished {day}', 300), method="json_ld", **base))
    return sorted(out.values(), key=lambda i: i.date, reverse=True)


def seen_urls(crawl: SiteCrawl) -> list[str]:
    """Final URLs of the newsroom / investor-relations pages the crawl already holds."""
    return [p.doc.final_url for p in crawl.pages if p.doc is not None and p.kind in NEWS_PAGE_KINDS]


def _same_site(url: str, domain: str) -> bool:
    return registrable_domain(host_of(url)) == domain


# ------------------------------------------------------------------------------- run --
async def discover_newsroom(ctx: ConnectorContext, crawl: SiteCrawl, *, today: date | None = None, crawled_only: bool = False) -> NewsroomResult:
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
    found: list[NewsItem] = []
    requests = 0

    def record(kind: str, url: str, status: str, note: str, items: int | None = None, retrieved_at: str | None = None) -> None:
        result.sources.append({"kind": kind, "url": url, "status": status, "note": note, **({"items": items} if items is not None else {}),
                               **({"retrieved_at": retrieved_at} if retrieved_at else {})})

    def read_listing(doc: PageDoc, page_kind: str, url: str, probe: bool = False) -> None:
        items = _items_from_doc(doc, page_kind)
        found.extend(items)
        kind = KIND_OF_PAGE[page_kind]
        if items:
            record(kind, url, "read", f"{len(items)} dated item(s) read" + (" (found by trying a common path)" if probe else ""), len(items), doc.retrieved_at)
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
    article_urls = {canonical_url(i.url) for i in found if i.url}

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
        if fetched >= s.news_discovery_max_pages or (ctx.budget is not None and hasattr(ctx.budget, "can_optional") and not ctx.budget.can_optional()):
            record(KIND_OF_PAGE[kind], url, "not_checked", "not read: the page or request limit for newsroom discovery was reached")
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
        if ctx.budget is not None and hasattr(ctx.budget, "can_optional") and not ctx.budget.can_optional():
            record("feed", feed_url, "not_checked", "not read: the research budget for optional pages was used up")
            continue
        res = await ctx.fetch(feed_url, connector="website", optional=True, accept="application/rss+xml,application/atom+xml,application/xml,text/xml;q=0.9,*/*;q=0.5", check_robots=True,
                              max_bytes=1_500_000, cache_ttl=s.cache_ttl_web_seconds)
        requests += 0 if res.from_cache else 1 + res.retries + res.redirects
        if not res.ok:
            cls = res.classification
            record("feed", feed_url, STATUS_OF.get(cls, "failed"), OUTCOME_NOTE.get(cls, f"the feed could not be read ({cls})"))
            continue
        rows = [r for r in parse_feed(res.text(), res.final_url) if len(r[0]) >= 12 and r[2]]
        for title, link, day, summary in rows:
            found.append(NewsItem(title=title, date=day or "", url=link, summary=summary[:400], span=truncate(f"{title} — {summary}" if summary else title, 300), method="rss_item",
                                  page_kind="news", page_url=res.final_url, feed=True, retrieved_at=res.retrieved_at, content_sha256=res.content_sha256))
        record("feed", feed_url, "read" if rows else "no_dated_items", f"{len(rows)} dated item(s) read" if rows else "the feed lists no dated items", len(rows), res.retrieved_at)

    # observations: newest first, dated, not in the future, within the age window
    oldest = (today - timedelta(days=s.news_max_age_days)).isoformat()
    latest = (today + timedelta(days=1)).isoformat()
    unique: dict[str, NewsItem] = {}  # one observation per page or feed that states an item: the same announcement read in two places keeps both as evidence
    headlines: set[str] = set()
    for item in sorted(found, key=lambda i: (i.date, not i.feed), reverse=True):
        if not item.date or item.date > latest or item.date < oldest:
            continue
        head = f"{item.date}|{fold(item.title)[:80]}"
        if head not in headlines and len(headlines) >= s.news_max_items:
            continue
        headlines.add(head)
        unique.setdefault(f"{head}|{item.page_url}", item)
    chosen = list(unique.values())
    for item in chosen:
        doc = item.doc
        base = _page_base(crawl, doc) if doc is not None else {
            "module": "website", "source_id": "website", "source_name": f"Official company website ({crawl.domain})", "source_class": crawl.source_class,
            "source_url": item.page_url, "retrieved_at": item.retrieved_at or now_iso(), "content_sha256": item.content_sha256, "tier": "B",
            "identity_score": crawl.audit.score if crawl.audit else 0.0, "identity_signals": list(crawl.audit.signals) if crawl.audit else []}
        base = {**base, "module": MODULE}
        key = f"{item.date}|{fold(item.title)[:80]}"
        result.observations.append(Observation(
            field="news_item", value=truncate(item.title, 220), key_suffix=key, as_of=item.date, effective_from=item.date, claim_span=item.span, extraction_method=item.method,
            label="Company news" if item.page_kind == "news" else "Investor relations",
            attributes={"url": item.url or item.page_url, "date": item.date, "summary": item.summary or None, "page_kind": item.page_kind, "origin": "investor_relations" if item.page_kind == "investors" else "company_newsroom",
                        "feed": item.feed},
            document_title=(doc.title if doc is not None else None) or None, **base))
    result.items = len(headlines)
    read = [x for x in result.sources if x["status"] == "read"]
    state = ("available" if read else "blocked" if result.sources and all(x["status"] == "blocked" for x in result.sources) else
             "available" if any(x["status"] == "no_dated_items" for x in result.sources) else "not_available" if (not result.sources or all(x["status"] == "not_found" for x in result.sources))
             else "failed")
    if read:
        note = f"{result.items} dated announcement(s) read from {len(read)} page(s)/feed(s) on {crawl.domain}"
    elif crawled_only and not result.sources:
        state = "not_applicable"
        note = "Company news was not part of this research plan, and the website crawl reached no newsroom or investor-relations page."
    else:
        note = "; ".join(f"{x['kind'].replace('_', ' ')} {x['url']}: {x['note']}" for x in result.sources[:4]) or "no newsroom page found"
    result.module = ModuleResult(module=MODULE, source_id=SOURCE_ID, source_name=SOURCE_NAME, source_class=crawl.source_class, state=state, url=crawl.homepage.final_url,  # type: ignore[arg-type]
                                 retrieved_at=now_iso(), note=note, requests=requests, tier="B", value={"sources": result.sources, "items": result.items})
    return result
