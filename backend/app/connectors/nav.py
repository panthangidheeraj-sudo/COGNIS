"""NAV Arbeidsplassen job ads (pam-stilling-feed): free, official, Norway-wide.

How it works
------------
* The feed is a continuous log of every ad (no search on NAV's side). COGNIS keeps a small local index of the feed
  *summaries* — uuid, status, title, business name, municipality, last change — synced incrementally (ETag /
  If-Modified-Since) over a six-month window (an ad can be active for at most six months). Feed pages are never
  cached raw and contact persons are never stored.
* Research: candidates are indexed ACTIVE ads whose business name carries the company's distinctive name tokens
  (or a registered establishment's name). For each candidate (bounded per company) the full ad is re-read from NAV:
  its *current* status, the employer's organisation number, dates and links. The ad is published only when the
  employer resolves to the exact company (``identity.employer.resolve_employer``: organisation number, registered
  establishment, register parent, or exact name confirmed by the verified website / a registered address).
  Everything else stays an internal, unverified candidate with its reason.
* NAV's terms (arbeidsplassen.nav.no/vilkar-api): inactive or deleted ads are never published and are masked in the
  index (so previously published ads disappear from profiles), ads are re-read before publication, and links point to
  the ad on arbeidsplassen.nav.no and to the employer's own application page.
* No NAV match is never evidence that a company is not hiring.

Authentication: ``NAV_FEED_TOKEN`` (a free private token NAV issues on request) or, by default, the public token NAV
publishes for the feed (it rotates; it is fetched at runtime, kept in memory only and redacted from all output).
"""
from __future__ import annotations

import re
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

from ..config import Settings
from ..core.util import clean_ws, date_only, now_iso, parse_iso, truncate
from ..evidence.models import ModuleResult, Observation
from ..identity.employer import EmployerResolution, WorkAddress, resolve_employer
from ..identity.model import CanonicalIdentity
from ..identity.normalization import distinctive_tokens, normalize_name
from ..net.http import FetchResult, HttpClient
from ..runtime.budgets import CompanyBudget, RunBudget
from ..security.redaction import register_secret
from ..storage.db import Database
from . import brreg
from .base import ConnectorContext, not_run
from .jobs import JobItem

SOURCE_ID = "nav"
SOURCE_NAME = "NAV Arbeidsplassen"
SOURCE_CLASS = "official_job_feed"
MODULE = "nav_jobs"
FEED_PATH = "/api/v1/feed"
TOKEN_PATH = "/api/publicToken"
AD_PAGE = "https://arbeidsplassen.nav.no/stillinger/stilling/{uuid}"
FEED_MAX_BYTES = 12_000_000
INDEX_MAX_AGE_HOURS = 48  # an index older than this may miss recent ads
UNREACHABLE = {"timeout", "network", "server_error", "rate_limited", "blocked", "client_error", "unsafe_url", "too_large"}
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


# ----------------------------------------------------------------- parsing --
@dataclass
class FeedItem:
    uuid: str
    status: str  # ACTIVE | INACTIVE
    title: str | None
    business_name: str | None
    municipal: str | None
    modified: str | None
    entry_url: str | None


@dataclass
class NavAd:
    uuid: str
    status: str
    title: str
    employer_name: str | None = None
    employer_orgnr: str | None = None
    employer_homepage: str | None = None
    business_name: str | None = None
    published: str | None = None
    updated: str | None = None
    expires: str | None = None
    modified: str | None = None
    link: str | None = None
    source_url: str | None = None
    application_url: str | None = None
    application_due: str | None = None
    work_locations: list[dict[str, Any]] = field(default_factory=list)
    occupation: str | None = None
    engagement_type: str | None = None
    extent: str | None = None
    position_count: int | None = None
    sector: str | None = None

    def addresses(self) -> list[WorkAddress]:
        return [WorkAddress(street=w.get("address"), postal_code=w.get("postalCode"), municipality=w.get("municipal") or w.get("city")) for w in self.work_locations]

    def location(self) -> str | None:
        names = [clean_ws(w.get("city") or w.get("municipal") or "") for w in self.work_locations]
        names = [n.title() if n.isupper() else n for n in names if n]
        return ", ".join(dict.fromkeys(names)) or None

    def page_url(self) -> str:
        link = clean_ws(self.link or "")
        return link if link.startswith("https://arbeidsplassen.nav.no/") else AD_PAGE.format(uuid=self.uuid)


