"""One company, end to end: SOURCE DATA → IDENTITY → EVIDENCE → REASONING → SYNTHESIS.

``research_company`` always returns a terminal ``ResearchRecord`` — it never
raises. Identity is anchored on the organisation number in the official
register; nothing from the web is used until the exact entity is verified.
The LLM (optional) plans extra actions, reads verified pages and writes the
summary; Python executes and validates everything.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings, get_settings
from ..connectors import brreg, geonorge, norid, optional, search
from ..connectors import jobs as jobs_conn
from ..connectors.base import ConnectorContext, not_run
from ..connectors.website import ENRICHMENT_KINDS, SiteCrawl, crawl_site, fetch_page, site_links
from ..core.util import clean_ws, format_int, format_money, now_iso, stable_id, truncate
from ..evidence.gate import Claim, absences, publish
from ..evidence.models import ModuleResult, Observation
from ..extraction import registry_facts as rf
from ..extraction import web_facts as wf
from ..identity.match import audit_site
from ..identity.model import CanonicalIdentity, identity_from_bulk
from ..identity.normalization import WEBMAIL_DOMAINS, email_domain, normalize_org_number, org_checksum_ok
from ..logging_setup import get_logger
from ..net.http import HttpClient
from ..providers.llm_base import LLMProvider
from ..runtime.budgets import CompanyBudget, RunBudget
from ..security.urls import canonical_url, host_of, normalize_website, registrable_domain
from . import llm_tasks
from .record import build_record

log = get_logger("agent")

EventSink = Callable[[str, dict[str, Any]], None]

STEP_META: dict[str, tuple[str, str, str]] = {
    # key → (label, source kind, source name)
    "registry": ("Company register", "registry", "Brønnøysundregistrene — Enhetsregisteret"),
    "roles": ("Roles and board", "people", "Brønnøysundregistrene — roller"),
    "subunits": ("Registered establishments", "registry", "Brønnøysundregistrene — underenheter"),
    "group": ("Group structure", "registry", "Brønnøysundregistrene — konsernstruktur"),
    "accounts": ("Annual accounts", "financial", "Regnskapsregisteret"),
    "filings": ("Filed annual reports", "financial", "Regnskapsregisteret — årsregnskap (kopi)"),
    "website": ("Official website", "website", "Official company website"),
    "jobs": ("Careers and job postings", "jobs", "Company careers pages"),
    "news": ("Company news", "news", "Company newsroom"),
    "geo": ("Map location", "registry", "Kartverket — Geonorge"),
    "extract": ("Read verified pages", "website", "Language model (quote-verified)"),
    "synthesis": ("Executive summary", "web", "Language model (evidence-grounded)"),
}


@dataclass
class ResearchOptions:
    mode: str = "deep"  # quick | deep | competition
    fresh: bool = False
    include_website: bool = True
    include_geo: bool = True
    step_keys: list[str] | None = None  # user-edited plan (frontend)


@dataclass
class ResearchState:
    org_number: str
    run_id: str
    started_at: str
    options: ResearchOptions
    identity: CanonicalIdentity | None = None
    modules: dict[str, ModuleResult] = field(default_factory=dict)
    extra_modules: list[ModuleResult] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    rejections: list = field(default_factory=list)
    absence_list: list = field(default_factory=list)
    crawl: SiteCrawl | None = None
    site_attempts: list[dict[str, Any]] = field(default_factory=list)
    search_summary: dict[str, int] | None = None
    jobs: list[jobs_conn.JobItem] = field(default_factory=list)
    jobs_note: str | None = None
    jobs_checked: bool = False
    roles: list[dict[str, Any]] = field(default_factory=list)
    locations: list[dict[str, Any]] = field(default_factory=list)
    financial_records: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    entity_state: str = "complete"
    terminal_status: str = "completed"
    published_keys: set[str] = field(default_factory=set)
    timed_out: bool = False


class Orchestrator:
    def __init__(self, *, http: HttpClient, run_budget: RunBudget, provider: LLMProvider | None = None, settings: Settings | None = None):
        self.http = http
        self.run_budget = run_budget
        self.provider = provider
        self.settings = settings or get_settings()

    async def research(
        self,
        org_number: str,
        *,
        run_id: str,
        bulk_row: dict[str, Any] | None = None,
        bulk_meta: dict[str, Any] | None = None,
        options: ResearchOptions | None = None,
        on_event: EventSink | None = None,
    ) -> dict[str, Any]:
        """Research one organisation number. Always returns a terminal record; never raises."""
        opts = options or ResearchOptions()
        org = normalize_org_number(org_number)
        state = ResearchState(org_number=org, run_id=run_id, started_at=now_iso(), options=opts)
        s = self.settings
        budget = CompanyBudget(self.run_budget, max_requests=s.per_company_max_requests, max_seconds=s.per_company_max_seconds,
                               max_llm_calls=0 if opts.mode == "registry" else (s.max_llm_calls_per_company if opts.mode != "quick" else 1), max_searches=s.max_searches_per_company)
        runner = llm_tasks.LLMRunner(self.provider, budget)
        emit = _safe_sink(on_event)
        started = time.monotonic()
        try:
            await asyncio.wait_for(self._run(state, budget, runner, bulk_row, bulk_meta, emit), timeout=s.per_company_max_seconds + 15)
        except TimeoutError:
            state.timed_out = True
            state.errors.append({"stage": "orchestrator", "error": "per-company time limit reached; partial results were finalised", "retryable": True})
        except Exception as exc:  # the record must still be terminal
            log.exception("research failed", extra={"org_number": org})
            state.errors.append({"stage": "orchestrator", "error": f"internal error ({type(exc).__name__})", "retryable": True})
            if state.identity is None and state.entity_state == "complete":
                state.entity_state = "submission_error"
                state.terminal_status = "failed"
        # Finalise: gate everything gathered so far (also after a timeout).
        try:
            self._finalise(state)
        except Exception as exc:
            log.exception("finalise failed", extra={"org_number": org})
            state.errors.append({"stage": "finalise", "error": f"internal error ({type(exc).__name__})"})
        operations = budget.snapshot()
        operations["runtime_ms"] = int((time.monotonic() - started) * 1000)
        operations["llm"] = {"calls": runner.calls, "tokens": runner.tokens, "model": runner.model, "provider": getattr(self.provider, "name", None)}
        state.errors.extend(runner.errors)
        record = build_record(state, operations=operations, completed_at=now_iso())
        emit("finished", {"record": record})
        return record

    def offline_record(self, org_number: str, *, run_id: str, bulk_row: dict[str, Any] | None, bulk_meta: dict[str, Any] | None, reason: str = "budget_exhausted") -> dict[str, Any]:
        """Terminal record without any network call (run budget exhausted): bulk-snapshot facts only, every live source marked blocked."""
        org = normalize_org_number(org_number)
        st = ResearchState(org_number=org, run_id=run_id, started_at=now_iso(), options=ResearchOptions(mode="competition"))
        note = f"{reason}: not queried because the run budget was exhausted"
        if bulk_row is not None:
            meta = bulk_meta or {}
            ident = identity_from_bulk(bulk_row, source_url=meta.get("source_url") or "https://data.brreg.no/enhetsregisteret/api/enheter/lastned",
                                       retrieved_at=meta.get("retrieved_at") or st.started_at, content_sha256=meta.get("content_sha256"))
            st.identity = ident
            st.modules["registry"] = ModuleResult(module="registry", source_id="brreg", source_name="Brønnøysundregistrene — Enhetsregisteret (bulk snapshot)",
                                                  source_class="official_registry_bulk", state="available", url=ident.source_url, retrieved_at=ident.retrieved_at,
                                                  content_sha256=meta.get("content_sha256"), value=_bulk_value(bulk_row), note=f"registry row key {org}")
            st.observations += rf.identity_observations(ident, st.modules["registry"])
        else:
            st.entity_state = "budget_exhausted"
        for name in ("registry_live", "roles", "locations", "financials", "financial_history", "group", "website", "jobs"):
            sid, sname, scls = brreg.SRC.get(name) or (name, name.replace("_", " ").title(), "company_owned")
            mod = not_run(name, source_id=sid, source_name=sname, source_class=scls, state="blocked", note=note, url=None)
            mod.classification = "budget_exhausted"
            st.modules[name] = mod
        self._finalise(st)
        return build_record(st, operations={"requests": 0, "runtime_ms": 0, "third_party_cost_usd": 0.0}, completed_at=now_iso())

    # ------------------------------------------------------------- pipeline --
    async def _run(self, st: ResearchState, budget: CompanyBudget, runner: llm_tasks.LLMRunner, bulk_row: dict[str, Any] | None,
                   bulk_meta: dict[str, Any] | None, emit: EventSink) -> None:
        s = self.settings
        ctx = ConnectorContext(org_number=st.org_number, http=self.http, budget=budget, run_id=st.run_id, settings=s, fresh=st.options.fresh)
        if not org_checksum_ok(st.org_number):
            st.errors.append({"stage": "input", "error": "organisation number fails the MOD11 check digit; looked up as given"})

        # ---- 1. identity (mandatory) --------------------------------------
        emit("stage", {"stage": "identify"})
        t0 = _step_start(emit, "registry")
        live_mod, identity = await brreg.fetch_entity(ctx, optional=False)
        st.modules["registry_live"] = live_mod
        if bulk_row is not None:
            meta = bulk_meta or {}
            bulk_identity = identity_from_bulk(bulk_row, source_url=meta.get("source_url") or "https://data.brreg.no/enhetsregisteret/api/enheter/lastned",
                                               retrieved_at=meta.get("retrieved_at") or st.started_at, content_sha256=meta.get("content_sha256"))
            st.modules["registry"] = ModuleResult(module="registry", source_id="brreg", source_name="Brønnøysundregistrene — Enhetsregisteret (bulk snapshot)",
                                                  source_class="official_registry_bulk", state="available", url=bulk_identity.source_url, retrieved_at=bulk_identity.retrieved_at,
                                                  content_sha256=meta.get("content_sha256"), value=_bulk_value(bulk_row), note=f"registry row key {st.org_number}")
            st.observations += rf.identity_observations(bulk_identity, st.modules["registry"])
            if identity is None:
                identity = bulk_identity
        st.identity = identity
        if identity is not None and live_mod.state == "available":
            st.observations += rf.identity_observations(identity, live_mod)
        self._step_done(st, emit, "registry", t0, live_mod if live_mod.state == "available" or "registry" not in st.modules else st.modules["registry"])
        if identity is None:
            st.entity_state = {"not_available": "not_found", "blocked": "blocked_policy", "failed": "source_error"}.get(live_mod.state, "not_found")
            if live_mod.classification == "budget_exhausted":
                st.entity_state = "budget_exhausted"
            if live_mod.classification == "robots_disallowed":
                st.entity_state = "blocked_robots"
            return
        self._publish_progress(st, emit)

        # ---- 2. official modules (parallel) --------------------------------
        emit("stage", {"stage": "gather"})
        wanted = set(st.options.step_keys or STEP_META)
        quick = st.options.mode in ("quick", "registry")

        async def run_step(key: str, coro):
            t = _step_start(emit, key)
            try:
                mod = await coro
            except Exception as exc:  # connector bug → failed module, research continues
                mod = not_run(key, source_id=key, source_name=STEP_META[key][2], source_class="official_other", state="failed", note=f"internal error ({type(exc).__name__})")
            return key, mod, t

        tasks = [run_step("roles", brreg.fetch_roles(ctx, optional=False)),
                 run_step("subunits", brreg.fetch_locations(ctx, optional=False)),
                 run_step("accounts", brreg.fetch_financials(ctx, identity, optional=False))]
        if "group" in wanted:
            tasks.append(run_step("group", brreg.fetch_group(ctx, identity)))
        if "filings" in wanted and not quick:
            tasks.append(run_step("filings", brreg.fetch_financial_history(ctx, identity)))
        if st.options.include_geo and st.options.mode != "competition" and "geo" in wanted:
            tasks.append(run_step("geo", geonorge.geocode(ctx, identity)))
        results = await asyncio.gather(*tasks)
        module_names = {"roles": "roles", "subunits": "locations", "accounts": "financials", "group": "group", "filings": "financial_history", "geo": "geo"}
        for key, mod, t in results:
            name = module_names[key]
            st.modules[name] = mod
            if name == "roles":
                st.roles = brreg.rich_roles(mod.raw) if mod.raw else []
                st.observations += rf.role_observations(mod, st.roles)
            elif name == "locations":
                st.locations = brreg.rich_locations(mod.raw) if mod.raw else []
                st.observations += rf.location_observations(mod, st.locations)
            elif name == "financials":
                st.financial_records = (mod.raw or {}).get("records", []) if isinstance(mod.raw, dict) else []
                st.observations += rf.financial_observations(mod)
            elif name == "group":
                st.observations += rf.group_observations(mod, st.org_number)
            elif name == "financial_history":
                st.observations += rf.filing_history_observations(mod)
            self._step_done(st, emit, key, t, mod)
        if "group" not in st.modules:
            st.modules["group"] = not_run("group", source_id="group", source_name=STEP_META["group"][2], source_class="official_group_structure", state="not_applicable",
                                          note="Not part of the selected research plan.")
        st.observations += _compat_observations(st)
        self._publish_progress(st, emit)

        # ---- 3. website: discover → verify identity → enrich ---------------
        if s.enable_website and st.options.include_website and "website" in wanted:
            await self._website(st, ctx, budget, emit)
        else:
            st.modules["website"] = not_run("website", source_id="website", source_name="Official company website", source_class="company_owned", state="not_applicable",
                                            note="Website research not part of this run.")
        # ---- 4. LLM: plan further actions, read verified pages --------------
        if st.crawl is not None and st.crawl.verified:
            emit("stage", {"stage": "verify"})
            await self._research_loop(st, ctx, budget, runner, emit)
            if s.enable_jobs and "jobs" in wanted:
                await self._jobs(st, ctx, emit)
            st.observations += wf.website_observations(st.crawl)
            st.observations += wf.news_observations(st.crawl)
            llm_obs: list[Observation] = []
            if runner.enabled and st.options.mode not in ("quick", "registry"):
                t = _step_start(emit, "extract")
                llm_obs = await llm_tasks.extract_website_facts(runner, st.crawl, identity)
                emit("step_completed", {"key": "extract", "facts": len(llm_obs), "evidence": len(llm_obs), "duration_ms": _ms(t),
                                        "outcome": "verified" if llm_obs else "not_available", "source_name": STEP_META["extract"][2],
                                        "message": None if llm_obs else "No quote-verified statements were extracted."})
            st.observations += llm_obs
            if not any(o.field == "business_description" for o in llm_obs):
                desc = wf.description_observation(st.crawl)
                if desc:
                    st.observations.append(desc)
        if "jobs" not in st.modules:
            st.modules["jobs"] = _derived_module("jobs", "Company careers pages", st.modules.get("website"), "No verified website, so no company-owned careers sources could be checked.")
        self._publish_progress(st, emit)

        # ---- 5. sources that need licences or review (reported, never scraped) -
        for mod in (await optional.proff_company(ctx), await optional.doffin_notices(ctx, identity), await optional.patentstyret_rights(ctx, identity),
                    optional.linkedin_module(), optional.shareholder_module(), optional.industry_module(identity, s.enable_industry_registries)):
            st.extra_modules.append(mod)

        # ---- 6. synthesis ---------------------------------------------------
        emit("stage", {"stage": "reconcile"})
        st.claims, st.rejections = publish(st.observations, st.org_number)
        emit("stage", {"stage": "synthesize"})
        t = _step_start(emit, "synthesis", announce=runner.enabled)
        st.summary = await _summarise(st, runner)
        if runner.enabled:
            emit("step_completed", {"key": "synthesis", "facts": 0, "evidence": len(st.summary.get("evidence_ids", [])) if st.summary else 0, "duration_ms": _ms(t),
                                    "outcome": "verified" if st.summary and st.summary.get("method") == "llm_grounded" else "not_available",
                                    "source_name": STEP_META["synthesis"][2]})
        if st.summary and st.summary.get("text"):
            emit("synthesis", {"text": st.summary["text"]})

    # --------------------------------------------------------------- website --
    def _site_candidates(self, st: ResearchState) -> list[tuple[str, str]]:
        ident = st.identity
        assert ident is not None
        out: list[tuple[str, str]] = []
        seen: set[str] = set()

        def add(url: str | None, origin: str) -> None:
            if not url:
                return
            dom = registrable_domain(host_of(url))
            if dom and dom not in seen and dom not in WEBMAIL_DOMAINS:
                seen.add(dom)
                out.append((url, origin))

        add(normalize_website(ident.website_raw or ident.website), "registry")
        dom = email_domain(ident.email)
        if dom and dom not in WEBMAIL_DOMAINS:
            add(normalize_website(dom), "email_domain")
        for loc in st.locations[:5]:
            add(normalize_website(loc.get("website")), "registry_subunit")
        return out

    async def _website(self, st: ResearchState, ctx: ConnectorContext, budget: CompanyBudget, emit: EventSink) -> None:
        s = self.settings
        identity = st.identity
        assert identity is not None
        t = _step_start(emit, "website")
        max_pages = s.max_pages_per_site if st.options.mode != "quick" else 3
        best: SiteCrawl | None = None
        for url, origin in self._site_candidates(st)[:3]:
            crawl = await self._crawl_with_norid(ctx, url, identity, origin=origin, max_pages=max_pages, st=st)
            best = _better(best, crawl)
            if crawl.verified:
                break
        if (best is None or not best.verified) and s.search_enabled and st.options.mode != "quick":
            best = _better(best, await self._search_for_site(st, ctx, identity, max_pages))
        if best is None:
            note = "The register lists no website and no company domain could be derived from registered contact details."
            if not s.search_enabled:
                note += " Web search discovery is not configured."
            elif st.search_summary is not None:
                note += f" Web search found no result that names the company ({st.search_summary['screened_out']} unrelated result(s) not fetched)."
            st.modules["website"] = not_run("website", source_id="website", source_name="Official company website", source_class="company_owned", state="not_available", note=note)
        else:
            st.crawl = best
            st.modules["website"] = best.module()
        self._step_done(st, emit, "website", t, st.modules["website"],
                        facts=1 if st.crawl and st.crawl.verified else 0,
                        message=None if st.crawl and st.crawl.verified else st.modules["website"].note)

    async def _crawl_with_norid(self, ctx: ConnectorContext, url: str, identity: CanonicalIdentity, *, origin: str, max_pages: int, st: ResearchState) -> SiteCrawl:
        crawl = await crawl_site(ctx, url, identity, origin="registry" if origin == "registry" else ("email_domain" if origin == "email_domain" else "search"),
                                 max_pages=max_pages)
        if origin == "registry_subunit":
            crawl.origin = "registry_subunit"
        if not crawl.verified and crawl.homepage is not None and crawl.domain.endswith(".no") and self.settings.enable_norid and not (crawl.audit and crawl.audit.parked):
            mod, holder = await norid.lookup_domain(ctx, crawl.domain)
            st.extra_modules.append(mod)
            if holder:
                crawl.audit = audit_site(identity, crawl.docs(), crawl.domain, registry_linked=origin == "registry", norid_holder_org=holder,
                                         parked=bool(crawl.audit and crawl.audit.parked))
                if crawl.verified:
                    crawl.state, crawl.note = "available", None
                    await _enrich_verified(ctx, crawl, max_pages)
        st.site_attempts.append({"url": url, "domain": crawl.domain, "origin": crawl.origin, "state": crawl.state,
                                 "decision": crawl.audit.decision if crawl.audit else "not_fetched", "score": round(crawl.audit.score, 2) if crawl.audit else None,
                                 "signals": crawl.audit.signals if crawl.audit else [], "conflicts": crawl.audit.conflicts if crawl.audit else [], "note": crawl.note})
        return crawl

    async def _search_for_site(self, st: ResearchState, ctx: ConnectorContext, identity: CanonicalIdentity, max_pages: int) -> SiteCrawl | None:
        tried = {a["domain"] for a in st.site_attempts}
        domains: list[str] = []
        screened: list[str] = []
        for query in search.identity_queries(identity.legal_name or "", identity.org_number, identity.municipality)[:2]:
            mod, hits = await search.web_search(ctx, query)
            st.extra_modules.append(mod)
            screened_here = 0
            for hit in hits:
                dom = hit.domain
                if not search.is_candidate_company_domain(dom) or dom in tried or dom in domains:
                    continue
                if search.hit_matches_company(hit, identity.legal_name):
                    domains.append(dom)
                elif dom not in screened:
                    screened.append(dom)
                    screened_here += 1
            st.trace.append({"action": "search_web", "query": query, "state": mod.state, "hits": len(hits), "screened_out": screened_here})
            if domains or mod.state == "blocked":
                break  # a name-matching candidate is enough; do not spend another search credit
        for dom in screened[:5]:
            st.site_attempts.append({"url": f"https://{dom}", "domain": dom, "origin": "search", "state": "screened_out", "decision": "screened_out", "score": None,
                                     "signals": [], "conflicts": [], "note": "search hit does not mention the company name; page not fetched"})
        st.search_summary = {"candidates": len(domains), "screened_out": len(screened)}
        best = None
        for dom in domains[:2]:
            crawl = await self._crawl_with_norid(ctx, f"https://{dom}", identity, origin="search", max_pages=max_pages, st=st)
            best = _better(best, crawl)
            if crawl.verified:
                break
        return best

    async def _jobs(self, st: ResearchState, ctx: ConnectorContext, emit: EventSink) -> None:
        crawl = st.crawl
        assert crawl is not None and st.identity is not None
        t = _step_start(emit, "jobs")
        modules, items, note = await jobs_conn.collect_jobs(ctx, crawl, st.identity.legal_name or "")
        st.extra_modules += modules
        st.jobs, st.jobs_note = items, note
        st.jobs_checked = bool(crawl.docs("careers") or crawl.ats_links)
        st.observations += wf.job_observations(crawl, items, note, st.jobs_checked)
        careers = crawl.docs("careers")
        src_doc = careers[0] if careers else crawl.homepage
        state = "available" if (items or st.jobs_checked) else "not_available"
        st.modules["jobs"] = ModuleResult(module="jobs", source_id="jobs", source_name=f"Company careers ({crawl.domain})", source_class=crawl.source_class, state=state,
                                          url=src_doc.final_url if src_doc else crawl.start_url, retrieved_at=src_doc.retrieved_at if src_doc else None,
                                          content_sha256=src_doc.content_sha256 if src_doc else None, note=note, tier="B",
                                          value={"current": sum(1 for j in items if j.state == "current"), "total": len(items), "checked": st.jobs_checked})
        current = sum(1 for j in items if j.state == "current")
        emit("step_completed", {"key": "jobs", "facts": len(items), "evidence": len(items), "duration_ms": _ms(t), "source_name": f"Company careers ({crawl.domain})",
                                "outcome": "verified" if items else "not_available",
                                "message": (f"{current} current opening(s) on company-owned pages" if items else note)})

    async def _research_loop(self, st: ResearchState, ctx: ConnectorContext, budget: CompanyBudget, runner: llm_tasks.LLMRunner, emit: EventSink) -> None:
        """Bounded follow-up: fetch more pages of the verified site. LLM chooses when available; otherwise a fixed rule."""
        crawl = st.crawl
        assert crawl is not None and st.identity is not None
        rounds = max(0, min(self.settings.max_research_rounds, 1 if st.options.mode == "quick" else self.settings.max_research_rounds))
        for round_no in range(rounds):
            if not budget.can_optional() or len(crawl.pages) >= self.settings.max_pages_per_site + 4:
                break
            options = _page_options(crawl)
            if not options:
                break
            have = {p.kind for p in crawl.pages if p.doc}
            missing = [k for k in ("careers", "news", "products", "about", "team", "investors") if k not in have]
            chosen = await llm_tasks.plan_actions(runner, st.identity, sorted(have), missing, options,
                                                  f"{budget.max_requests - budget.requests} requests, {int(budget.deadline_left())} s", max_actions=2) if runner.enabled else None
            planner = "llm" if chosen else "rule"
            if not chosen:
                # No (valid) model plan: fall back to the fixed rule — fetch the most informative missing page kinds.
                chosen = [o for o in options if o["hint"] in missing][:2]
            if not chosen:
                break
            for action in chosen:
                page_res, doc = await fetch_page(ctx, action["arg"], optional=True)
                kind = next((o["hint"] for o in options if o["arg"] == action["arg"]), "other")
                crawl.pages.append(_fetched(kind, page_res, doc))
                crawl.requests += 0 if page_res.from_cache else 1
                st.trace.append({"round": round_no + 1, "planner": planner, "tool": "fetch_page", "url": action["arg"], "kind": kind, "result": page_res.classification,
                                 "reason": action.get("reason")})
            if planner == "rule":
                break

    # ------------------------------------------------------------ publishing --
    def _publish_progress(self, st: ResearchState, emit: EventSink) -> None:
        claims, _ = publish(st.observations, st.org_number)
        latest: dict[str, str] = {}
        for claim in claims:
            if claim.reporting_period and claim.reporting_period > latest.get(claim.field, ""):
                latest[claim.field] = claim.reporting_period
        for claim in claims:
            if claim.reporting_period and claim.reporting_period != latest.get(claim.field):
                continue  # stream the current period only; history is in the saved profile
            key = claim.key(st.org_number)
            if key not in st.published_keys:
                st.published_keys.add(key)
                emit("fact", {"claim": claim})

    def _finalise(self, st: ResearchState) -> None:
        if not st.claims and st.observations:
            st.claims, st.rejections = publish(st.observations, st.org_number)
        for name in ("roles", "locations", "financials", "group", "financial_history", "website", "jobs"):
            if name not in st.modules:
                st.modules[name] = _missing_module(name, st)
        st.absence_list = absences(st.claims, st.modules, legal_form=st.identity.legal_form if st.identity else None)
        if st.summary is None and st.claims:
            st.summary = _deterministic_summary(st)

    def _step_done(self, st: ResearchState, emit: EventSink, key: str, t0: float, mod: ModuleResult, *, facts: int | None = None, message: str | None = None) -> None:
        fields = {o.field for o in st.observations if o.module == mod.module}
        n = facts if facts is not None else len(fields)
        payload = {"key": key, "source_name": mod.source_name or STEP_META[key][2], "duration_ms": _ms(t0), "facts": n, "evidence": n,
                   "state": mod.state, "message": message if message is not None else mod.note}
        if mod.state == "blocked":
            emit("step_blocked", payload)
        elif mod.state == "failed":
            emit("step_failed", {**payload, "retryable": True})
        else:
            payload["outcome"] = "verified" if (mod.state == "available" and n) else "not_available"
            emit("step_completed", payload)


# --------------------------------------------------------------------- helpers --
def _safe_sink(sink: EventSink | None) -> EventSink:
    def emit(kind: str, data: dict[str, Any]) -> None:
        if sink is None:
            return
        try:
            sink(kind, data)
        except Exception:  # a broken listener never breaks research
            pass
    return emit


def _step_start(emit: EventSink, key: str, *, announce: bool = True) -> float:
    if announce:
        emit("step_started", {"key": key, "source_name": STEP_META[key][2]})
    return time.monotonic()


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _better(a: SiteCrawl | None, b: SiteCrawl | None) -> SiteCrawl | None:
    if a is None:
        return b
    if b is None:
        return a
    if b.verified and not a.verified:
        return b
    if a.verified:
        return a
    rank = {"ambiguous": 0, "blocked": 1, "not_available": 2, "failed": 3}
    sa, sb = (a.audit.score if a.audit else -1), (b.audit.score if b.audit else -1)
    if a.origin == "registry" and b.origin != "registry" and a.homepage is not None:
        return a  # the register's own claim is the more informative failure
    return a if (rank.get(a.state, 9), -sa) <= (rank.get(b.state, 9), -sb) else b


def _fetched(kind: str, res, doc):  # noqa: ANN001
    from ..connectors.website import FetchedPage

    return FetchedPage(kind, res, doc)


async def _enrich_verified(ctx: ConnectorContext, crawl: SiteCrawl, max_pages: int) -> None:
    """After a late identity verification (e.g. via Norid), fetch the enrichment pages crawl_site skipped."""
    from ..extraction.html import is_ats, social_profile

    home = crawl.homepage
    if home is None:
        return
    grouped = site_links(home, crawl.domain)
    seen = {canonical_url(p.doc.final_url) for p in crawl.pages if p.doc}
    for kind in ENRICHMENT_KINDS:
        if len(crawl.pages) >= max_pages:
            break
        for link in grouped.get(kind, [])[:1]:
            if canonical_url(link.url) in seen:
                continue
            res, doc = await fetch_page(ctx, link.url, optional=True)
            crawl.pages.append(_fetched(kind, res, doc))
            seen.add(canonical_url(link.url))
    for doc in crawl.docs():
        for link in doc.links:
            prof = social_profile(link.url)
            if prof and all(s["url"] != canonical_url(link.url) for s in crawl.social):
                crawl.social.append({"network": prof[0], "handle": prof[1], "url": canonical_url(link.url), "page": doc.final_url})
            if is_ats(link.url) and all(canonical_url(a.url) != canonical_url(link.url) for a in crawl.ats_links):
                crawl.ats_links.append(link)


def _page_options(crawl: SiteCrawl) -> list[dict[str, str]]:
    home = crawl.homepage
    if home is None:
        return []
    fetched = {canonical_url(p.result.url) for p in crawl.pages} | {canonical_url(p.doc.final_url) for p in crawl.pages if p.doc}
    have_kinds = {p.kind for p in crawl.pages if p.doc}
    options: list[dict[str, str]] = []
    grouped = site_links(home, crawl.domain)
    for doc in crawl.docs():
        if doc is home:
            continue
        for kind, links in site_links(doc, crawl.domain).items():
            grouped.setdefault(kind, []).extend(links)
    for kind in ("careers", "news", "products", "about", "team", "investors", "locations", "sustainability"):
        for link in grouped.get(kind, [])[:2]:
            if canonical_url(link.url) in fetched or any(o["arg"] == link.url for o in options):
                continue
            if kind in have_kinds and kind not in ("news", "careers"):
                continue
            options.append({"tool": "fetch_page", "arg": link.url, "hint": kind})
    for link in crawl.ats_links[:1]:
        if canonical_url(link.url) not in fetched:
            options.append({"tool": "fetch_page", "arg": link.url, "hint": "careers"})
    return options[:8]


def _derived_module(name: str, source_name: str, website: ModuleResult | None, note: str) -> ModuleResult:
    state = website.state if website and website.state in ("blocked", "ambiguous", "failed", "not_applicable") else "not_available"
    return not_run(name, source_id=name, source_name=source_name, source_class="company_owned", state=state,
                   note=(website.note if website and website.state in ("blocked", "failed") and website.note else note), tier="B")


def _missing_module(name: str, st: ResearchState) -> ModuleResult:
    if st.identity is None:
        state = {"submission_error": "failed", "budget_exhausted": "blocked", "blocked_policy": "blocked", "blocked_robots": "blocked",
                 "source_error": "failed"}.get(st.entity_state, "not_available")
        note = "The organisation number could not be resolved in the register, so this source was not queried."
        if st.entity_state == "budget_exhausted":
            note = "budget_exhausted"
    elif st.timed_out:
        state, note = "failed", "Not reached before the per-company time limit."
    else:
        state, note = "not_applicable", "Not part of this research run."
    src = brreg.SRC.get(name)
    sid, sname, scls = src if src else (name, name.replace("_", " ").title(), "company_owned" if name in ("website", "jobs") else "official_other")
    return not_run(name, source_id=sid, source_name=sname, source_class=scls, state=state, note=note)


def _bulk_value(row: dict[str, Any]) -> dict[str, Any]:
    keys = ("organisation_number", "name", "legal_form", "employees", "bankrupt", "liquidating", "municipality", "municipality_number", "industry_code", "industry_label",
            "website", "latest_submitted_accounts")
    return {k: row.get(k) for k in keys if k in row}


def _compat_observations(st: ResearchState) -> list[Observation]:
    """Aggregate claims with the starter kit's field names (role_holders, available_filing_years, …)."""
    out: list[Observation] = []
    roles_mod = st.modules.get("roles")
    if roles_mod and roles_mod.state == "available":
        holders = [{"name": r["name"], "role": r.get("role")} for r in st.roles if r.get("name") and not r.get("inactive") and not r.get("deceased")]
        if holders:
            out.append(Observation(field="role_holders", value=holders, claim_span=f"rollegrupper: {len(holders)} active role(s)", extraction_method="structured_api",
                                   label="Role holders", **rf._base(roles_mod)))
    loc_mod = st.modules.get("locations")
    if loc_mod and loc_mod.state == "available":
        active = [x for x in st.locations if not x.get("deleted") and not x.get("closed")]
        out.append(Observation(field="registered_subunit_count", value=len(active), claim_span=f"underenheter returned {len(st.locations)} establishment(s)",
                               extraction_method="structured_api", label="Registered subunits", numeric=True, **rf._base(loc_mod)))
    hist = st.modules.get("financial_history")
    if hist and hist.state == "available" and isinstance(hist.value, dict) and hist.value.get("years"):
        out.append(Observation(field="available_filing_years", value=list(hist.value["years"]), claim_span=f"aarsregnskap/kopi years: {', '.join(hist.value['years'])}",
                               extraction_method="structured_api", label="Available filing years", **rf._base(hist)))
    return out


