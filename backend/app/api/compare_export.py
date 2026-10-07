"""Compare view, exports (csv/json/xlsx) and the system status endpoint."""
from __future__ import annotations

import csv
import io
import json
import time
from pathlib import Path
from typing import Any

from ..core.util import currency_unit, format_money, now_iso, stable_id, stated_currencies
from ..errors import ApiError
from ..providers.registry import describe
from .discover import FILTER_CAPABILITIES


def _series(p: dict[str, Any], key: str) -> dict[str, Any] | None:
    return next((s for s in p["financials"]["series"] if s["key"] == key), None)


def _latest_fact(p: dict[str, Any], key: str) -> dict[str, Any] | None:
    s = _series(p, key)
    return s["points"][-1]["fact"] if s and s["points"] else None


def _km(p: dict[str, Any], field: str) -> dict[str, Any] | None:
    f = next((k for k in p["keyMetrics"] if k["field"] == field), None)
    return f if f and f["status"] == "verified" else None


def _derived(org: str, path: str, label: str, value: Any, evidence: list[dict[str, Any]], *, unit: str | None = None, display: str | None = None) -> dict[str, Any]:
    out = {"id": f"{org}:{path}", "field": path, "label": label, "status": "verified", "value": value, "evidenceState": "primary" if evidence else "unverified",
           "evidence": evidence[:4]}
    if unit:
        out["unit"] = unit
    if display:
        out["displayValue"] = display
    return out


def _person(p: dict[str, Any], role: str) -> dict[str, Any] | None:
    x = next((x for x in p["people"]["people"] if x["role"] == role), None)
    return x["fact"] if x else None


