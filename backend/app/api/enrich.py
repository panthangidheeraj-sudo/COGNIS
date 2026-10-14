"""Discover enrichment: targeted, bounded lookups for the figures a result card is missing.

This is not research (nothing is saved as a report, no company is added to the Library). For each requested organisation, and only for the figures
asked for, it consults the sources that can answer that one question:

* revenue        — the latest filed annual accounts in Regnskapsregisteret, read through the same extraction and publication gate as research
                   (the amount keeps the currency its own filing states);
* employees      — the employee count registered in Enhetsregisteret. The register is the only official source; nothing else is guessed from;
* open positions — NAV Arbeidsplassen ads whose employer resolves to this exact organisation, and the careers page of the register-listed website
                   once that website has been verified as this company's. No web search is used.

Bounds: ``enrich_max_batch`` companies per call, ``enrich_concurrency`` companies at a time across all calls, a per-company request cap and time
limit, the HTTP client's response cache and per-host rate limits, NAV's cooldown, and a result cache (shorter when a source was unreachable).

Every figure comes back with a state, so a card can say exactly what is known:

* ``verified``      the named source states it (value, period and currency where they apply, source URL, retrieval time);
* ``none_found``    (openings) the sources were checked and none showed a verified opening — never reported as "0 openings";
* ``not_reported``  the official source holds no value for this company (no filed accounts, no registered employee count) — not a zero;
* ``unavailable``   a source could not be reached or read now — nothing is concluded;
* ``not_checked``   no permitted source could be checked (e.g. no register-listed website and no NAV index);
* ``unverified``    the source has data but it could not be verified (e.g. its values disagree).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from ..agent.hiring import WHY
from ..connectors import brreg, nav
from ..connectors import jobs as jobs_conn
from ..connectors.base import ConnectorContext
from ..connectors.website import crawl_site
from ..core.util import now_iso
from ..errors import ApiError
from ..evidence.gate import publish
from ..extraction import registry_facts as rf
from ..identity.model import CanonicalIdentity, identity_from_entity
from ..identity.normalization import normalize_org_number, org_checksum_ok
from ..logging_setup import get_logger
from ..runtime.budgets import CompanyBudget

log = get_logger("enrich")

FIELDS = ("revenue", "employees", "openPositions")
STATES = ("verified", "none_found", "not_reported", "unavailable", "not_checked", "unverified")
NOT_HIRING = "This is not evidence that the company has no openings."


def _why(classification: str) -> str:
    return WHY.get(classification, classification.replace("_", " "))


def _source(name: str, state: str, url: str | None = None, retrieved_at: str | None = None, note: str | None = None) -> dict[str, Any]:
    """One source consulted for a figure: ``state`` is checked | unavailable | not_checked."""
    out: dict[str, Any] = {"name": name, "state": state}
    for key, value in (("url", url), ("retrievedAt", retrieved_at), ("note", note)):
        if value:
            out[key] = value
    return out


def _field(state: str, note: str, sources: list[dict[str, Any]], **values: Any) -> dict[str, Any]:
    assert state in STATES, state
    return {"state": state, "note": note, "sources": sources, **{k: v for k, v in values.items() if v is not None}}


class Enricher:
    def __init__(self, services: Any):
        self.s = services
        self._sem: asyncio.Semaphore | None = None
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def sem(self) -> asyncio.Semaphore:
        if self._sem is None:  # created inside the running event loop
            self._sem = asyncio.Semaphore(max(1, int(self.s.settings.enrich_concurrency)))
        return self._sem

    # ------------------------------------------------------------------ API --
    async def enrich(self, body: dict[str, Any]) -> dict[str, Any]:
        st = self.s.settings
        if not st.enable_discover_enrichment:
            return {"items": [], "enabled": False, "checkedAt": now_iso(),
                    "note": "Discover enrichment is switched off (ENABLE_DISCOVER_ENRICHMENT=false); open a company to research it."}
        orgs: list[str] = []
        for value in body.get("orgNumbers") or []:
            org = normalize_org_number(str(value))
            if len(org) == 9 and org_checksum_ok(org) and org not in orgs:
                orgs.append(org)
        if len(orgs) > st.enrich_max_batch:
            raise ApiError("invalid", f"At most {st.enrich_max_batch} companies can be looked up per request.", status=400)
        fields = [f for f in (body.get("fields") or FIELDS) if f in FIELDS] or list(FIELDS)
        items = await asyncio.gather(*(self._company(org, fields) for org in orgs))
        return {"items": items, "enabled": True, "checkedAt": now_iso()}

    # ----------------------------------------------------------- internals --
    async def _company(self, org: str, fields: list[str]) -> dict[str, Any]:
        lock = self._locks.setdefault(org, asyncio.Lock())
        async with lock:  # two requests for the same company share one lookup
            hit = self._cache.get(org)
            if hit and hit[0] > time.monotonic() and all(f in hit[1]["fields"] for f in fields):
                return {**hit[1], "fields": {f: hit[1]["fields"][f] for f in fields}, "cached": True}
            async with self.sem:
                result = await self._lookup(org, fields)
            st = self.s.settings
            failed = any(v["state"] == "unavailable" for v in result["fields"].values())
            self._cache[org] = (time.monotonic() + (st.enrich_retry_after_seconds if failed else st.enrich_cache_ttl_seconds), result)
            if len(self._cache) > 5000:
                for key in sorted(self._cache, key=lambda k: self._cache[k][0])[:1000]:
                    self._cache.pop(key, None)
                    self._locks.pop(key, None)
            return result

    def _ctx(self, org: str, max_requests: int) -> ConnectorContext:
        """A context with its own small request budget (and the shared per-company time limit): one source can never starve another."""
        st = self.s.settings
        budget = CompanyBudget(self.s.budget, max_requests=max_requests, max_seconds=st.enrich_company_timeout_seconds, max_llm_calls=0, max_searches=0)
        return ConnectorContext(org_number=org, http=self.s.http, budget=budget, run_id="discover-enrich", settings=st)

    async def _lookup(self, org: str, fields: list[str]) -> dict[str, Any]:
        ctx = self._ctx(org, 2)  # the register entity (only when no recent search row exists) and the filed accounts
        identity: CanonicalIdentity | None = None
        recent = self.s.recent_entity(org)
        if recent is not None:  # the register row the search just returned: no second register call
            retrieved_at, row = recent
            identity = identity_from_entity(org, row, source_url=brreg.BRREG_ENTITY.format(org=org), retrieved_at=retrieved_at, content_sha256=None)
        else:
            mod, identity = await brreg.fetch_entity(ctx, optional=False)
            if identity is None:
                why = mod.note or _why(mod.classification or mod.state or "failed")
                reg = _source("Enhetsregisteret", "unavailable", brreg.BRREG_ENTITY.format(org=org), note=why)
                state = "unavailable" if mod.state in ("failed", "blocked") else "not_checked"
                note = (f"The company register could not be read ({why}), so nothing could be looked up." if state == "unavailable"
                        else "The company register has no entity with this organisation number.")
                return {"orgNumber": org, "checkedAt": now_iso(), "fields": {f: _field(state, note, [reg]) for f in fields}}

        out: dict[str, Any] = {}
        if "employees" in fields:
            out["employees"] = self._employees(identity)
        tasks: dict[str, Any] = {}
        if "revenue" in fields:
            tasks["revenue"] = self._revenue(ctx, identity)
        if "openPositions" in fields:
            tasks["openPositions"] = self._openings(org, identity)
        done = await asyncio.gather(*(self._bounded(name, coro) for name, coro in tasks.items()))
        out.update(dict(zip(tasks.keys(), done, strict=True)))
        return {"orgNumber": org, "checkedAt": now_iso(), "fields": {f: out[f] for f in fields}}

    async def _bounded(self, name: str, coro: Any) -> dict[str, Any]:
        limit = self.s.settings.enrich_company_timeout_seconds
        try:
            return await asyncio.wait_for(coro, timeout=limit)
        except TimeoutError:
            return _field("unavailable", f"The lookup did not finish within {limit:.0f} s, so nothing is concluded. It is tried again on a later visit.", [])
        except Exception as exc:  # a connector bug is reported for this figure; the other figures and companies are unaffected
            log.exception("enrichment failed", extra={"field": name})
            return _field("unavailable", f"The lookup failed (internal error: {type(exc).__name__}), so nothing is concluded.", [])

    # -------------------------------------------------------------- figures --
    @staticmethod
    def _employees(identity: CanonicalIdentity) -> dict[str, Any]:
        src = _source("Enhetsregisteret", "checked", identity.source_url, identity.retrieved_at)
        if identity.employees is not None:
            as_of = identity.employees_as_of
            return _field("verified", "Employee count registered in Enhetsregisteret" + (f" (registered {as_of})." if as_of else "."), [src],
                          value=identity.employees, asOf=as_of)
        return _field("not_reported", "Enhetsregisteret holds no employee count for this company. That is not a verified zero, and no other "
                                      "source is used to estimate it.", [src])

    @staticmethod
    async def _revenue(ctx: ConnectorContext, identity: CanonicalIdentity) -> dict[str, Any]:
        mod = await brreg.fetch_financials(ctx, identity, optional=True)
        if mod.state == "available":
            src = _source("Regnskapsregisteret", "checked", mod.url, mod.retrieved_at)
            claims, _ = publish(rf.financial_observations(mod), identity.org_number)  # the same gate as research: nothing unverified passes
            revenue = [c for c in claims if c.field == "revenue" and isinstance(c.value, (int, float))]
            if not revenue:
                consolidated = any(c.field == "consolidated_revenue" for c in claims)
                return _field("not_reported", "The filed accounts are group (consolidated) accounts only; the company's own revenue is not stated."
                              if consolidated else "The latest filed annual accounts state no revenue figure.", [src])
            latest = max(revenue, key=lambda c: c.reporting_period or "")
            if latest.conflict:
                return _field("unverified", "The filed figures disagree with each other, so no revenue is shown. Open the company to review the filing.", [src])
            end = (latest.reporting_period or "").split("/")[-1]
            period = latest.period_label or (f"FY{end[:4]}" if end[:4].isdigit() else None)
            obs = latest.primary
            return _field("verified", f"Latest filed annual accounts ({period})." if period else "Latest filed annual accounts.", [src],
                          value=float(latest.value), currency=latest.currency or "", period=period, evidence=obs.claim_span if obs else None)
        if mod.state in ("not_available", "not_applicable"):
            src = _source("Regnskapsregisteret", "checked", mod.url, mod.retrieved_at)
            return _field("not_reported", (mod.note or "No annual accounts are filed for this company.") + " This is not a revenue of zero.", [src])
        why = mod.note or _why(mod.classification or "failed")
        return _field("unavailable", f"Regnskapsregisteret could not be read ({why}). This says nothing about the company's revenue.",
                      [_source("Regnskapsregisteret", "unavailable", mod.url, note=why)])

    async def _openings(self, org: str, identity: CanonicalIdentity) -> dict[str, Any]:
        st = self.s.settings
        current: list[jobs_conn.JobItem] = []
        sources: list[dict[str, Any]] = []
        unread = 0  # NAV ads that name the company but were not read within the lookup limit

        # 1) NAV Arbeidsplassen: ads whose employer resolves to this exact organisation (local index, then the ads themselves)
        if st.enable_nav_jobs:
            try:
                res = await asyncio.wait_for(nav.nav_jobs(self._ctx(org, st.enrich_nav_max_reads), identity, [], None, nav.NavIndex(self.s.db)),
                                             timeout=st.nav_step_timeout_seconds)
                state = {"available": "checked", "failed": "unavailable", "blocked": "unavailable"}.get(res.module.state, "not_checked")
                unread = sum(1 for c in res.candidates if c.get("status") == "not_checked")
                note = res.module.note or None
                if state == "checked" and unread:
                    note = f"{unread} NAV ad{'' if unread == 1 else 's'} that may be this company's could not be read within the lookup limit."
                sources.append(_source(nav.SOURCE_NAME, state, res.module.url, res.module.retrieved_at, note))
                current += [j for j in res.jobs if j.state == "current"]
            except TimeoutError:
                sources.append(_source(nav.SOURCE_NAME, "unavailable", note=f"NAV did not answer within {st.nav_step_timeout_seconds:.0f} s."))
        else:
            sources.append(_source(nav.SOURCE_NAME, "not_checked", note="NAV job ads are switched off (ENABLE_NAV_JOBS=false)."))

        # 2) the careers page of the register-listed website, used only once the site is verified as this company's (no web search)
        careers = "Company careers page"
        if not st.enrich_check_careers or not st.enable_website:
            sources.append(_source(careers, "not_checked", note="Website checks are switched off by configuration."))
        elif not identity.website:
            sources.append(_source(careers, "not_checked", note="The register lists no website. A research run can look for one."))
        else:
            ctx = self._ctx(org, st.enrich_site_max_requests)
            crawl = await crawl_site(ctx, identity.website, identity, origin="registry", max_pages=max(1, st.enrich_site_pages))
            if not crawl.verified:
                if crawl.state in ("failed", "blocked"):
                    sources.append(_source(careers, "unavailable", crawl.start_url, note=f"The register-listed website could not be read ({_why(crawl.note or crawl.state)})."))
                else:
                    sources.append(_source(careers, "not_checked", crawl.start_url,
                                           note="The register-listed website could not be verified as this company's site, so its careers page was not used."))
            else:
                company = await jobs_conn.collect_jobs(ctx, crawl, identity.legal_name or "", max_ats_pages=1, max_detail_pages=1)
                page = (crawl.docs("careers") or [crawl.homepage])[0]
                url = page.final_url if page is not None else crawl.start_url
                if company.failures and not company.jobs:
                    reasons = "; ".join(f"{f['name']}: {_why(f['classification'])}" for f in company.failures)
                    sources.append(_source(careers, "unavailable", url, note=f"{reasons}."))
                else:
                    note = "Careers page read." if company.careers_found else "The verified website links no careers page."
                    if company.incomplete:
                        note += " Not fully read: " + "; ".join(company.incomplete) + "."
                    sources.append(_source(careers, "checked", url, page.retrieved_at if page is not None else None, note))
                    current += [j for j in company.jobs if j.state == "current"]

        jobs = [j for j in jobs_conn.dedupe_jobs(current) if j.state == "current"]
        checked = [s["name"] for s in sources if s["state"] == "checked"]
        down = [s for s in sources if s["state"] == "unavailable"]
        not_checked = [s for s in sources if s["state"] == "not_checked"]
        if jobs:
            partial = bool(down or not_checked or unread)
            names = ", ".join(dict.fromkeys(s["name"] for s in sources if s["state"] == "checked"))
            note = f"{len(jobs)} verified current opening{'' if len(jobs) == 1 else 's'} ({names})."
            if partial:
                note += " Not every job source could be checked, so there may be more."
            return _field("verified", note, sources, value=len(jobs), lowerBound=True if partial else None)  # present only when it is a lower bound
        if down:
            why = "; ".join(f"{s['name']}: {s.get('note') or 'unavailable'}".rstrip(".") for s in down)
            return _field("unavailable", f"{why}. {NOT_HIRING}", sources)
        if unread:
            return _field("unverified", f"{unread} NAV ad{'' if unread == 1 else 's'} naming this company could not be checked within the lookup limit, so "
                                        f"no conclusion is drawn. Open the company to research its hiring. {NOT_HIRING}", sources)
        if checked:
            return _field("none_found", f"No verified openings in {' and '.join(checked)}. This does not mean the company is not hiring.", sources)
        why = "; ".join((s.get("note") or s["name"]).rstrip(".") for s in not_checked)
        return _field("not_checked", f"No job source could be checked: {why}. {NOT_HIRING}", sources)
