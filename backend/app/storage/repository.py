"""Persistence of research records (the database is the agent's memory).

``save_record`` writes, in one transaction: the company row, source snapshots,
evidence, current facts with version history, detected changes, a profile
version (the full record, hashed) and the company-run row. Saving the same
record twice is a no-op (idempotent by content hash).
"""
from __future__ import annotations

import json
from typing import Any

from ..core.util import now_iso, sha256_json, stable_id
from .db import Database, dumps, loads


def _value_sha(value: Any) -> str:
    return sha256_json(value)[:24]


def save_record(db: Database, record: dict[str, Any], *, changes: list[dict[str, Any]] | None = None, label: str | None = None) -> str:
    """Persist a research record. Returns the profile-version id."""
    org = record["organisation_number"]
    now = now_iso()
    content = {k: v for k, v in record.items() if k not in ("operations", "trace", "started_at", "completed_at", "run_id")}
    digest = sha256_json(content)
    version_id = "pv-" + stable_id(org, digest, length=16)
    identity = record.get("identity") or {}
    with db.transaction() as conn:
        existing = conn.execute("SELECT id FROM profile_versions WHERE id = ?", (version_id,)).fetchone()
        conn.execute(
            """INSERT INTO companies(org_number, legal_name, legal_form, status, municipality, municipality_number, industry_code, industry_label, website, employees,
                                     registry_json, first_seen_at, updated_at, last_researched_at, research_state)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(org_number) DO UPDATE SET legal_name=excluded.legal_name, legal_form=excluded.legal_form, status=excluded.status,
                 municipality=excluded.municipality, municipality_number=excluded.municipality_number, industry_code=excluded.industry_code,
                 industry_label=excluded.industry_label, website=excluded.website, employees=excluded.employees, registry_json=excluded.registry_json,
                 updated_at=excluded.updated_at, last_researched_at=excluded.last_researched_at, research_state=excluded.research_state""",
            (org, identity.get("legal_name"), identity.get("legal_form"), identity.get("status"), identity.get("municipality"), identity.get("municipality_number"),
             identity.get("industry_code"), identity.get("industry_label"), _official_site(record) or identity.get("website"), identity.get("employees"), dumps(identity),
             now, now, record.get("completed_at"), "researched" if record.get("mode") != "registry" else "not_researched"),
        )
        if existing is None:
            conn.execute("INSERT INTO profile_versions(id, org_number, created_at, content_sha256, research_json, label, run_id) VALUES (?,?,?,?,?,?,?)",
                         (version_id, org, record.get("completed_at") or now, digest, dumps(record), label, record.get("run_id")))
        else:
            # Same content re-researched: keep one version, refresh its timestamps (idempotent re-run).
            conn.execute("UPDATE profile_versions SET research_json = ?, created_at = ? WHERE id = ?", (dumps(record), record.get("completed_at") or now, version_id))
        for name, mod in (record.get("modules") or {}).items():
            if not mod.get("url") or not mod.get("retrieved_at"):
                continue
            snap_id = "snap-" + stable_id(org, name, mod.get("url"), mod.get("content_sha256") or mod.get("state"), length=16)
            conn.execute(
                """INSERT OR IGNORE INTO source_snapshots(id, org_number, source_name, source_class, url, canonical_url, final_url, retrieved_at, http_status,
                                                          content_type, content_sha256, normalized_sha256, title, bytes, identity_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (snap_id, org, mod.get("source_name") or name, mod.get("source_class") or "", mod.get("url"), mod.get("url"), mod.get("final_url"), mod.get("retrieved_at"),
                 mod.get("http_status"), None, mod.get("content_sha256"), _value_sha(mod.get("value")), None, None,
                 dumps((mod.get("value") or {}).get("identity_assessment")) if isinstance(mod.get("value"), dict) else None),
            )
        for ev in record.get("evidence") or []:
            conn.execute(
                """INSERT OR IGNORE INTO evidence(id, org_number, snapshot_id, field, source_name, source_class, source_url, retrieved_at, content_sha256, claim_span,
                                                  extraction_method, identity_score, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ev["id"], org, None, None, ev.get("source_name") or ev.get("source_id") or "", ev.get("source_class") or "", ev.get("source_url"), ev.get("retrieved_at") or now,
                 ev.get("content_sha256"), ev.get("claim_span"), ev.get("extraction_method"), ev.get("identity_score"), now),
            )
        seen_keys = set()
        for claim in record.get("claims") or []:
            key = claim["key"]
            seen_keys.add(key)
            vsha = _value_sha(claim["value"])
            row = conn.execute("SELECT value_sha, version FROM facts WHERE claim_key = ?", (key,)).fetchone()
            if row is None:
                conn.execute(
                    """INSERT INTO facts(claim_key, org_number, field, value_json, value_sha, availability, reporting_period, effective_from, effective_to, source_class,
                                         confidence, evidence_ids_json, first_seen_at, last_seen_at, version, current) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,1)""",
                    (key, org, claim["field"], dumps(claim["value"]), vsha, claim["availability"], claim.get("reporting_period"), claim.get("effective_from"),
                     claim.get("effective_to"), claim.get("source_class"), claim.get("confidence"), dumps(claim.get("evidence_ids")), now, now),
                )
                conn.execute("INSERT OR IGNORE INTO fact_versions(claim_key, version, value_json, observed_at, evidence_ids_json) VALUES (?,?,?,?,?)",
                             (key, 1, dumps(claim["value"]), now, dumps(claim.get("evidence_ids"))))
            elif row["value_sha"] != vsha:
                version = int(row["version"]) + 1
                conn.execute("""UPDATE facts SET value_json=?, value_sha=?, availability=?, confidence=?, evidence_ids_json=?, last_seen_at=?, version=?, current=1
                                WHERE claim_key=?""", (dumps(claim["value"]), vsha, claim["availability"], claim.get("confidence"), dumps(claim.get("evidence_ids")), now, version, key))
                conn.execute("INSERT OR IGNORE INTO fact_versions(claim_key, version, value_json, observed_at, evidence_ids_json) VALUES (?,?,?,?,?)",
                             (key, version, dumps(claim["value"]), now, dumps(claim.get("evidence_ids"))))
            else:
                conn.execute("UPDATE facts SET last_seen_at=?, current=1, evidence_ids_json=? WHERE claim_key=?", (now, dumps(claim.get("evidence_ids")), key))
        # Facts not re-observed in a run that checked their module become historical (never deleted).
        checked = {name for name, mod in (record.get("modules") or {}).items() if mod.get("state") == "available"}
        for row in conn.execute("SELECT claim_key, field FROM facts WHERE org_number = ? AND current = 1", (org,)).fetchall():
            if row["claim_key"] not in seen_keys and _module_for_field(row["field"]) in checked:
                conn.execute("UPDATE facts SET current = 0 WHERE claim_key = ?", (row["claim_key"],))
        for ch in changes or []:
            conn.execute(
                """INSERT OR IGNORE INTO changes(id, org_number, field, category, kind, old_value_json, new_value_json, detected_at, effective_at, source_url, source_class,
                                                 old_content_sha256, new_content_sha256, material, headline, payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ch["id"], org, ch["field"], ch.get("category"), ch.get("kind"), dumps(ch.get("old_value")), dumps(ch.get("new_value")), ch.get("detected_at") or now,
                 ch.get("effective_at"), ch.get("source_url"), ch.get("source_class"), ch.get("old_content_sha256"), ch.get("new_content_sha256"),
                 1 if ch.get("material", True) else 0, ch.get("headline"), dumps(ch)),
            )
        if record.get("run_id"):
            claims = record.get("claims") or []
            conn.execute(
                """INSERT OR REPLACE INTO company_runs(run_id, org_number, status, terminal_state, started_at, finished_at, requests, llm_calls, facts_found, facts_published,
                                                      facts_rejected, error_summary) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (record["run_id"], org, record.get("terminal_status") or "completed", record.get("entity_state"), record.get("started_at"), record.get("completed_at"),
                 int((record.get("operations") or {}).get("requests") or 0), int(((record.get("operations") or {}).get("llm") or {}).get("calls") or 0),
                 len(claims) + len(record.get("rejections") or []), len(claims), len(record.get("rejections") or []),
                 "; ".join(str(e.get("error")) for e in (record.get("errors") or [])[:3]) or None),
            )
    return version_id


