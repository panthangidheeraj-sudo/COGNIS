"""Job pages found by web search (Tavily). Search results are candidates, never evidence.

When the company's own careers sources yield no current opening, one targeted search asks for pages on the company's identity-verified
domain or on known applicant-tracking hosts that mention the company. Every hit then goes through the same checks as any other page:

1. host: the verified website or a known job-board host; never NAV's web pages, LinkedIn, Finn.no, Indeed, Glassdoor or other platforms;
2. fetch: robots.txt, SSRF policy, per-host rate limit and request budget apply (a refusal is recorded, never worked around);
3. employer: the page's ``JobPosting`` must tie itself to this exact organisation (it is on the verified domain, names the verified website,
   states the organisation number, or names the exact registered name and links to the verified website). A similar name is not enough;
4. status: end date, "closed" notices and the age of the posting are checked; an undated posting found only by search is not current.

Only postings that pass all four become jobs (``source="discovered"``). Everything else stays an internal candidate with its reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..core.util import now_iso
from ..evidence.models import ModuleResult
from ..extraction.html import ATS_HOSTS, PageDoc
from ..identity.employer import exact_legal_name, org_numbers_in
from ..identity.model import CanonicalIdentity
from ..identity.normalization import LEGAL_SUFFIXES
from ..runtime.budgets import CompanyBudget, RunBudget
from ..security.urls import canonical_url, host_of, registrable_domain
from . import search
from .base import ConnectorContext, not_run
from .jobs import JobItem, closed_notice, is_nav_host, jobs_from_jsonld
from .website import SiteCrawl, fetch_page

MODULE = "job_discovery"
SOURCE_ID = "job_discovery"
SOURCE_NAME = "Job pages found by search (Tavily)"
JOB_BOARD_HOSTS = [h for h in ATS_HOSTS if h != "arbeidsplassen.nav.no"]  # NAV ads come from NAV's official feed only


@dataclass
class DiscoveryResult:
    jobs: list[JobItem] = field(default_factory=list)
    modules: list[ModuleResult] = field(default_factory=list)  # the search call itself
    candidates: list[dict[str, Any]] = field(default_factory=list)  # every hit considered and what became of it (internal, never published)
    module: ModuleResult | None = None
    searched: bool = False


def short_name(legal_name: str) -> str:
    tokens = (legal_name or "").replace("A/S", "AS").split()
    if len(tokens) > 1 and tokens[-1].casefold().strip(".") in LEGAL_SUFFIXES:
        tokens = tokens[:-1]
    return " ".join(tokens)


def _can_spend(budget: CompanyBudget | RunBudget | None) -> bool:
    if isinstance(budget, CompanyBudget):
        return budget.can_optional()
    if isinstance(budget, RunBudget):
        return budget.time_for_optional() and budget.can_spend(optional=True)
    return True


def employer_basis(doc: PageDoc, job: JobItem, identity: CanonicalIdentity, verified_domain: str) -> str | None:
    """How a discovered posting is tied to this exact organisation, or None."""
    if registrable_domain(host_of(doc.final_url)) == verified_domain:
        return "verified_domain"  # the posting is published on the company's identity-verified website
    org = (job.raw or {}).get("hiring_org") or {}
    if any(registrable_domain(host_of(u)) == verified_domain for u in org.get("urls") or []):
        return "hiring_organization_website"
    if identity.org_number in org_numbers_in([doc.text]):
        return "organisation_number_on_page"
    if exact_legal_name(org.get("name"), identity) and any(registrable_domain(host_of(link.url)) == verified_domain for link in doc.links):
        return "exact_name_and_website_link"
    return None


def _skipped(note: str, state: str = "not_applicable") -> DiscoveryResult:
    return DiscoveryResult(module=not_run(MODULE, source_id=SOURCE_ID, source_name=SOURCE_NAME, source_class="search_discovery", state=state, note=note, tier="C"))


async def discover_jobs(ctx: ConnectorContext, crawl: SiteCrawl, identity: CanonicalIdentity, known: list[JobItem]) -> DiscoveryResult:
    s = ctx.settings
    if not s.enable_job_discovery:
        return _skipped("Job-page discovery disabled by configuration.")
    if not s.search_enabled:
        return _skipped("Search discovery not configured (TAVILY_API_KEY missing); company careers pages and linked job boards were still checked.")
    if not crawl.verified:
        return _skipped("No identity-verified website to anchor the search.")
    if not _can_spend(ctx.budget):
        return _skipped("Not run: the research budget for optional lookups was used up.", state="blocked")

    legal_name = identity.legal_name or ""
    query = f'{short_name(legal_name)} ledige stillinger karriere jobb'
    mod, hits = await search.web_search(ctx, query, count=10, include_domains=[crawl.domain, *JOB_BOARD_HOSTS])
    out = DiscoveryResult(modules=[mod], searched=True)
    if mod.state in ("blocked", "failed"):
        out.module = not_run(MODULE, source_id=SOURCE_ID, source_name=SOURCE_NAME, source_class="search_discovery", state=mod.state,
                             note=f"Web search was unavailable ({mod.note or mod.state}); this is not evidence about hiring.", tier="C")
        return out

    known_urls = {canonical_url(j.url) for j in known}
    site_title = crawl.homepage.title if crawl.homepage else ""
    fetched = 0
    now = datetime.now(UTC)
    for hit in hits:
        cand: dict[str, Any] = {"url": hit.url, "title": hit.title[:140], "rank": hit.rank}
        dom = hit.domain
        if is_nav_host(hit.url) or not (dom == crawl.domain or any(host_of(hit.url) == h or host_of(hit.url).endswith("." + h) for h in JOB_BOARD_HOSTS)):
            out.candidates.append({**cand, "status": "ignored", "reason": "not the verified website or a known job board (platforms such as NAV's site, Finn.no, LinkedIn are not used)"})
            continue
        if canonical_url(hit.url) in known_urls:
            continue  # already found on the company's own pages
        if dom != crawl.domain and not search.hit_matches_company(hit, legal_name):
            out.candidates.append({**cand, "status": "ignored", "reason": "the search hit does not mention the company; page not fetched"})
            continue
        if fetched >= s.job_discovery_max_pages or not _can_spend(ctx.budget):
            out.candidates.append({**cand, "status": "not_checked", "reason": "page limit or budget reached"})
            continue
        res, doc = await fetch_page(ctx, hit.url, connector="job_discovery", optional=True)
        fetched += 1
        if doc is None:
            reason = {"robots_disallowed": "robots.txt does not allow fetching this page (respected)", "not_found": "the page no longer exists",
                      "gone": "the page no longer exists"}.get(res.classification, f"the page could not be read ({res.classification})")
            out.candidates.append({**cand, "status": "blocked" if res.classification in ("robots_disallowed", "blocked") else "unreadable", "reason": reason})
            continue
        postings = jobs_from_jsonld(doc, legal_name, site_title, now=now, max_age_days=s.job_max_age_days)
        if not postings:
            out.candidates.append({**cand, "status": "unverified", "reason": "no structured job posting on the page, so its employer and status cannot be verified"})
            continue
        notice = closed_notice(doc) if len(postings) == 1 else None
        for job in postings:
            info = {**cand, "title": job.title}
            basis = employer_basis(doc, job, identity, crawl.domain)
            if basis is None:
                named = (job.raw.get("hiring_org") or {}).get("name")
                out.candidates.append({**info, "status": "wrong_company" if named else "unverified",
                                       "reason": f"employer {named!r} is not tied to this organisation's verified website or organisation number" if named
                                       else "the posting names no employer that can be tied to this organisation"})
                continue
            if notice:
                job.state, job.details["closed_notice"] = "closed", notice
            elif job.state == "current" and not (job.valid_through or job.posted_at or job.details.get("updated_at")):
                job.state, job.details["state_reason"] = "stale", "no posting, update or end date: not shown to be current"
            if job.state != "current":
                why = job.details.get("closed_notice") or job.details.get("state_reason") or (
                    f"the posting ended {job.valid_through}" if job.valid_through else f"the posting is older than {s.job_max_age_days} days")
                out.candidates.append({**info, "status": job.state, "reason": why})
                continue
            job.source = "discovered"
            job.details.update({"identity_basis": basis, "found_by": "web search", "discovery_query": query})
            job.evidence_span = f"{job.evidence_span} · found by web search, verified on {doc.final_url} ({basis.replace('_', ' ')})"
            known_urls.add(canonical_url(job.url))
            out.jobs.append(job)
    accepted, rejected = len(out.jobs), len([c for c in out.candidates if c["status"] not in ("ignored", "not_checked")])
    note = f"Search suggested {len(hits)} page(s); {accepted} posting(s) verified as this company's and current" + (f", {rejected} candidate(s) rejected" if rejected else "") + "."
    out.module = ModuleResult(module=MODULE, source_id=SOURCE_ID, source_name=SOURCE_NAME, source_class="search_discovery", state="available" if hits else "not_available",
                              note=note if hits else "Search returned no job pages for this company.", tier="C", retrieved_at=now_iso(),
                              value={"query": query, "hits": len(hits), "fetched": fetched, "accepted": accepted, "candidates": out.candidates[:20]})
    return out