# ------------------------------------------------------------------- summary --
def _fact_lines(st: ResearchState) -> list[tuple[str, str, list[str]]]:
    """(sentence-ready fact text, evidence id, fields) from published claims only."""
    from .record import evidence_id

    by_field: dict[str, list[Claim]] = {}
    for c in st.claims:
        by_field.setdefault(c.field, []).append(c)

    def first(f: str) -> Claim | None:
        items = by_field.get(f) or []
        return items[0] if items else None

    def eid(c: Claim) -> str:
        o = c.primary
        return evidence_id(o) if o else ""

    lines: list[tuple[str, str, list[str]]] = []
    name = first("legal_name")
    form = first("legal_form")
    ind = first("industry_label")
    if name:
        text = f"Legal name: {name.value}"
        if form:
            text += f"; legal form {form.value} ({(form.attributes or {}).get('description') or ''})".replace(" ()", "")
        lines.append((text, eid(name), ["legal_name", "legal_form"]))
    if ind:
        lines.append((f"Registered industry: {ind.value}", eid(ind), ["industry_label"]))
    status = first("registration_status")
    if status and status.value != "active":
        lines.append((f"Register status: {(status.attributes or {}).get('label') or status.value}", eid(status), ["registration_status"]))
    muni = first("municipality")
    if muni:
        lines.append((f"Registered business address municipality: {muni.value}", eid(muni), ["municipality"]))
    founded = first("founded_date")
    if founded:
        lines.append((f"Founded (register): {founded.value}", eid(founded), ["founded_date"]))
    emp = first("registered_employees")
    if emp:
        lines.append((f"Employees registered in Enhetsregisteret: {format_int(emp.value)}", eid(emp), ["registered_employees"]))
    revs = sorted(by_field.get("revenue", []), key=lambda c: c.reporting_period or "", reverse=True)
    if revs:
        r = revs[0]
        lines.append((f"Revenue {r.period_label}: {format_money(r.value, r.currency)}", eid(r), ["revenue"]))
        res = next((c for c in by_field.get("annual_result", []) if c.reporting_period == r.reporting_period), None)
        if res:
            lines.append((f"Annual result {res.period_label}: {format_money(res.value, res.currency)}", eid(res), ["annual_result"]))
    ceo = first("ceo")
    if ceo:
        lines.append((f"General manager (daglig leder): {ceo.value}", eid(ceo), ["ceo"]))
    chair = first("board_chair")
    if chair:
        lines.append((f"Chair of the board: {chair.value}", eid(chair), ["board_chair"]))
    parent = first("parent_company")
    if parent:
        lines.append((f"Parent company (group register): {parent.value}", eid(parent), ["parent_company"]))
    subs = by_field.get("subsidiary") or []
    if subs:
        lines.append((f"Subsidiaries in the group register: {len(subs)}", eid(subs[0]), ["subsidiary"]))
    est = first("registered_establishment_count")
    if est and est.value:
        lines.append((f"Registered establishments (underenheter): {est.value}", eid(est), ["registered_establishment_count"]))
    site = first("official_website")
    if site:
        lines.append((f"Verified official website: {site.value}", eid(site), ["official_website"]))
    desc = first("business_description")
    if desc:
        translated = (desc.attributes or {}).get("translation")
        lines.append((f"Company-stated description: {translated or desc.value}", eid(desc), ["business_description"]))
    jobs = first("open_positions_count")
    if jobs:
        lines.append((f"Current job postings on company-owned pages: {jobs.value}", eid(jobs), ["open_positions_count"]))
    return lines


