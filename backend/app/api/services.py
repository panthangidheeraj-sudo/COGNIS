"""Application services shared by the API routes.

``Services`` owns the HTTP client (SSRF-safe, cached, budgeted), the LLM
provider, the orchestrator and the database. Research for one organisation
number is serialised with a per-company lock so concurrent requests never
race on the same record.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from ..agent import llm_tasks
from ..agent.orchestrator import Orchestrator, ResearchOptions, new_run_id
from ..competition.changes import compat_profile, diff_profile
from ..config import Settings, get_settings
from ..connectors import brreg, nav
from ..connectors.base import ConnectorContext
from ..core.util import now_iso
from ..errors import ApiError
from ..identity.normalization import normalize_org_number, org_checksum_ok
from ..logging_setup import get_logger, log_event
from ..net.http import HttpClient
from ..providers.llm_base import LLMProvider
from ..providers.registry import build_provider
from ..runtime.budgets import unlimited_budget
from ..security.redaction import redact
from ..storage import repository as repo
from ..storage.cache import ResponseCache
from ..storage.db import Database, dumps, get_db, loads
from .profile_builder import build_profile, summary_from_entity

EventSink = Callable[[str, dict[str, Any]], None]
log = get_logger("services")


class Services:
    def __init__(self, settings: Settings | None = None, *, db: Database | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 provider: LLMProvider | None = None, use_provider: bool = False):
        self.settings = settings or get_settings()
        self.db = db or get_db()
        self.http = HttpClient(transport=transport, cache=ResponseCache(self.db), recorder=repo.tool_call_recorder(self.db))
        self.provider = provider if use_provider else build_provider(self.http, self.settings)
        self.budget = unlimited_budget()
        self.orch = Orchestrator(http=self.http, run_budget=self.budget, provider=self.provider, settings=self.settings, db=self.db)
        self._locks: dict[str, asyncio.Lock] = {}
        self._nav_task: asyncio.Task | None = None
        self._registry_failure: tuple[float, str, ApiError] | None = None
        self.nav_last_sync: dict[str, Any] | None = None
        self.started_at = now_iso()
        from .research_runs import RunManager
        from .sheets import SheetManager

        self.runs = RunManager(self)
        self.sheets = SheetManager(self)

    def start_background(self) -> None:
        """Keep the NAV job-ad index fresh while the API runs (bounded syncs; never blocks a request)."""
        if self.settings.enable_nav_jobs and self.settings.app_env != "test" and self._nav_task is None:
            self._nav_task = asyncio.create_task(self._nav_loop())

    async def _nav_loop(self) -> None:
        while True:
            try:
                self.nav_last_sync = await nav.sync_feed(self.http, self.db, self.settings)
                log_event(log, "nav feed sync", status=self.nav_last_sync.get("status"), pages=self.nav_last_sync.get("pages"), index=self.nav_last_sync.get("index"))
                wait = self.settings.nav_sync_interval_seconds if self.nav_last_sync.get("status") in ("up_to_date", "disabled") else 20
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # a failing sync must never take the API down
                log.warning(f"nav feed sync failed: {type(exc).__name__}")
                wait = 300
            await asyncio.sleep(wait)

    async def aclose(self) -> None:
        if self._nav_task is not None:
            self._nav_task.cancel()
        await self.runs.shutdown()
        await self.sheets.shutdown()
        await self.http.aclose()

    # ------------------------------------------------------------- helpers --
    def runner(self) -> llm_tasks.LLMRunner:
        return llm_tasks.LLMRunner(self.provider, self.budget)

    def ctx(self, org: str = "", *, fresh: bool = False) -> ConnectorContext:
        return ConnectorContext(org_number=org, http=self.http, budget=self.budget, run_id="api", settings=self.settings, fresh=fresh)

    @staticmethod
    def clean_org(value: str) -> str:
        org = normalize_org_number(value)
        if len(org) != 9:
            raise ApiError("invalid", "An organisation number has 9 digits.", status=400)
        if not org_checksum_ok(org):
            raise ApiError("invalid", f"{org} is not a valid Norwegian organisation number (check digit).", status=400)
        return org

    # ------------------------------------------------------------ research --
    async def research(self, org: str, *, mode: str = "deep", step_keys: list[str] | None = None, fresh: bool = False, on_event: EventSink | None = None,
                       run_id: str | None = None, focus: str | None = None) -> dict[str, Any]:
        lock = self._locks.setdefault(org, asyncio.Lock())
        async with lock:
            previous = repo.latest_record(self.db, org)
            previous_version = repo.latest_version_id(self.db, org)
            record = await self.orch.research(org, run_id=run_id or new_run_id("api"), on_event=on_event,
                                              options=ResearchOptions(mode=mode, fresh=fresh, include_website=mode != "registry", step_keys=step_keys, focus=focus))
            if record.get("identity") is None:
                return record
            changes: list[dict[str, Any]] = []
            if previous is not None and previous.get("identity") and mode != "registry" and previous.get("mode") != "registry":
                try:
                    changes = diff_profile(compat_profile(previous), compat_profile(record), detected_at=record.get("completed_at"))
                except ValueError:
                    changes = []
                record["previous_completed_at"] = previous.get("completed_at")
            elif previous is not None and previous.get("mode") != "registry" and mode == "registry":
                return previous  # never replace a full research with a registry-only lookup
            record["changes"] = changes
            label = "Registry lookup" if mode == "registry" else ("Update" if previous is not None and previous.get("mode") != "registry" else "Initial research")
            is_new_version = not repo.version_exists(self.db, repo.version_id_for(record))
            version_id = repo.save_record(self.db, record, changes=changes, label=label)
            record["version_id"] = version_id
            # Run bookkeeping for the caller (set after saving, so it is not part of the stored record).
            record["previous_version_id"] = previous_version
            record["new_version"] = is_new_version
            record["facts_changed"] = previous is None or previous.get("mode") == "registry" or repo.facts_digest(previous) != repo.facts_digest(record)
            if mode != "registry":
                from .library import ensure_company_artifact, record_signals

                ensure_company_artifact(self, record, version_id, label)
                record_signals(self, record, changes)
            return record

    async def ensure_record(self, org: str) -> dict[str, Any]:
        record = repo.latest_record(self.db, org)
        if record is not None:
            return record
        record = await self.research(org, mode="registry")
        if record.get("identity") is None:
            state = record.get("entity_state")
            if state in ("blocked_policy", "blocked_robots", "budget_exhausted"):
                raise ApiError("blocked", "The company register could not be reached right now.", status=403)
            if state in ("source_error", "submission_error"):
                raise ApiError("unavailable", "The company register did not respond. Please try again.", status=503)
            raise ApiError("not_found", f"No company with organisation number {org} was found in Enhetsregisteret.", status=404)
        return record

    def profile_for(self, record: dict[str, Any]) -> dict[str, Any]:
        org = record["organisation_number"]
        art = self.db.one("SELECT id, tags_json FROM artifacts WHERE type = 'company' AND org_number = ?", (org,))
        nav_ids = [(j.get("details") or {}).get("nav_uuid") for j in (record.get("jobs") or {}).get("items") or [] if j.get("source") == "nav"]
        inactive = nav.NavIndex(self.db).inactive([u for u in nav_ids if u]) if nav_ids else set()
        return build_profile(record, changes=record.get("changes") or [], previous_at=record.get("previous_completed_at"),
                             artifact_id=art["id"] if art else None, tags=loads(art["tags_json"], []) if art else [], inactive_job_ids=inactive)

    async def profile(self, org: str) -> dict[str, Any]:
        record = await self.ensure_record(org)
        self.db.execute("INSERT INTO recent_companies(org_number, viewed_at) VALUES (?, ?) ON CONFLICT(org_number) DO UPDATE SET viewed_at = excluded.viewed_at",
                        (org, now_iso()))
        return self.profile_for(record)

    def summary_for(self, org: str) -> dict[str, Any] | None:
        record = repo.latest_record(self.db, org)
        return self.profile_for(record)["company"] if record else None

    # -------------------------------------------------------------- search --
    async def search_entities(self, params: dict[str, Any], *, retries: int | None = None) -> tuple[list[dict[str, Any]], int]:
        """Search Enhetsregisteret. A failure is raised as an ``unavailable`` ApiError that carries its real cause (see ``brreg.RegistryFailure``),
        never as an empty result and never as a generic message."""
        outcome = await brreg.search_entities(self.ctx(), params, retries=retries)
        if outcome.failure is not None:
            raise self.registry_error(outcome.failure, params)
        self._registry_failure = None
        return outcome.rows, outcome.total

    def registry_error(self, failure: brreg.RegistryFailure, params: dict[str, Any]) -> ApiError:
        # The search parameters are registry filters (names, municipality numbers, industry codes), never credentials; redact() still runs over them.
        shown = {k: redact(str(v))[:120] for k, v in params.items() if v not in (None, "")}
        log_event(log, "enhetsregisteret search failed", logging.WARNING, reason=failure.kind, http_status=failure.http_status, attempts=failure.attempts,
                  elapsed_ms=failure.elapsed_ms, detail=failure.detail, params=shown)
        error = ApiError("unavailable", f"Company search in Enhetsregisteret failed. {failure.cause}", status=503, details=failure.as_details())
        self._registry_failure = (time.monotonic(), now_iso(), error)
        return error

    def recent_registry_failure(self, within_seconds: float = 300.0) -> tuple[str, ApiError] | None:
        """The last registry-search failure this server itself observed, if it is recent: ``(when, error)``. The fallback to already-verified
        companies is only ever offered on the strength of a failure the server saw, never on the client's word."""
        if self._registry_failure is None:
            return None
        at, when, error = self._registry_failure
        return (when, error) if time.monotonic() - at <= within_seconds else None

    def summaries_for_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for row in rows:
            org = str(row.get("organisasjonsnummer") or "")
            stored = self.summary_for(org) if org else None
            out.append(stored or summary_from_entity(row))
        return out

    async def resolve_query(self, query: str, *, auto_pick: bool = True) -> tuple[str | None, list[dict[str, Any]]]:
        """Return (org, candidates). Never guesses: several plausible matches → no org + candidates.

        A typed *name* is only ever a search term. With ``auto_pick=False`` (starting research) even a single match is returned as a candidate
        to be confirmed, because "exactly one registry name equals the text" is not the same as "this is the company the user means".
        A typed organisation number is an identifier, so it resolves directly (after the format and check-digit tests)."""
        digits = normalize_org_number(query)
        if len(digits) == 9 and len(query.strip().replace(" ", "")) <= 11:
            return self.clean_org(digits), []
        text = query.strip()
        for prefix in ("research ", "undersøk ", "analyse "):
            if text.lower().startswith(prefix):
                text = text[len(prefix):]
        if len(text) < 2:
            raise ApiError("invalid", "Type a company name or a 9-digit organisation number.", status=400)
        rows, _total = await self.search_entities({"navn": text, "size": 10})
        if not rows:
            return None, []
        norm = _norm(text)
        exact = [r for r in rows if _norm(r.get("navn")) == norm or _norm(_strip_form(r.get("navn"))) == norm]
        if auto_pick and len(exact) == 1:
            return str(exact[0]["organisasjonsnummer"]), []
        if auto_pick and len(rows) == 1:
            return str(rows[0]["organisasjonsnummer"]), []
        return None, self.summaries_for_rows((exact or rows)[:8])

    # ------------------------------------------------------------- storage --
    def kv_get(self, key: str, default: Any = None) -> Any:
        row = self.db.one("SELECT data_json FROM artifacts WHERE id = ?", (f"kv:{key}",))
        return loads(row["data_json"], default) if row else default

    def kv_set(self, key: str, value: Any) -> None:
        now = now_iso()
        self.db.execute("""INSERT INTO artifacts(id, type, title, created_at, updated_at, data_json, archived) VALUES (?,?,?,?,?,?,1)
                           ON CONFLICT(id) DO UPDATE SET data_json = excluded.data_json, updated_at = excluded.updated_at""",
                        (f"kv:{key}", "kv", key, now, now, dumps(value)))


def same_company_name(a: str | None, b: str | None) -> bool:
    """True when two spellings of a legal name are the same company name (case, punctuation and the legal form are ignored)."""
    na, nb = _norm(a), _norm(b)
    return bool(na) and (na == nb or _norm(_strip_form(a)) == _norm(_strip_form(b)))


def _strip_form(name: str | None) -> str:
    import re

    return re.sub(r"\s+(AS|ASA|ANS|DA|ENK|SA|NUF|BA|KS|STI)$", "", (name or "").strip(), flags=re.I)


def _norm(name: str | None) -> str:
    import re

    return re.sub(r"[^a-z0-9æøå]+", " ", (name or "").casefold()).strip()
