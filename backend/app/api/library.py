"""Library (saved artifacts), versions, reports, watchlist signals and assessments."""
from __future__ import annotations

import re
from typing import Any

from ..connectors import brreg
from ..core.util import now_iso, stable_id
from ..errors import ApiError
from ..storage import repository as repo
from ..storage.db import dumps, loads

CAPABILITIES = {"rename": True, "duplicate": True, "tag": True, "archive": True, "delete": False, "refresh": True, "export": True, "pin": True}
SIGNAL_KIND = {"leadership": "leadership", "financial": "financial", "filing": "filing", "hiring": "hiring", "employees": "hiring", "location": "location",
               "address": "location", "status": "announcement", "ownership": "announcement", "event": "announcement"}


def company_artifact_id(org: str) -> str:
    return f"art-{org}"


def ensure_company_artifact(s: Any, record: dict[str, Any], version_id: str, label: str) -> str:
    org = record["organisation_number"]
    aid = company_artifact_id(org)
    now = now_iso()
    title = (record.get("identity") or {}).get("legal_name") or org
    s.db.execute("""INSERT INTO artifacts(id, type, title, org_number, created_at, updated_at, tags_json, pinned, archived, data_json)
                    VALUES (?, 'company', ?, ?, ?, ?, '[]', 0, 0, '{}')
                    ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at""", (aid, title, org, now, now))
    exists = s.db.one("SELECT id FROM artifact_versions WHERE artifact_id = ? AND profile_version_id = ?", (aid, version_id))
    if exists is None:
        s.db.execute("INSERT INTO artifact_versions(id, artifact_id, profile_version_id, created_at, label, note) VALUES (?,?,?,?,?,?)",
                     ("v-" + stable_id(aid, version_id, length=10), aid, version_id, record.get("completed_at") or now, label, None))
    return aid


def record_signals(s: Any, record: dict[str, Any], changes: list[dict[str, Any]]) -> None:
    org = record["organisation_number"]
    name = (record.get("identity") or {}).get("legal_name") or org
    for ch in changes:
        if not ch.get("material"):
            continue
        kind = SIGNAL_KIND.get(ch.get("category") or "", "announcement")
        title = f"{name}: {ch.get('headline') or ch.get('label')}"
        ev = [{"id": f"{ch['id']}-ev", "sourceId": "brreg" if (ch.get("field") or "").startswith(("registry", "roles", "locations")) else
               ("accounts" if (ch.get("field") or "").startswith("financ") else f"web-{org}"), "url": ch.get("source_url"),
               "retrievedAt": ch.get("retrieved_at") or ch.get("detected_at"), "excerpt": f"{ch.get('label')}: {ch.get('old_display') or '—'} → {ch.get('new_display') or '—'}"}]
        s.db.execute("INSERT OR IGNORE INTO signals(id, org_number, kind, title, detected_at, evidence_json, seen) VALUES (?,?,?,?,?,?,0)",
                     ("sig-" + ch["id"], org, kind, title, ch.get("detected_at") or now_iso(), dumps(ev)))


# --------------------------------------------------------------- summaries --
def _company_summary(s: Any, row: Any) -> dict[str, Any] | None:
    record = repo.latest_record(s.db, row["org_number"])
    if record is None:
        return None
    profile = s.profile_for(record)
    c = profile["company"]
    rev = next((x for x in profile["financials"]["series"] if x["key"] == "revenue"), None)
    out = {"id": row["id"], "type": "company", "title": row["title"], "subtitle": " · ".join(x for x in [(c.get("industry") or {}).get("description"), c.get("municipality")] if x),
           "orgNumber": row["org_number"], "municipality": c.get("municipality"), "updatedAt": row["updated_at"], "researchedAt": c.get("lastResearchedAt"),
           "coverage": c["coverage"], "tags": loads(row["tags_json"], []), "pinned": bool(row["pinned"]), "archived": bool(row["archived"]),
           "changeCount": c.get("changeCount") or 0, "openPositions": c.get("openPositions")}
    if row["viewed_at"]:
        out["viewedAt"] = row["viewed_at"]
    if rev and len(rev["points"]) >= 2:
        out["sparkline"] = [p["fact"]["value"] for p in rev["points"]]
    return {k: v for k, v in out.items() if v is not None or k == "openPositions"}


