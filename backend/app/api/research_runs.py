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

from ..agent.focus import GENERIC as GENERIC_FOCUS
from ..agent.orchestrator import new_run_id
from ..agent.record import claim_to_dict
from ..core.util import now_iso
from ..errors import ApiError
from ..evidence.gate import Claim
from ..logging_setup import get_logger
from ..storage import run_history
from .briefs import answer as answer_question
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
    "news": ("Company news and announcements", "news", True),
    "extract": ("Read verified pages (AI, quote-checked)", "website", True),
    "followup": ("Follow-up website pages", "website", True),
    "crosscheck": ("Cross-check facts across sources", "verification", True),
}
QUICK_KEYS = ["registry", "accounts", "roles", "subunits", "group", "website", "jobs", "news"]
# Deep adds: the multi-year filing history, further website pages (the ones about the research focus first), AI reading of the verified pages
# (when a model is configured), press coverage inside the news step (when search is configured) and a cross-source check of what was published.
DEEP_KEYS = ["registry", "accounts", "roles", "subunits", "group", "filings", "website", "followup", "jobs", "news", "extract", "crosscheck"]
COVERAGE_LABELS = {"company_record": "Company record", "financials": "Financials", "people_locations": "People & locations", "website": "Company website",
                   "hiring_activity": "Hiring & public activity"}