async def _summarise(st: ResearchState, runner: llm_tasks.LLMRunner) -> dict[str, Any] | None:
    if st.identity is None or not st.claims:
        return None
    lines = _fact_lines(st)
    if runner.enabled and st.options.mode not in ("quick", "registry"):
        text, method = await llm_tasks.synthesize(runner, st.identity, [(t, e) for t, e, _ in lines])
        if text:
            return {"text": text, "method": method, "evidence_ids": [e for _, e, _ in lines if e], "generated_at": now_iso(),
                    "sentences": [{"text": t, "evidence_ids": [e]} for t, e, _ in lines]}
    return _deterministic_summary(st, lines)


def _deterministic_summary(st: ResearchState, lines: list[tuple[str, str, list[str]]] | None = None) -> dict[str, Any] | None:
    """Template summary built only from published claims (used when no LLM is configured or its output failed validation)."""
    lines = lines if lines is not None else _fact_lines(st)
    if not lines or st.identity is None:
        return None
    by = {f: c for c in reversed(st.claims) for f in [c.field]}
    ident = st.identity
    sentences: list[dict[str, Any]] = []

    def add(text: str, *fields: str) -> None:
        ids = [eid for _t, eid, fs in lines if set(fs) & set(fields)]
        if ids:
            sentences.append({"text": text, "evidence_ids": ids})

    name = by.get("legal_name")
    lead = f"{name.value if name else ident.legal_name}"
    form = by.get("legal_form")
    form_text = str(form.attributes.get("description") or form.value) if form else ""
    lead += f" is a Norwegian {form_text[:1].lower() + form_text[1:]}" if form else " is a registered Norwegian entity"
    muni = by.get("municipality")
    if muni:
        lead += f" registered in {muni.value}"
    ind = by.get("industry_label")
    if ind:
        lead += f", in the industry “{ind.value}”"
    add(lead + ".", "legal_name", "legal_form", "municipality", "industry_label")
    desc = by.get("business_description")
    if desc:
        text = desc.attributes.get("translation") or desc.value
        add(f"The company describes itself as follows: “{truncate(clean_ws(text), 220)}”", "business_description")
    revs = sorted([c for c in st.claims if c.field == "revenue"], key=lambda c: c.reporting_period or "", reverse=True)
    if revs:
        r = revs[0]
        res = next((c for c in st.claims if c.field == "annual_result" and c.reporting_period == r.reporting_period), None)
        sent = f"Filed accounts for {r.period_label} show revenue of {format_money(r.value, r.currency)}"
        sent += f" and an annual result of {format_money(res.value, res.currency)}." if res else "."
        add(sent, "revenue", "annual_result")
    emp = by.get("registered_employees")
    if emp:
        add(f"The register reports {format_int(emp.value)} employees.", "registered_employees")
    ceo = by.get("ceo")
    chair = by.get("board_chair")
    if ceo or chair:
        parts = []
        if ceo:
            parts.append(f"{ceo.value} is registered as general manager")
        if chair:
            parts.append(f"{chair.value} as chair of the board")
        add(("; ".join(parts) + ".")[0].upper() + ("; ".join(parts) + ".")[1:], "ceo", "board_chair")
    parent = by.get("parent_company")
    if parent:
        add(f"It is part of a group with {parent.value} as parent company.", "parent_company")
    jobs = by.get("open_positions_count")
    if jobs:
        add(f"{jobs.value} current job posting(s) were found on company-owned pages.", "open_positions_count")
    status = by.get("registration_status")
    if status and status.value != "active":
        add(f"Register status: {status.attributes.get('label') or status.value}.", "registration_status")
    text = " ".join(s["text"] for s in sentences)
    return {"text": text, "method": "deterministic_template", "evidence_ids": list(dict.fromkeys(e for s in sentences for e in s["evidence_ids"])),
            "generated_at": now_iso(), "sentences": sentences}


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}-{stable_id(now_iso(), time.time_ns(), length=12)}"