def _report_summary(row: Any) -> dict[str, Any]:
    data = loads(row["data_json"], {})
    return {"id": row["id"], "type": "report", "title": row["title"], "subtitle": "Company brief" if data.get("kind") == "company_brief" else "Deep research report",
            "orgNumber": row["org_number"], "updatedAt": row["updated_at"], "tags": loads(row["tags_json"], []), "pinned": bool(row["pinned"]),
            "archived": bool(row["archived"]), **({"viewedAt": row["viewed_at"]} if row["viewed_at"] else {})}


def _sheet_summaries(s: Any) -> list[dict[str, Any]]:
    out = []
    for sheet in s.sheets.list():
        meta = s.kv_get(f"sheet-meta:{sheet['id']}", {}) or {}
        out.append({"id": f"sheet-{sheet['id']}", "type": "data_sheet", "title": sheet["title"], "subtitle": sheet.get("description") or f"{sheet['rowCount']} companies",
                    "updatedAt": sheet["updatedAt"], "tags": meta.get("tags", []), "pinned": bool(meta.get("pinned")), "archived": bool(meta.get("archived")),
                    "targetId": sheet["id"], "itemCount": sheet["rowCount"]})
    return out


def _watchlist_summary(s: Any) -> list[dict[str, Any]]:
    rows = s.db.all("SELECT org_number, added_at FROM watchlist")
    if not rows:
        return []
    unseen = s.db.one("SELECT COUNT(DISTINCT org_number) AS n FROM signals WHERE seen = 0 AND org_number IN (SELECT org_number FROM watchlist)")["n"]
    updated = max(r["added_at"] for r in rows)
    return [{"id": "watchlist", "type": "watchlist", "title": "Watchlist", "subtitle": f"{len(rows)} companies", "updatedAt": updated, "tags": [], "pinned": False,
             "archived": False, "itemCount": len(rows), "changeCount": unseen}]


def all_summaries(s: Any, *, include_archived: bool = True) -> list[dict[str, Any]]:
    out = []
    for row in s.db.all("SELECT * FROM artifacts WHERE type IN ('company','report') ORDER BY updated_at DESC"):
        item = _company_summary(s, row) if row["type"] == "company" else _report_summary(row)
        if item:
            out.append(item)
    out += _sheet_summaries(s)
    out += _watchlist_summary(s)
    if not include_archived:
        out = [x for x in out if not x["archived"]]
    return out


def list_library(s: Any, *, q: str | None, type_: str, sort: str, page: int, page_size: int, tag: str | None, include_archived: bool) -> dict[str, Any]:
    items = all_summaries(s, include_archived=include_archived)
    if q:
        needle = q.casefold()
        items = [x for x in items if needle in (x["title"] + " " + (x.get("subtitle") or "") + " " + (x.get("orgNumber") or "") + " " + " ".join(x["tags"])).casefold()]
    if tag:
        items = [x for x in items if tag in x["tags"]]
    facets = {"all": len(items)}
    for t in ("company", "report", "data_sheet", "comparison", "watchlist", "saved_search"):
        facets[t] = sum(1 for x in items if x["type"] == t)
    if type_ and type_ != "all":
        items = [x for x in items if x["type"] == type_]
    keyfn = {
        "name": lambda x: x["title"].casefold(),
        "researched": lambda x: x.get("researchedAt") or "",
        "coverage": lambda x: (x.get("coverage") or {}).get("complete", -1),
        "changed": lambda x: x.get("changeCount") or 0,
    }.get(sort, lambda x: x["updatedAt"])
    items.sort(key=keyfn, reverse=sort != "name")
    items.sort(key=lambda x: not x["pinned"])
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    start = (page - 1) * page_size
    return {"items": items[start:start + page_size], "total": len(items), "page": page, "pageSize": page_size, "facets": facets}


