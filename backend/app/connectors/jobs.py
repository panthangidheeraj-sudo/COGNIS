"""Job postings from company-owned sources (plus pages found by search, once verified).

1. ``JobPosting`` structured data on pages of the verified company website;
2. job links on the verified careers page;
3. the applicant-tracking system (ATS) page the verified website links to;
4. job pages suggested by web search (``job_discovery.py``): candidates only, used after they are fetched and verified.

A posting is "current" only while nothing says otherwise: a passed ``validThrough``, a "closed" notice on its page, or (without any end
date) a posting date/update older than ``job_max_age_days`` makes it stale. An ATS posting naming a different hiring organisation is
discarded. The same opening found in several places is merged by ``dedupe_jobs`` and keeps every URL, its dates and its status.
NAV Arbeidsplassen is read only through its official feed (``nav.py``), never by fetching its web pages.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from ..core.util import clean_ws, date_only, parse_iso, stable_id
from ..evidence.models import ModuleResult
from ..extraction.html import Link, PageDoc, find_span, jsonld_of_type
from ..identity.normalization import distinctive_tokens
from ..security.urls import canonical_url, host_of, registrable_domain
from .base import ConnectorContext, module_from_fetch
from .website import FetchedPage, SiteCrawl, fetch_page, site_links

JOB_PATH = re.compile(r"/(jobs?|stilling(er)?|jobb(er)?|vacanc(y|ies)|positions?|career[s]?/[^/]+|ledige-stillinger/[^/]+|annonse|ads?)/[^/?#]{3,}", re.I)
CLOSED_MARKERS = re.compile(
    r"(s[øo]knadsfristen\s+(er\s+)?(ute|utl[øo]pt|passert)|fristen\s+(er\s+)?(ute|utl[øo]pt|passert)|stillingen\s+er\s+(besatt|utl[øo]pt|stengt|avsluttet|ikke lenger)"
    r"|ikke\s+lenger\s+(ledig|tilgjengelig|aktiv)|annonsen\s+er\s+(utl[øo]pt|avsluttet|fjernet)|no longer accepting applications|applications?\s+(are\s+)?closed"
    r"|(job|position|vacancy|role|posting)\s+(is\s+)?no longer (available|open)|(job|position|vacancy|role|posting)\s+has\s+(been\s+)?(closed|filled|expired))", re.I)
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
    source: str = "company"  # company (careers page / linked job board) | discovered (found by search, verified) | nav (NAV Arbeidsplassen, employer verified)
    details: dict[str, Any] = field(default_factory=dict)  # source metadata: updated_at, identity_basis, employer org no., merged duplicates (see dedupe_jobs)
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


def hiring_org_info(job: dict[str, Any]) -> dict[str, Any]:
    """What a JobPosting says about its employer (name and web addresses); used to verify postings found by search."""
    org = job.get("hiringOrganization")
    if not isinstance(org, dict):
        return {"name": clean_ws(org) if isinstance(org, str) else None, "urls": []}
    same = org.get("sameAs")
    candidates = [org.get("url"), *(same if isinstance(same, list) else [same])]
    return {"name": clean_ws(org.get("name")) or None, "urls": [u for u in candidates if isinstance(u, str) and u]}


def _org_matches(hiring: str | None, legal_name: str, site_title: str) -> bool:
    if not hiring:
        return True
    tokens = distinctive_tokens(legal_name)
    hay = hiring.casefold()
    if tokens and all(t in hay for t in tokens):
        return True
    brand = (site_title or "").split("|")[0].split("–")[0].split("-")[0].strip().casefold()
    return bool(brand) and len(brand) >= 3 and (brand in hay or hay in brand)


def _valid_until(value: object) -> datetime | None:
    """End of the posting's validity. A date-only ``validThrough`` is inclusive: the posting is open during that whole day."""
    text = str(value or "").strip()
    dt = parse_iso(text)
    return dt + timedelta(days=1) if dt and len(text) <= 10 else dt


