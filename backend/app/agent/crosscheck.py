"""Deep research: how well do independent sources agree on what was published?

The publication gate already merges observations per fact. This step *reports* the result of that merge so a Deep run shows its extra verification:
which facts are confirmed by two or more independent sources, which rest on a single source and which sources disagree. It reads the gated claims
only — it never adds, removes or upgrades a fact, and it never needs to find "more" to be useful: an honest "nothing could be cross-checked" is a result.
"""
from __future__ import annotations

from typing import Any

from ..evidence.gate import Claim, canonical_value

# Event-like records (one per announcement/notice/posting) are not facts that two sources would restate.
_NOT_CHECKED = {"news_item", "job_posting", "procurement_award", "procurement_notice_as_buyer", "summary", "website_title"}
SAMPLE = 8


def analyse(claims: list[Claim]) -> dict[str, Any]:
    checked = corroborated = conflicts = 0
    confirmed_items: list[dict[str, Any]] = []
    conflict_items: list[dict[str, Any]] = []
    for c in claims:
        if c.availability != "available" or c.field in _NOT_CHECKED or c.value in (None, ""):
            continue
        checked += 1
        agreeing = [o for o in c.observations if canonical_value(o.value) == canonical_value(c.value) and o.currency == c.currency]
        sources = sorted({o.source_name or o.source_id for o in agreeing})
        independent = len({o.source_id for o in agreeing})
        label = c.label or c.field.replace("_", " ").capitalize()
        if c.conflict:
            conflicts += 1
            if len(conflict_items) < SAMPLE:
                conflict_items.append({"field": c.field, "label": label, "reason": c.conflict.get("reason"),
                                       "candidates": [{"source": _source_of(cand), "value": str(cand.get("value"))[:80]} for cand in c.conflict.get("candidates", [])[:3]]})
        elif independent >= 2:
            corroborated += 1
            if len(confirmed_items) < SAMPLE:
                confirmed_items.append({"field": c.field, "label": label, "sources": sources[:4]})
    return {"checked": checked, "corroborated": corroborated, "singleSource": max(0, checked - corroborated - conflicts), "conflicts": conflicts,
            "corroboratedFacts": confirmed_items, "conflictFacts": conflict_items}


def _source_of(candidate: dict[str, Any]) -> str | None:
    obs = candidate.get("observations") or []
    return (obs[0].source_name if obs else None) or candidate.get("source_id")


def describe(result: dict[str, Any]) -> str:
    if not result["checked"]:
        return "No published facts were available to cross-check."
    parts = [f"{result['corroborated']} of {result['checked']} facts are confirmed by two or more independent sources",
             f"{result['singleSource']} rest on a single source"]
    parts.append(f"{result['conflicts']} source disagreement(s) kept visible" if result["conflicts"] else "no source disagreements")
    return "; ".join(parts) + "."