def summary_by_id(s: Any, aid: str) -> dict[str, Any]:
    for item in all_summaries(s):
        if item["id"] == aid:
            return item
    raise ApiError("not_found", "This library item does not exist.", status=404)


# ------------------------------------------------------------- artifacts --
def _versions(s: Any, aid: str) -> list[dict[str, Any]]:
    rows = s.db.all("SELECT * FROM artifact_versions WHERE artifact_id = ? ORDER BY created_at DESC", (aid,))
    return [{"id": r["id"], "createdAt": r["created_at"], "label": "Current" if i == 0 else r["label"], "isCurrent": i == 0, **({"note": r["note"]} if r["note"] else {})}
            for i, r in enumerate(rows)]


def get_artifact(s: Any, aid: str, version_id: str | None = None) -> dict[str, Any]:
    row = s.db.one("SELECT * FROM artifacts WHERE id = ?", (aid,))
    if row is None or row["type"] not in ("company", "report"):
        raise ApiError("not_found", "This library item does not exist.", status=404)
    s.db.execute("UPDATE artifacts SET viewed_at = ? WHERE id = ?", (now_iso(), aid))
    if row["type"] == "report":
        data = loads(row["data_json"], {})
        record = repo.record_by_version(s.db, data.get("profile_version_id") or "") or repo.latest_record(s.db, row["org_number"])
        if record is None:
            raise ApiError("not_found", "The research behind this report is no longer available.", status=404)
        profile = s.profile_for(record)
        return {"id": aid, "type": "report", "title": row["title"], "kind": data.get("kind") or "company_brief", "orgNumber": row["org_number"], "createdAt": row["created_at"],
                "updatedAt": row["updated_at"], "sections": data.get("sections") or [], "profile": profile, "tags": loads(row["tags_json"], []), "pinned": bool(row["pinned"])}
    versions = _versions(s, aid)
    if not versions:
        raise ApiError("not_found", "This dossier has no saved research yet.", status=404)
    vid = version_id or versions[0]["id"]
    vrow = s.db.one("SELECT profile_version_id FROM artifact_versions WHERE id = ? AND artifact_id = ?", (vid, aid))
    if vrow is None:
        raise ApiError("not_found", "This version does not exist.", status=404)
    record = repo.record_by_version(s.db, vrow["profile_version_id"])
    if record is None:
        raise ApiError("not_found", "The research behind this version is no longer available.", status=404)
    profile = s.profile_for(record)
    profile["artifactId"] = aid
    latest = versions[0]
    return {"id": aid, "type": "company", "title": row["title"], "orgNumber": row["org_number"], "createdAt": row["created_at"], "updatedAt": row["updated_at"],
            "versionId": vid, "versions": versions, "tags": loads(row["tags_json"], []), "pinned": bool(row["pinned"]), "profile": profile,
            "freshness": {"state": "saved", "lastUpdatedAt": latest["createdAt"], "staleAreas": _stale_count(record), "changedSources": 0, "newFilings": 0}}


def _stale_count(record: dict[str, Any]) -> int:
    from ..core.util import parse_iso, utc_now

    done = parse_iso(record.get("completed_at"))
    if not done:
        return 0
    age_days = (utc_now() - done).total_seconds() / 86400
    return (1 if age_days > 7 else 0) + (1 if age_days > 30 else 0) + (1 if age_days > 1 else 0)