def _s(value: Any) -> str | None:
    text = clean_ws(str(value)) if value not in (None, "") else ""
    return text or None


def parse_feed_page(body: Any) -> tuple[list[FeedItem], str | None]:
    """Feed page → (items, relative next_url). Tolerates missing fields; skips items without a uuid."""
    if not isinstance(body, dict):
        return [], None
    items: list[FeedItem] = []
    for item in body.get("items") or []:
        if not isinstance(item, dict):
            continue
        entry = item.get("_feed_entry") or {}
        uuid = _s(entry.get("uuid") or entry.get("id") or item.get("id"))
        if not uuid:
            continue
        items.append(FeedItem(uuid=uuid, status=(_s(entry.get("status")) or "ACTIVE").upper(), title=_s(entry.get("title") or item.get("title")),
                              business_name=_s(entry.get("businessName")), municipal=_s(entry.get("municipal")),
                              modified=_s(entry.get("sistEndret") or item.get("date_modified")), entry_url=_s(item.get("url"))))
    return items, _s(body.get("next_url"))


def parse_entry(body: Any) -> NavAd | None:
    """Full feed entry → ``NavAd``. Contact persons are deliberately not read (personal data; NAV's terms)."""
    if not isinstance(body, dict):
        return None
    ad = body.get("json") if isinstance(body.get("json"), dict) else (body.get("ad_content") if isinstance(body.get("ad_content"), dict) else body)
    uuid = _s(body.get("uuid") or ad.get("uuid") or body.get("id"))
    if not uuid:
        return None
    employer = ad.get("employer") if isinstance(ad.get("employer"), dict) else {}
    occupation = None
    for oc in ad.get("occupationCategories") or []:
        if isinstance(oc, dict) and (oc.get("level2") or oc.get("level1")):
            occupation = _s(oc.get("level2") or oc.get("level1"))
            break
    try:
        positions = int(ad.get("positioncount")) if ad.get("positioncount") not in (None, "") else None
    except (TypeError, ValueError):
        positions = None
    return NavAd(
        uuid=uuid, status=(_s(body.get("status") or ad.get("status")) or "ACTIVE").upper(), title=_s(ad.get("title")) or "",
        employer_name=_s(employer.get("name")), employer_orgnr=_s(employer.get("orgnr")), employer_homepage=_s(employer.get("homepage")),
        business_name=_s(ad.get("businessName") or body.get("businessName")), published=_s(ad.get("published")), updated=_s(ad.get("updated")),
        expires=_s(ad.get("expires")), modified=_s(body.get("sistEndret") or ad.get("sistEndret")), link=_s(ad.get("link")), source_url=_s(ad.get("sourceurl")),
        application_url=_s(ad.get("applicationUrl")), application_due=_s(ad.get("applicationDue")),
        work_locations=[w for w in (ad.get("workLocations") or []) if isinstance(w, dict)], occupation=occupation,
        engagement_type=_s(ad.get("engagementtype")), extent=_s(ad.get("extent")), position_count=positions, sector=_s(ad.get("sector")),
    )


def is_current(ad: NavAd, now: datetime | None = None) -> bool:
    """ACTIVE and not past its expiry date."""
    if ad.status != "ACTIVE":
        return False
    exp = parse_iso(ad.expires) if ad.expires else None
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=UTC)
    return exp is None or exp >= (now or datetime.now(UTC)) - timedelta(days=1)


