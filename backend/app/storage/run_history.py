"""Research-run snapshots: one row per run, kept beside the saved report versions.

A company has one Library card and a chain of report versions (identical evidence maps to one version). The run table is what remembers *each run*:
the mode, the focus or question, when it ran, how it ended, what it cost and which report version it produced — including runs that failed,
were cancelled or found nothing new.
"""
from __future__ import annotations

from typing import Any

from .db import Database, dumps, loads

TERMINAL = ("completed", "partial", "failed", "cancelled")


def save_run(db: Database, snap: dict[str, Any]) -> None:
    db.execute(
        """INSERT OR REPLACE INTO company_research_runs(id, org_number, artifact_id, mode, prompt, status, started_at, finished_at, profile_version_id,
                                                         previous_version_id, evidence_changed, summary_json, effort_json, steps_json, answer_json, issues_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (snap["id"], snap["org_number"], snap.get("artifact_id"), snap["mode"], snap.get("prompt"), snap["status"], snap["started_at"], snap.get("finished_at"),
         snap.get("profile_version_id"), snap.get("previous_version_id"), None if snap.get("evidence_changed") is None else int(bool(snap["evidence_changed"])),
         dumps(snap.get("summary")), dumps(snap.get("effort")), dumps(snap.get("steps") or []), dumps(snap.get("answer")), dumps(snap.get("issues") or [])),
    )


def runs_for_org(db: Database, org: str, limit: int = 50) -> list[dict[str, Any]]:
    """Newest first (runs that start in the same second keep their save order)."""
    rows = db.all("SELECT * FROM company_research_runs WHERE org_number = ? ORDER BY started_at DESC, rowid DESC LIMIT ?", (org, limit))
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "id": r["id"], "mode": r["mode"], "prompt": r["prompt"], "status": r["status"], "startedAt": r["started_at"], "finishedAt": r["finished_at"],
            "profileVersionId": r["profile_version_id"], "previousVersionId": r["previous_version_id"],
            "evidenceChanged": None if r["evidence_changed"] is None else bool(r["evidence_changed"]),
            "summary": loads(r["summary_json"], None), "effort": loads(r["effort_json"], None), "steps": loads(r["steps_json"], []),
            "answer": loads(r["answer_json"], None), "issues": loads(r["issues_json"], []),
        })
    return out