def compare_versions(s: Any, aid: str, from_id: str, to_id: str) -> dict[str, Any]:
    a = get_artifact(s, aid, from_id)
    b = get_artifact(s, aid, to_id)
    rows = []
    for key, label, fn in _VERSION_ROWS:
        va, vb = fn(a["profile"]), fn(b["profile"])
        rows.append({"key": key, "label": label, "from": va, "to": vb, "changed": va != vb})
    fv = next(v for v in a["versions"] if v["id"] == from_id)
    tv = next(v for v in b["versions"] if v["id"] == to_id)
    return {"artifactId": aid, "from": fv, "to": tv, "rows": rows}


def _latest(p: dict[str, Any], key: str) -> str | None:
    s = next((x for x in p["financials"]["series"] if x["key"] == key), None)
    if not s or not s["points"]:
        return None
    pt = s["points"][-1]
    return f"{pt['fact'].get('displayValue') or pt['fact']['value']} ({pt['period']})"


def _person(p: dict[str, Any], role: str) -> str | None:
    return next((x["name"] for x in p["people"]["people"] if x["role"] == role), None)


_VERSION_ROWS = [
    ("legalName", "Legal name", lambda p: p["company"]["legalName"]),
    ("status", "Status", lambda p: p["company"].get("statusLabel")),
    ("employees", "Registered employees", lambda p: None if p["company"].get("employees") is None else str(p["company"]["employees"])),
    ("revenue", "Revenue (latest filed)", lambda p: _latest(p, "revenue")),
    ("annual_result", "Annual result (latest filed)", lambda p: _latest(p, "annual_result")),
    ("ceo", "CEO", lambda p: _person(p, "CEO")),
    ("chair", "Chair of the board", lambda p: _person(p, "Chair of the board")),
    ("website", "Verified website", lambda p: p["website"].get("domain") if p["website"]["status"] == "available" else None),
    ("openPositions", "Open positions", lambda p: None if p["hiring"]["totalCurrent"] is None else str(p["hiring"]["totalCurrent"])),
    ("locations", "Registered establishments", lambda p: str(sum(1 for loc in p["locations"]["locations"] if loc["kind"] == "operating"))),
    ("coverage", "Coverage", lambda p: f"{p['company']['coverage']['complete']}/{p['company']['coverage']['total']}"),
]


def patch_artifact(s: Any, aid: str, patch: dict[str, Any]) -> dict[str, Any]:
    if aid.startswith("sheet-"):
        sid = aid.removeprefix("sheet-")
        meta = s.kv_get(f"sheet-meta:{sid}", {}) or {}
        for key in ("tags", "pinned", "archived"):
            if key in patch and patch[key] is not None:
                meta[key] = patch[key]
        s.kv_set(f"sheet-meta:{sid}", meta)
        if patch.get("title"):
            s.sheets.rename(sid, str(patch["title"]))
        return summary_by_id(s, aid)
    row = s.db.one("SELECT * FROM artifacts WHERE id = ?", (aid,))
    if row is None:
        raise ApiError("not_found", "This library item does not exist.", status=404)
    sets, params = ["updated_at = ?"], [now_iso()]
    if patch.get("title"):
        sets.append("title = ?")
        params.append(str(patch["title"])[:200])
    if patch.get("tags") is not None:
        tags = [re.sub(r"\s+", " ", str(t)).strip()[:40] for t in patch["tags"] if str(t).strip()][:20]
        sets.append("tags_json = ?")
        params.append(dumps(tags))
    for key in ("pinned", "archived"):
        if patch.get(key) is not None:
            sets.append(f"{key} = ?")
            params.append(1 if patch[key] else 0)
    s.db.execute(f"UPDATE artifacts SET {', '.join(sets)} WHERE id = ?", (*params, aid))
    return summary_by_id(s, aid)


