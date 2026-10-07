"""Application services shared by the API routes.

``Services`` owns the HTTP client (SSRF-safe, cached, budgeted), the LLM
provider, the orchestrator and the database. Research for one organisation
number is serialised with a per-company lock so concurrent requests never
race on the same record.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx

from ..agent import llm_tasks
from ..agent.orchestrator import Orchestrator, ResearchOptions, new_run_id
from ..competition.changes import compat_profile, diff_profile
from ..config import Settings, get_settings
from ..connectors import brreg
from ..connectors.base import ConnectorContext
from ..core.util import now_iso
from ..errors import ApiError
from ..identity.normalization import normalize_org_number, org_checksum_ok
from ..net.http import HttpClient
from ..providers.llm_base import LLMProvider
from ..providers.registry import build_provider
from ..runtime.budgets import unlimited_budget
from ..storage import repository as repo
from ..storage.cache import ResponseCache
from ..storage.db import Database, dumps, get_db, loads
from .profile_builder import build_profile, summary_from_entity

EventSink = Callable[[str, dict[str, Any]], None]


class Services:
    def __init__(self, settings: Settings | None = None, *, db: Database | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 provider: LLMProvider | None = None, use_provider: bool = False):
        self.settings = settings or get_settings()
        self.db = db or get_db()
        self.http = HttpClient(transport=transport, cache=ResponseCache(self.db), recorder=repo.tool_call_recorder(self.db))
        self.provider = provider if use_provider else build_provider(self.http, self.settings)
        self.budget = unlimited_budget()
        self.orch = Orchestrator(http=self.http, run_budget=self.budget, provider=self.provider, settings=self.settings)
        self._locks: dict[str, asyncio.Lock] = {}
        self.started_at = now_iso()
        from .research_runs import RunManager
        from .sheets import SheetManager

        self.runs = RunManager(self)
        self.sheets = SheetManager(self)

    async def aclose(self) -> None:
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
                       run_id: str | None = None) -> dict[str, Any]:
        lock = self._locks.setdefault(org, asyncio.Lock())
        async with lock:
            previous = repo.latest_record(self.db, org)
            record = await self.orch.research(org, run_id=run_id or new_run_id("api"), on_event=on_event,
                                              options=ResearchOptions(mode=mode, fresh=fresh, include_website=mode != "registry", step_keys=step_keys))
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
            version_id = repo.save_record(self.db, record, changes=changes, label=label)
            record["version_id"] = version_id
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
        return build_profile(record, changes=record.get("changes") or [], previous_at=record.get("previous_completed_at"),
                             artifact_id=art["id"] if art else None, tags=loads(art["tags_json"], []) if art else [])

    async def profile(self, org: str) -> dict[str, Any]:
        record = await self.ensure_record(org)
        self.db.execute("INSERT INTO recent_companies(org_number, viewed_at) VALUES (?, ?) ON CONFLICT(org_number) DO UPDATE SET viewed_at = excluded.viewed_at",
                        (org, now_iso()))
        return self.profile_for(record)

    def summary_for(self, org: str) -> dict[str, Any] | None:
        record = repo.latest_record(self.db, org)
        return self.profile_for(record)["company"] if record else None

    # -------------------------------------------------------------- search --
    async def search_entities(self, params: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
        rows, total, error = await brreg.search_entities(self.ctx(), params)
        if error and not rows:
            raise ApiError("unavailable", "Company search in Enhetsregisteret is unavailable right now.", status=503, details={"reason": error})
        return rows, total

    def summaries_for_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for row in rows:
            org = str(row.get("organisasjonsnummer") or "")
            stored = self.summary_for(org) if org else None
            out.append(stored or summary_from_entity(row))
        return out

    async def resolve_query(self, query: str) -> tuple[str | None, list[dict[str, Any]]]:
        """Return (org, candidates). Never guesses: several plausible matches → no org + candidates."""
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
        if len(exact) == 1:
            return str(exact[0]["organisasjonsnummer"]), []
        if len(rows) == 1:
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


def _strip_form(name: str | None) -> str:
    import re

    return re.sub(r"\s+(AS|ASA|ANS|DA|ENK|SA|NUF|BA|KS|STI)$", "", (name or "").strip(), flags=re.I)


def _norm(name: str | None) -> str:
    import re

    return re.sub(r"[^a-z0-9æøå]+", " ", (name or "").casefold()).strip()
