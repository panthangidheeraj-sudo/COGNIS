"""Press coverage found by web search (Tavily). Search results are candidates, never evidence.

The company's own newsroom and investor-relations pages come first (``newsroom.py``). This module adds *reputable secondary sources* — business
press, trade press, wire services and exchange notices — for announcements the company's own pages do not show. One targeted search asks for
articles that name the company, restricted to an allowlist of outlets (``secondary_news_domains``). Every hit then goes through the checks any
other page goes through:

1. outlet: the host must be on the allowlist; anything else is recorded as ignored, never fetched;
2. fetch: robots.txt, the SSRF policy, per-host rate limits and request budgets apply — a refusal is recorded and never worked around;
3. article: a headline, a publication date inside the age window and not in the future must be readable from the page itself;
4. identity: the article must tie itself to *this exact organisation* — its organisation number is on the page, or it names the exact registered name
   (suffix-insensitive) in its headline and links to the verified website, or names the exact registered name in its headline. A similar name, a
   single shared word, or the search engine's own snippet is never enough, and a page that states another organisation's number is rejected.

Only what passes all four becomes a ``news_item``: the headline, the publication date, the link, and a short verbatim lead (at most 300 characters; the
headline alone when the page says ``nosnippet``). Full article text is never stored. Every candidate that does not pass is kept, with the reason, so the
report can show what was looked at. Failing search or an unconfigured key is reported as a source limitation — it says nothing about what happened.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from ..core.util import clean_ws, date_only, fold, now_iso, truncate
from ..evidence.models import ModuleResult, Observation
from ..extraction.html import PageDoc, jsonld_of_type
from ..identity.employer import org_numbers_in
from ..identity.model import CanonicalIdentity
from ..identity.normalization import is_generic_name, name_in_text, normalize_name
from ..security.urls import host_of, registrable_domain
from . import search
from .base import ConnectorContext, not_run
from .job_discovery import _can_spend, short_name
from .website import SiteCrawl, fetch_page

MODULE = "news_discovery"
SOURCE_ID = "news_discovery"
SOURCE_NAME = "News coverage found by search (Tavily)"
SOURCE_CLASS = "secondary_news"
ARTICLE_TYPES = ("NewsArticle", "Article", "ReportageNewsArticle", "AnalysisNewsArticle", "BlogPosting", "PressRelease")
MAX_ACCEPTED = 10
EXCERPT_CHARS = 300
BOILERPLATE = re.compile(r"(cookie|personvern|privacy|javascript|abonnement|subscribe|logg inn|log in|©|all rights reserved)", re.I)
IDENTITY_SCORE = {"organisation_number_on_page": 1.0, "exact_name_and_website_link": 0.97, "exact_legal_name_in_headline": 0.95}


@dataclass
class Article:
    headline: str
    day: str
    lead: str
    nosnippet: bool = False


@dataclass
class NewsSearchResult:
    observations: list[Observation] = field(default_factory=list)
    modules: list[ModuleResult] = field(default_factory=list)  # the search call itself
    candidates: list[dict[str, Any]] = field(default_factory=list)  # every hit considered and what became of it
    module: ModuleResult | None = None
    searched: bool = False

    def summary(self) -> dict[str, Any]:
        """What the record stores about this search (``record["news"]["search"]``)."""
        mod = self.module
        value = (mod.value or {}) if mod is not None else {}
        return {"state": mod.state if mod is not None else "not_applicable", "note": mod.note if mod is not None else None, "query": value.get("query"),
                "hits": value.get("hits"), "accepted": value.get("accepted", 0), "candidates": self.candidates[:25]}


def allowed_domains(domains: str) -> list[str]:
    return [d.strip().lower().lstrip(".") for d in (domains or "").split(",") if d.strip()]


def outlet_of(url: str, allowed: list[str]) -> str | None:
    """The allowlisted outlet this URL belongs to, or None."""
    host = host_of(url)
    return next((d for d in allowed if host == d or host.endswith("." + d)), None)


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", fold(text)).strip()


def _strip_site_name(title: str) -> str:
    """"Headline | E24" → "Headline" (only when what remains is still a headline)."""
    for sep in (" | ", " – ", " — ", " - "):
        head, _, tail = title.rpartition(sep)
        if head and len(head) >= 12 and len(tail) <= 32:
            return head.strip()
    return title


def _article_url(art: dict[str, Any]) -> str:
    main = art.get("mainEntityOfPage")
    return str(art.get("url") or (main.get("@id") if isinstance(main, dict) else main) or "")


def read_article(doc: PageDoc) -> tuple[Article | None, str | None]:
    """The article a page is, or why it is not one: (article, None) | (None, reason). Reads the page only; nothing is guessed."""
    ld = jsonld_of_type(doc, *ARTICLE_TYPES)
    chosen: dict[str, Any] | None = None
    if len(ld) == 1:
        chosen = ld[0]
    elif len(ld) > 1:
        here = {u.rstrip("/") for u in (doc.final_url, doc.canonical) if u}
        chosen = next((a for a in ld if _article_url(a).rstrip("/") in here), None)
        if chosen is None:
            return None, "the page lists several articles (a section page), not one article"
    candidates = [clean_ws(str((chosen or {}).get("headline") or (chosen or {}).get("name") or "")), clean_ws(doc.og.get("title", "")),
                  clean_ws(doc.headings[0]) if doc.headings else "", clean_ws(doc.title)]
    surface = _norm(" ".join([doc.title, doc.og.get("title", ""), *doc.headings[:6], doc.text[:6000]]))
    headline = next((h for h in (_strip_site_name(c) for c in candidates) if len(h) >= 12 and _norm(h)[:48] in surface), "")
    if not headline:
        return None, "no headline could be read from the page"
    raw_date = str((chosen or {}).get("datePublished") or (chosen or {}).get("dateCreated") or doc.og.get("published_time") or "")
    day = date_only(raw_date) or next((date_only(t.datetime[:10]) for t in doc.times if t.datetime), None)
    if not day:
        return None, "the page states no publication date"
    lead = next((p for p in doc.paragraphs if len(p) >= 60 and not BOILERPLATE.search(p) and _norm(p)[:40] != _norm(headline)[:40]), "")
    nosnippet = any(flag in doc.robots_meta for flag in ("nosnippet", "noarchive", "none"))
    return Article(headline=truncate(headline, 220), day=day, lead="" if nosnippet else truncate(lead, EXCERPT_CHARS), nosnippet=nosnippet), None


def identity_basis(doc: PageDoc, article: Article, identity: CanonicalIdentity, verified_domain: str | None) -> tuple[str | None, str | None]:
    """How the article is tied to this exact organisation: (basis, None) or (None, reason). A similar name proves nothing."""
    numbers = org_numbers_in([doc.text])
    if identity.org_number in numbers:
        return "organisation_number_on_page", None
    if numbers:
        return None, "the page states a different organisation number"
    legal = re.sub(r"\ba\s*/\s*s\b", "AS", identity.legal_name or "", flags=re.I)  # "A/S" is the older spelling of AS
    in_head = name_in_text(legal, article.headline) and not continues_into_longer_name(article.headline, legal)
    in_lead = name_in_text(legal, article.lead) and not continues_into_longer_name(article.lead, legal)
    links_home = bool(verified_domain) and any(registrable_domain(host_of(link.url)) == verified_domain for link in doc.links)
    if links_home and (in_head or in_lead):
        return "exact_name_and_website_link", None
    if in_head and not is_generic_name(legal) and len(normalize_name(legal)) >= 5:
        return "exact_legal_name_in_headline", None
    return None, "the article does not name this exact organisation in its headline (a similar name or a shared word is not enough)"


_LEGAL_FORM = r"(?:AS|ASA|A/S|ANS|DA|SA|ENK|NUF|KS|BA|SF|IKS|Ltd|Limited|AB|Oy|GmbH|Inc|LLC|ApS)"
_CAPITAL_WORD = r"[A-ZÆØÅ][\wæøåÆØÅ&.-]*"


def continues_into_longer_name(text: str, legal_name: str) -> bool:
    """True when the company's name only begins a longer company name in the text ("Autobjørn Bergen AS" for "Autobjørn AS"). Such a text names a different
    organisation, so it is never matched to this one by name."""
    core = " ".join(normalize_name(legal_name).split())
    if not core:
        return False
    words = r"\s+".join(re.escape(w) for w in core.split())
    after = re.compile(rf"(?<!\w){words}(?:\s+(?:{_CAPITAL_WORD})){{1,3}}\s+{_LEGAL_FORM}\b", re.I)
    before = re.compile(rf"{_CAPITAL_WORD}\s+(?i:{words})\s+{_LEGAL_FORM}\b")
    for m in after.finditer(text):  # case-insensitive match, then require the added words to look like name words (capitalised in the original)
        tail = text[m.start() + len(core):m.end()].split()
        if tail and all(w[:1].isupper() for w in tail[:-1]):
            return True
    return bool(before.search(text))


def _skipped(note: str, state: str = "not_applicable") -> NewsSearchResult:
    return NewsSearchResult(module=not_run(MODULE, source_id=SOURCE_ID, source_name=SOURCE_NAME, source_class="search_discovery", state=state, note=note, tier="C"))


def _observation(doc: PageDoc, article: Article, basis: str, identity: CanonicalIdentity, outlet: str, query: str) -> Observation:
    span = truncate(f"{article.headline} — {article.lead}" if article.lead else article.headline, EXCERPT_CHARS)
    key = f"{article.day}|{fold(article.headline)[:80]}"
    return Observation(
        field="news_item", value=article.headline, key_suffix=key, as_of=article.day, effective_from=article.day, claim_span=span, extraction_method="secondary_article",
        label="Press coverage", module=MODULE, source_id=f"news-{outlet}", source_name=f"{outlet} (found by web search)", source_class=SOURCE_CLASS, source_url=doc.final_url,
        retrieved_at=doc.retrieved_at or now_iso(), content_sha256=doc.content_sha256, tier="B", identity_score=IDENTITY_SCORE[basis],
        identity_signals=[basis], document_title=doc.title or None,
        attributes={"url": doc.final_url, "date": article.day, "summary": article.lead or None, "origin": "secondary_news", "outlet": outlet, "identity_basis": basis,
                    "found_by": "web search", "discovery_query": query, "organisation_number": identity.org_number})


async def discover_news(ctx: ConnectorContext, crawl: SiteCrawl | None, identity: CanonicalIdentity, *, today: date | None = None,
                          on_search: Callable[[], None] | None = None) -> NewsSearchResult:
    s = ctx.settings
    today = today or date.today()
    if not s.enable_secondary_news or not s.enable_news_discovery:
        return _skipped("News coverage search is switched off by configuration.")
    if not s.search_enabled:
        return _skipped("News coverage search is not configured (TAVILY_API_KEY missing). The company's own newsroom and investor-relations pages and the registers were still checked.")
    allowed = allowed_domains(s.secondary_news_domains)
    if not allowed:
        return _skipped("No news outlets are configured for coverage search.")
    if is_generic_name(identity.legal_name):
        return _skipped("The registered name is too generic to search press coverage without mixing up companies; only the company's own pages and the registers were used.")
    if not _can_spend(ctx.budget):
        return _skipped("Not run: the research budget for optional lookups was used up.", state="blocked")

    legal = identity.legal_name or ""
    query = f'"{short_name(legal)}" kontrakt avtale partnerskap oppkjøp resultater contract agreement partnership acquisition results'
    if on_search is not None:  # every skip condition is behind us: a search request is really about to be sent
        on_search()
    mod, hits = await search.web_search(ctx, query, count=10, include_domains=allowed, topic="news", days=min(s.news_max_age_days, 365))
    out = NewsSearchResult(modules=[mod], searched=True)
    if mod.state in ("blocked", "failed"):
        out.module = not_run(MODULE, source_id=SOURCE_ID, source_name=SOURCE_NAME, source_class="search_discovery", state=mod.state,
                             note=f"Web search was unavailable ({mod.note or mod.state}), so press coverage could not be checked. This is not evidence that nothing was reported.", tier="C")
        return out

    verified_domain = crawl.domain if crawl is not None and crawl.verified else None
    oldest = (today - timedelta(days=s.news_max_age_days)).isoformat()
    latest = (today + timedelta(days=1)).isoformat()
    fetched = 0
    seen: set[str] = set()
    for hit in hits:
        cand: dict[str, Any] = {"url": hit.url, "title": hit.title[:140], "rank": hit.rank}
        outlet = outlet_of(hit.url, allowed)
        if outlet is None:
            out.candidates.append({**cand, "status": "ignored", "reason": "the outlet is not on the list of reputable sources; page not fetched"})
            continue
        if not search.hit_matches_company(hit, legal):
            out.candidates.append({**cand, "status": "ignored", "reason": "the search hit does not mention the company; page not fetched"})
            continue
        if hit.url in seen:
            continue
        seen.add(hit.url)
        if len(out.observations) >= MAX_ACCEPTED:
            out.candidates.append({**cand, "status": "not_checked", "reason": "enough articles were already verified"})
            continue
        if fetched >= s.secondary_news_max_pages or not _can_spend(ctx.budget):
            out.candidates.append({**cand, "status": "not_checked", "reason": "page limit or budget reached"})
            continue
        res, doc = await fetch_page(ctx, hit.url, connector="news_discovery", optional=True)
        fetched += 1
        if doc is None:
            reason = {"robots_disallowed": "robots.txt does not allow fetching this page (respected)", "blocked": "the outlet refused access (not worked around)",
                      "not_found": "the page no longer exists", "gone": "the page no longer exists"}.get(res.classification, f"the page could not be read ({res.classification})")
            out.candidates.append({**cand, "status": "blocked" if res.classification in ("robots_disallowed", "blocked") else "unreadable", "reason": reason})
            continue
        article, why = read_article(doc)
        if article is None:
            out.candidates.append({**cand, "status": "unverified", "reason": why})
            continue
        cand["title"], cand["date"] = article.headline[:140], article.day
        if article.day > latest:
            out.candidates.append({**cand, "status": "rejected", "reason": "the article is dated in the future"})
            continue
        if article.day < oldest:
            out.candidates.append({**cand, "status": "rejected", "reason": f"the article is older than {s.news_max_age_days} days"})
            continue
        basis, why = identity_basis(doc, article, identity, verified_domain)
        if basis is None:
            out.candidates.append({**cand, "status": "unverified", "reason": why})
            continue
        out.observations.append(_observation(doc, article, basis, identity, outlet, query))
        out.candidates.append({**cand, "status": "accepted", "reason": f"tied to this organisation by {basis.replace('_', ' ')}", "outlet": outlet})
    accepted = len(out.observations)
    rejected = len([c for c in out.candidates if c["status"] in ("unverified", "rejected", "unreadable", "blocked")])
    note = (f"Search suggested {len(hits)} article(s); {accepted} verified as reporting on this company" + (f", {rejected} could not be used" if rejected else "") + "."
            if hits else "Search returned no press coverage for this company (this does not mean none exists).")
    out.module = ModuleResult(module=MODULE, source_id=SOURCE_ID, source_name=SOURCE_NAME, source_class="search_discovery", state="available" if hits else "not_available", note=note,
                              tier="C", retrieved_at=now_iso(), value={"query": query, "hits": len(hits), "fetched": fetched, "accepted": accepted, "candidates": out.candidates[:20]})
    return out
