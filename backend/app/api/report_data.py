"""The saved research view behind the Full Research Report (PDF) and the Evidence & Sources export.

Everything here reads the *saved* research record (``repo.latest_record``) and the profile built from it. Nothing is re-researched, re-fetched or
invented at export time: a fact that was not established stays "unavailable" and says why. Both exports share one numbering of sources (S1…) and
evidence (E1…) so a reference in the PDF can be found in the CSV/JSON export and the other way round.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.util import format_money
from ..errors import ApiError
from ..storage import repository as repo
from .sources import SourceIndex, to_frontend_evidence

NO_SAVED_RESEARCH = ("No saved research exists for this company yet, so there is nothing to export. Run research on the company first; "
                     "reports and evidence exports are built only from saved results.")

SECTION_TITLES = {
    "identity": "Company identity", "summary": "Executive summary", "metrics": "Key metrics", "financials": "Financial performance",
    "people": "People & leadership", "locations": "Locations & establishments", "digital": "Digital presence", "hiring": "Hiring & careers",
    "activity": "Recent activity", "changes": "Changes detected", "relationships": "Relationships", "coverage": "Research coverage",
}

MODULE_LABELS = {
    "registry_live": "Enhetsregisteret (live register lookup)", "registry": "Enhetsregisteret (bulk snapshot)", "roles": "Roles register (board, CEO)",
    "locations": "Registered establishments (sub-units)", "group": "Group structure (parent company)", "financials": "Regnskapsregisteret — annual accounts",
    "financial_history": "Regnskapsregisteret — filed annual reports (history)", "geo": "Kartverket Geonorge — address coordinates",
    "website": "Company website (identity-verified)", "jobs": "Careers pages and linked job boards", "nav_jobs": "NAV Arbeidsplassen job ads",
    "procurement_ted": "TED — EU public procurement", "procurement_doffin": "Doffin — public procurement (open data)",
    "ip": "Patentstyret — intellectual property", "linkedin": "LinkedIn", "shareholders": "Shareholder register", "industry": "Sector registry",
    "websearch": "Web search (discovery)",
}

MODULE_STATES = {"available": "Checked", "not_available": "Unavailable", "blocked": "Blocked", "not_applicable": "Not applicable / not part of this run",
                 "failed": "Failed", "source_error": "Source error", "ambiguous": "Ambiguous", "pending": "Not researched"}

# Verification vocabulary used by both exports. ``verified`` / ``unverified`` / ``conflict`` / ``unavailable`` describe a fact; the other two describe
# written text: ``ai_synthesis`` (a language model wrote it from the evidence) and ``compiled_from_facts`` (a fixed template over verified facts).
UNAVAILABLE_STATUS = {"not_available": "Unavailable", "blocked": "Blocked", "pending": "Not researched", "failed": "Failed", "researching": "In progress",
                      "ambiguous": "Ambiguous", "stale": "Stale"}
EVIDENCE_STATE_LABEL = {"verified": "Verified · 2+ sources", "primary": "Verified · primary", "secondary": "Secondary only",
                        "conflict": "Conflict", "unverified": "Unverified"}


def verification_of(fact: dict[str, Any]) -> tuple[str, str]:
    """(key, label) — one place decides how a fact is described, in the PDF and in the exports."""
    status = fact.get("status")
    if status != "verified":
        key = "unverified" if status in ("ambiguous", "stale") else "unavailable"
        return key, UNAVAILABLE_STATUS.get(status or "", "Unavailable")
    state = fact.get("evidenceState") or "unverified"
    key = {"verified": "verified", "primary": "verified", "conflict": "conflict"}.get(state, "unverified")
    return key, EVIDENCE_STATE_LABEL.get(state, "Unverified")


def derive_state(evidence: list[dict[str, Any]], sources: dict[str, dict[str, Any]]) -> str:
    """Evidence state for items that do not carry one (jobs, events, changes): the same rule the profile builder applies to facts."""
    if not evidence:
        return "unverified"
    primary = [e for e in evidence if (sources.get(e["sourceId"]) or {}).get("tier") == "primary"]
    distinct = {e["sourceId"] for e in evidence}
    return "verified" if len(distinct) >= 2 and primary else "primary" if primary else "secondary"


def display_value(f: dict[str, Any]) -> str:
    """The value as the profile shows it: the backend's own text, else an amount in the currency its filing states, else the plain value."""
    v = f.get("displayValue")
    if v:
        return str(v)
    val = f.get("value")
    if val is None:
        return ""
    if isinstance(val, bool):
        return "Yes" if val else "No"
    if isinstance(val, (int, float)) and f.get("currency"):
        return format_money(val, f["currency"])
    return str(val)