def _official_site(record: dict[str, Any]) -> str | None:
    for c in record.get("claims") or []:
        if c["field"] == "official_website":
            return c["value"]
    return None


def _module_for_field(field: str) -> str:
    if field in ("ceo", "board_chair", "board_member", "deputy_board_member", "deputy_chair", "auditor", "accountant", "contact_person", "proprietor", "role_holders"):
        return "roles"
    if field.startswith("registered_establishment") or field == "registered_subunit_count":
        return "locations"
    if field in ("parent_company", "ultimate_parent_company", "subsidiary"):
        return "group"
    if field in ("job_posting", "open_positions_count"):
        return "jobs"
    if field in ("news_item", "official_website", "website_title", "website_description", "business_description", "contact_email", "contact_phone") or field.startswith("social_profile_"):
        return "website"
    return "registry_live"


# ------------------------------------------------------------------ reads --
def latest_record(db: Database, org: str) -> dict[str, Any] | None:
    row = db.one("SELECT research_json FROM profile_versions WHERE org_number = ? ORDER BY created_at DESC LIMIT 1", (org,))
    return loads(row["research_json"]) if row else None


def previous_record(db: Database, org: str, before_version: str | None = None) -> dict[str, Any] | None:
    rows = db.all("SELECT id, research_json FROM profile_versions WHERE org_number = ? ORDER BY created_at DESC LIMIT 2", (org,))
    if before_version:
        rows = [r for r in rows if r["id"] != before_version]
        return loads(rows[0]["research_json"]) if rows else None
    return loads(rows[1]["research_json"]) if len(rows) > 1 else None


