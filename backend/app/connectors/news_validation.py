"""One set of rules for what counts as a news item, shared by the company newsroom, RSS feeds and press-article discovery.

A news item is published only when ALL of these hold, and every rejection is kept (with its reason) for diagnostics:

* a real article URL — an absolute http(s) address that is not a bare domain, a section / listing / archive / tag page, a navigation or product/service
  page, a file, a share link, or the very listing page the item was read from;
* a meaningful headline — several words, not navigation text ("Read more", "Nyheter"), not just the company name or a date;
* a genuine publication date — one the page or feed states as the *publication* date (``datePublished``, ``article:published_time``, RSS ``pubDate``, a
  printed date on the item). ``dateModified``, ``updated``, ``dateCreated``, feed-build dates and the date COGNIS fetched the page are never used,
  and the date is never filled in from the retrieval date;
* inside the age window and not in the future.

Identity (is the article about THIS company?) is judged separately by the caller; the newsroom of an identity-verified site is the company's own.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from datetime import date, timedelta

from ..core.util import fold
from ..identity.normalization import normalize_name

# Where a date came from. Only these describe when the item was published.
# ``datePublished`` is JSON-LD, ``published_time`` is ``article:published_time``, ``time_itemprop_datePublished`` an article-scoped <time itemprop="datePublished">,
# ``rss_pubDate`` / ``atom_published`` the item's own field in a same-site feed. A feed date can supply the date, but the linked article page is still fetched and checked.
PUBLICATION_DATE_SOURCES = {"datePublished", "published_time", "time_itemprop_datePublished", "rss_pubDate", "atom_published"}
# Everything else is a hint at best: a generic <time datetime>, a date printed on a listing card, a generic <date> / dc:date feed field, modification and build dates.
NON_PUBLICATION_DATE_SOURCES = {"dateModified", "dateCreated", "updated", "lastBuildDate", "retrieved_at", "last_modified_header", "listing_card_date", "generic_time_element",
                                "time_element", "printed_date", "dc_date", "feed_date_field"}

SECTION_SEGMENTS = {
    "nyheter", "news", "presse", "press", "pressemeldinger", "pressroom", "newsroom", "media", "mediesenter", "arkiv", "archive", "arkivet", "category", "kategori",
    "kategorier", "tag", "tags", "emne", "emner", "page", "side", "feed", "rss", "search", "sok", "søk", "investor", "investors", "investor-relations", "ir", "blog",
    "blogg", "aktuelt", "artikler", "articles", "nyhetsarkiv", "publikasjoner", "publications", "rapporter", "reports", "events", "arrangementer", "kalender",
}
NON_ARTICLE_SEGMENTS = {
    "produkter", "produkt", "products", "product", "tjenester", "tjeneste", "services", "service", "losninger", "løsninger", "solutions", "priser", "pricing",
    "kontakt", "kontakt-oss", "contact", "contact-us", "om-oss", "about", "about-us", "karriere", "careers", "jobs", "ledige-stillinger", "team", "ansatte",
    "personvern", "privacy", "cookies", "vilkar", "vilkår", "terms", "login", "logg-inn", "handlekurv", "cart", "checkout", "butikk", "shop", "bestill", "tilbud",
    "referanser", "cases", "kunder", "customers", "partnere", "partners", "faq", "support", "kundeservice", "sitemap", "sitemap.xml",
}
NAV_TITLES = {
    "les mer", "read more", "mer", "more", "nyheter", "news", "presse", "press", "kontakt", "kontakt oss", "contact", "hjem", "home", "om oss", "about", "about us",
    "produkter", "tjenester", "karriere", "se alle", "view all", "vis alle", "alle nyheter", "all news", "arkiv", "archive", "les saken", "les mer her", "klikk her",
    "neste", "forrige", "next", "previous", "tilbake", "back", "meny", "menu", "søk", "search", "investor", "investors", "pressemeldinger", "press releases",
}
MONTHS = re.compile(r"\b(jan(uar|uary)?|feb(ruar|ruary)?|mars?|march|apr(il)?|mai|may|juni?|june?|juli?|july?|aug(ust)?|sep(t(ember)?)?|okt(ober)?|oct(ober)?|nov(ember)?|des(ember)?|dec(ember)?)\b")
NAV_PATTERN = re.compile(r"^(se|vis|les|gå til|see|view|read|show|go to)\s+(alle|all|mer|more|flere|hele|the)\b")
FILE_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|svg|webp|zip|docx?|xlsx?|pptx?|mp[34]|xml|rss|atom|json|css|js)$", re.I)
SHARE_PATH = re.compile(r"/(share|sharer|intent|plugins|dialog)(/|$|\?)", re.I)
PAGINATION = re.compile(r"^(page|side|p)[-_]?\d+$|^\d{1,3}$", re.I)


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str | None = None


def url_problem(url: str | None, *, listing_url: str | None = None, article_page: bool = False) -> str | None:
    """Why ``url`` is not a real article URL, or None when it looks like one. ``article_page``: the page itself was fetched and read as a single article
    (headline + publication date + body), so the weak 'single short path segment' shape heuristic is not applied."""
    if not url or not url.strip():
        return "no article link: the item has no URL of its own"
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "not an absolute http(s) article URL"
    path = parts.path or ""
    segments = [s for s in path.split("/") if s]
    if not segments:
        return "the URL is a bare domain / home page, not an article"
    if SHARE_PATH.search(path) or "sharer" in parts.netloc:
        return "the URL is a share / social-plugin link"
    if FILE_EXT.search(path):
        return "the URL is a file, feed or asset, not an article page"
    if listing_url:
        a, b = urllib.parse.urlsplit(listing_url), parts
        if (a.hostname or "").removeprefix("www.") == (b.hostname or "").removeprefix("www.") and a.path.rstrip("/") == b.path.rstrip("/"):
            return "the URL is the listing page the item was read from, not the article"
    last = fold(urllib.parse.unquote(segments[-1]))
    if any(fold(urllib.parse.unquote(s)) in NON_ARTICLE_SEGMENTS for s in segments[:1]) and len(segments) == 1:
        return "the URL is a product, service or navigation page"
    if len(segments) == 1 and last in SECTION_SEGMENTS | NON_ARTICLE_SEGMENTS:
        return "the URL is a section / listing page, not an article"
    if last in SECTION_SEGMENTS | NON_ARTICLE_SEGMENTS or PAGINATION.match(last):
        return "the URL is a section, listing, archive or pagination page, not an article"
    if len(segments) >= 2 and fold(segments[-2]) in {"tag", "tags", "category", "kategori", "emne", "page", "side", "author", "forfatter"}:
        return "the URL is a tag / category / author listing, not an article"
    if not article_page and len(segments) == 1 and "-" not in last and not re.search(r"\d", last) and len(last) < 20:
        return "a single short path segment looks like a section or product page, not an article"
    return None


def title_problem(title: str | None, *, company_name: str | None = None) -> str | None:
    t = re.sub(r"\s+", " ", (title or "")).strip()
    if len(t) < 12:
        return "the headline is too short to be a meaningful title"
    if fold(t).strip(" .:|-") in NAV_TITLES or NAV_PATTERN.match(fold(t)):
        return "the 'headline' is navigation text"
    words = re.findall(r"\w+", t)
    if len(words) < 3:
        return "the headline has fewer than three words"
    if not re.sub(r"[\d\W_]+", "", MONTHS.sub("", fold(t)), flags=re.U):
        return "the headline is only a date or number"
    if company_name and normalize_name(t) == normalize_name(company_name):
        return "the headline is just the company name"
    return None


def date_problem(day: str | None, source: str | None, *, today: date, max_age_days: int) -> str | None:
    if not day or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return "the item states no publication date"
    if source in NON_PUBLICATION_DATE_SOURCES:
        return f"the only date available is a '{source}' date, which is not the publication date"
    if source is not None and source not in PUBLICATION_DATE_SOURCES:
        return f"the date source '{source}' is not a publication date"
    try:
        parsed = date.fromisoformat(day)
    except ValueError:
        return "the stated date is not a real calendar date"
    if parsed > today + timedelta(days=1):
        return "the item is dated in the future"
    if parsed < today - timedelta(days=max_age_days):
        return f"the item is older than {max_age_days} days"
    return None


def validate_item(*, title: str | None, url: str | None, day: str | None, date_source: str | None, today: date, max_age_days: int,
                  listing_url: str | None = None, company_name: str | None = None) -> Verdict:
    """The first rule an item breaks, or ok."""
    for problem in (url_problem(url, listing_url=listing_url), title_problem(title, company_name=company_name),
                    date_problem(day, date_source, today=today, max_age_days=max_age_days)):
        if problem:
            return Verdict(False, problem)
    return Verdict(True)


def body_problem(paragraphs: list[str], *, minimum: int = 120) -> str | None:
    """A press article must have readable article text, not just a headline over a paywall / script shell."""
    total = sum(len(p) for p in paragraphs if len(p) >= 40)
    if total < minimum:
        return f"the page has no readable article text ({total} characters of body text, {minimum} needed)"
    return None
