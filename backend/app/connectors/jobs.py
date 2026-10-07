"""Job postings from company-owned sources only.

1. ``JobPosting`` structured data on pages of the verified company website;
2. job links on the verified careers page;
3. the applicant-tracking system (ATS) page the verified website links to.

A posting whose ``validThrough`` has passed is historical, never "current".
An ATS posting naming a different hiring organisation is discarded.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..core.util import clean_ws, date_only, parse_iso, stable_id
from ..evidence.models import ModuleResult
from ..extraction.html import Link, PageDoc, jsonld_of_type
from ..identity.normalization import distinctive_tokens
from ..security.urls import canonical_url, host_of, registrable_domain
from .base import ConnectorContext, module_from_fetch
from .website import SiteCrawl, fetch_page

JOB_PATH = re.compile(r"/(jobs?|stilling(er)?|jobb(er)?|vacanc(y|ies)|positions?|career[s]?/[^/]+|ledige-stillinger/[^/]+|annonse|ads?)/[^/?#]{3,}", re.I)
GENERIC_JOB_TEXT = {"ledige stillinger", "se alle stillinger", "alle stillinger", "jobs", "careers", "karriere", "jobb hos oss", "les mer", "read more", "apply", "søk", "søk her", "se stilling", "open positions", "view all jobs"}


@dataclass
class JobItem:
    id: str
    title: str
    url: str
    source_url: str
    source_host: str
    location: str | None = None
    department: str | None = None
    employment_type: str | None = None
    posted_at: str | None = None
    valid_through: str | None = None
    state: str = "current"  # current | stale | closed
    evidence_span: str = ""
    method: str = "json_ld"
    retrieved_at: str | None = None
    content_sha256: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("raw", None)
        return data


def _location(job: dict[str, Any]) -> str | None:
    loc = job.get("jobLocation")
    locs = loc if isinstance(loc, list) else [loc]
    names = []
    for item in locs:
        if not isinstance(item, dict):
            continue
        addr = item.get("address") or {}
        if isinstance(addr, dict):
            name = addr.get("addressLocality") or addr.get("addressRegion")
            if name:
                names.append(clean_ws(str(name)))
    return ", ".join(dict.fromkeys(names)) or None


def _hiring_org(job: dict[str, Any]) -> str | None:
    org = job.get("hiringOrganization")
    if isinstance(org, dict):
        return clean_ws(org.get("name"))
    if isinstance(org, str):
        return clean_ws(org)
    return None


def _org_matches(hiring: str | None, legal_name: str, site_title: str) -> bool:
    if not hiring:
        return True
    tokens = distinctive_tokens(legal_name)
    hay = hiring.casefold()
    if tokens and all(t in hay for t in tokens):
        return True
    brand = (site_title or "").split("|")[0].split("–")[0].split("-")[0].strip().casefold()
    return bool(brand) and len(brand) >= 3 and (brand in hay or hay in brand)


def jobs_from_jsonld(doc: PageDoc, legal_name: str, site_title: str, *, now: datetime | None = None) -> list[JobItem]:
    out: list[JobItem] = []
    now = now or datetime.now(UTC)
    for job in jsonld_of_type(doc, "JobPosting"):
        title = clean_ws(str(job.get("title") or job.get("name") or ""))
        if not title or not _org_matches(_hiring_org(job), legal_name, site_title):
            continue
        url = str(job.get("url") or doc.final_url)
        valid = job.get("validThrough")
        valid_dt = parse_iso(str(valid)) if valid else None
        state = "stale" if valid_dt and valid_dt < now else "current"
        out.append(JobItem(
            id=stable_id(canonical_url(url), title, length=12), title=title[:200], url=url, source_url=doc.final_url, source_host=host_of(doc.final_url),
            location=_location(job), department=clean_ws(str(job.get("occupationalCategory") or job.get("industry") or "")) or None,
            employment_type=clean_ws(str(job.get("employmentType") or "")) or None, posted_at=date_only(str(job.get("datePosted") or "")),
            valid_through=date_only(str(valid)) if valid else None, state=state, evidence_span=f'JobPosting "{title}"' + (f" · datePosted {job.get('datePosted')}" if job.get("datePosted") else ""),
            method="json_ld", retrieved_at=doc.retrieved_at, content_sha256=doc.content_sha256,
        ))
    return out


def job_links(doc: PageDoc) -> list[Link]:
    out = []
    for link in doc.links:
        text = clean_ws(link.text)
        if not text or text.casefold() in GENERIC_JOB_TEXT or len(text) < 6 or len(text) > 140:
            continue
        path = urllib.parse.urlsplit(link.url).path
        if JOB_PATH.search(path):
            out.append(link)
    return out


async def collect_jobs(ctx: ConnectorContext, crawl: SiteCrawl, legal_name: str, *, max_ats_pages: int = 1, max_detail_pages: int = 3) -> tuple[list[ModuleResult], list[JobItem], str]:
    """Return (module results, jobs, status_note). Only runs on a verified site."""
    modules: list[ModuleResult] = []
    jobs: dict[str, JobItem] = {}
    site_title = crawl.homepage.title if crawl.homepage else ""
    careers_docs = crawl.docs("careers")

    def add(items: list[JobItem]) -> None:
        for item in items:
            key = canonical_url(item.url) + "|" + item.title.casefold()
            if key not in jobs:
                jobs[key] = item

    for doc in crawl.docs():
        add(jobs_from_jsonld(doc, legal_name, site_title))
    for doc in careers_docs:
        for link in job_links(doc):
            if registrable_domain(host_of(link.url)) != crawl.domain and not any(a.url == link.url for a in crawl.ats_links):
                continue
            add([JobItem(id=stable_id(canonical_url(link.url), link.text, length=12), title=clean_ws(link.text)[:200], url=link.url, source_url=doc.final_url,
                         source_host=host_of(doc.final_url), evidence_span=f'Careers page link "{clean_ws(link.text)}"', method="careers_page_link",
                         retrieved_at=doc.retrieved_at, content_sha256=doc.content_sha256)])

    ats_pages = 0
    for link in crawl.ats_links:
        if ats_pages >= max_ats_pages:
            break
        res, doc = await fetch_page(ctx, link.url, connector="company_ats", optional=True)
        ats_pages += 1
        mod = module_from_fetch("jobs_ats", source_id="ats", source_name=f"Company job board ({host_of(link.url)})", source_class="company_linked_job_board", result=res,
                                value={"url": link.url})
        modules.append(mod)
        if doc is None:
            continue
        found = jobs_from_jsonld(doc, legal_name, site_title)
        add(found)
        details = 0
        for jl in job_links(doc):
            if details >= max_detail_pages:
                break
            if host_of(jl.url) != host_of(doc.final_url):
                continue
            if any(canonical_url(j.url) == canonical_url(jl.url) for j in jobs.values()):
                continue
            dres, ddoc = await fetch_page(ctx, jl.url, connector="company_ats", optional=True)
            details += 1
            detail_items = jobs_from_jsonld(ddoc, legal_name, site_title) if ddoc else []
            if detail_items:
                add(detail_items)
            elif ddoc is not None:
                add([JobItem(id=stable_id(canonical_url(jl.url), jl.text, length=12), title=clean_ws(jl.text)[:200], url=jl.url, source_url=doc.final_url,
                             source_host=host_of(doc.final_url), evidence_span=f'Job board link "{clean_ws(jl.text)}"', method="ats_link",
                             retrieved_at=doc.retrieved_at, content_sha256=doc.content_sha256)])
        for jl in job_links(doc):
            if host_of(jl.url) == host_of(doc.final_url):
                add([JobItem(id=stable_id(canonical_url(jl.url), jl.text, length=12), title=clean_ws(jl.text)[:200], url=jl.url, source_url=doc.final_url,
                             source_host=host_of(doc.final_url), evidence_span=f'Job board link "{clean_ws(jl.text)}"', method="ats_link",
                             retrieved_at=doc.retrieved_at, content_sha256=doc.content_sha256)])

    items = list(jobs.values())[: ctx.settings.max_jobs_per_company]
    if items:
        note = f"{sum(1 for j in items if j.state == 'current')} current posting(s) found on company-owned pages"
    elif careers_docs or crawl.ats_links:
        note = "A careers page was checked; no individual postings could be read from it."
    else:
        note = "No careers page or job board was found on the verified website."
    return modules, items, note