def record_versions(db: Database, org: str) -> list[dict[str, Any]]:
    return [{"id": r["id"], "created_at": r["created_at"], "label": r["label"], "run_id": r["run_id"]}
            for r in db.all("SELECT id, created_at, label, run_id FROM profile_versions WHERE org_number = ? ORDER BY created_at DESC", (org,))]


def record_by_version(db: Database, version_id: str) -> dict[str, Any] | None:
    row = db.one("SELECT research_json FROM profile_versions WHERE id = ?", (version_id,))
    return loads(row["research_json"]) if row else None


def changes_for(db: Database, org: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = db.all("SELECT payload_json FROM changes WHERE org_number = ? ORDER BY detected_at DESC LIMIT ?", (org, limit))
    return [loads(r["payload_json"], {}) for r in rows]


def company_run_record(db: Database, run_id: str, org: str) -> dict[str, Any] | None:
    row = db.one("SELECT research_json FROM profile_versions WHERE org_number = ? AND run_id = ? ORDER BY created_at DESC LIMIT 1", (org, run_id))
    return loads(row["research_json"]) if row else None


def save_run(db: Database, run_id: str, *, kind: str, status: str, started_at: str, finished_at: str | None, input_count: int, completed_count: int,
             requests: int, cost_usd: float, llm_calls: int, report: dict[str, Any] | None) -> None:
    db.execute("""INSERT INTO research_runs(run_id, kind, status, started_at, finished_at, input_count, completed_count, requests, cost_usd, llm_calls, report_json)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET status=excluded.status, finished_at=excluded.finished_at,
                  completed_count=excluded.completed_count, requests=excluded.requests, cost_usd=excluded.cost_usd, llm_calls=excluded.llm_calls, report_json=excluded.report_json""",
               (run_id, kind, status, started_at, finished_at, input_count, completed_count, requests, cost_usd, llm_calls, json.dumps(report, default=str) if report else None))


def tool_call_recorder(db: Database):
    """HttpClient recorder → tool_calls table (URLs arrive already redacted)."""
    def record(row: dict[str, Any]) -> None:
        db.execute("""INSERT INTO tool_calls(run_id, org_number, connector, operation, url, classification, http_status, duration_ms, retries, from_cache, at)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                   (row.get("run_id"), row.get("org_number"), row.get("connector") or "", row.get("operation"), (row.get("url") or "")[:1000], row.get("classification"),
                    row.get("http_status"), row.get("duration_ms"), row.get("retries"), row.get("from_cache"), now_iso()))
    return record
