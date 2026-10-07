"""Official Signalpost OUTPUT_CONTRACT envelope, built from a research record.

Primary keys follow OUTPUT_CONTRACT.md exactly::

    organisation_number, run{run_id, started_at, completed_at, terminal_status},
    claims[{field, value, availability, confidence, evidence_ids}],
    evidence[{id, source_url, source_class, retrieved_at, content_sha256, claim_span}],
    changes[], errors[], operations{requests, runtime_ms, third_party_cost_usd}

Additional keys are additive only (reporting periods, labels, module states,
synthesis) so a strict reader of the contract is unaffected.
"""
from __future__ import annotations

from typing import Any

from ..evidence.models import AVAILABILITY_STATES

# Starter-kit module terminal states (validator compatibility).
TERMINAL_STATES = {"complete", "not_applicable", "not_found", "blocked_policy", "blocked_robots", "source_error", "budget_exhausted", "submission_error"}
CORE_MODULES = ("registry_live", "roles", "locations", "group", "financials", "financial_history", "website", "jobs")


def module_terminal_state(mod: dict[str, Any] | None) -> str:
    if not mod:
        return "submission_error"
    state = mod.get("state")
    cls = mod.get("classification")
    note = str(mod.get("note") or "").casefold()
    if cls == "budget_exhausted" or "budget_exhausted" in note:
        return "budget_exhausted"
    if state == "available":
        return "complete"
    if state == "not_applicable":
        return "not_applicable"
    if state in ("not_available", "ambiguous"):
        return "not_found"
    if state == "blocked":
        return "blocked_robots" if (cls == "robots_disallowed" or "robots" in note) else "blocked_policy"
    if state == "failed":
        return "source_error"
    return "submission_error"


def _latest_periods(claims: list[dict[str, Any]]) -> dict[str, str]:
    latest: dict[str, str] = {}
    for c in claims:
        rp = c.get("reporting_period")
        if rp and c.get("availability") == "available" and rp > latest.get(c["field"], ""):
            latest[c["field"]] = rp
    return latest


def contract_claims(record: dict[str, Any]) -> list[dict[str, Any]]:
    claims = record.get("claims") or []
    latest = _latest_periods(claims)
    out: list[dict[str, Any]] = []
    for c in claims:
        item = {"field": c["field"], "value": c["value"], "availability": c["availability"], "confidence": c["confidence"], "evidence_ids": list(c.get("evidence_ids") or [])}
        for key in ("label", "key_suffix", "reporting_period", "period_label", "unit", "currency", "as_of", "effective_from", "effective_to", "extraction_method"):
            if c.get(key) not in (None, ""):
                item[key] = c[key]
        if c.get("reporting_period"):
            item["temporal"] = "current" if c["reporting_period"] == latest.get(c["field"]) else "historical"
        elif c.get("current") is False:
            item["temporal"] = "historical"
        if c.get("conflict"):
            item["conflict"] = c["conflict"]
        out.append(item)
    for a in record.get("absences") or []:
        out.append({"field": a["field"], "value": None, "availability": a["availability"], "confidence": None, "evidence_ids": list(a.get("evidence_ids") or []),
                    "note": a.get("note")})
    if not out:
        # An unresolvable organisation number still gets one terminal claim.
        state = "failed" if record.get("entity_state") in ("submission_error", "source_error") else (
            "blocked" if record.get("entity_state") in ("blocked_policy", "blocked_robots", "budget_exhausted") else "not_available")
        out.append({"field": "legal_name", "value": None, "availability": state, "confidence": None, "evidence_ids": [],
                    "note": "The organisation number could not be resolved in Enhetsregisteret."})
    return out