def comparison(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    orgs = [p["company"]["orgNumber"] for p in profiles]

    def row(key: str, label: str, fn: Any, unit: str | None = None, *, money: bool = False) -> dict[str, Any]:
        values = [fn(p) for p in profiles]
        out = {"key": key, "label": label, "values": values}
        if money:  # the unit is whatever the compared filings state — one shared code, or an explicit "mixed currencies" (never converted)
            found = [v.get("currency") for v in values if v and v.get("status") == "verified"]
            if found:
                out["unit"] = currency_unit(found)
                out["currencies"] = [(v.get("currency") if v and v.get("status") == "verified" else None) for v in values]
        elif unit:
            out["unit"] = unit
        return out

    def filing(p: dict[str, Any]) -> dict[str, Any] | None:
        rev = _series(p, "revenue") or (p["financials"]["series"][0] if p["financials"]["series"] else None)
        if not rev or not rev["points"]:
            return None
        pt = rev["points"][-1]
        return _derived(p["company"]["orgNumber"], "compare.filing", "Latest filing", pt["period"], pt["fact"]["evidence"][:1])

    def board(p: dict[str, Any]) -> dict[str, Any] | None:
        b = [x for x in p["people"]["people"] if x["roleGroup"] == "board"]
        return _derived(p["company"]["orgNumber"], "compare.board", "Board roles", len(b), [e for x in b for e in x["fact"]["evidence"][:1]]) if b else None

    def latest_event(p: dict[str, Any]) -> dict[str, Any] | None:
        ev = next((e for e in p["activity"]["events"] if e["significance"] == "major"), None)
        return _derived(p["company"]["orgNumber"], "compare.event", "Latest major event", f"{ev['date']}: {ev['title']}", ev["evidence"]) if ev else None

    def changes(p: dict[str, Any]) -> dict[str, Any] | None:
        n = len([c for c in p["changes"]["changes"] if c["material"]])
        if p["changes"]["status"] == "pending":
            return None
        return _derived(p["company"]["orgNumber"], "compare.changes", "Material changes", n, [e for c in p["changes"]["changes"] for e in c["evidence"]][:3])

    def ratio(key: str):  # noqa: ANN202
        def fn(p: dict[str, Any]) -> dict[str, Any] | None:
            r = next((r for r in p["financials"].get("ratios") or [] if r["key"] == key), None)
            src = _latest_fact(p, "revenue") or _latest_fact(p, "equity")
            return _derived(p["company"]["orgNumber"], f"compare.{key}", r["label"], r["value"], (src or {}).get("evidence", [])[:1], unit="%", display=f"{r['value']:.1f}%") if r else None
        return fn

    summary = [
        row("revenue", "Revenue", lambda p: _latest_fact(p, "revenue"), money=True),
        row("employees", "Employees", lambda p: _km(p, "overview.employees"), "people"),
        row("hiring", "Hiring", lambda p: _km(p, "overview.openPositions"), "roles"),
        row("locations", "Locations", lambda p: _km(p, "overview.locations"), "sites"),
        row("filing", "Latest filing", filing),
    ]
    sections = [
        {"id": "overview", "label": "Overview", "rows": [
            row("legalForm", "Legal form", lambda p: p["identity"].get("legalForm")),
            row("founded", "Founded", lambda p: p["identity"].get("founded")),
            row("industry", "Industry", lambda p: p["identity"].get("industry")),
            row("status", "Status", lambda p: p["identity"].get("status")),
            row("address", "Registered address", lambda p: p["identity"].get("registeredAddress")),
            row("website", "Website", lambda p: p["identity"].get("website") if (p["identity"].get("website") or {}).get("status") == "verified" else None)]},
        {"id": "financials", "label": "Financials", "rows": [
            row("revenue", "Revenue", lambda p: _latest_fact(p, "revenue"), money=True),
            row("operating_result", "Operating result", lambda p: _latest_fact(p, "operating_result"), money=True),
            row("annual_result", "Annual result", lambda p: _latest_fact(p, "annual_result"), money=True),
            row("total_assets", "Total assets", lambda p: _latest_fact(p, "total_assets"), money=True),
            row("equity", "Equity", lambda p: _latest_fact(p, "equity"), money=True),
            row("debt", "Total debt", lambda p: _latest_fact(p, "debt"), money=True),
            row("operating_margin", "Operating margin", ratio("operating_margin"), "%"),
            row("equity_ratio", "Equity ratio", ratio("equity_ratio"), "%")]},
        {"id": "people", "label": "People", "rows": [row("ceo", "CEO", lambda p: _person(p, "CEO")), row("chair", "Chair of the board", lambda p: _person(p, "Chair of the board")),
                                                     row("board", "Board roles", board)]},
        {"id": "locations", "label": "Locations", "rows": [row("establishments", "Registered establishments", lambda p: _km(p, "overview.locations"), "sites")]},
        {"id": "hiring", "label": "Hiring", "rows": [row("open_positions", "Open positions", lambda p: _km(p, "overview.openPositions"), "roles")]},
        {"id": "activity", "label": "Activity", "rows": [row("latest_event", "Latest major event", latest_event)]},
        {"id": "changes", "label": "Changes", "rows": [row("material_changes", "Material changes since previous research", changes)]},
    ]
    series = []
    for key, label in (("revenue", "Revenue"), ("operating_result", "Operating result"), ("annual_result", "Annual result")):
        periods = sorted({pt["period"] for p in profiles for pt in (_series(p, key) or {}).get("points", [])})
        if not periods:
            continue
        points = [{"period": per, "values": [next((pt["fact"]["value"] for pt in (_series(p, key) or {}).get("points", []) if pt["period"] == per), None) for p in profiles]}
                  for per in periods]
        per_company = [[pt["fact"].get("currency") for pt in (_series(p, key) or {}).get("points", [])] for p in profiles]
        flat = [c for cs in per_company for c in cs]
        # One y-axis is only honest when every plotted amount is in the same stated currency; otherwise the series says "mixed currencies".
        series.append({"key": key, "label": label, "unit": currency_unit(flat), "currencies": [stated_currencies(cs) for cs in per_company],
                       "mixedCurrency": len(stated_currencies(flat)) > 1 or not all(flat), "points": points})
    source_index: dict[str, Any] = {}
    for p in profiles:
        source_index.update(p["sourceIndex"])
    return {"companies": [p["company"] for p in profiles], "summary": summary, "sections": sections, "series": series, "generatedAt": now_iso(),
            "sourceIndex": source_index, "orgNumbers": orgs}


# ------------------------------------------------------------------ exports --
def _fact_rows(p: dict[str, Any], opts: dict[str, Any]) -> list[dict[str, Any]]:
    from .briefs import _all_facts

    rows = []
    for f in _all_facts(p):
        ev = f["evidence"][0] if f["evidence"] else {}
        src = p["sourceIndex"].get(ev.get("sourceId"), {}) if ev else {}
        currency = f.get("currency") if isinstance(f.get("value"), (int, float)) and not isinstance(f.get("value"), bool) else None
        # `value` is always built from the fact's own currency; `raw_value` is the unrounded number exactly as filed; `currency` names the unit of both.
        value = f.get("displayValue") or (format_money(f["value"], currency) if currency else f["value"])
        row = {"org_number": p["company"]["orgNumber"], "company": p["company"]["legalName"], "field": f["field"], "label": f["label"], "value": value,
               "raw_value": f["value"], "currency": currency or "", "status": f["status"], "evidence_state": f["evidenceState"]}
        if opts.get("reportingPeriods", True):
            row["reporting_period"] = f.get("reportingPeriod") or ""
        if opts.get("sourceLinks", True):
            row["source"] = src.get("name") or ev.get("sourceId", "")
            row["source_url"] = ev.get("url") or ""
        if opts.get("retrievalDates", True):
            row["retrieved_at"] = ev.get("retrievedAt") or ""
        if opts.get("evidence", True):
            row["evidence_excerpt"] = ev.get("excerpt") or ""
        rows.append(row)
    if opts.get("changes"):
        for c in p["changes"]["changes"]:
            rows.append({"org_number": p["company"]["orgNumber"], "company": p["company"]["legalName"], "field": f"change.{c['category']}", "label": c.get("headline") or c["label"],
                         "value": f"{c.get('previous') or ''} → {c.get('current') or ''}", "raw_value": None, "currency": "", "status": "verified", "evidence_state": "primary",
                         "reporting_period": "", "source": "", "source_url": (c["evidence"][0].get("url") if c["evidence"] else "") or "",
                         "retrieved_at": c["detectedAt"], "evidence_excerpt": ""})
    return rows


def _sheet_rows(sheet: dict[str, Any], opts: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for r in sheet["rows"]:
        out = {"org_number": r["company"].get("orgNumber"), "company": r["company"].get("legalName")}
        for col in sheet["columns"]:
            cell = r["cells"].get(col["id"]) or {}
            out[col["title"]] = cell.get("display") if cell.get("status") == "verified" else f"[{cell.get('status', 'pending')}]"
            if col["valueType"] == "currency":  # the unit of the amount travels with it: the display text, the unrounded number and the code
                verified = cell.get("status") == "verified"
                out[f"{col['title']} — currency"] = (cell.get("currency") or "") if verified else ""
                out[f"{col['title']} — raw value"] = cell.get("value") if verified else None
            if opts.get("sourceLinks", True) and col["kind"] != "identity":
                ev = (cell.get("evidence") or [{}])[0]
                out[f"{col['title']} — source"] = ev.get("url") or ""
            if opts.get("retrievalDates") and col["kind"] != "identity":
                out[f"{col['title']} — retrieved"] = ((cell.get("evidence") or [{}])[0]).get("retrievedAt") or ""
        rows.append(out)
    return rows


async def export(s: Any, req: dict[str, Any]) -> dict[str, Any]:
    target = req.get("target") or {}
    fmt = req.get("format") or "csv"
    opts = req.get("options") or {}
    if fmt not in ("csv", "json", "xlsx"):
        return {"status": "failed", "filename": "", "message": "PDF export is not available from this backend yet; use CSV, Excel or JSON."}
    ttype, tid = target.get("type"), str(target.get("id") or "")
    name = "export"
    rows: list[dict[str, Any]]
    payload: Any
    if ttype in ("company", "artifact"):
        if ttype == "artifact" and tid.startswith("sheet-"):
            ttype, tid = "sheet", tid.removeprefix("sheet-")
        else:
            org = tid.removeprefix("art-").split("-copy-")[0] if ttype == "artifact" and tid.startswith("art-") else tid
            if ttype == "artifact" and tid.startswith("rep-"):
                row = s.db.one("SELECT org_number FROM artifacts WHERE id = ?", (tid,))
                org = row["org_number"] if row else ""
            org = s.clean_org(org)
            p = await s.profile(org)
            rows = _fact_rows(p, opts)
            payload = p
            name = f"{p['company']['legalName']}-{org}"
    if ttype == "sheet":
        sheet = s.sheets.get(tid)
        rows = _sheet_rows(sheet, opts)
        payload = sheet
        name = sheet["title"]
    elif ttype == "comparison":
        orgs = [s.clean_org(o) for o in tid.split(",") if o.strip()]
        profiles = [await s.profile(o) for o in orgs]
        rows = [r for p in profiles for r in _fact_rows(p, opts)]
        payload = comparison(profiles)
        name = "comparison-" + "-".join(orgs)
    elif ttype not in ("company", "artifact"):
        raise ApiError("invalid", "Unknown export target.", status=400)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name).strip("-")[:80] or "export"
    eid = "exp-" + stable_id(safe, fmt, time.time_ns(), length=12)
    folder = Path(s.settings.data_dir) / "exports"
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{safe}.{fmt}"
    path = folder / f"{eid}.{fmt}"
    if fmt == "json":
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        ctype = "application/json"
    elif fmt == "csv":
        buf = io.StringIO()
        keys = list(dict.fromkeys(k for r in rows for k in r))
        writer = csv.DictWriter(buf, fieldnames=keys)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: ("" if v is None else v) for k, v in r.items()})
        path.write_text("﻿" + buf.getvalue(), encoding="utf-8")
        ctype = "text/csv"
    else:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Facts" if ttype != "sheet" else "Sheet"
        keys = list(dict.fromkeys(k for r in rows for k in r))
        ws.append(keys)
        for r in rows:
            ws.append([("" if r.get(k) is None else (r.get(k) if isinstance(r.get(k), (int, float, str)) else json.dumps(r.get(k), ensure_ascii=False))) for k in keys])
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(60, max(10, max(len(str(c.value or "")) for c in col[:50]) + 2))
        wb.save(path)
        ctype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    s.db.execute("INSERT INTO exports(id, filename, path, content_type, created_at) VALUES (?,?,?,?,?)", (eid, filename, str(path), ctype, now_iso()))
    return {"status": "ready", "filename": filename, "url": f"{s.settings.api_prefix}/exports/{eid}/download"}