# ------------------------------------------------------------------- index --
class NavIndex:
    """Local index of NAV feed summaries (SQLite)."""

    def __init__(self, db: Database):
        self.db = db

    def state(self) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM nav_feed_state WHERE id = 1")
        return dict(row) if row else {}

    def save_state(self, **values: Any) -> None:
        if not self.db.one("SELECT 1 FROM nav_feed_state WHERE id = 1"):
            self.db.execute("INSERT INTO nav_feed_state(id) VALUES (1)")
        cols = ", ".join(f"{k} = ?" for k in values)
        self.db.execute(f"UPDATE nav_feed_state SET {cols} WHERE id = 1", list(values.values()))

    def apply(self, items: list[FeedItem]) -> tuple[int, int]:
        """Upsert ACTIVE summaries; mask INACTIVE ones (kept only by uuid so previously published ads can be hidden)."""
        active = inactive = 0
        seen = now_iso()
        with self.db.transaction() as conn:
            for it in items:
                if it.status == "ACTIVE":
                    active += 1
                    conn.execute(
                        "INSERT INTO nav_ads(uuid, status, title, business_name, name_norm, municipal, entry_url, modified_at, seen_at) VALUES (?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(uuid) DO UPDATE SET status=excluded.status, title=excluded.title, business_name=excluded.business_name, "
                        "name_norm=excluded.name_norm, municipal=excluded.municipal, entry_url=excluded.entry_url, modified_at=excluded.modified_at, seen_at=excluded.seen_at",
                        (it.uuid, "ACTIVE", it.title, it.business_name, normalize_name(it.business_name), it.municipal, it.entry_url, it.modified, seen))
                else:
                    inactive += 1
                    self._mask(conn, it.uuid, it.modified, seen)
        return active, inactive

    @staticmethod
    def _mask(conn: Any, uuid: str, modified: str | None, seen: str) -> None:
        conn.execute(
            "INSERT INTO nav_ads(uuid, status, modified_at, seen_at) VALUES (?, 'INACTIVE', ?, ?) "
            "ON CONFLICT(uuid) DO UPDATE SET status='INACTIVE', title=NULL, business_name=NULL, name_norm=NULL, municipal=NULL, "
            "modified_at=COALESCE(excluded.modified_at, nav_ads.modified_at), seen_at=excluded.seen_at", (uuid, modified, seen))

    def mark_inactive(self, uuid: str) -> None:
        with self.db.transaction() as conn:
            self._mask(conn, uuid, None, now_iso())

    def purge(self, before_iso: str) -> int:
        cur = self.db.execute("DELETE FROM nav_ads WHERE modified_at IS NOT NULL AND modified_at < ?", (before_iso,))
        return cur.rowcount or 0

    def counts(self) -> dict[str, int]:
        rows = self.db.all("SELECT status, COUNT(*) AS n FROM nav_ads GROUP BY status")
        return {r["status"]: int(r["n"]) for r in rows}

    def inactive(self, uuids: list[str]) -> set[str]:
        if not uuids:
            return set()
        marks = ",".join("?" * len(uuids))
        return {r["uuid"] for r in self.db.all(f"SELECT uuid FROM nav_ads WHERE status = 'INACTIVE' AND uuid IN ({marks})", uuids)}

    def candidates(self, names: list[str | None], limit: int) -> list[dict[str, Any]]:
        """ACTIVE ads whose business name contains all distinctive tokens of one of ``names`` (candidates only)."""
        token_sets = [(normalize_name(n), distinctive_tokens(n)) for n in names if n]
        token_sets = [(norm, toks) for norm, toks in token_sets if norm]
        if not token_sets:
            return []
        out: dict[str, dict[str, Any]] = {}
        for norm, toks in token_sets:
            probe = max(toks, key=len) if toks else norm
            rows = self.db.all("SELECT * FROM nav_ads WHERE status = 'ACTIVE' AND name_norm LIKE ? ORDER BY modified_at DESC LIMIT 400", (f"%{probe}%",))
            for r in rows:
                have = set((r["name_norm"] or "").split())
                if (r["name_norm"] or "") == norm or (toks and set(toks) <= have):
                    out.setdefault(r["uuid"], dict(r))
        exact = {norm for norm, _ in token_sets}
        # exact name matches first (most likely the company itself), then the most recently changed
        ranked = sorted(out.values(), key=lambda r: r.get("modified_at") or "", reverse=True)
        ranked.sort(key=lambda r: (r.get("name_norm") or "") not in exact)
        return ranked[:limit]


# ------------------------------------------------------------------- token --
class _Token:
    """NAV_FEED_TOKEN, or NAV's public feed token (fetched at runtime, memory only, redacted everywhere)."""

    def __init__(self) -> None:
        self.public: str | None = None
        self.fetched_at = 0.0
        self.failure: str | None = None  # why the last attempt to get the public token failed (timeout, network, …)

    async def get(self, http: HttpClient, settings: Settings, *, refresh: bool = False) -> tuple[str | None, str]:
        if settings.nav_feed_token:
            register_secret(settings.nav_feed_token)
            return settings.nav_feed_token, "private"
        if not settings.nav_use_public_token:
            return None, "none"
        if self.public and not refresh and time.monotonic() - self.fetched_at < 6 * 3600:
            return self.public, "public"
        res = await http.fetch(settings.nav_feed_base.rstrip("/") + TOKEN_PATH, connector="nav_feed", use_cache=False, accept="text/plain, */*", optional=True,
                               interval_key="nav")
        match = _JWT.search(res.text()) if res.ok else None
        if match:
            self.public, self.fetched_at, self.failure = match.group(0), time.monotonic(), None
            register_secret(self.public)
            return self.public, "public"
        self.failure = res.classification if not res.ok else "invalid_content"
        return None, "public"