def contract_evidence(record: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for e in record.get("evidence") or []:
        item = {"id": e["id"], "source_url": e.get("source_url"), "source_class": e.get("source_class"), "retrieved_at": e.get("retrieved_at"),
                "content_sha256": e.get("content_sha256"), "claim_span": e.get("claim_span")}
        for key in ("source_name", "extraction_method", "document_title", "reporting_period"):
            if e.get(key):
                item[key] = e[key]
        out.append(item)
    return out


def contract_errors(record: dict[str, Any]) -> list[dict[str, Any]]:
    errors = [dict(e) for e in record.get("errors") or []]
    for name, mod in (record.get("modules") or {}).items():
        if mod.get("state") == "failed":
            errors.append({"stage": name, "error": mod.get("note") or mod.get("classification") or "source error", "source_url": mod.get("url"),
                           "classification": mod.get("classification"), "retryable": mod.get("classification") in ("timeout", "network", "server_error", "rate_limited")})
    return errors


def synthesis_block(record: dict[str, Any], claims: list[dict[str, Any]], changes: list[dict[str, Any]]) -> dict[str, Any]:
    summary = record.get("summary") or {}
    available = [c for c in claims if c["availability"] == "available"]
    by_field: dict[str, list[dict[str, Any]]] = {}
    for c in available:
        by_field.setdefault(c["field"], []).append(c)

    def fact(field: str, label: str) -> dict[str, Any] | None:
        items = by_field.get(field)
        if not items:
            return None
        best = max(items, key=lambda c: c.get("reporting_period") or "")
        out = {"label": label, "value": best["value"], "evidence_ids": best["evidence_ids"]}
        if best.get("period_label"):
            out["period"] = best["period_label"]
        return out

    def collect(*items: dict[str, Any] | None) -> list[dict[str, Any]]:
        return [i for i in items if i]

    people = [{"name": c["value"], "role": c.get("label"), "evidence_ids": c["evidence_ids"]} for f in ("ceo", "board_chair", "deputy_chair", "board_member", "proprietor", "auditor")
              for c in by_field.get(f, [])]
    return {
        "summary": summary.get("text") or "",
        "method": summary.get("method"),
        "sentences": summary.get("sentences") or [],
        "sections": {
            "COMPANY": collect(fact("legal_name", "Legal name"), fact("legal_form", "Legal form"), fact("industry_label", "Industry"), fact("registration_status", "Status"),
                               fact("founded_date", "Founded"), fact("registered_employees", "Employees"), fact("official_website", "Verified website"),
                               fact("business_description", "Business description")),
            "PEOPLE": people,
            "LOCATIONS": collect(fact("business_address", "Business address"), fact("municipality", "Municipality"), fact("registered_establishment_count", "Registered establishments")),
            "FINANCIALS": collect(fact("revenue", "Revenue"), fact("operating_result", "Operating result"), fact("annual_result", "Annual result"),
                                  fact("total_assets", "Total assets"), fact("equity", "Equity"), fact("debt", "Debt")),
            "HIRING": [{"value": c["value"], "evidence_ids": c["evidence_ids"]} for c in by_field.get("job_posting", [])],
            "PUBLIC_ACTIVITY": [{"value": c["value"], "date": c.get("as_of"), "evidence_ids": c["evidence_ids"]} for c in by_field.get("news_item", [])],
            "RECENT_CHANGES": [{"field": ch.get("field"), "old_value": ch.get("old_value"), "new_value": ch.get("new_value"), "source_url": ch.get("source_url"),
                                "retrieved_at": ch.get("retrieved_at")} for ch in changes],
            "UNKNOWN": sorted({c["field"] for c in claims if c["availability"] != "available"}),
            "SOURCES": list(dict.fromkeys(e.get("source_url") for e in record.get("evidence") or [] if e.get("source_url"))),
        },
        "policy": "Every statement derives from available, evidence-linked claims; unknown fields are listed, never guessed.",
    }


def build_envelope(record: dict[str, Any], *, run_id: str, started_at: str | None = None, completed_at: str | None = None,
                   changes: list[dict[str, Any]] | None = None, extra_errors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    claims = contract_claims(record)
    changes = changes or []
    ops = record.get("operations") or {}
    modules = record.get("modules") or {}
    module_states = {}
    for name in CORE_MODULES:
        mod = modules.get(name)
        module_states[name] = {"state": module_terminal_state(mod), "availability": (mod or {}).get("state"), "retry_count": 0,
                               "final_timestamp": (mod or {}).get("retrieved_at") or record.get("completed_at"), "note": (mod or {}).get("note")}
    if "registry" in modules:
        module_states["registry"] = {"state": module_terminal_state(modules["registry"]), "availability": "available", "retry_count": 0,
                                     "final_timestamp": modules["registry"].get("retrieved_at"), "note": None}
    entity_state = record.get("entity_state") or "complete"
    if entity_state not in TERMINAL_STATES:
        entity_state = "submission_error"
    terminal_status = record.get("terminal_status") or ("failed" if entity_state == "submission_error" else "completed")
    envelope = {
        "organisation_number": record["organisation_number"],
        "run": {"run_id": run_id, "started_at": started_at or record.get("started_at"), "completed_at": completed_at or record.get("completed_at"),
                "terminal_status": terminal_status},
        "claims": claims,
        "evidence": contract_evidence(record),
        "changes": changes,
        "errors": contract_errors(record) + list(extra_errors or []),
        "operations": {
            "requests": int(ops.get("requests") or 0),
            "runtime_ms": int(ops.get("runtime_ms") or 0),
            "third_party_cost_usd": round(float(ops.get("third_party_cost_usd") or 0.0), 6),
            "llm_calls": int((ops.get("llm") or {}).get("calls") or ops.get("llm_calls") or 0),
            "requests_by_connector": ops.get("requests_by_connector") or {},
        },
        # -- additive keys --
        "state": entity_state,
        "modules": module_states,
        "synthesis": synthesis_block(record, claims, changes),
    }
    attempts = [{k: a.get(k) for k in ("domain", "origin", "state", "decision", "score", "signals", "conflicts", "note")} for a in record.get("site_attempts") or []]
    if attempts:
        envelope["website_attempts"] = attempts
    conflicts = [{"field": c["field"], "reporting_period": c.get("reporting_period"), **c["conflict"]} for c in record.get("claims") or [] if c.get("conflict")]
    if conflicts:
        envelope["conflicts"] = conflicts
    return envelope


def validate_envelope(env: dict[str, Any]) -> list[str]:
    """Structural checks for one envelope (contract + evidence integrity)."""
    problems: list[str] = []
    for key in ("organisation_number", "run", "claims", "evidence", "changes", "errors", "operations"):
        if key not in env:
            problems.append(f"missing key {key}")
    if problems:
        return problems
    if env["run"].get("terminal_status") not in ("completed", "failed"):
        problems.append("run.terminal_status is not terminal")
    ids = {e["id"] for e in env["evidence"]}
    for e in env["evidence"]:
        for key in ("id", "source_url", "source_class", "retrieved_at", "content_sha256", "claim_span"):
            if key not in e:
                problems.append(f"evidence {e.get('id')} missing {key}")
    if not env["claims"]:
        problems.append("no claims")
    for c in env["claims"]:
        if c.get("availability") not in AVAILABILITY_STATES:
            problems.append(f"claim {c.get('field')} has invalid availability {c.get('availability')}")
        missing = [i for i in c.get("evidence_ids") or [] if i not in ids]
        if missing:
            problems.append(f"claim {c.get('field')} cites unknown evidence {missing[:2]}")
        if c.get("availability") == "available":
            if c.get("value") is None:
                problems.append(f"available claim {c.get('field')} has no value")
            if not c.get("evidence_ids"):
                problems.append(f"available claim {c.get('field')} has no evidence")
        elif c.get("value") is not None:
            problems.append(f"non-available claim {c.get('field')} carries a value")
    return problems


def validate_envelopes(envelopes: list[dict[str, Any]], expected: list[str]) -> dict[str, Any]:
    orgs = [e.get("organisation_number") for e in envelopes]
    per = {e.get("organisation_number"): validate_envelope(e) for e in envelopes}
    invalid_states = [{"organisation_number": e.get("organisation_number"), "module": m, "state": s.get("state")}
                      for e in envelopes for m, s in (e.get("modules") or {}).items() if s.get("state") not in TERMINAL_STATES]
    checks = {
        "exact_expected_count": len(envelopes) == len(expected),
        "unique_organisation_numbers": len(orgs) == len(set(orgs)),
        "all_expected_present": set(orgs) == set(expected),
        "all_entity_states_terminal": all(e.get("state") in TERMINAL_STATES for e in envelopes),
        "all_module_states_terminal": not invalid_states,
        "all_runs_terminal": all((e.get("run") or {}).get("terminal_status") in ("completed", "failed") for e in envelopes),
        "evidence_integrity": not any(per.values()),
        "zero_silent_drops": len(envelopes) == len(expected) and set(orgs) == set(expected),
    }
    return {"passed": all(checks.values()), "checks": checks, "invalid_states": invalid_states[:50],
            "envelope_problems": {k: v[:5] for k, v in per.items() if v}}
