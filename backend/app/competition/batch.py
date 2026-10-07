"""Evaluator batch runner: exactly one terminal envelope per input organisation number.

Bounded concurrency, one central run budget (requests / cost / runtime with a
finalisation reserve), per-company time limits, resumable from the database,
deterministic output order (input order), and a completeness check before the
outputs are written.
"""
from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from ..agent.orchestrator import Orchestrator, ResearchOptions, new_run_id
from ..config import Settings, get_settings
from ..core.util import now_iso
from ..logging_setup import get_logger, log_event
from ..net.http import HttpClient
from ..providers.llm_base import LLMProvider
from ..providers.registry import build_provider, describe
from ..runtime.budgets import BudgetLimits, RunBudget
from ..storage import repository as repo
from ..storage.cache import ResponseCache
from ..storage.db import Database, get_db
from .changes import compat_profile, diff_profile
from .envelope import build_envelope, validate_envelopes
from .io import InputError, load_bulk, read_jsonl, read_organisation_inputs, write_jsonl

log = get_logger("batch")


@dataclass
class BatchConfig:
    organisations: str
    output: str
    bulk: str | None = None
    profiles_output: str | None = None
    report: str | None = None
    run_id: str | None = None
    expected_count: int | None = None
    previous_profiles: str | None = None
    max_requests: int | None = None
    max_cost_usd: float | None = None
    max_runtime_seconds: float | None = None
    budget_headroom: float | None = None
    workers: int | None = None
    resume: bool = False
    fresh: bool = False
    mode: str = "competition"
    # test / embedding hooks
    transport: httpx.AsyncBaseTransport | None = None
    provider: LLMProvider | None = field(default=None, repr=False)
    use_provider_override: bool = False
    db: Database | None = None