TOKEN = _Token()


async def _get(http: HttpClient, settings: Settings, url: str, *, budget: CompanyBudget | RunBudget | None, headers: dict[str, str] | None = None,
               run_id: str | None = None, org: str | None = None) -> FetchResult:
    """Authenticated GET (re-fetches the public token once when NAV rotated it)."""
    for attempt in (0, 1):
        token, _kind = await TOKEN.get(http, settings, refresh=attempt == 1)
        if not token:  # a token endpoint that timed out is "unreachable", not "refused"
            return FetchResult(url, url, 0, TOKEN.failure or "blocked", error="no NAV feed token", retrieved_at=now_iso())
        res = await http.fetch(url, connector="nav_feed", budget=budget, optional=True, headers={"Authorization": f"Bearer {token}", **(headers or {})},
                               accept="application/json", use_cache=False, max_bytes=FEED_MAX_BYTES, interval_key="nav", run_id=run_id, org_number=org)
        if res.status != 401 or settings.nav_feed_token:
            return res
    return res


# -------------------------------------------------------------------- sync --
async def sync_feed(http: HttpClient, db: Database, settings: Settings, *, budget: CompanyBudget | RunBudget | None = None, max_pages: int | None = None,
                    max_seconds: float | None = None) -> dict[str, Any]:
    """Bring the local index up to date (bounded). Safe to call repeatedly; resumes where the last call stopped."""
    if not settings.enable_nav_jobs:
        return {"status": "disabled"}
    index = NavIndex(db)
    st = index.state()
    base = settings.nav_feed_base.rstrip("/")
    window_start = datetime.now(UTC) - timedelta(days=settings.nav_index_window_days)
    url = st.get("page_url") or base + FEED_PATH
    conditional: dict[str, str] = {}
    if not st.get("page_url"):
        conditional["If-Modified-Since"] = format_datetime(window_start, usegmt=True)
        index.save_state(window_start=window_start.isoformat(timespec="seconds"), started_at=now_iso(), caught_up=0, pages_total=0)
    elif st.get("caught_up"):
        if st.get("etag"):
            conditional["If-None-Match"] = st["etag"]
        if st.get("last_modified"):
            conditional["If-Modified-Since"] = st["last_modified"]
    pages = active = inactive = 0
    t0 = time.monotonic()
    limit_pages = max_pages if max_pages is not None else settings.nav_sync_max_pages
    limit_seconds = max_seconds if max_seconds is not None else settings.nav_sync_max_seconds
    status, error = "partial", None
    newest = st.get("newest_modified")
    while pages < limit_pages and time.monotonic() - t0 < limit_seconds:
        res = await _get(http, settings, url, budget=budget, headers=conditional)
        if res.status == 304:
            status = "up_to_date"
            break
        if not res.ok:
            status, error = "failed", f"{res.classification}{f' (HTTP {res.status})' if res.status else ''}"
            break
        try:
            body = res.json()
        except ValueError:
            status, error = "failed", "malformed feed page"
            break
        items, next_url = parse_feed_page(body)
        if pages == 0 and "If-Modified-Since" in conditional and not st.get("page_url") and items:
            floor = (window_start - timedelta(days=31)).isoformat(timespec="seconds")
            if all((it.modified or "9999") < floor for it in items):
                # the feed should start at the requested time; say so if it did not (the index still converges, more slowly)
                error = "the feed started before the requested six-month window (If-Modified-Since not applied)"
        a, i = index.apply(items)
        active, inactive, pages = active + a, inactive + i, pages + 1
        newest = max([newest or "", *[it.modified or "" for it in items]]) or newest
        if next_url:
            url = urllib.parse.urljoin(base + "/", next_url)
            conditional = {}
            index.save_state(page_url=url, caught_up=0, pages_total=(st.get("pages_total") or 0) + pages, newest_modified=newest, last_error=None)
            continue
        # end of the feed: remember this page and its validators, poll it next time
        index.save_state(page_url=url, caught_up=1, etag=res.headers.get("etag"), last_modified=res.headers.get("last-modified"), synced_at=now_iso(),
                         pages_total=(st.get("pages_total") or 0) + pages, newest_modified=newest, last_error=None)
        status = "up_to_date"
        break
    if status == "up_to_date":
        index.save_state(synced_at=now_iso(), caught_up=1, last_error=error)
    elif error:
        index.save_state(last_error=error)
    purged = index.purge(window_start.isoformat(timespec="seconds"))
    return {"status": status, "pages": pages, "active_upserts": active, "inactive_masked": inactive, "purged": purged, "error": error,
            "seconds": round(time.monotonic() - t0, 1), "index": index.counts(), "newest_modified": newest}