def duplicate_artifact(s: Any, aid: str) -> dict[str, Any]:
    row = s.db.one("SELECT * FROM artifacts WHERE id = ?", (aid,))
    if row is None or row["type"] not in ("company", "report"):
        raise ApiError("invalid", "Only dossiers and reports can be duplicated.", status=400)
    new_id = f"{aid}-copy-{stable_id(now_iso(), aid, length=6)}"
    now = now_iso()
    s.db.execute("""INSERT INTO artifacts(id, type, title, org_number, target_id, created_at, updated_at, tags_json, pinned, archived, data_json)
                    VALUES (?,?,?,?,?,?,?,?,0,0,?)""", (new_id, row["type"], f"{row['title']} (copy)", row["org_number"], row["target_id"], now, now, row["tags_json"], row["data_json"]))
    for v in s.db.all("SELECT * FROM artifact_versions WHERE artifact_id = ?", (aid,)):
        s.db.execute("INSERT INTO artifact_versions(id, artifact_id, profile_version_id, created_at, label, note) VALUES (?,?,?,?,?,?)",
                     (v["id"] + "-c" + new_id[-6:], new_id, v["profile_version_id"], v["created_at"], v["label"], v["note"]))
    if row["type"] == "company":
        return _company_summary(s, s.db.one("SELECT * FROM artifacts WHERE id = ?", (new_id,))) or summary_by_id(s, new_id)
    return _report_summary(s.db.one("SELECT * FROM artifacts WHERE id = ?", (new_id,)))


def by_org(s: Any, org: str) -> dict[str, Any] | None:
    row = s.db.one("SELECT * FROM artifacts WHERE type = 'company' AND id = ?", (company_artifact_id(org),))
    return _company_summary(s, row) if row else None


async def create_report(s: Any, org: str, kind: str, sections: list[str]) -> dict[str, Any]:
    record = await s.ensure_record(org)
    version = s.db.one("SELECT id FROM profile_versions WHERE org_number = ? ORDER BY created_at DESC LIMIT 1", (org,))
    name = (record.get("identity") or {}).get("legal_name") or org
    rid = "rep-" + stable_id(org, kind, now_iso(), length=10)
    now = now_iso()
    title = f"{name} — {'Company brief' if kind == 'company_brief' else 'Deep research report'}"
    s.db.execute("""INSERT INTO artifacts(id, type, title, org_number, created_at, updated_at, tags_json, pinned, archived, data_json)
                    VALUES (?, 'report', ?, ?, ?, ?, '[]', 0, 0, ?)""", (rid, title, org, now, now, dumps({"kind": kind, "sections": sections, "profile_version_id": version["id"] if version else None})))
    return _report_summary(s.db.one("SELECT * FROM artifacts WHERE id = ?", (rid,)))


async def assessment(s: Any, aid: str) -> dict[str, Any]:
    row = s.db.one("SELECT * FROM artifacts WHERE id = ?", (aid,))
    if row is None or not row["org_number"]:
        raise ApiError("not_found", "This library item does not exist.", status=404)
    org = row["org_number"]
    record = repo.latest_record(s.db, org)
    if record is None:
        raise ApiError("not_found", "No saved research for this item.", status=404)
    from ..core.util import parse_iso, utc_now

    done = parse_iso(record.get("completed_at"))
    age = (utc_now() - done).total_seconds() / 86400 if done else 0
    stale = []
    if age > 1:
        stale.append({"area": "Company record", "reason": f"Register data last checked {int(age)} day(s) ago"})
    if age > 7:
        stale.append({"area": "Hiring", "reason": f"Careers pages last checked {int(age)} days ago"})
    if age > 30:
        stale.append({"area": "Website", "reason": f"Website last read {int(age)} days ago"})
    changed, new_filings = [], 0
    # One fresh register request (bypassing the cache) tells whether the source changed since the saved research.
    mod, ident = await brreg.fetch_entity(s.ctx(org, fresh=True))
    saved = (record.get("modules") or {}).get("registry_live") or {}
    if mod.state == "available" and saved.get("content_sha256") and mod.content_sha256 != saved.get("content_sha256"):
        changed.append({"sourceId": "brreg", "sourceName": "Brønnøysundregistrene", "detail": "The register record changed since the saved research"})
    saved_year = (record.get("identity") or {}).get("latest_accounts_year")
    if ident and ident.latest_accounts_year and saved_year and ident.latest_accounts_year > saved_year:
        new_filings = int(ident.latest_accounts_year) - int(saved_year)
        changed.append({"sourceId": "accounts", "sourceName": "Regnskapsregisteret", "detail": f"Annual accounts for {ident.latest_accounts_year} are now registered"})
    profile = s.profile_for(record)
    missing = [k["label"] for k in profile["knowns"] if k["status"] in ("unknown", "blocked")]
    return {"staleAreas": stale, "changedSources": changed, "newFilings": new_filings, "missingFields": missing, "checkedAt": now_iso()}