async def run_batch(cfg: BatchConfig, settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    started_at = now_iso()
    t0 = time.monotonic()
    inputs = read_organisation_inputs(cfg.organisations)
    orgs = [i["organisation_number"] for i in inputs]
    if cfg.expected_count is not None and len(orgs) != cfg.expected_count:
        raise InputError(f"Expected {cfg.expected_count} organisations, received {len(orgs)}")
    bulk_rows, bulk_meta = load_bulk(cfg.bulk, orgs)
    previous: dict[str, dict[str, Any]] = {}
    if cfg.previous_profiles:
        previous = {row["organisation_number"]: row for row in read_jsonl(cfg.previous_profiles) if row.get("organisation_number")}
    run_id = cfg.run_id or new_run_id("batch")

    limits = BudgetLimits(
        max_requests=cfg.max_requests if cfg.max_requests is not None else s.max_requests,
        max_cost_usd=cfg.max_cost_usd if cfg.max_cost_usd is not None else s.max_external_cost_usd,
        max_runtime_seconds=cfg.max_runtime_seconds if cfg.max_runtime_seconds is not None else s.max_run_seconds,
        headroom=cfg.budget_headroom if cfg.budget_headroom is not None else s.budget_headroom,
        finalize_reserve_seconds=s.finalize_reserve_seconds,
    )
    budget = RunBudget(limits)
    db = cfg.db or get_db()
    cache = None if cfg.fresh else ResponseCache(db)
    workers = max(1, min(cfg.workers or s.max_concurrency, 32))
    repo.save_run(db, run_id, kind="batch", status="running", started_at=started_at, finished_at=None, input_count=len(orgs), completed_count=0, requests=0,
                  cost_usd=0.0, llm_calls=0, report=None)

    records: dict[str, dict[str, Any]] = {}
    resumed = 0
    if cfg.resume:
        for org in orgs:
            rec = repo.company_run_record(db, run_id, org)
            if rec is not None:
                records[org] = rec
                resumed += 1
    runtimes: list[int] = []
    async with HttpClient(transport=cfg.transport, cache=cache, recorder=repo.tool_call_recorder(db)) as http:
        provider = cfg.provider if cfg.use_provider_override else build_provider(http, s)
        orch = Orchestrator(http=http, run_budget=budget, provider=provider, settings=s)
        sem = asyncio.Semaphore(workers)
        done = 0

        async def one(org: str) -> None:
            nonlocal done
            if org in records:
                return
            async with sem:
                if budget.remaining_seconds() <= limits.finalize_reserve_seconds or (limits.max_requests is not None and budget.spend.requests >= limits.max_requests):
                    record = orch.offline_record(org, run_id=run_id, bulk_row=bulk_rows.get(org), bulk_meta=bulk_meta)
                else:
                    record = await orch.research(org, run_id=run_id, bulk_row=bulk_rows.get(org), bulk_meta=bulk_meta,
                                                 options=ResearchOptions(mode=cfg.mode, fresh=cfg.fresh, include_geo=False))
            records[org] = record
            runtimes.append(int((record.get("operations") or {}).get("runtime_ms") or 0))
            try:
                repo.save_record(db, record)
            except Exception as exc:  # persistence problems never drop an envelope
                log_event(log, "save_failed", org_number=org, error=type(exc).__name__)
            done += 1
            if done % 10 == 0:
                log_event(log, "progress", run_id=run_id, done=done + resumed, total=len(orgs), requests=budget.spend.requests)

        await asyncio.gather(*(one(org) for org in orgs))

    completed_at = now_iso()
    envelopes = []
    profiles = []
    change_total = 0
    for org in orgs:
        record = records[org]
        profile = compat_profile(record)
        changes: list[dict[str, Any]] = []
        extra_errors: list[dict[str, Any]] = []
        if org in previous:
            try:
                changes = diff_profile(previous[org], profile)
            except ValueError as exc:
                extra_errors.append({"stage": "change_detection", "error": str(exc)})
        change_total += len(changes)
        envelopes.append(build_envelope(record, run_id=run_id, started_at=started_at, completed_at=completed_at, changes=changes, extra_errors=extra_errors))
        profiles.append(profile)
    validation = validate_envelopes(envelopes, orgs)
    write_jsonl(cfg.output, envelopes)
    if cfg.profiles_output:
        write_jsonl(cfg.profiles_output, profiles)
    report = _report(run_id, started_at, completed_at, time.monotonic() - t0, orgs, envelopes, records, budget, bulk_meta, validation, resumed, change_total,
                     previous, runtimes, s)
    if cfg.report:
        Path(cfg.report).parent.mkdir(parents=True, exist_ok=True)
        Path(cfg.report).write_text(_json(report), encoding="utf-8")
    repo.save_run(db, run_id, kind="batch", status="completed" if validation["passed"] else "failed", started_at=started_at, finished_at=completed_at,
                  input_count=len(orgs), completed_count=len(envelopes), requests=budget.spend.requests, cost_usd=budget.spend.cost_usd,
                  llm_calls=budget.spend.llm_calls, report=report)
    return report


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n"


def _report(run_id: str, started_at: str, completed_at: str, elapsed: float, orgs: list[str], envelopes: list[dict[str, Any]], records: dict[str, dict[str, Any]],
            budget: RunBudget, bulk_meta: dict[str, Any], validation: dict[str, Any], resumed: int, change_total: int, previous: dict[str, Any],
            runtimes: list[int], s: Settings) -> dict[str, Any]:
    field_counts: dict[str, dict[str, int]] = {}
    for env in envelopes:
        for c in env["claims"]:
            row = field_counts.setdefault(c["field"], {"available": 0, "not_available": 0, "blocked": 0, "not_applicable": 0, "ambiguous": 0, "failed": 0})
            row[c["availability"]] = row.get(c["availability"], 0) + 1
    core = ["legal_name", "registration_status", "industry_code", "registered_employees", "ceo", "board_chair", "revenue", "official_website", "business_description",
            "open_positions_count"]
    companies_with = {f: sum(1 for env in envelopes if any(c["field"] == f and c["availability"] == "available" for c in env["claims"])) for f in core}
    module_states: dict[str, dict[str, int]] = {}
    for env in envelopes:
        for m, st in (env.get("modules") or {}).items():
            module_states.setdefault(m, {}).setdefault(st["state"], 0)
            module_states[m][st["state"]] += 1
    rejections: dict[str, int] = {}
    for rec in records.values():
        for r in rec.get("rejections") or []:
            rejections[r.get("reason", "?")] = rejections.get(r.get("reason", "?"), 0) + 1
    runtimes_sorted = sorted(runtimes)
    snap = budget.snapshot()
    return {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "elapsed_seconds": round(elapsed, 2),
        "expected_count": len(orgs),
        "emitted_envelopes": len(envelopes),
        "resumed_profiles": resumed,
        "registry": bulk_meta,
        "llm": describe(s),
        "search_enabled": s.search_enabled,
        "operations": {
            "requests": snap["requests"],
            "third_party_cost_usd": snap["third_party_cost_usd"],
            "llm_calls": snap["llm_calls"],
            "cache_hits": snap["cache_hits"],
            "requests_by_connector": snap["requests_by_connector"],
            "cost_by_connector": snap["cost_by_connector"],
            "blocked_by_budget": snap["blocked_by_budget"],
            "company_runtime_ms": {
                "p50": runtimes_sorted[len(runtimes_sorted) // 2] if runtimes_sorted else None,
                "p95": runtimes_sorted[min(len(runtimes_sorted) - 1, int(len(runtimes_sorted) * 0.95))] if runtimes_sorted else None,
                "mean": int(statistics.mean(runtimes_sorted)) if runtimes_sorted else None,
            },
            "requests_per_company": round(snap["requests"] / max(1, len(orgs) - resumed), 2),
            "cost_per_company_usd": round(snap["third_party_cost_usd"] / max(1, len(orgs) - resumed), 6),
        },
        "budget": snap["limits"],
        "coverage": {
            "companies_with_field": companies_with,
            "available_claims": sum(v["available"] for v in field_counts.values()),
            "claims_by_field": field_counts,
        },
        "module_states": module_states,
        "entity_states": {st: sum(1 for e in envelopes if e["state"] == st) for st in sorted({e["state"] for e in envelopes})},
        "identity": {
            "verified_websites": companies_with.get("official_website", 0),
            "ambiguous_websites": sum(1 for e in envelopes if (e.get("modules") or {}).get("website", {}).get("availability") == "ambiguous"),
            "rejected_observations": rejections,
            "website_attempts": _attempt_summary(envelopes),
        },
        "conflicts": sum(len(e.get("conflicts") or []) for e in envelopes),
        "change_detection": {"previous_profiles_loaded": len(previous), "total_changes": change_total},
        "errors": sum(len(e["errors"]) for e in envelopes),
        "validation": validation,
        "settings": s.limits_summary(),
    }


def _attempt_summary(envelopes: list[dict]) -> dict:
    """How website candidates fared, by origin and decision, with the most common reasons (diagnostics only)."""
    import re
    from collections import Counter

    by_outcome: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    for env in envelopes:
        for a in env.get("website_attempts") or []:
            by_outcome[f"{a.get('origin')} / {a.get('decision')}"] += 1
            if a.get("decision") not in ("verified",):
                reasons[f"{a.get('origin')}: " + re.sub(r"\d{9}", "<org>", re.sub(r"score [0-9.]+", "score n", a.get("note") or a.get("decision") or ""))[:80]] += 1
    return {"by_origin_and_decision": dict(by_outcome.most_common()), "top_reasons": dict(reasons.most_common(8))}