def index_health(db: Database | None, settings: Settings) -> dict[str, Any]:
    """For /status: is the NAV connector working (index synced recently, no standing error)?"""
    if not settings.enable_nav_jobs:
        return {"status": "unavailable", "note": "Disabled (ENABLE_NAV_JOBS=false)."}
    if not settings.nav_feed_token and not settings.nav_use_public_token:
        return {"status": "unavailable", "note": "No NAV token: set NAV_FEED_TOKEN or NAV_USE_PUBLIC_TOKEN=true."}
    if db is None:
        return {"status": "degraded", "note": "Job-ad index not available."}
    st = NavIndex(db).state()
    counts = NavIndex(db).counts()
    synced = parse_iso(st.get("synced_at")) if st.get("synced_at") else None
    if st.get("last_error") and not synced:
        return {"status": "degraded", "note": f"Job-ad feed sync failing: {st['last_error']}."}
    if not synced:
        return {"status": "degraded", "note": "Job-ad index is still being built (first sync)." if st else "Job-ad index not synced yet."}
    age_h = (datetime.now(UTC) - synced).total_seconds() / 3600
    note = f"{counts.get('ACTIVE', 0):,} active ads indexed; synced {synced.strftime('%Y-%m-%d %H:%M')} UTC. Ads are shown only when the employer resolves to the exact organisation."
    if st.get("last_error") or age_h > 24:
        return {"status": "degraded", "note": f"Index last synced {age_h:.0f} h ago" + (f"; last error: {st['last_error']}" if st.get("last_error") else "") + "."}
    return {"status": "available", "note": note}


# ---------------------------------------------------------------- research --
@dataclass
class NavResult:
    module: ModuleResult
    jobs: list[JobItem] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)  # unverified, never published


def _can_optional(budget: CompanyBudget | RunBudget | None) -> bool:
    if isinstance(budget, CompanyBudget):
        return budget.can_optional()
    if isinstance(budget, RunBudget):
        return budget.time_for_optional() and budget.can_spend(optional=True)
    return True


def _module(state: str, note: str, *, value: Any = None, url: str | None = None, retrieved_at: str | None = None, requests: int = 0) -> ModuleResult:
    return ModuleResult(module=MODULE, source_id=SOURCE_ID, source_name=SOURCE_NAME, source_class=SOURCE_CLASS, state=state, url=url, retrieved_at=retrieved_at,  # type: ignore[arg-type]
                        note=note, value=value, requests=requests, tier="A")


def _search_names(identity: CanonicalIdentity, establishments: list[dict[str, Any]]) -> list[str]:
    names = [identity.legal_name, *[f.get("name") for f in identity.former_names if isinstance(f, dict)], *[e.get("name") for e in establishments if not e.get("deleted")]]
    return [n for n in dict.fromkeys(n for n in names if n)]