# ---------------------------------------------------------------- watchlist --
def watchlist(s: Any) -> dict[str, Any]:
    items = []
    changed = 0
    last_checked = None
    for row in s.db.all("SELECT * FROM watchlist ORDER BY added_at DESC"):
        summary = s.summary_for(row["org_number"])
        if summary is None:
            continue
        sigs = signals_for(s, row["org_number"], unseen_only=True)
        changed += 1 if sigs else 0
        items.append({"company": summary, "addedAt": row["added_at"], "lastCheckedAt": row["last_checked_at"], "signals": sigs})
        last_checked = max(last_checked or row["last_checked_at"], row["last_checked_at"])
    return {"id": "watchlist", "title": "Watchlist", "items": items, "changedCount": changed, "lastCheckedAt": last_checked or now_iso()}


def signals_for(s: Any, org: str | None = None, *, unseen_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT s.*, c.legal_name FROM signals s LEFT JOIN companies c ON c.org_number = s.org_number WHERE 1=1"
    params: list[Any] = []
    if org:
        sql += " AND s.org_number = ?"
        params.append(org)
    if unseen_only:
        sql += " AND s.seen = 0"
    sql += " ORDER BY s.detected_at DESC LIMIT 300"
    return [{"id": r["id"], "kind": r["kind"], "orgNumber": r["org_number"], "companyName": r["legal_name"] or r["org_number"], "title": r["title"],
             "detectedAt": r["detected_at"], "evidence": loads(r["evidence_json"], [])} for r in s.db.all(sql, params)]


def signal_feed(s: Any) -> list[dict[str, Any]]:
    from datetime import date, timedelta

    groups: dict[str, list[dict[str, Any]]] = {}
    for sig in signals_for(s):
        groups.setdefault(sig["detectedAt"][:10], []).append(sig)
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    out = []
    for day in sorted(groups, reverse=True):
        sigs = groups[day]
        counts: dict[str, int] = {}
        for sig in sigs:
            counts[sig["kind"]] = counts.get(sig["kind"], 0) + 1
        label = "Today" if day == today else "Yesterday" if day == yesterday else day
        out.append({"date": day, "label": label, "signals": sigs,
                    "summary": [{"kind": k, "count": n, "label": f"{n} {k} signal{'s' if n != 1 else ''}"} for k, n in sorted(counts.items(), key=lambda kv: -kv[1])],
                    "sourceIndex": _signal_sources(sigs)})
    return out


def _signal_sources(sigs: list[dict[str, Any]]) -> dict[str, Any]:
    from .sources import STATIC_SOURCES, website_source

    out: dict[str, Any] = {}
    for sig in sigs:
        for ev in sig["evidence"]:
            sid = ev["sourceId"]
            if sid in STATIC_SOURCES:
                out[sid] = STATIC_SOURCES[sid]
            elif sid.startswith("web-"):
                from ..security.urls import host_of, registrable_domain

                out[sid] = website_source(sig["orgNumber"], registrable_domain(host_of(ev.get("url"))) or "website")
    return out
