"""Web discovery (Tavily Search API). Results are *candidates*, never claim evidence.

Provider-agnostic shape: ``web_search(ctx, query)`` returns ``SearchHit`` rows; the orchestrator fetches the
underlying page itself (robots.txt, SSRF policy, budgets) and runs the identity gate. Tavily's own page
snippets are never used as evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..core.util import fold
from ..evidence.models import ModuleResult
from ..identity.normalization import ascii_fold, distinctive_tokens, name_in_text
from ..security.urls import host_of, registrable_domain
from .base import ConnectorContext, module_from_fetch, not_run

TAVILY_ENDPOINT = "https://api.tavily.com/search"
SEARCH_SOURCE = {"source_id": "websearch", "source_name": "Web search (Tavily)", "source_class": "search_discovery"}

# Directories, registries, social networks and aggregators: never treated as a company's own site.
NON_COMPANY_DOMAINS = {
    "brreg.no", "proff.no", "purehelp.no", "gulesider.no", "1881.no", "180.no", "regnskapstall.no", "firmaonline.no", "kompass.com",
    "enirogate.no", "infobel.com", "dnb.com", "bisnode.no", "forvalt.no", "allabolag.se", "opencorporates.com", "linkedin.com", "facebook.com",
    "instagram.com", "twitter.com", "x.com", "youtube.com", "wikipedia.org", "finn.no", "arbeidsplassen.nav.no", "nav.no", "google.com",
    "bing.com", "duckduckgo.com", "yelp.com", "tripadvisor.com", "tripadvisor.no", "trustpilot.com", "glassdoor.com", "indeed.com",
    "kununu.com", "mittanbud.no", "anbudstorget.no", "byggstart.no", "legelisten.no", "nettavisen.no", "vg.no", "dagbladet.no", "aftenposten.no",
    "dn.no", "e24.no", "nrk.no", "tv2.no", "finansavisen.no", "kapital.no", "hegnar.no", "estate.no", "nyheter24.no", "lokalavisen.no",
    "bizzdo.no", "roaringapps.com", "northdata.com", "northdata.de", "companieshouse.gov.uk", "doffin.no", "mercell.com", "eniro.no",
    "krak.no", "hitta.se", "foretaksregisteret.no", "virksomhet.brreg.no", "firmasok.no", "regnskapsbanken.no", "ravninfo.com",
    "nettbutikk.no", "facebook.no", "tiktok.com", "pinterest.com", "medium.com", "github.com", "apple.com", "play.google.com",
}


@dataclass
class SearchHit:
    title: str
    url: str
    description: str
    rank: int
    query: str
    age: str | None = None
    score: float | None = None

    @property
    def domain(self) -> str:
        return registrable_domain(host_of(self.url))


def is_candidate_company_domain(domain: str) -> bool:
    return bool(domain) and domain not in NON_COMPANY_DOMAINS and not domain.endswith((".gov", ".gov.uk"))


def hit_matches_company(hit: SearchHit, legal_name: str | None) -> bool:
    """Cheap pre-screen before any page is fetched: the hit's title, snippet, URL or domain must show the company's name
    (full legal name, all distinctive name words, or a distinctive word inside the domain). Never evidence, only candidate selection."""
    text = " ".join([hit.title, hit.description, hit.url])
    if name_in_text(legal_name, text):
        return True
    tokens = distinctive_tokens(legal_name)
    if not tokens:
        return False  # generic names are too ambiguous to chase through search
    surface = fold(text)
    if all(re.search(rf"\b{re.escape(t)}\b", surface) for t in tokens):
        return True
    label = ascii_fold(hit.domain.split(".")[0])
    return any(len(t) >= 4 and ascii_fold(t) in label for t in tokens)


def _request_body(query: str, count: int, *, minimal: bool) -> dict[str, Any]:
    body: dict[str, Any] = {"query": query[:380], "search_depth": "basic", "max_results": count,
                            "include_answer": False, "include_raw_content": False, "include_images": False}
    if not minimal:  # optional hints; dropped if the API rejects them (400/422)
        body.update({"country": "norway", "exclude_domains": sorted(NON_COMPANY_DOMAINS)[:150], "include_usage": True})
    return body


async def web_search(ctx: ConnectorContext, query: str, *, count: int = 10) -> tuple[ModuleResult, list[SearchHit]]:
    s = ctx.settings
    if not s.search_enabled:
        return not_run("search", **SEARCH_SOURCE, state="not_applicable",
                       note="Search discovery not configured (TAVILY_API_KEY missing)." if not s.tavily_api_key else "Search disabled by configuration.", tier="C"), []
    tripped = getattr(ctx.http, "tripped", {}).get("search")
    if tripped:  # key rejected or plan credits used up earlier in this run: do not keep calling
        return not_run("search", **SEARCH_SOURCE, state="blocked", note=tripped, tier="C"), []

    async def call(minimal: bool):  # noqa: ANN202
        return await ctx.fetch(
            TAVILY_ENDPOINT,
            connector="tavily_search",
            method="POST",
            json_body=_request_body(query, count, minimal=minimal),
            headers={"Authorization": f"Bearer {s.tavily_api_key or ''}", "Content-Type": "application/json"},
            accept="application/json",
            expect="json",
            cost_usd=s.tavily_cost_per_request_usd,
            search=True,
            cache_ttl=s.cache_ttl_search_seconds,
            optional=True,
        )

    res = await call(minimal=False)
    if res.status in (400, 422):  # an optional parameter was refused: retry once with the bare query
        res = await call(minimal=True)
    note = None
    if res.status == 401:
        note = "Tavily rejected the API key (HTTP 401) - check TAVILY_API_KEY."
    elif res.status in (432, 433):
        note = f"Tavily plan credit limit reached (HTTP {res.status}) - search discovery is paused for this run."
    if note and hasattr(ctx.http, "tripped"):
        ctx.http.tripped["search"] = note

    hits: list[SearchHit] = []
    credits = None
    if res.ok:
        body: dict[str, Any] = res.json() or {}
        credits = (body.get("usage") or {}).get("credits")
        for index, row in enumerate((body.get("results") or [])[:count]):
            url = row.get("url")
            if url:
                hits.append(SearchHit(title=row.get("title") or "", url=url, description=(row.get("content") or "")[:400], rank=index + 1, query=query,
                                      age=row.get("published_date"), score=row.get("score")))
    mod = module_from_fetch("search", **SEARCH_SOURCE, result=res, value={"query": query, "hits": [h.__dict__ for h in hits], "credits": credits}, tier="C", note=note)
    if res.ok and not hits:
        mod.state, mod.note = "not_available", f"No results for {query!r}"
    return mod, hits


def identity_queries(legal_name: str, org_number: str, municipality: str | None) -> list[str]:
    """Targeted identity-first queries (Norwegian + English patterns)."""
    spaced = f"{org_number[:3]} {org_number[3:6]} {org_number[6:]}"
    return [f'"{legal_name}" {municipality or ""}'.strip(), f'"{legal_name}" "{spaced}"', f'"{org_number}"']
