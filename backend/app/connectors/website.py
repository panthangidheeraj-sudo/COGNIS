"""Focused, respectful website crawler for company-owned sites.

Order: homepage → identity pages (contact/about) → identity gate → only when
verified: careers, news, team, products, locations, investors, sustainability.
Same-site only, robots.txt respected, bounded pages, deduplicated URLs.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup

from ..evidence.models import ModuleResult
from ..extraction.html import Link, PageDoc, classify_link, is_ats, looks_parked, parse_html, social_profile
from ..identity.match import IdentityAudit, audit_site
from ..identity.model import CanonicalIdentity
from ..net.http import FetchResult
from ..security.urls import canonical_url, host_of, registrable_domain
from .base import ConnectorContext, module_from_fetch

HTML_ACCEPT = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"
IDENTITY_KINDS = ("contact", "about")
ENRICHMENT_KINDS = ("careers", "news", "team", "products", "locations", "investors", "sustainability")


@dataclass
class FetchedPage:
    kind: str
    result: FetchResult
    doc: PageDoc | None


@dataclass
class SiteCrawl:
    start_url: str
    source_class: str
    origin: str  # registry | email_domain | search | registry_subunit
    domain: str = ""
    pages: list[FetchedPage] = field(default_factory=list)
    audit: IdentityAudit | None = None
    state: str = "not_available"
    note: str | None = None
    social: list[dict[str, str]] = field(default_factory=list)
    ats_links: list[Link] = field(default_factory=list)
    requests: int = 0

    @property
    def homepage(self) -> PageDoc | None:
        return next((p.doc for p in self.pages if p.kind == "home" and p.doc), None)

    def docs(self, kind: str | None = None) -> list[PageDoc]:
        return [p.doc for p in self.pages if p.doc and (kind is None or p.kind == kind)]

    @property
    def verified(self) -> bool:
        return bool(self.audit and self.audit.decision == "verified")

    def module(self) -> ModuleResult:
        home = next((p for p in self.pages if p.kind == "home"), None)
        if home is None:
            return ModuleResult(module="website", source_id="website", source_name="Official company website", source_class=self.source_class,
                                state="not_available", url=self.start_url, note=self.note)
        mod = module_from_fetch("website", source_id="website", source_name=f"Official company website ({self.domain})", source_class=self.source_class,
                                result=home.result, value=self.value(), note=self.note)
        if mod.state == "available" and not self.verified:
            mod.state = "ambiguous" if not (self.audit and self.audit.decision == "rejected") else "not_available"
        mod.requests = self.requests
        return mod

    def value(self) -> dict[str, Any]:
        home = self.homepage
        return {
            "final_url": home.final_url if home else None,
            "domain": self.domain,
            "title": home.title if home else None,
            "description": (home.description or home.og.get("description")) if home else None,
            "social_links": sorted(({"platform": s["network"], "url": s["url"]} for s in self.social), key=lambda x: (x["platform"], x["url"])),
            "pages": {p.kind: p.doc.final_url for p in self.pages if p.doc},
            "identity_assessment": self.audit.to_dict() if self.audit else None,
            "origin": self.origin,
        }


async def fetch_page(ctx: ConnectorContext, url: str, *, connector: str = "website", optional: bool = True) -> tuple[FetchResult, PageDoc | None]:
    res = await ctx.fetch(url, connector=connector, optional=optional, accept=HTML_ACCEPT, expect="html", check_robots=True, cache_ttl=ctx.settings.cache_ttl_web_seconds)
    if not res.ok:
        return res, None
    return res, parse_html(url, res.final_url, res.text(), content_sha256=res.content_sha256, retrieved_at=res.retrieved_at)


def site_links(home: PageDoc, domain: str) -> dict[str, list[Link]]:
    """Same-site links grouped by page kind, best candidate first (shortest path, label match)."""
    grouped: dict[str, list[Link]] = {}
    for link in home.links:
        if registrable_domain(host_of(link.url)) != domain:
            continue
        if re.search(r"\.(pdf|jpg|jpeg|png|gif|zip|docx?|xlsx?|svg|webp|mp4)$", urllib.parse.urlsplit(link.url).path, re.I):
            continue
        kind = classify_link(link.url, link.text)
        if kind:
            grouped.setdefault(kind, []).append(link)
    for kind in grouped:
        grouped[kind].sort(key=lambda link: (len(urllib.parse.urlsplit(link.url).path.strip("/").split("/")), len(link.url)))
    return grouped


async def sitemap_links(ctx: ConnectorContext, home: PageDoc, domain: str, limit: int = 300) -> list[Link]:
    origin = f"{urllib.parse.urlsplit(home.final_url).scheme}://{urllib.parse.urlsplit(home.final_url).netloc}"
    candidates = list(ctx.http.robots.sitemaps.get(origin.lower(), []))[:2] or [origin + "/sitemap.xml"]
    links: list[Link] = []
    for sitemap in candidates[:1]:
        res = await ctx.fetch(sitemap, connector="website", optional=True, accept="application/xml,text/xml;q=0.9,*/*;q=0.5", check_robots=True, max_bytes=1_500_000)
        if not res.ok:
            continue
        soup = BeautifulSoup(res.body, "xml")
        for loc in soup.find_all("loc")[: limit * 2]:
            url = (loc.get_text() or "").strip()
            if url and registrable_domain(host_of(url)) == domain and not url.endswith(".xml"):
                links.append(Link(url, ""))
            if len(links) >= limit:
                break
    return links


async def crawl_site(
    ctx: ConnectorContext,
    start_url: str,
    identity: CanonicalIdentity,
    *,
    origin: str,
    max_pages: int,
    norid_holder_org: str | None = None,
) -> SiteCrawl:
    registry_linked = origin == "registry"
    source_class = "company_owned" if registry_linked else ("company_owned_email_domain" if origin == "email_domain" else "company_owned_discovered")
    crawl = SiteCrawl(start_url=start_url, source_class=source_class, origin=origin, domain=registrable_domain(host_of(start_url)))
    res, home = await fetch_page(ctx, start_url, optional=True)
    crawl.requests += 0 if res.from_cache else 1 + res.retries + res.redirects
    crawl.pages.append(FetchedPage("home", res, home))
    if home is None:
        crawl.state = {"robots_disallowed": "blocked", "blocked": "blocked", "budget_exhausted": "blocked", "not_found": "not_available", "gone": "not_available"}.get(res.classification, "failed")
        crawl.note = res.error or res.classification
        return crawl
    final_domain = registrable_domain(host_of(home.final_url))
    if final_domain and final_domain != crawl.domain:
        # Redirected to another domain (rebrand, parent, reseller). Identity is judged on the final site.
        crawl.domain = final_domain
    parked = looks_parked(home)
    grouped = site_links(home, crawl.domain)
    if not any(k in grouped for k in IDENTITY_KINDS) and not parked:
        for link in await sitemap_links(ctx, home, crawl.domain):
            kind = classify_link(link.url, link.text)
            if kind:
                grouped.setdefault(kind, []).append(link)

    seen = {canonical_url(home.final_url), canonical_url(start_url)}
    budget_pages = max(1, max_pages)

    async def take(kind: str) -> None:
        for link in grouped.get(kind, [])[:2]:
            key = canonical_url(link.url)
            if key in seen:
                continue
            seen.add(key)
            if len(crawl.pages) >= budget_pages:
                return
            page_res, doc = await fetch_page(ctx, link.url, optional=True)
            crawl.requests += 0 if page_res.from_cache else 1 + page_res.retries + page_res.redirects
            crawl.pages.append(FetchedPage(kind, page_res, doc))
            if doc is not None:
                return

    if not parked:
        for kind in IDENTITY_KINDS:
            await take(kind)
    crawl.audit = audit_site(identity, crawl.docs(), crawl.domain, registry_linked=registry_linked, norid_holder_org=norid_holder_org, parked=parked)
    if not crawl.verified:
        crawl.state = "ambiguous" if crawl.audit.decision == "ambiguous" else "not_available"
        crawl.note = "; ".join(crawl.audit.conflicts) or f"identity not established (score {crawl.audit.score:.2f})"
        return crawl

    crawl.state = "available"
    for kind in ENRICHMENT_KINDS:
        if len(crawl.pages) >= budget_pages or not ctx.budget or not getattr(ctx.budget, "can_optional", lambda: True)():
            break
        await take(kind)

    for doc in crawl.docs():
        for link in doc.links:
            prof = social_profile(link.url)
            if prof and all(s["url"] != canonical_url(link.url) for s in crawl.social):
                crawl.social.append({"network": prof[0], "handle": prof[1], "url": canonical_url(link.url), "page": doc.final_url})
            if is_ats(link.url) and all(canonical_url(a.url) != canonical_url(link.url) for a in crawl.ats_links):
                crawl.ats_links.append(link)
    return crawl