@dataclass
class Registry:
    """Numbers every source (S1…) and every piece of evidence (E1…) once, in the order the report first cites them."""

    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    source_numbers: dict[str, int] = field(default_factory=dict)

    def add(self, ev: dict[str, Any], support: dict[str, Any] | None = None) -> int:
        entry = self.evidence.get(ev["id"])
        if entry is None:
            entry = {"n": len(self.evidence) + 1, "id": ev["id"], "evidence": ev, "supports": []}
            self.evidence[ev["id"]] = entry
        if support and support not in entry["supports"]:
            entry["supports"].append(support)
        return entry["n"]

    def number(self, ev_id: str) -> int | None:
        entry = self.evidence.get(ev_id)
        return entry["n"] if entry else None

    def entries(self) -> list[dict[str, Any]]:
        return sorted(self.evidence.values(), key=lambda e: e["n"])

    def source_number(self, source_id: str) -> int | None:
        return self.source_numbers.get(source_id)


@dataclass
class SavedResearch:
    org: str
    record: dict[str, Any]
    profile: dict[str, Any]
    versions: list[dict[str, Any]]
    change_log: list[dict[str, Any]]
    generated_at: str
    items: list[dict[str, Any]] = field(default_factory=list)
    registry: Registry = field(default_factory=Registry)

    @property
    def company(self) -> dict[str, Any]:
        return self.profile["company"]

    @property
    def summary_method(self) -> str | None:
        return (self.record.get("summary") or {}).get("method")

    @property
    def is_full_research(self) -> bool:
        return self.record.get("mode") != "registry"


def load_saved_research(s: Any, org: str, *, generated_at: str) -> SavedResearch:
    """Load the latest saved record for ``org``. Raises a clear 404 when none exists — never triggers new research."""
    record = repo.latest_record(s.db, org)
    if record is None or not record.get("identity"):
        raise ApiError("not_found", NO_SAVED_RESEARCH, status=404)
    profile = s.profile_for(record)
    sr = SavedResearch(org=org, record=record, profile=profile, versions=repo.record_versions(s.db, org), change_log=repo.changes_for(s.db, org, limit=2000),
                       generated_at=generated_at)
    return build_view(sr)


def build_view(sr: SavedResearch) -> SavedResearch:
    """Collect every item that carries evidence and number the evidence and sources (deterministic, in report order)."""
    extra: dict[str, dict[str, Any]] = {}
    sr.items = collect_items(sr.profile, sr.record, extra)
    reg = Registry()
    source_index = dict(sr.profile.get("sourceIndex") or {})
    for item in sr.items:
        support = {"section": item["section"], "label": item["label"], "itemId": item["id"], "reportingPeriod": item.get("reportingPeriod")}
        for ev in item["evidence"]:
            reg.add(ev, support)
            source_index.setdefault(ev["sourceId"], {"id": ev["sourceId"], "name": ev["sourceId"], "kind": "web", "tier": "secondary", "official": False})
    for sid, src in extra.items():
        source_index.setdefault(sid, src)
    usage = [u["source"]["id"] for u in sr.profile.get("sources") or []]
    order = [sid for sid in usage if sid in source_index] + [sid for sid in sorted(source_index) if sid not in usage]
    reg.sources = {sid: source_index[sid] for sid in order}
    reg.source_numbers = {sid: i + 1 for i, sid in enumerate(order)}
    sr.registry = reg
    return sr