# Plan step → the optional workflow in the effort report that explains why it did not run
EFFORT_FLOW = {"filings": "filings", "website": "site_pages", "followup": "followup", "extract": "extract", "news": "press", "crosscheck": "crosscheck"}
MODULE_FOR_STEP = {"jobs": "jobs", "website": "website", "filings": "financial_history", "extract": "website", "news": "news"}
TIME_LIMIT_MESSAGE = "The research time limit was reached before this source finished. What it had read was kept; nothing else was assumed."
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
    outcome: str | None = None  # completed | partial — only for runs that finished and saved a report; failed/cancelled runs have none
    issues: list[str] = field(default_factory=list)
    saved: bool = False  # the run's evidence was written as a report version

    def to_json(self) -> dict[str, Any]:
        active = self.status in ("running", "awaiting_confirmation", "planning")
        out: dict[str, Any] = {"id": self.id, "query": self.query, "mode": self.mode, "status": self.status, "plan": self.plan, "startedAt": self.started_at,
                               "capabilities": CAPS_ACTIVE if active else CAPS_NONE, "autoSaved": self.auto_saved}
        for key, value in (("prompt", self.prompt), ("company", self.company), ("ambiguity", self.ambiguity), ("stage", self.stage), ("finishedAt", self.finished_at),
                           ("artifactId", self.artifact_id), ("coverage", self.coverage), ("summary", self.summary), ("outcome", self.outcome),
                           ("issues", self.issues or None)):
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
            org = self.s.clean_org(str(body["orgNumber"]))  # 9 digits + check digit; the registry lookup below confirms it exists
        else:
            if not query:
                raise ApiError("invalid", "Type a company name or a 9-digit organisation number.", status=400)
            # A typed name never starts research by itself: the user must pick (or confirm the single match) first.
            org, candidates = await self.s.resolve_query(query, auto_pick=False)
            if org is None and candidates:
                one = len(candidates) == 1
                message = ("One registered company matches this name. Confirm it is the company you mean — COGNIS never guesses."
                           if one else "Several registered companies match this name. Pick the exact company — COGNIS never guesses.")
                run = Run(id=new_run_id("run"), query=query, mode=mode, prompt=prompt, status="ambiguous", plan=plan_for(mode, step_keys, llm=self._llm()),
                          started_at=now_iso(), ambiguity={"query": query, "candidates": candidates, "message": message})
                self.runs[run.id] = run
                return run.to_json()
            if org is None:
                raise ApiError("not_found", f"No Norwegian company matched “{query}”. Try the full legal name or the 9-digit organisation number.", status=404)
        record = await self.s.ensure_record(org)  # registry lookup: an unknown number stops here (404)
        company = self.s.profile_for(record)["company"]
        expected = str(body.get("expectedName") or "").strip()
        from .services import same_company_name  # local import: services imports this module

        if expected and not same_company_name(expected, company.get("legalName")):
            # The caller confirmed a different company than the one registered under this number (stale or edited selection).
            raise ApiError("ambiguous", f"Organisation number {org} is registered to “{company.get('legalName')}”, not “{expected}”. Select the company again.",
                           details={"orgNumber": org, "expectedName": expected, "registeredName": company.get("legalName")})
        plan = plan_for(mode, step_keys, llm=self._llm())
        run = Run(id=new_run_id("run"), query=query or org, mode=mode, prompt=prompt, status="awaiting_confirmation" if plan["requiresConfirmation"] else "running",
                  plan=plan, started_at=now_iso(), org=org, company=company)
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
            self._close_open_steps(run, running="step.cancelled", message="Stopped: research was cancelled before this source finished.",
                                   pending_message="Not started: research was cancelled.")
            self._emit(run, "run.failed", message="Research cancelled before it started. Nothing was saved.", cancelled=True)
        run.status = "cancelled"
        return run.to_json()

    def unsupported(self, what: str) -> None:
        raise ApiError("invalid", f"{what} is not supported by this backend.", status=400)

    async def events(self, run_id: str, last_seq: int) -> AsyncIterator[str]:
        run = self._get(run_id)
        sent = last_seq
        idle = 0.0
        while True:
            # Clear the signal *before* collecting: an event emitted while this generator is suspended at a yield keeps the signal set, so the wait below
            # returns at once. (Clearing afterwards swallowed such events and delayed them until the 15 s keep-alive — progress arrived in bursts.)
            run.changed.clear()
            pending = [e for e in run.events if e["seq"] > sent]
            for event in pending:
                sent = event["seq"]
                yield f"id: {event['seq']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
            if run.terminal and sent >= run.events[-1]["seq"]:
                return
            if run.status in ("ambiguous",):
                return
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
        elif t == "step.progress":
            patch(e["stepId"], detail=e.get("message"))
        elif t == "step.completed":
            patch(e["stepId"], status="done", sourceName=e.get("sourceName"), finishedAt=e["at"], durationMs=e.get("durationMs"), factCount=e.get("factCount"),
                  evidenceCount=e.get("evidenceCount"), outcome=e.get("outcome"), message=e.get("message"))
        elif t == "step.failed":
            patch(e["stepId"], status="failed", message=e.get("message"), retryable=e.get("retryable"), finishedAt=e["at"])
            run.counts["failed"] += 1
        elif t == "step.blocked":
            patch(e["stepId"], status="blocked", message=e.get("message"), finishedAt=e["at"])
            run.counts["blocked"] += 1
        elif t == "step.skipped":
            patch(e["stepId"], status="skipped", message=e.get("message"), finishedAt=e["at"])
        elif t == "step.cancelled":
            patch(e["stepId"], status="cancelled", message=e.get("message"), finishedAt=e["at"])

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
            elif kind in ("step_started", "step_completed", "step_failed", "step_blocked", "step_progress"):
                sid = f"s-{data['key']}"
                if sid not in plan_ids:
                    return
                if kind == "step_started":
                    self._emit(run, "step.started", stepId=sid, sourceName=data.get("source_name"))
                elif kind == "step_progress":
                    if data.get("message"):
                        self._emit(run, "step.progress", stepId=sid, message=str(data["message"]))
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

        record: dict[str, Any] | None = None
        answer: dict[str, Any] | None = None
        try:
            focus = None if (run.prompt or "").strip().casefold() in GENERIC_FOCUS else (run.prompt or "").strip()
            record = await self.s.research(org, mode=run.mode, step_keys=keys + ["geo"], on_event=sink, run_id=run.id, focus=focus)
            if record.get("identity") is None:
                raise ApiError("unavailable", _no_identity_message(record))
            run.saved = True
            effort = record.get("effort") or {}
            timed_out = bool(effort.get("timedOut"))
            self._settle_steps(run, record, effort, timed_out)
            profile = self.s.profile_for(record)
            self._emit(run, "stage.changed", stage="verify")
            self._emit(run, "stage.changed", stage="reconcile")
            self._emit(run, "stage.changed", stage="synthesize")
            if run.prompt and run.prompt.strip().casefold() not in ("company brief", "research this company"):
                # A focus prompt or custom question is answered from the evidence that is about it, not with the generic company summary.
                answer = await answer_question(profile, run.prompt, self.s.runner(), origin="fresh_research")
            else:
                answer = answer_from_summary(profile, run.prompt)
            if profile.get("summary") and not run.synthesis_text:
                self._emit(run, "synthesis.delta", text=profile["summary"]["text"])
            self._emit(run, "synthesis.completed", answer=answer)
            self._emit(run, "stage.changed", stage="save")
            coverage = profile["company"]["coverage"]
            facts_verified = sum(1 for f in _verified_facts(profile))
            outcome, issues = judge_outcome(coverage, blocked=run.counts["blocked"], failed=run.counts["failed"], timed_out=timed_out)
            summary = {
                "coverage": coverage, "sourcesVerified": len(profile["sources"]), "primarySources": profile["quality"]["primarySources"],
                "secondarySources": profile["quality"]["secondarySources"], "factsVerified": facts_verified, "conflicts": profile["quality"]["conflicts"],
                "identityConflicts": sum(1 for a in record.get("site_attempts") or [] if a.get("decision") in ("ambiguous", "rejected") and a.get("conflicts")),
                "changesDetected": sum(1 for c in profile["changes"]["changes"] if c["material"]), "blockedSources": run.counts["blocked"],
                "failedSources": run.counts["failed"], "elapsedMs": int((time.monotonic() - run.t0) * 1000), "outcome": outcome, "issues": issues,
                "effort": effort or None,
                # What happened to the report: a run that found the same facts still saves its own version, and earlier versions are always kept.
                "report": {"newVersion": bool(record.get("new_version")), "factsChanged": record.get("facts_changed"), "versionId": record.get("version_id")},
            }
            run.artifact_id = profile.get("artifactId")
            run.auto_saved = bool(run.artifact_id)
            run.coverage = coverage
            run.summary = summary
            run.company = profile["company"]
            run.outcome, run.issues = outcome, issues
            run.status = "completed"
            run.finished_at = now_iso()
            self._snapshot(run, outcome, record=record, answer=answer, issues=issues)
            self._emit(run, "run.completed", artifactId=run.artifact_id, autoSaved=run.auto_saved, coverage=coverage, summary=summary, outcome=outcome, issues=issues)
        except asyncio.CancelledError:
            run.status = "cancelled"
            run.finished_at = now_iso()
            if not run.terminal:
                self._close_open_steps(run, running="step.cancelled", message="Stopped: research was cancelled before this source finished.",
                                       pending_message="Not started: research was cancelled.")
                kept = "Research cancelled. The evidence it had gathered was already saved as a report version." if run.saved else "Research cancelled. Nothing from this run was saved."
                self._snapshot(run, "cancelled", record=record if run.saved else None, answer=answer, issues=[kept])
                self._emit(run, "run.failed", message=kept, cancelled=True)
            raise
        except ApiError as exc:
            self._fail(run, exc.message, record)
        except Exception as exc:  # never leave a stream hanging
            log.exception("research run failed", extra={"run_id": run.id})
            self._fail(run, f"Research failed ({type(exc).__name__}). Please try again.", record)

    # ------------------------------------------------------------ run end ----
    def _fail(self, run: Run, message: str, record: dict[str, Any] | None) -> None:
        run.status = "failed"
        run.finished_at = now_iso()
        self._close_open_steps(run, running="step.failed", message=f"Stopped: {message}", pending_message="Not started: the research run failed.")
        self._snapshot(run, "failed", record=record if run.saved else None, issues=[message])
        self._emit(run, "run.failed", message=message)

    def _close_open_steps(self, run: Run, *, running: str, message: str, pending_message: str) -> None:
        """A run that ends early must not leave a source looking busy or waiting: running steps are stopped, steps never reached are marked skipped."""
        for step in list(run.plan["steps"]):
            if step["status"] == "running":
                extra = {"retryable": True} if running == "step.failed" else {}
                self._emit(run, running, stepId=step["id"], sourceName=step.get("sourceName") or step["label"], message=message, **extra)
            elif step["status"] == "pending":
                self._emit(run, "step.skipped", stepId=step["id"], sourceName=step["label"], message=pending_message)

    def _settle_steps(self, run: Run, record: dict[str, Any], effort: dict[str, Any], timed_out: bool) -> None:
        """Planned steps that never reported get their real state: skipped (with the reason) or, if the time limit stopped them, failed."""
        started = {e.get("stepId") for e in run.events if e["type"] == "step.started"}
        done = {e.get("stepId") for e in run.events if e["type"] in ("step.completed", "step.failed", "step.blocked", "step.skipped", "step.cancelled")}
        modules = record.get("modules") or {}
        flows = {f["key"]: f for f in effort.get("workflows") or []}
        for step in run.plan["steps"]:
            if step["id"] in done:
                continue
            if step["id"] in started:
                if timed_out:
                    self._emit(run, "step.failed", stepId=step["id"], sourceName=step.get("sourceName") or step["label"], message=TIME_LIMIT_MESSAGE, retryable=True)
                else:
                    self._emit(run, "step.completed", stepId=step["id"], sourceName=step.get("sourceName") or step["label"], factCount=0, evidenceCount=0, durationMs=0,
                               outcome="not_available")
                continue
            note = (modules.get(MODULE_FOR_STEP.get(step["key"], step["key"])) or {}).get("note")
            flow = flows.get(EFFORT_FLOW.get(step["key"], ""))
            reason = "Not reached: the research time limit was reached." if timed_out else (note or (flow or {}).get("detail"))
            self._emit(run, "step.skipped", stepId=step["id"], sourceName=step["label"], message=reason or "Not needed for this company given the verified evidence.")

    def _snapshot(self, run: Run, status: str, *, record: dict[str, Any] | None = None, answer: dict[str, Any] | None = None, issues: list[str] | None = None) -> None:
        """Write this run to the company's run history. A failure here is logged and never changes the research result."""
        if not run.org:
            return
        try:
            from .library import company_artifact_id

            steps = [{k: s.get(k) for k in ("key", "label", "status", "sourceName", "message", "durationMs", "factCount", "evidenceCount", "outcome") if s.get(k) is not None}
                     for s in run.plan["steps"]]
            run_history.save_run(self.s.db, {
                "id": run.id, "org_number": run.org, "artifact_id": company_artifact_id(run.org) if record else None, "mode": run.mode, "prompt": run.prompt,
                "status": status, "started_at": run.started_at, "finished_at": run.finished_at or now_iso(),
                "profile_version_id": (record or {}).get("version_id"), "previous_version_id": (record or {}).get("previous_version_id"),
                "evidence_changed": (record or {}).get("facts_changed") if record else None, "summary": run.summary, "effort": (record or {}).get("effort"),
                "steps": steps, "answer": answer, "issues": issues or [],
            })
        except Exception:
            log.exception("could not save the run history entry", extra={"run_id": run.id})