def ad_observation(ad: NavAd, res: FetchResult, resolution: EmployerResolution, item_id: str) -> Observation:
    org_txt = f" (org. no. {resolution.record_org_number})" if resolution.record_org_number else ""
    employer = ad.employer_name or ad.business_name or "employer"
    span = (f'NAV Arbeidsplassen ad {ad.uuid}: "{truncate(ad.title, 160)}" — employer {employer}{org_txt}'
            + (f"; published {date_only(ad.published)}" if ad.published else "") + (f"; expires {date_only(ad.expires)}" if ad.expires else ""))
    return Observation(
        field="job_posting", value=ad.title, key_suffix=item_id, module=MODULE, source_id=SOURCE_ID, source_name=SOURCE_NAME, source_class=SOURCE_CLASS,
        source_url=ad.page_url(), retrieved_at=res.retrieved_at, content_sha256=res.content_sha256, claim_span=span, extraction_method="nav_feed_entry",
        tier="A", label="Job posting", current=True, as_of=date_only(ad.published), effective_from=date_only(ad.published), effective_to=date_only(ad.expires),
        identity_score=resolution.score, identity_signals=list(resolution.signals),
        attributes={"source": "nav", "nav_uuid": ad.uuid, "identity_basis": resolution.basis, "employer_org_number": resolution.record_org_number,
                    "location": ad.location(), "department": ad.occupation, "employment_type": ad.engagement_type, "extent": ad.extent,
                    "positions": ad.position_count, "state": "current", "url": ad.page_url(), "application_url": ad.application_url,
                    "original_source_url": ad.source_url, "posted_at": date_only(ad.published), "updated_at": ad.updated, "valid_through": date_only(ad.expires)},
    )