def _fact_item(section: str, f: dict[str, Any], **extra: Any) -> dict[str, Any]:
    vkey, vlabel = verification_of(f)
    item = {"section": section, "type": "fact", "id": f["id"], "field": f.get("field") or f["id"], "label": f["label"], "value": f.get("value"),
            "display": display_value(f), "currency": f.get("currency"), "unit": f.get("unit"), "reportingPeriod": f.get("reportingPeriod"), "status": f["status"],
            "evidenceState": f.get("evidenceState"), "verification": vkey, "verificationLabel": vlabel, "freshness": f.get("freshness"),
            "verifiedAt": f.get("verifiedAt"), "note": f.get("note"), "conflict": f.get("conflict"), "evidence": list(f.get("evidence") or [])}
    item.update(extra)
    return item


def _plain_item(section: str, typ: str, iid: str, label: str, display: str, evidence: list[dict[str, Any]], sources: dict[str, dict[str, Any]], **extra: Any) -> dict[str, Any]:
    state = derive_state(evidence, sources)
    vkey = {"verified": "verified", "primary": "verified"}.get(state, "unverified")
    item = {"section": section, "type": typ, "id": iid, "field": f"{section}.{typ}", "label": label, "value": display, "display": display, "currency": None, "unit": None,
            "reportingPeriod": None, "status": "verified" if evidence else "not_available", "evidenceState": state, "verification": vkey,
            "verificationLabel": EVIDENCE_STATE_LABEL[state], "freshness": None, "verifiedAt": None, "note": None, "conflict": None, "evidence": list(evidence)}
    item.update(extra)
    return item


