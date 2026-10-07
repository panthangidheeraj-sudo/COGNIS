"""Research runs for the frontend: plan → (confirm) → stream of ResearchEvents (SSE).

Events carry a monotonically increasing ``seq`` and are kept in memory per run
so a reconnecting client can replay everything after ``lastSeq``. The UI shows
only what these events say: a step appears only when the backend starts it,
and a fact appears only after the publication gate confirmed it.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from ..agent.orchestrator import new_run_id
from ..agent.record import claim_to_dict
from ..core.util import now_iso
from ..errors import ApiError
from ..evidence.gate import Claim
from ..logging_setup import get_logger
from .briefs import answer_from_summary
from .profile_builder import Builder

log = get_logger("runs")

STEP_DEFS: dict[str, tuple[str, str, bool]] = {
    # key → (label, source kind, optional)
    "registry": ("Verify identity", "registry", False),
    "accounts": ("Annual accounts", "financial", False),
    "roles": ("Leadership and board", "people", False),
    "subunits": ("Registered establishments", "registry", True),
    "group": ("Group structure", "registry", True),
    "filings": ("Filed annual reports", "financial", True),
    "website": ("Company website", "website", True),
    "jobs": ("Careers and hiring", "jobs", True),
    "extract": ("Read verified pages (AI, quote-checked)", "website", True),
}
QUICK_KEYS = ["registry", "accounts", "roles", "subunits", "group", "website", "jobs"]
DEEP_KEYS = ["registry", "accounts", "roles", "subunits", "group", "filings", "website", "jobs", "extract"]
STREAM_FACT_FIELDS = {"legal_name": "identity.legalName", "registration_status": "identity.status", "business_address": "identity.registeredAddress",
                      "registered_employees": "overview.employees", "ceo": "people.ceo", "board_chair": "people.chair", "official_website": "identity.website",
                      "business_description": "overview.description", "open_positions_count": "overview.openPositions", "parent_company": "relationships.parent",
                      "registered_establishment_count": "overview.locations", "revenue": "financials.revenue", "annual_result": "financials.annual_result"}
CAPS_ACTIVE = {"pause": False, "cancel": True, "retryFailed": False, "editPlan": True}
CAPS_NONE = {"pause": False, "cancel": False, "retryFailed": False, "editPlan": False}


def plan_for(mode: str, step_keys: list[str] | None, *, llm: bool) -> dict[str, Any]:
    keys = [k for k in (step_keys or (DEEP_KEYS if mode == "deep" else QUICK_KEYS)) if k in STEP_DEFS]
    for required in ("registry", "accounts", "roles"):
        if required not in keys:
            keys.insert(0 if required == "registry" else len(keys), required)
    if not llm:
        keys = [k for k in keys if k != "extract"]
    steps = [{"id": f"s-{k}", "key": k, "label": STEP_DEFS[k][0], "sourceKind": STEP_DEFS[k][1], "optional": STEP_DEFS[k][2], "status": "pending"} for k in keys]
    available = [{"key": k, "label": d[0], "sourceKind": d[1]} for k, d in STEP_DEFS.items() if k not in keys and (llm or k != "extract")]
    return {"steps": steps, "requiresConfirmation": mode == "deep" and not step_keys, "availableSteps": available}


@dataclass
class Run:
    id: str
    query: str
    mode: str
    prompt: str | None
    status: str
    plan: dict[str, Any]
    started_at: str
    org: str | None = None
    company: dict[str, Any] | None = None
    ambiguity: dict[str, Any] | None = None
    stage: str | None = None
    finished_at: str | None = None
    artifact_id: str | None = None
    auto_saved: bool = False
    coverage: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    task: asyncio.Task | None = None
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    t0: float = field(default_factory=time.monotonic)
    synthesis_text: str = ""
    counts: dict[str, int] = field(default_factory=lambda: {"blocked": 0, "failed": 0})

    def to_json(self) -> dict[str, Any]:
        active = self.status in ("running", "awaiting_confirmation", "planning")
        out: dict[str, Any] = {"id": self.id, "query": self.query, "mode": self.mode, "status": self.status, "plan": self.plan, "startedAt": self.started_at,
                               "capabilities": CAPS_ACTIVE if active else CAPS_NONE, "autoSaved": self.auto_saved}
        for key, value in (("prompt", self.prompt), ("company", self.company), ("ambiguity", self.ambiguity), ("stage", self.stage), ("finishedAt", self.finished_at),
                           ("artifactId", self.artifact_id), ("coverage", self.coverage), ("summary", self.summary)):
            if value is not None:
                out[key] = value
        return out

    @property
    def terminal(self) -> bool:
        return bool(self.events) and self.events[-1]["type"] in ("run.completed", "run.failed")


class RunManager:
    def __init__(self, services: Any):
        self.s = services
        self.runs: dict[str, Run] = {}

    async def shutdown(self) -> None:
        for run in self.runs.values():
            if run.task and not run.task.done():
                run.task.cancel()

    # ---------------------------------------------------------------- API ---
    async def start(self, body: dict[str, Any]) -> dict[str, Any]:
        query = str(body.get("query") or "").strip()
        mode = "deep" if body.get("mode") == "deep" else "quick"
        prompt = body.get("prompt") or None
        step_keys = body.get("stepKeys") or None
        org = None
        if body.get("orgNumber"):
            org = self.s.clean_org(str(body["orgNumber"]))
        else:
            if not query:
                raise ApiError("invalid", "Type a company name or a 9-digit organisation number.", status=400)
            org, candidates = await self.s.resolve_query(query)
            if org is None and candidates:
                run = Run(id=new_run_id("run"), query=query, mode=mode, prompt=prompt, status="ambiguous", plan=plan_for(mode, step_keys, llm=self._llm()),
                          started_at=now_iso(), ambiguity={"query": query, "candidates": candidates,
                                                           "message": "Several registered companies match this name. Pick the exact company — COGNIS never guesses."})
                self.runs[run.id] = run
                return run.to_json()
            if org is None:
                raise ApiError("not_found", f"No Norwegian company matched “{query}”. Try the full legal name or the 9-digit organisation number.", status=404)
        record = await self.s.ensure_record(org)
        plan = plan_for(mode, step_keys, llm=self._llm())
        run = Run(id=new_run_id("run"), query=query or org, mode=mode, prompt=prompt, status="awaiting_confirmation" if plan["requiresConfirmation"] else "running",
                  plan=plan, started_at=now_iso(), org=org, company=self.s.profile_for(record)["company"])
        self.runs[run.id] = run
        if run.status == "running":
            self._launch(run)
        return run.to_json()

    async def confirm(self, run_id: str, step_keys: list[str]) -> dict[str, Any]:
        run = self._get(run_id)
        if run.status != "awaiting_confirmation" or not run.org:
            raise ApiError("invalid", "This research run is not waiting for confirmation.", status=400)
        run.plan = plan_for(run.mode, step_keys or [s["key"] for s in run.plan["steps"]], llm=self._llm())
        run.plan["requiresConfirmation"] = False
        run.status = "running"
        self._launch(run)
        return run.to_json()

    def get(self, run_id: str) -> dict[str, Any]:
        return self._get(run_id).to_json()

    async def cancel(self, run_id: str) -> dict[str, Any]:
        run = self._get(run_id)
        if run.task and not run.task.done():
            run.task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(run.task), timeout=2)
            except (asyncio.CancelledError, TimeoutError, Exception):
                pass
        if not run.terminal:
            run.status = "cancelled"
            run.finished_at = now_iso()
            self._emit(run, "run.failed", message="Research cancelled. Verified data gathered so far is kept in the saved profile only if the run completed.")
        run.status = "cancelled"
        return run.to_json()

    def unsupported(self, what: str) -> None:
        raise ApiError("invalid", f"{what} is not supported by this backend.", status=400)

    async def events(self, run_id: str, last_seq: int) -> AsyncIterator[str]:
        run = self._get(run_id)
        sent = last_seq
        idle = 0.0
        while True:
            pending = [e for e in run.events if e["seq"] > sent]
            for event in pending:
                sent = event["seq"]
                yield f"id: {event['seq']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
            if run.terminal and sent >= run.events[-1]["seq"]:
                return
            if run.status in ("ambiguous",):
                return
            run.changed.clear()
            try:
                await asyncio.wait_for(run.changed.wait(), timeout=15)
                idle = 0.0
            except TimeoutError:
                idle += 15
                yield ": keep-alive\n\n"
                if idle > 900:
                    return

    # ------------------------------------------------------------ internals --
    def _llm(self) -> bool:
        return self.s.provider is not None

    def _get(self, run_id: str) -> Run:
        run = self.runs.get(run_id)
        if run is None:
            raise ApiError("not_found", "Research run not found.", status=404)
        return run

    def _emit(self, run: Run, kind: str, **payload: Any) -> None:
        if kind == "stage.changed" and any(e["type"] == "stage.changed" and e.get("stage") == payload.get("stage") for e in run.events):
            return  # each pipeline stage is announced once
        seq = (run.events[-1]["seq"] if run.events else 0) + 1
        event = {"type": kind, "seq": seq, "runId": run.id, "at": now_iso(), **payload}
        run.events.append(event)
        self._apply(run, event)
        run.changed.set()

    def _apply(self, run: Run, e: dict[str, Any]) -> None:
        def patch(step_id: str, **kw: Any) -> None:
            for s in run.plan["steps"]:
                if s["id"] == step_id:
                    s.update({k: v for k, v in kw.items() if v is not None})

        t = e["type"]
        if t == "stage.changed":
            run.stage = e["stage"]
        elif t == "step.started":
            patch(e["stepId"], status="running", sourceName=e.get("sourceName"), startedAt=e["at"])
        elif t == "step.completed":
            patch(e["stepId"], status="done", sourceName=e.get("sourceName"), finishedAt=e["at"], durationMs=e.get("durationMs"), factCount=e.get("factCount"),
                  evidenceCount=e.get("evidenceCount"), outcome=e.get("outcome"), message=e.get("message"))
        elif t == "step.failed":
            patch(e["stepId"], status="failed", message=e.get("message"), retryable=e.get("retryable"), finishedAt=e["at"])
            run.counts["failed"] += 1
        elif t == "step.blocked":
            patch(e["stepId"], status="blocked", message=e.get("message"), finishedAt=e["at"])
            run.counts["blocked"] += 1

    def _launch(self, run: Run) -> None:
        self._emit(run, "run.started")
        self._emit(run, "stage.changed", stage="discover")
        run.task = asyncio.create_task(self._execute(run))

    async def _execute(self, run: Run) -> None:
        keys = [s["key"] for s in run.plan["steps"]]
        plan_ids = {f"s-{k}" for k in keys}
        legal_name = (run.company or {}).get("legalName")
        org = run.org or ""

        def sink(kind: str, data: dict[str, Any]) -> None:
            if kind == "stage":
                self._emit(run, "stage.changed", stage=data["stage"])
            elif kind in ("step_started", "step_completed", "step_failed", "step_blocked"):
                sid = f"s-{data['key']}"
                if sid not in plan_ids:
                    return
                if kind == "step_started":
                    self._emit(run, "step.started", stepId=sid, sourceName=data.get("source_name"))
                elif kind == "step_completed":
                    payload = {"stepId": sid, "sourceName": data.get("source_name"), "factCount": int(data.get("facts") or 0), "evidenceCount": int(data.get("evidence") or 0),
                               "durationMs": int(data.get("duration_ms") or 0), "outcome": data.get("outcome") or "not_available"}
                    if data.get("message"):
                        payload["message"] = data["message"]
                    self._emit(run, "step.completed", **payload)
                elif kind == "step_failed":
                    self._emit(run, "step.failed", stepId=sid, sourceName=data.get("source_name"), message=data.get("message") or "The source did not respond.",
                               retryable=False)
                else:
                    self._emit(run, "step.blocked", stepId=sid, sourceName=data.get("source_name"), message=data.get("message") or "Source access blocked.")
            elif kind == "fact":
                fact = _stream_fact(data["claim"], org, legal_name)
                if fact is not None:
                    self._emit(run, "fact.confirmed", fact=fact)
            elif kind == "synthesis":
                words = str(data.get("text") or "").split(" ")
                for i in range(0, len(words), 6):
                    chunk = " ".join(words[i:i + 6]) + (" " if i + 6 < len(words) else "")
                    run.synthesis_text += chunk
                    self._emit(run, "synthesis.delta", text=chunk)

        try:
            record = await self.s.research(org, mode=run.mode, step_keys=keys + ["geo"], on_event=sink, run_id=run.id)
            # Steps the plan listed but the evidence made unnecessary (e.g. careers without a verified site).
            started = {e.get("stepId") for e in run.events if e["type"] == "step.started"}
            done = {e.get("stepId") for e in run.events if e["type"] in ("step.completed", "step.failed", "step.blocked")}
            modules = record.get("modules") or {}
            for step in run.plan["steps"]:
                if step["id"] in done:
                    continue
                if step["id"] in started:
                    self._emit(run, "step.completed", stepId=step["id"], sourceName=step.get("sourceName") or step["label"], factCount=0, evidenceCount=0, durationMs=0,
                               outcome="not_available")
                    continue
                note = (modules.get({"jobs": "jobs", "website": "website", "filings": "financial_history", "extract": "website"}.get(step["key"], step["key"])) or {}).get("note")
                self._emit(run, "step.started", stepId=step["id"], sourceName=step["label"])
                self._emit(run, "step.completed", stepId=step["id"], sourceName=step["label"], factCount=0, evidenceCount=0, durationMs=0, outcome="not_available",
                           message=note or "Not applicable for this company given the verified evidence.")
            profile = self.s.profile_for(record)
            self._emit(run, "stage.changed", stage="verify")
            self._emit(run, "stage.changed", stage="reconcile")
            self._emit(run, "stage.changed", stage="synthesize")
            answer = answer_from_summary(profile, run.prompt)
            if profile.get("summary") and not run.synthesis_text:
                self._emit(run, "synthesis.delta", text=profile["summary"]["text"])
            self._emit(run, "synthesis.completed", answer=answer)
            self._emit(run, "stage.changed", stage="save")
            coverage = profile["company"]["coverage"]
            facts_verified = sum(1 for f in _verified_facts(profile))
            summary = {
                "coverage": coverage, "sourcesVerified": len(profile["sources"]), "primarySources": profile["quality"]["primarySources"],
                "secondarySources": profile["quality"]["secondarySources"], "factsVerified": facts_verified, "conflicts": profile["quality"]["conflicts"],
                "identityConflicts": sum(1 for a in record.get("site_attempts") or [] if a.get("decision") in ("ambiguous", "rejected") and a.get("conflicts")),
                "changesDetected": sum(1 for c in profile["changes"]["changes"] if c["material"]), "blockedSources": run.counts["blocked"],
                "failedSources": run.counts["failed"], "elapsedMs": int((time.monotonic() - run.t0) * 1000),
            }
            run.artifact_id = profile.get("artifactId")
            run.auto_saved = bool(run.artifact_id)
            run.coverage = coverage
            run.summary = summary
            run.company = profile["company"]
            run.status = "completed"
            run.finished_at = now_iso()
            self._emit(run, "run.completed", artifactId=run.artifact_id, autoSaved=run.auto_saved, coverage=coverage, summary=summary)
        except asyncio.CancelledError:
            run.status = "cancelled"
            run.finished_at = now_iso()
            if not run.terminal:
                self._emit(run, "run.failed", message="Research cancelled. Nothing from this run was saved.")
            raise
        except ApiError as exc:
            run.status = "failed"
            run.finished_at = now_iso()
            self._emit(run, "run.failed", message=exc.message)
        except Exception as exc:  # never leave a stream hanging
            log.exception("research run failed", extra={"run_id": run.id})
            run.status = "failed"
            run.finished_at = now_iso()
            self._emit(run, "run.failed", message=f"Research failed ({type(exc).__name__}). Please try again.")


def _verified_facts(profile: dict[str, Any]) -> list[dict[str, Any]]:
    out = [f for f in profile["identity"].values() if isinstance(f, dict) and f.get("status") == "verified"]
    out += [pt["fact"] for s in profile["financials"]["series"] for pt in s["points"]]
    out += [p["fact"] for p in profile["people"]["people"]]
    out += [loc["fact"] for loc in profile["locations"]["locations"] if loc["kind"] != "registered_address"]
    out += [f for f in profile["keyMetrics"] if f["status"] == "verified" and f["field"].startswith("overview.")]
    if profile.get("description"):
        out.append(profile["description"])
    return out


def _stream_fact(claim: Claim, org: str, legal_name: str | None) -> dict[str, Any] | None:
    path = STREAM_FACT_FIELDS.get(claim.field)
    if path is None:
        return None
    index: dict[str, dict[str, Any]] = {}
    cd = claim_to_dict(claim, org, index)
    record = {"organisation_number": org, "identity": {"legal_name": legal_name}, "claims": [cd], "evidence": list(index.values()), "modules": {}, "mode": "deep"}
    b = Builder(record)
    if claim.field in ("revenue", "annual_result"):
        year = (claim.reporting_period or "")[-10:-6] or ""
        return b.money_fact(f"{path}.{year}", claim.label or claim.field, cd, period=claim.period_label, fid=f"{org}:{path}.{year}")
    value = cd["value"]
    if claim.field == "registration_status":
        value = (cd.get("attributes") or {}).get("label") or value
    if claim.field == "business_description":
        value = (cd.get("attributes") or {}).get("translation") or value
    return b.fact(path, claim.label or claim.field, cd, value=value, fid=f"{org}:{path}")
