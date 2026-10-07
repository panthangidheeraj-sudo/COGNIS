"""The research record: one JSON document per company per run.

It is the single source for the evaluator envelope, the starter-compatible
profile (change detection), the frontend ``CompanyProfile`` and the database.
Evidence ids are deterministic: the same source bytes + span always get the
same id, which keeps re-runs idempotent.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..core.util import stable_id
from ..evidence.gate import Claim
from ..evidence.models import ModuleResult, Observation

if TYPE_CHECKING:  # pragma: no cover
    from .orchestrator import ResearchState

RECORD_SCHEMA = 1


def evidence_id(obs: Observation) -> str:
    return "ev-" + stable_id(obs.module, obs.source_url or "", obs.content_sha256 or "", obs.claim_span, length=16)


def module_evidence_id(mod: ModuleResult) -> str:
    return "ev-" + stable_id("module", mod.module, mod.url or "", mod.content_sha256 or "", mod.state, length=16)


def _evidence(obs: Observation) -> dict[str, Any]:
    return {
        "id": evidence_id(obs), "source_url": obs.source_url, "source_class": obs.source_class, "source_id": obs.source_id, "source_name": obs.source_name,
        "retrieved_at": obs.retrieved_at, "content_sha256": obs.content_sha256, "claim_span": obs.claim_span, "extraction_method": obs.extraction_method,
        "module": obs.module, "document_title": obs.document_title, "excerpt_language": obs.excerpt_language, "page": obs.page,
        "identity_score": round(obs.identity_score, 2), "reporting_period": obs.reporting_period, "tier": obs.tier,
        "translation": (obs.attributes or {}).get("translation"),
    }


def _module_evidence(mod: ModuleResult) -> dict[str, Any]:
    return {
        "id": module_evidence_id(mod), "source_url": mod.final_url or mod.url, "source_class": mod.source_class, "source_id": mod.source_id, "source_name": mod.source_name,
        "retrieved_at": mod.retrieved_at, "content_sha256": mod.content_sha256,
        "claim_span": (mod.note or f"{mod.module}: {mod.state}")[:300], "extraction_method": "source_status", "module": mod.module, "tier": mod.tier,
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return str(value)


def claim_to_dict(claim: Claim, org: str, evidence_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ids = []
    for obs in claim.observations:
        ev = _evidence(obs)
        evidence_index.setdefault(ev["id"], ev)
        if ev["id"] not in ids:
            ids.append(ev["id"])
    conflict = None
    if claim.conflict:
        conflict = {
            "reason": claim.conflict.get("reason"), "resolution": claim.conflict.get("resolution"),
            "candidates": [{"value": _jsonable(c["value"]), "currency": c.get("currency"), "source_class": c["source_class"], "source_id": c["source_id"], "source_url": c["source_url"],
                            "retrieved_at": c["retrieved_at"], "evidence_ids": [evidence_id(o) for o in c["observations"]]} for c in claim.conflict["candidates"]],
        }
    winner_ids = [evidence_id(o) for o in claim.observations if (o.value == claim.value and o.currency == claim.currency) or not claim.conflict] or ids
    return {
        "field": claim.field, "value": _jsonable(claim.value), "availability": claim.availability, "confidence": claim.confidence, "label": claim.label,
        "key": claim.key(org), "key_suffix": claim.key_suffix, "reporting_period": claim.reporting_period, "period_label": claim.period_label, "unit": claim.unit,
        "currency": claim.currency, "as_of": claim.as_of, "effective_from": claim.effective_from, "effective_to": claim.effective_to, "current": claim.current,
        "source_class": claim.source_class, "evidence_ids": list(dict.fromkeys(winner_ids)) if claim.conflict else ids, "conflict": conflict,
        "attributes": _jsonable({k: v for k, v in (claim.attributes or {}).items() if k not in ("quote_verified",)}),
        "extraction_method": claim.primary.extraction_method if claim.primary else None,
    }


def build_record(st: ResearchState, *, operations: dict[str, Any], completed_at: str) -> dict[str, Any]:
    org = st.org_number
    evidence_index: dict[str, dict[str, Any]] = {}
    claims = [claim_to_dict(c, org, evidence_index) for c in st.claims]
    all_modules = {**st.modules}
    for mod in st.extra_modules:
        name = mod.module
        i = 2
        while name in all_modules:
            name = f"{mod.module}_{i}"
            i += 1
        all_modules[name] = mod
    absences = []
    for ab in st.absence_list:
        ev_ids = []
        for name in ab.modules:
            mod = st.modules.get(name)
            if mod is None:
                continue
            ev = _module_evidence(mod)
            if mod.retrieved_at or mod.url:
                evidence_index.setdefault(ev["id"], ev)
                ev_ids.append(ev["id"])
        absences.append({"field": ab.field, "value": None, "availability": ab.availability, "confidence": None, "evidence_ids": ev_ids, "note": ab.note,
                         "modules": ab.modules})
    crawl = st.crawl
    website = None
    if crawl is not None:
        website = {
            "domain": crawl.domain, "url": crawl.homepage.final_url if crawl.homepage else crawl.start_url, "start_url": crawl.start_url, "origin": crawl.origin,
            "verified": crawl.verified, "state": crawl.state, "note": crawl.note, "source_class": crawl.source_class,
            "audit": crawl.audit.to_dict() if crawl.audit else None,
            "pages": [{"kind": p.kind, "url": p.doc.final_url if p.doc else p.result.url, "title": p.doc.title if p.doc else None, "status": p.result.classification,
                       "retrieved_at": p.result.retrieved_at, "content_sha256": p.result.content_sha256, "lang": p.doc.lang if p.doc else None} for p in crawl.pages],
            "social": crawl.social, "ats_links": [{"url": a.url, "text": a.text} for a in crawl.ats_links],
            "https": bool(crawl.homepage and crawl.homepage.final_url.startswith("https://")),
            "languages": sorted({(p.doc.lang or "")[:2] for p in crawl.pages if p.doc and p.doc.lang}),
        }
    identity = st.identity.to_dict() if st.identity else None
    return {
        "schema": RECORD_SCHEMA,
        "organisation_number": org,
        "run_id": st.run_id,
        "mode": st.options.mode,
        "started_at": st.started_at,
        "completed_at": completed_at,
        "entity_state": st.entity_state,
        "terminal_status": st.terminal_status,
        "identity": _jsonable(identity),
        "modules": {name: _jsonable(mod.snapshot_meta()) for name, mod in all_modules.items()},
        "claims": claims,
        "absences": absences,
        "evidence": sorted(evidence_index.values(), key=lambda e: e["id"]),
        "rejections": [_jsonable(r.__dict__) for r in st.rejections[:150]],
        "website": _jsonable(website),
        "site_attempts": _jsonable(st.site_attempts),
        "jobs": {"items": [j.to_dict() for j in st.jobs], "note": st.jobs_note, "checked": st.jobs_checked},
        "roles": _jsonable(st.roles),
        "locations": _jsonable(st.locations),
        "financial_records": _jsonable(st.financial_records),
        "summary": _jsonable(st.summary),
        "errors": _jsonable(st.errors),
        "trace": _jsonable(st.trace),
        "operations": _jsonable(operations),
    }