def collect_items(profile: dict[str, Any], record: dict[str, Any], extra_sources: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Every fact / job / event / change / summary of the saved view, in the order the report presents them. Facts shown twice (the registered address is
    both an identity fact and a location) appear once."""
    P = profile
    sources = P.get("sourceIndex") or {}
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        if item["id"] in seen:
            return
        seen.add(item["id"])
        items.append(item)

    for f in P["identity"].values():
        if isinstance(f, dict) and "evidence" in f:
            add(_fact_item("identity", f))
    if P.get("description"):
        add(_fact_item("identity", P["description"]))
    summary = record.get("summary") or {}
    if summary.get("text"):
        ev_by_id = {e["id"]: e for it in items for e in it["evidence"]}
        raw = {e["id"]: e for e in record.get("evidence") or []}
        domain = (record.get("website") or {}).get("domain") if (record.get("website") or {}).get("verified") else None
        idx = SourceIndex(P["company"]["orgNumber"], domain)
        evidence = []
        for eid in summary.get("evidence_ids") or []:
            ev = ev_by_id.get(eid) or (to_frontend_evidence(raw[eid], idx, P["company"]["legalName"]) if eid in raw else None)
            if ev:
                evidence.append(ev)
        sources = {**idx.sources, **sources}
        if extra_sources is not None:
            extra_sources.update({sid: src for sid, src in idx.sources.items() if sid not in (P.get("sourceIndex") or {})})
        method = summary.get("method")
        vkey, vlabel = ("ai_synthesis", "AI synthesis — not a verified fact") if method == "llm_grounded" else ("compiled_from_facts", "Compiled from verified facts (template, no AI)")
        add({"section": "summary", "type": "summary", "id": f"{P['company']['orgNumber']}:summary", "field": "summary.text", "label": "Executive summary", "value": summary["text"],
             "display": summary["text"], "currency": None, "unit": None, "reportingPeriod": None, "status": "verified", "evidenceState": derive_state(evidence, sources),
             "verification": vkey, "verificationLabel": vlabel, "freshness": None, "verifiedAt": summary.get("generated_at"), "note": None, "conflict": None,
             "evidence": evidence, "method": method, "sentences": summary.get("sentences") or []})
    for f in P["keyMetrics"]:
        add(_fact_item("metrics", f))
    for series in P["financials"]["series"]:
        for pt in series["points"]:
            add(_fact_item("financials", pt["fact"], reportingPeriod=pt["period"], seriesKey=series["key"]))
    for person in P["people"]["people"]:
        add(_fact_item("people", person["fact"], role=person["role"], person=person["name"]))
    for loc in P["locations"]["locations"]:
        add(_fact_item("locations", loc["fact"]))
    web = P["website"]
    if web.get("verification"):
        add(_fact_item("digital", web["verification"]))
    if web.get("description"):
        add(_fact_item("digital", web["description"]))
    for soc in web.get("social") or []:
        add(_fact_item("digital", soc["fact"]))
    for sig in web.get("signals") or []:
        if sig.get("fact"):
            add(_fact_item("digital", sig["fact"]))
    for job in P["hiring"]["jobs"]:
        add(_plain_item("hiring", "job", job["id"], job["title"], f"{job['title']} ({job['state']})", job["evidence"], sources,
                        reportingPeriod=job.get("postedAt"), note=f"Listing state: {job['state']}"))
    for ev in P["activity"]["events"]:
        add(_plain_item("activity", "event", ev["id"], ev["title"], ev["date"], ev["evidence"], sources, reportingPeriod=ev["date"]))
    for ch in P["changes"]["changes"]:
        add(_plain_item("changes", "change", ch["id"], ch["label"], f"{ch.get('previous') or '—'} → {ch.get('current') or '—'}", ch["evidence"], sources,
                        verifiedAt=ch.get("detectedAt")))
    for rel in P["relationships"]:
        add(_plain_item("relationships", "relationship", rel["id"], rel["label"], rel["entity"]["name"], rel["evidence"], sources))
    for name, mod in (record.get("modules") or {}).items():
        if mod.get("state") != "available":
            state = mod.get("state") or "not_available"
            add({"section": "coverage", "type": "source_check", "id": f"{P['company']['orgNumber']}:module.{name}", "field": f"modules.{name}",
                 "label": MODULE_LABELS.get(name, name), "value": MODULE_STATES.get(state, state), "display": MODULE_STATES.get(state, state), "currency": None, "unit": None,
                 "reportingPeriod": None, "status": "not_available" if state in ("not_available", "not_applicable") else state, "evidenceState": "unverified",
                 "verification": "unavailable", "verificationLabel": MODULE_STATES.get(state, state), "freshness": None, "verifiedAt": mod.get("retrieved_at"),
                 "note": mod.get("note"), "conflict": None, "evidence": []})
    return items


# ----------------------------------------------------------------------- Evidence & Sources export --
EVIDENCE_COLUMNS = [
    "org_number", "company", "section", "item_type", "item_id", "field", "label", "value", "raw_value", "currency", "reporting_period", "verification_status",
    "verification_detail", "fact_status", "evidence_state", "evidence_ref", "evidence_id", "source_ref", "source_id", "source_name", "source_kind", "source_tier",
    "official_source", "source_url", "document_title", "page", "evidence_excerpt", "excerpt_language", "excerpt_translation", "evidence_reporting_period",
    "stated_value", "retrieved_at", "verified_at", "freshness", "note", "research_completed_at", "research_mode", "exported_at",
]


def _source_of(sr: SavedResearch, ev: dict[str, Any]) -> dict[str, Any]:
    return sr.registry.sources.get(ev["sourceId"]) or {"id": ev["sourceId"], "name": ev["sourceId"]}


def evidence_rows(sr: SavedResearch) -> list[dict[str, Any]]:
    """One row per (fact, piece of evidence). A fact with no evidence — unavailable, or never evidenced — still gets one row, so what is *missing* is as
    visible as what is known."""
    c = sr.company
    base = {"org_number": c["orgNumber"], "company": c["legalName"], "research_completed_at": sr.record.get("completed_at") or "",
            "research_mode": sr.record.get("mode") or "", "exported_at": sr.generated_at}
    rows: list[dict[str, Any]] = []
    for it in sr.items:
        raw = it["value"] if isinstance(it["value"], (int, float)) and not isinstance(it["value"], bool) else ""
        if isinstance(raw, float) and raw.is_integer():
            raw = int(raw)  # 21789260, not 21789260.0
        row = {**base, "section": SECTION_TITLES.get(it["section"], it["section"]), "item_type": it["type"], "item_id": it["id"], "field": it["field"], "label": it["label"],
               "value": it["display"], "raw_value": raw, "currency": it.get("currency") or "", "reporting_period": it.get("reportingPeriod") or "",
               "verification_status": it["verification"], "verification_detail": it["verificationLabel"], "fact_status": it["status"],
               "evidence_state": it.get("evidenceState") or "", "verified_at": it.get("verifiedAt") or "", "freshness": it.get("freshness") or "", "note": it.get("note") or ""}
        if not it["evidence"]:
            rows.append({**row, **{k: "" for k in EVIDENCE_COLUMNS if k not in row}})
            continue
        for ev in it["evidence"]:
            src = _source_of(sr, ev)
            rows.append({**row, "evidence_ref": f"E{sr.registry.number(ev['id'])}", "evidence_id": ev["id"], "source_ref": f"S{sr.registry.source_number(ev['sourceId']) or ''}",
                         "source_id": ev["sourceId"], "source_name": src.get("name", ""), "source_kind": src.get("kind", ""), "source_tier": src.get("tier", ""),
                         "official_source": "yes" if src.get("official") else "no", "source_url": ev.get("url") or "", "document_title": ev.get("documentTitle") or "",
                         "page": ev.get("page") or "", "evidence_excerpt": ev.get("excerpt") or "", "excerpt_language": ev.get("excerptLanguage") or "",
                         "excerpt_translation": ev.get("excerptTranslation") or "", "evidence_reporting_period": ev.get("reportingPeriod") or "",
                         "stated_value": ev.get("statedValue") or "", "retrieved_at": ev.get("retrievedAt") or ""})
    return [{k: r.get(k, "") for k in EVIDENCE_COLUMNS} for r in rows]


def evidence_json(sr: SavedResearch) -> dict[str, Any]:
    c = sr.company
    reg = sr.registry
    sources = [{"ref": f"S{reg.source_number(sid)}", **src} for sid, src in reg.sources.items()]
    evidence = []
    for entry in reg.entries():
        ev = entry["evidence"]
        evidence.append({"ref": f"E{entry['n']}", "sourceRef": f"S{reg.source_number(ev['sourceId'])}", **ev,
                         "supports": [{"section": SECTION_TITLES.get(s["section"], s["section"]), "label": s["label"], "itemId": s["itemId"], "reportingPeriod": s["reportingPeriod"]}
                                      for s in entry["supports"]]})
    facts = []
    for it in sr.items:
        facts.append({"section": SECTION_TITLES.get(it["section"], it["section"]), "type": it["type"], "id": it["id"], "field": it["field"], "label": it["label"],
                      "value": it["value"], "displayValue": it["display"], "currency": it.get("currency"), "reportingPeriod": it.get("reportingPeriod"),
                      "verification": it["verification"], "verificationLabel": it["verificationLabel"], "status": it["status"], "evidenceState": it.get("evidenceState"),
                      "freshness": it.get("freshness"), "verifiedAt": it.get("verifiedAt"), "note": it.get("note"), "conflict": it.get("conflict"),
                      "evidenceRefs": [f"E{reg.number(e['id'])}" for e in it["evidence"]]})
    counts: dict[str, int] = {}
    for it in sr.items:
        counts[it["verification"]] = counts.get(it["verification"], 0) + 1
    return {"company": {"orgNumber": c["orgNumber"], "legalName": c["legalName"], "status": c.get("statusLabel")},
            "research": {"completedAt": sr.record.get("completed_at"), "mode": sr.record.get("mode"), "summaryMethod": sr.summary_method,
                         "versionsSaved": len(sr.versions)},
            "exportedAt": sr.generated_at, "counts": {"items": len(sr.items), "evidence": len(evidence), "sources": len(sources), **{f"verification.{k}": v for k, v in sorted(counts.items())}},
            "sources": sources, "evidence": evidence, "facts": facts}