# ------------------------------------------------------------------- status --
def system_status(s: Any) -> dict[str, Any]:
    st = s.settings
    recent = s.db.all("SELECT connector, classification FROM tool_calls ORDER BY id DESC LIMIT 200")
    brreg_calls = [r for r in recent if (r["connector"] or "").startswith("brreg")]
    brreg_failing = brreg_calls and sum(1 for r in brreg_calls if r["classification"] in ("timeout", "network", "server_error")) > len(brreg_calls) / 2
    llm = describe(st)
    sources = [
        {"name": "Brønnøysundregistrene — Enhetsregisteret", "kind": "registry", "status": "degraded" if brreg_failing else "available"},
        {"name": "Regnskapsregisteret", "kind": "financial", "status": "degraded" if brreg_failing else "available"},
        {"name": "Company websites (identity-verified)", "kind": "website", "status": "available" if st.enable_website else "unavailable"},
        {"name": "Company careers pages and linked job boards", "kind": "jobs", "status": "available" if st.enable_jobs else "unavailable"},
        {"name": "Web search discovery (Tavily)", "kind": "web", "status": "available" if st.search_enabled else "unavailable",
         **({} if st.search_enabled else {"note": "Not configured (TAVILY_API_KEY). Registry-listed and e-mail-domain websites are still checked."})},
        {"name": "Norid domain holder (RDAP)", "kind": "registry", "status": "available" if st.enable_norid else "unavailable"},
        {"name": "Kartverket — Geonorge", "kind": "registry", "status": "available" if st.enable_geocoding else "unavailable"},
        {"name": f"Language model ({llm['model'] or 'none'})", "kind": "web", "status": "available" if llm["enabled"] else "unavailable",
         **({} if llm["enabled"] else {"note": "No LLM configured — deterministic extraction and templated summaries are used."})},
        {"name": "Proff.no", "kind": "financial", "status": "available" if (st.enable_proff and st.proff_api_key) else "unavailable", "note": "Requires a licensed API key."},
        {"name": "Doffin (public procurement)", "kind": "regulatory", "status": "available" if (st.enable_doffin and st.doffin_api_key) else "unavailable",
         "note": "Requires a subscription key and access review."},
        {"name": "LinkedIn", "kind": "people", "status": "unavailable", "note": "Automated collection is not permitted; only company pages linked from verified websites are shown."},
        {"name": "NAV — arbeidsplassen", "kind": "jobs", "status": "unavailable", "note": "The public feed carries no organisation numbers, so postings cannot be matched safely."},
    ]
    return {"mode": "live", "backend": "degraded" if brreg_failing else "connected", "research": "online", "version": st.version, "sources": sources,
            "capabilities": {"exports": ["csv", "xlsx", "json"], "pdfReports": False, "pauseResearch": False, "cancelResearch": True, "watchlist": True, "versions": True,
                             "archive": True, "tags": True, "share": False, "discoverFilters": FILTER_CAPABILITIES},
            "checkedAt": now_iso()}


def metrics(s: Any) -> dict[str, Any]:
    def n(sql: str) -> int:
        return int(s.db.one(sql)[0] or 0)

    return {"companies": n("SELECT COUNT(*) FROM companies"), "researched": n("SELECT COUNT(*) FROM companies WHERE research_state = 'researched'"),
            "profile_versions": n("SELECT COUNT(*) FROM profile_versions"), "facts": n("SELECT COUNT(*) FROM facts"), "evidence": n("SELECT COUNT(*) FROM evidence"),
            "changes": n("SELECT COUNT(*) FROM changes"), "tool_calls": n("SELECT COUNT(*) FROM tool_calls"), "runs": n("SELECT COUNT(*) FROM research_runs"),
            "budget": s.budget.snapshot()}