def judge_outcome(coverage: dict[str, Any] | None, *, blocked: int, failed: int, timed_out: bool) -> tuple[str, list[str]]:
    """A run is "completed" only when every area was verified and no source was unreachable; anything less is "partial", with the reasons."""
    issues: list[str] = []
    if timed_out:
        issues.append("The research time limit was reached; sources that had not finished were not used.")
    if failed:
        issues.append(f"{failed} source{'s' if failed != 1 else ''} could not be reached.")
    if blocked:
        issues.append(f"{blocked} source{'s' if blocked != 1 else ''} blocked access.")
    areas = (coverage or {}).get("areas") or []
    total = int((coverage or {}).get("total") or 0)
    gaps = [a for a in areas if a.get("status") != "complete"]
    if not coverage or not total:
        issues.append("Coverage was not reported, so completeness cannot be confirmed.")
    elif gaps or int(coverage.get("complete") or 0) < total:
        names = ", ".join(COVERAGE_LABELS.get(a.get("area"), str(a.get("area")).replace("_", " ")) for a in gaps)
        issues.append(f"{coverage.get('complete', 0)} of {total} areas verified" + (f" — not verified: {names}." if names else "."))
    return ("partial" if issues else "completed"), issues


def _no_identity_message(record: dict[str, Any]) -> str:
    state = record.get("entity_state")
    if state in ("blocked_policy", "blocked_robots", "budget_exhausted"):
        return "The company register could not be reached right now, so nothing was researched or saved."
    if state in ("source_error", "submission_error"):
        return "The company register did not respond, so nothing was researched or saved. Please try again."
    return "The company could not be found in the register, so nothing was researched or saved."


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