async def nav_jobs(ctx: ConnectorContext, identity: CanonicalIdentity, establishments: list[dict[str, Any]], verified_domain: str | None,
                   index: NavIndex | None, *, now: datetime | None = None) -> NavResult:
    s = ctx.settings
    if not s.enable_nav_jobs:
        return NavResult(not_run(MODULE, source_id=SOURCE_ID, source_name=SOURCE_NAME, source_class=SOURCE_CLASS, state="not_applicable", note="NAV job ads disabled by configuration."))
    if index is None:
        return NavResult(not_run(MODULE, source_id=SOURCE_ID, source_name=SOURCE_NAME, source_class=SOURCE_CLASS, state="not_applicable",
                                 note="The NAV job-ad index is not available in this context."))
    st = index.state()
    if not st.get("pages_total") and not index.counts():
        return NavResult(_module("not_available", "The NAV job-ad index has not been synced yet, so NAV ads could not be checked (this says nothing about hiring).",
                                 url=s.nav_feed_base))
    synced = parse_iso(st.get("synced_at")) if st.get("synced_at") else None
    fresh = bool(st.get("caught_up")) and synced is not None and (datetime.now(UTC) - synced) < timedelta(hours=INDEX_MAX_AGE_HOURS)
    coverage = {"index_synced_at": st.get("synced_at"), "index_caught_up": bool(st.get("caught_up")), "index_fresh": fresh, "index_window_start": st.get("window_start")}
    candidates = index.candidates(_search_names(identity, establishments), limit=s.nav_max_candidates_per_company)
    result = NavResult(_module("available", "", url=s.nav_feed_base, retrieved_at=now_iso()))
    if not candidates:
        result.module.note = ("No active NAV ad in the index names this organisation. NAV covers only ads registered with NAV, so this is not evidence that the "
                              "company is not hiring.") + ("" if st.get("caught_up") else " The index is still catching up with the feed.")
        result.module.value = {"verified": 0, "unverified": 0, **coverage}
        return result

    parents: dict[str, str | None] = {}

    async def parent_of(org: str) -> str | None:
        if org not in parents:
            parents[org] = await brreg.subunit_parent(ctx, org)
        return parents[org]

    budget = ctx.budget
    base = s.nav_feed_base.rstrip("/")
    read = streak = 0  # ads read successfully · consecutive unreachable responses
    failures: dict[str, int] = {}
    halted: str | None = None  # set once NAV looks unreachable: the remaining candidates are not requested (no point waiting for each to time out)
    for cand in candidates:
        if halted:
            result.candidates.append({"uuid": cand["uuid"], "business_name": cand.get("business_name"), "status": "not_checked", "reason": f"NAV stopped responding ({halted})"})
            continue
        if not _can_optional(budget):
            result.candidates.append({"uuid": cand["uuid"], "business_name": cand.get("business_name"), "status": "not_checked", "reason": "budget"})
            continue
        entry_url = urllib.parse.urljoin(base + "/", cand.get("entry_url") or f"api/v1/feedentry/{cand['uuid']}")
        res = await _get(ctx.http, s, entry_url, budget=budget, run_id=ctx.run_id, org=ctx.org_number)
        result.module.requests += 0 if res.from_cache else 1
        if res.classification in ("not_found", "gone"):
            index.mark_inactive(cand["uuid"])  # deleted at NAV: remove
            streak = 0
            continue
        if not res.ok:
            streak += 1
            failures[res.classification] = failures.get(res.classification, 0) + 1
            result.candidates.append({"uuid": cand["uuid"], "business_name": cand.get("business_name"), "status": "not_checked",
                                      "reason": f"the ad could not be read ({res.classification})"})
            if res.classification in UNREACHABLE and streak >= max(1, s.nav_max_consecutive_failures):
                halted = res.classification.replace("_", " ")
            continue
        streak = 0
        try:
            ad = parse_entry(res.json())
        except ValueError:
            ad = None
        if ad is None:
            failures["invalid_content"] = failures.get("invalid_content", 0) + 1
            result.candidates.append({"uuid": cand["uuid"], "business_name": cand.get("business_name"), "status": "not_checked", "reason": "the ad could not be read (malformed)"})
            continue
        read += 1
        if ad.status != "ACTIVE":
            index.mark_inactive(ad.uuid)  # inactive at NAV: never published, masked in the index
            continue
        resolution = await resolve_employer(identity, record_org_number=ad.employer_orgnr, record_name=ad.employer_name, alt_names=[ad.business_name],
                                            record_homepage=ad.employer_homepage, work_addresses=ad.addresses(), establishments=establishments,
                                            verified_domain=verified_domain, parent_of=parent_of)
        if not resolution.exact:
            result.candidates.append({"uuid": ad.uuid, "title": ad.title, "business_name": ad.business_name, "employer_name": ad.employer_name,
                                      "employer_org_number": resolution.record_org_number, "status": resolution.status, "reason": resolution.reason,
                                      "url": ad.page_url()})
            continue
        if not is_current(ad, now):
            result.candidates.append({"uuid": ad.uuid, "title": ad.title, "status": "expired", "reason": f"The ad expired on {date_only(ad.expires)}.", "url": ad.page_url()})
            continue
        item_id = f"nav-{ad.uuid}"
        obs = ad_observation(ad, res, resolution, item_id)
        result.observations.append(obs)
        result.jobs.append(JobItem(
            id=item_id, title=truncate(ad.title, 200), url=ad.page_url(), source_url=ad.page_url(), source_host="arbeidsplassen.nav.no", location=ad.location(),
            department=ad.occupation, employment_type=ad.engagement_type, posted_at=date_only(ad.published), valid_through=date_only(ad.expires), state="current",
            evidence_span=obs.claim_span, method="nav_feed", retrieved_at=res.retrieved_at, content_sha256=res.content_sha256, source="nav",
            details={"nav_uuid": ad.uuid, "employer_org_number": resolution.record_org_number, "identity_basis": resolution.basis, "updated_at": ad.updated,
                     "application_url": ad.application_url, "original_source_url": ad.source_url, "positions": ad.position_count, "extent": ad.extent}))
    verified, unverified = len(result.jobs), len([c for c in result.candidates if c["status"] != "not_checked"])
    unreadable = len([c for c in result.candidates if c["status"] == "not_checked"])
    why = ", ".join(f"{k.replace('_', ' ')}" for k in sorted(failures, key=failures.get, reverse=True)) or None  # type: ignore[arg-type]
    parts = [f"{verified} active NAV ad(s) verified to this organisation"]
    if unverified:
        reasons = sorted({c["status"].replace("_", " ") for c in result.candidates if c["status"] != "not_checked"})
        parts.append(f"{unverified} similarly named ad(s) not published ({', '.join(reasons)})")
    if unreadable:
        parts.append(f"{unreadable} candidate ad(s) could not be checked" + (f" ({why})" if why else ""))
    result.module.note = "; ".join(parts) + "." + ("" if verified else " This is not evidence that the company is not hiring.")
    result.module.value = {"verified": verified, "unverified": unverified, "unreadable": unreadable, "read": read, "failure": why, **coverage}
    if read == 0 and unreadable and failures:
        # Nothing could be read from NAV: the source was unavailable, which says nothing about hiring (never "no openings").
        blocked = set(failures) <= {"blocked", "rate_limited", "client_error"}
        result.module.state = "blocked" if blocked else "failed"
        result.module.note = (f"NAV Arbeidsplassen could not be checked ({why}); its ads were not read. This is not evidence that the company is not hiring.")
    return result


def current_titles(jobs: list[JobItem]) -> list[str]:
    return [j.title for j in jobs if j.state == "current"]