def posting_state(valid_through: object, posted: object, updated: object, now: datetime, max_age_days: int) -> str:
    """current | stale. Stale = past its end date, or (no end date) neither posted nor updated within ``max_age_days``."""
    end = _valid_until(valid_through)
    if end is not None:
        return "stale" if end < now else "current"
    last = max([d for d in (parse_iso(str(posted or "")), parse_iso(str(updated or ""))) if d], default=None)
    if last is not None and (now - last).days > max_age_days:
        return "stale"
    return "current"


def closed_notice(doc: PageDoc) -> str | None:
    """Wording on the page that says the position is closed ("søknadsfristen er utløpt", "no longer accepting applications", …)."""
    m = CLOSED_MARKERS.search(doc.text or "")
    return find_span(doc.text, m.group(0), radius=40) if m else None


def jobs_from_jsonld(doc: PageDoc, legal_name: str, site_title: str, *, now: datetime | None = None, max_age_days: int = 180) -> list[JobItem]:
    out: list[JobItem] = []
    now = now or datetime.now(UTC)
    for job in jsonld_of_type(doc, "JobPosting"):
        title = clean_ws(str(job.get("title") or job.get("name") or ""))
        if not title or not _org_matches(_hiring_org(job), legal_name, site_title):
            continue
        url = str(job.get("url") or doc.final_url)
        valid = job.get("validThrough")
        posted, updated = date_only(str(job.get("datePosted") or "")), date_only(str(job.get("dateModified") or ""))
        state = posting_state(valid, posted, updated, now, max_age_days)
        out.append(JobItem(
            id=stable_id(canonical_url(url), title, length=12), title=title[:200], url=url, source_url=doc.final_url, source_host=host_of(doc.final_url),
            location=_location(job), department=clean_ws(str(job.get("occupationalCategory") or job.get("industry") or "")) or None,
            employment_type=clean_ws(str(job.get("employmentType") or "")) or None, posted_at=posted,
            valid_through=date_only(str(valid)) if valid else None, state=state, evidence_span=f'JobPosting "{title}"' + (f" · datePosted {job.get('datePosted')}" if job.get("datePosted") else ""),
            method="json_ld", retrieved_at=doc.retrieved_at, content_sha256=doc.content_sha256,
            details={"updated_at": updated, "employer": _hiring_org(job)}, raw={"hiring_org": hiring_org_info(job)},
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


def is_nav_host(url: str) -> bool:
    return registrable_domain(host_of(url)) == "nav.no"


# ------------------------------------------------------------------ merging --
STATE_RANK = {"current": 0, "stale": 1, "closed": 2}
SOURCE_RANK = {"company": 0, "nav": 1, "discovered": 2}
METHOD_RANK = {"json_ld": 0, "nav_feed": 0, "ats_link": 1, "careers_page_link": 2}


def title_key(title: str) -> str:
    """Comparable job title: no case, punctuation or bracketed extras such as "(m/k)" or "(100 %)"."""
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", title or "")
    return " ".join(re.sub(r"[^\w]+", " ", text.casefold()).split())


def _place(job: JobItem) -> set[str]:
    return {part.strip().casefold() for part in re.split(r"[,/;]", job.location or "") if part.strip()}


def _own_urls(job: JobItem) -> set[str]:
    """Addresses that identify this very listing (a JSON-LD posting without its own URL has only the page it was found on: not an identity)."""
    return {canonical_url(job.url)} if canonical_url(job.url) != canonical_url(job.source_url) else set()


def _refs(job: JobItem) -> set[str]:
    """Where a NAV ad says the original posting / application form is. Several ads may share one (a general application page), so a reference
    only ever matches another listing's own address, never another reference."""
    return {canonical_url(u) for u in (job.details.get("application_url"), job.details.get("original_source_url")) if isinstance(u, str) and u.startswith("http")}


def _dates_conflict(a: JobItem, b: JobItem) -> bool:
    pa, pb = parse_iso(a.posted_at or ""), parse_iso(b.posted_at or "")
    return bool(pa and pb and abs((pa - pb).days) > 45)


def same_opening(a: JobItem, b: JobItem) -> bool:
    if _own_urls(a) & (_own_urls(b) | _refs(b)) or _own_urls(b) & _refs(a):
        return True
    if title_key(a.title) != title_key(b.title) or not title_key(a.title):
        return False
    pa, pb = _place(a), _place(b)
    return (not pa or not pb or bool(pa & pb)) and not _dates_conflict(a, b)


def _priority(job: JobItem) -> tuple[int, int, int]:
    richer = -sum(1 for v in (job.posted_at, job.valid_through, job.location, job.details.get("updated_at")) if v)
    return SOURCE_RANK.get(job.source, 3), METHOD_RANK.get(job.method, 3), richer


def _listing(job: JobItem) -> dict[str, Any]:
    return {"id": job.id, "source": job.source, "url": job.url, "source_host": job.source_host, "state": job.state, "posted_at": job.posted_at,
            "valid_through": job.valid_through, "updated_at": job.details.get("updated_at"), "retrieved_at": job.retrieved_at, "method": job.method,
            "nav_uuid": job.details.get("nav_uuid")}


def dedupe_jobs(jobs: list[JobItem]) -> list[JobItem]:
    """One entry per opening. The best-described listing (company page before NAV before search; structured data before bare links) is kept;
    the others are recorded in ``details["merged"]`` with their own URL, dates and status, and fill dates the kept one lacks.
    If listings disagree, the most cautious status wins (closed > stale > current): an opening is "current" only if nobody says otherwise."""
    kept: list[JobItem] = []
    for job in sorted(jobs, key=_priority):
        home = next((k for k in kept if same_opening(k, job)), None)
        if home is None:
            job.details = {**job.details, "merged": list(job.details.get("merged") or [])}
            kept.append(job)
            continue
        home.details.setdefault("merged", []).append(_listing(job))
        for attr in ("posted_at", "valid_through", "location", "department", "employment_type"):
            if not getattr(home, attr) and getattr(job, attr):
                setattr(home, attr, getattr(job, attr))
        if not home.details.get("updated_at") and job.details.get("updated_at"):
            home.details["updated_at"] = job.details["updated_at"]
        if STATE_RANK.get(job.state, 0) > STATE_RANK.get(home.state, 0):
            home.details["state_conflict"] = f"{job.source} listing says {job.state}"
            home.state = job.state
    return kept


# --------------------------------------------------------------- collection --
@dataclass
class CompanyJobs:
    modules: list[ModuleResult]
    jobs: list[JobItem]
    note: str
    careers_found: bool = False  # a careers page was fetched and read
    failures: list[dict[str, str]] = field(default_factory=list)  # company-owned job sources that could not be read: {kind, name, classification, url}
    incomplete: list[str] = field(default_factory=list)  # reasons a company source was not fully read (budget, page limit)


_BLOCKING = {"timeout", "network", "server_error", "rate_limited", "blocked", "robots_disallowed", "client_error", "too_large", "invalid_content", "unsafe_url"}


async def collect_jobs(ctx: ConnectorContext, crawl: SiteCrawl, legal_name: str, *, max_ats_pages: int = 1, max_detail_pages: int = 3) -> CompanyJobs:
    """Company-owned job sources on the verified site. Only runs on a verified site."""
    modules: list[ModuleResult] = []
    found: list[JobItem] = []
    out = CompanyJobs(modules, [], "")
    site_title = crawl.homepage.title if crawl.homepage else ""
    max_age = ctx.settings.job_max_age_days
    now = datetime.now(UTC)

    # A careers page the homepage links to but that was never fetched (page limit): fetch it, it is the primary source.
    if not any(p.kind == "careers" for p in crawl.pages) and crawl.homepage is not None:
        links = site_links(crawl.homepage, crawl.domain).get("careers", [])
        if links:
            res, doc = await fetch_page(ctx, links[0].url, optional=True)
            crawl.pages.append(FetchedPage("careers", res, doc))
            crawl.requests += 0 if res.from_cache else 1
    careers_docs = crawl.docs("careers")
    for page in crawl.pages:
        if page.kind == "careers" and page.doc is None:
            if page.result.classification == "budget_exhausted":
                out.incomplete.append("the request budget ran out before the careers page was read")
            elif page.result.classification in _BLOCKING:
                out.failures.append({"kind": "careers", "name": "Company careers page", "classification": page.result.classification, "url": page.result.url})
    out.careers_found = bool(careers_docs)

    for doc in crawl.docs():
        found += jobs_from_jsonld(doc, legal_name, site_title, now=now, max_age_days=max_age)
    for doc in careers_docs:
        for link in job_links(doc):
            if registrable_domain(host_of(link.url)) != crawl.domain and not any(a.url == link.url for a in crawl.ats_links):
                continue
            if is_nav_host(link.url):
                continue
            found.append(JobItem(id=stable_id(canonical_url(link.url), link.text, length=12), title=clean_ws(link.text)[:200], url=link.url, source_url=doc.final_url,
                                 source_host=host_of(doc.final_url), evidence_span=f'Careers page link "{clean_ws(link.text)}"', method="careers_page_link",
                                 retrieved_at=doc.retrieved_at, content_sha256=doc.content_sha256))

    ats_pages = 0
    known_urls = {canonical_url(j.url) for j in found}
    for link in crawl.ats_links:
        if is_nav_host(link.url):
            continue  # NAV ads are read through NAV's official feed only
        if ats_pages >= max_ats_pages:
            break
        res, doc = await fetch_page(ctx, link.url, connector="company_ats", optional=True)
        ats_pages += 1
        mod = module_from_fetch("jobs_ats", source_id="ats", source_name=f"Company job board ({host_of(link.url)})", source_class="company_linked_job_board", result=res,
                                value={"url": link.url})
        modules.append(mod)
        if doc is None:
            if res.classification == "budget_exhausted":
                out.incomplete.append(f"the request budget ran out before the job board {host_of(link.url)} was read")
            elif res.classification in _BLOCKING:
                out.failures.append({"kind": "job_board", "name": f"Company job board ({host_of(link.url)})", "classification": res.classification, "url": link.url})
            continue
        out.careers_found = True
        found += jobs_from_jsonld(doc, legal_name, site_title, now=now, max_age_days=max_age)
        details = 0
        for jl in job_links(doc):
            if host_of(jl.url) != host_of(doc.final_url):
                continue
            item = JobItem(id=stable_id(canonical_url(jl.url), jl.text, length=12), title=clean_ws(jl.text)[:200], url=jl.url, source_url=doc.final_url,
                           source_host=host_of(doc.final_url), evidence_span=f'Job board link "{clean_ws(jl.text)}"', method="ats_link",
                           retrieved_at=doc.retrieved_at, content_sha256=doc.content_sha256)
            if canonical_url(jl.url) in known_urls or details >= max_detail_pages:
                found.append(item)
                continue
            dres, ddoc = await fetch_page(ctx, jl.url, connector="company_ats", optional=True)
            details += 1
            known_urls.add(canonical_url(jl.url))
            if ddoc is None:
                if dres.classification in ("not_found", "gone"):
                    continue  # the listing no longer exists at the job board: not an opening
                found.append(item)
                continue
            detail_items = jobs_from_jsonld(ddoc, legal_name, site_title, now=now, max_age_days=max_age)
            notice = closed_notice(ddoc)
            for d in detail_items or [item]:
                if notice:
                    d.state, d.details["closed_notice"] = "closed", notice
            found += detail_items or [item]

    items = dedupe_jobs(found)[: ctx.settings.max_jobs_per_company]
    if items:
        note = f"{sum(1 for j in items if j.state == 'current')} current posting(s) found on company-owned pages"
    elif out.failures:
        note = "; ".join(f"{f['name']} could not be read ({f['classification'].replace('_', ' ')})" for f in out.failures) + "."
    elif careers_docs or crawl.ats_links:
        note = "A careers page was checked; no individual postings could be read from it."
    else:
        note = "No careers page or job board was found on the verified website."
    out.jobs, out.note = items, note
    return out
