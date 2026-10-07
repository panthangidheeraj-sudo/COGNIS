"""Data Sheets: company lists from register criteria, standard + AI columns, batch research with SSE progress.

An AI column is an instruction mapped (deterministically, LLM-assisted when
configured) to one supported, evidence-backed field. Every cell carries its own
evidence and status; nothing is filled from the model's own knowledge.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from ..agent import llm_tasks
from ..core.util import format_int, now_iso, stable_id, title_case_no
from ..errors import ApiError
from ..logging_setup import get_logger
from ..storage import repository as repo
from ..storage.db import dumps, loads

log = get_logger("sheets")

# field → (title, valueType, cell description, planned sources, research mode, unit)
# Currency columns carry no column-level unit: each cell states the currency its own filing is in (cell['currency'], and in `display`).
FIELDS: dict[str, tuple[str, str, str, list[str], str, str | None]] = {
    "ceo": ("CEO", "person", "The registered general manager (daglig leder) from the roles register.", ["Brønnøysundregistrene — roles"], "registry", None),
    "board_chair": ("Chair of the board", "person", "The registered chair of the board.", ["Brønnøysundregistrene — roles"], "registry", None),
    "board_member": ("Board members", "text", "All registered board members.", ["Brønnøysundregistrene — roles"], "registry", None),
    "auditor": ("Auditor", "text", "The registered auditor.", ["Brønnøysundregistrene — roles"], "registry", None),
    "revenue": ("Revenue (latest filed)", "currency", "Revenue from the latest filed annual accounts, with its reporting period.", ["Regnskapsregisteret"], "registry", None),
    "operating_result": ("Operating result", "currency", "Operating result from the latest filed annual accounts.", ["Regnskapsregisteret"], "registry", None),
    "annual_result": ("Annual result", "currency", "Annual result (profit/loss) from the latest filed annual accounts.", ["Regnskapsregisteret"], "registry", None),
    "equity": ("Equity", "currency", "Equity from the latest filed annual accounts.", ["Regnskapsregisteret"], "registry", None),
    "total_assets": ("Total assets", "currency", "Total assets from the latest filed annual accounts.", ["Regnskapsregisteret"], "registry", None),
    "debt": ("Total debt", "currency", "Total debt from the latest filed annual accounts.", ["Regnskapsregisteret"], "registry", None),
    "registered_employees": ("Employees (registered)", "number", "Employee count reported to Enhetsregisteret (missing is not zero).", ["Brønnøysundregistrene"], "registry", "people"),
    "founded_date": ("Founded", "date", "Founding date (stiftelsesdato) in Enhetsregisteret.", ["Brønnøysundregistrene"], "registry", None),
    "official_website": ("Website (verified)", "url", "The company's own website, only when identity is verified (org. number, register link or domain holder).",
                         ["Brønnøysundregistrene", "Company website", "Norid"], "quick", None),
    "open_positions_count": ("Open positions", "number", "Current job postings on company-owned careers pages or the job board they link to.", ["Company website", "Company job board"], "quick", "roles"),
    "social_profile_linkedin": ("LinkedIn page", "url", "The LinkedIn company page linked from the verified website (LinkedIn itself is not scraped).", ["Company website"], "quick", None),
    "business_description": ("What they do", "text", "What the company says it does, quoted from its verified website.", ["Company website"], "quick", None),
    "parent_company": ("Parent company", "text", "The parent company in the group register.", ["Brønnøysundregistrene — group structure"], "registry", None),
    "registered_establishment_count": ("Establishments", "number", "Number of registered establishments (underenheter).", ["Brønnøysundregistrene — sub-units"], "registry", "sites"),
    "latest_filed_accounts_year": ("Latest filed accounts", "text", "The latest annual accounts year registered.", ["Brønnøysundregistrene"], "registry", None),
    "registered_email": ("E-mail (registered)", "text", "The e-mail address registered in Enhetsregisteret.", ["Brønnøysundregistrene"], "registry", None),
    "registration_status": ("Status", "text", "Registration status (active, bankruptcy, liquidation).", ["Brønnøysundregistrene"], "registry", None),
    "industry_label": ("Industry", "text", "Registered industry (NACE).", ["Brønnøysundregistrene"], "registry", None),
}
RULES: list[tuple[str, str]] = [
    (r"\b(ceo|chief executive|daglig leder|managing director|general manager|adm\.? ?dir)", "ceo"),
    (r"(chair|styreleder|styrets leder)", "board_chair"),
    (r"(board members?|styremedlem|styret\b|the board)", "board_member"),
    (r"(auditor|revisor)", "auditor"),
    (r"(operating (result|profit)|driftsresultat|ebit\b)", "operating_result"),
    (r"(revenue|turnover|omsetning|driftsinntekt|sales)", "revenue"),
    (r"(net (profit|income)|årsresultat|annual result|profit|loss|resultat)", "annual_result"),
    (r"(equity|egenkapital)", "equity"),
    (r"(total assets|eiendeler|balance sheet)", "total_assets"),
    (r"(\bdebt\b|gjeld|liabilit)", "debt"),
    (r"(linkedin)", "social_profile_linkedin"),
    (r"(hiring|open positions|openings|vacanc|job postings|jobs\b|ledige stillinger|stillinger|recruit)", "open_positions_count"),
    (r"(website|nettside|hjemmeside|homepage|domain|url)", "official_website"),
    (r"(what (does|do) (it|they) do|description|beskrivelse|business model|products?|services?|tjenester|what they do)", "business_description"),
    (r"(parent|morselskap|owner|eier|konsern|group)", "parent_company"),
    (r"(employees|ansatte|headcount|staff|workforce)", "registered_employees"),
    (r"(founded|stiftet|established|founding|age of)", "founded_date"),
    (r"(establishments|offices|locations|avdelinger|underenheter|branches)", "registered_establishment_count"),
    (r"(latest (filing|accounts)|filed accounts|årsregnskap)", "latest_filed_accounts_year"),
    (r"(e-?mail|epost)", "registered_email"),
    (r"(status|bankrupt|konkurs|liquidation|avvikling)", "registration_status"),
    (r"(industry|nace|bransje|næring|sector)", "industry_label"),
]
STANDARD_COLUMNS = [
    {"id": "company", "title": "Company", "kind": "identity", "valueType": "text", "width": 260, "frozen": True},
    {"id": "org", "title": "Org. number", "kind": "identity", "valueType": "text", "width": 120},
    {"id": "municipality", "title": "Municipality", "kind": "standard", "valueType": "text", "width": 140},
    {"id": "industry", "title": "Industry", "kind": "standard", "valueType": "text", "width": 220},
    {"id": "employees", "title": "Employees (registered)", "kind": "standard", "valueType": "number", "width": 120, "unit": "people"},
    {"id": "revenue", "title": "Revenue (latest filed)", "kind": "standard", "valueType": "currency", "width": 150},
    {"id": "ceo", "title": "CEO", "kind": "standard", "valueType": "person", "width": 180},
    {"id": "website", "title": "Website (verified)", "kind": "standard", "valueType": "url", "width": 180},
]
STANDARD_FIELD = {"employees": "registered_employees", "revenue": "revenue", "ceo": "ceo", "website": "official_website", "municipality": "municipality",
                  "industry": "industry_label"}


def map_instruction(text: str) -> str | None:
    t = text.casefold()
    for pattern, fld in RULES:
        if re.search(pattern, t):
            return fld
    return None


@dataclass
class Batch:
    run_id: str
    total: int
    done: int = 0
    running: int = 0
    failed: int = 0
    state: str = "running"
    errors: list[dict[str, str]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)

    def status(self) -> dict[str, Any]:
        pending = max(0, self.total - self.done - self.running - self.failed)
        out = {"runId": self.run_id, "state": self.state, "total": self.total, "done": self.done, "running": self.running, "pending": pending, "failed": self.failed,
               "errors": self.errors[-20:], "sourceUsage": [{"sourceName": k, "calls": v} for k, v in self.usage.items()]}
        if self.done and self.state == "running":
            per = (time.monotonic() - self.started) / max(1, self.done)
            out["etaSeconds"] = int(per * (pending + self.running))
        return out


@dataclass
class SheetStream:
    seq: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    batch: Batch | None = None
    task: asyncio.Task | None = None


class SheetManager:
    def __init__(self, services: Any):
        self.s = services
        self.streams: dict[str, SheetStream] = {}

    async def shutdown(self) -> None:
        for st in self.streams.values():
            if st.task and not st.task.done():
                st.task.cancel()

    # ------------------------------------------------------------ storage --
    def _row(self, sid: str) -> Any:
        row = self.s.db.one("SELECT * FROM sheets WHERE id = ?", (sid,))
        if row is None:
            raise ApiError("not_found", "This data sheet does not exist.", status=404)
        return row

    def _summary(self, row: Any) -> dict[str, Any]:
        cols = loads(row["columns_json"], [])
        n = self.s.db.one("SELECT COUNT(*) AS n FROM sheet_rows WHERE sheet_id = ?", (row["id"],))["n"]
        out = {"id": row["id"], "title": row["title"], "rowCount": n, "columnCount": len(cols), "updatedAt": row["updated_at"], "criteria": loads(row["criteria_json"], [])}
        if row["description"]:
            out["description"] = row["description"]
        return out

    def list(self) -> list[dict[str, Any]]:
        return [self._summary(r) for r in self.s.db.all("SELECT * FROM sheets ORDER BY updated_at DESC")]

    def get(self, sid: str) -> dict[str, Any]:
        row = self._row(sid)
        out = self._summary(row)
        out["columns"] = loads(row["columns_json"], [])
        rows = []
        sources: dict[str, Any] = {}
        for r in self.s.db.all("SELECT * FROM sheet_rows WHERE sheet_id = ? ORDER BY position", (sid,)):
            cells = loads(r["cells_json"], {})
            rows.append({"id": r["row_id"], "company": loads(r["company_json"], {}), "cells": cells})
            for cell in cells.values():
                for ev in cell.get("evidence") or []:
                    src = (cell.get("_sources") or {}).get(ev["sourceId"])
                    if src:
                        sources[ev["sourceId"]] = src
        for row_ in rows:
            for cell in row_["cells"].values():
                cell.pop("_sources", None)
        out["rows"] = rows
        st = self.streams.get(sid)
        if st and st.batch:
            out["batch"] = st.batch.status()
        out["sourceIndex"] = sources
        return out

    def _touch(self, sid: str) -> None:
        self.s.db.execute("UPDATE sheets SET updated_at = ? WHERE id = ?", (now_iso(), sid))

    async def create(self, body: dict[str, Any]) -> dict[str, Any]:
        from .discover import discover

        title = str(body.get("title") or "Untitled sheet").strip()[:120]
        criteria = body.get("criteria") or []
        filters = {c["key"]: c["value"] for c in criteria if isinstance(c, dict) and c.get("key")}
        text = body.get("text")
        result = await discover(self.s, {"filters": filters, "text": None if filters else text, "page": 1, "pageSize": 50, "sort": "relevance"})
        sid = "sh-" + stable_id(title, now_iso(), length=10)
        now = now_iso()
        description = " · ".join(c.get("display") or str(c.get("value")) for c in criteria if isinstance(c, dict)) or (text or None)
        self.s.db.execute("INSERT INTO sheets(id, title, description, criteria_json, columns_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                          (sid, title, description, dumps(criteria), dumps(STANDARD_COLUMNS), now, now))
        for i, company in enumerate(result["items"]):
            org = company["orgNumber"]
            cells = self._initial_cells(company)
            comp = {k: company.get(k) for k in ("orgNumber", "legalName", "municipality", "industry", "website") if company.get(k) is not None}
            self.s.db.execute("INSERT INTO sheet_rows(sheet_id, row_id, position, org_number, company_json, cells_json) VALUES (?,?,?,?,?,?)",
                              (sid, org, i, org, dumps(comp), dumps(cells)))
        return self._summary(self._row(sid))

    def _initial_cells(self, company: dict[str, Any]) -> dict[str, Any]:
        from .sources import STATIC_SOURCES

        org = company["orgNumber"]
        ev = [{"id": f"ev-brreg-{org}", "sourceId": "brreg", "url": f"https://data.brreg.no/enhetsregisteret/api/enheter/{org}", "retrievedAt": now_iso(),
               "excerpt": f"Enhetsregisteret — {company['legalName']}"}]
        src = {"brreg": STATIC_SOURCES["brreg"]}

        def cell(value: Any, display: str | None = None) -> dict[str, Any]:
            if value is None:
                return {"status": "pending", "value": None, "evidence": []}
            return {"status": "verified", "value": value, "display": display or str(value), "evidenceState": "primary", "evidence": ev, "sourceName": "Brønnøysundregistrene",
                    "updatedAt": now_iso(), "_sources": src}

        industry = company.get("industry") or {}
        return {"company": cell(company["legalName"]), "org": cell(org), "municipality": cell(company.get("municipality")),
                "industry": cell(industry.get("description") if industry else None), "employees": cell(company.get("employees"), format_int(company["employees"]) if company.get("employees") is not None else None),
                "revenue": {"status": "pending", "value": None, "evidence": []}, "ceo": {"status": "pending", "value": None, "evidence": []},
                "website": {"status": "pending", "value": None, "evidence": []}}

    def rename(self, sid: str, title: str) -> dict[str, Any]:
        self._row(sid)
        self.s.db.execute("UPDATE sheets SET title = ?, updated_at = ? WHERE id = ?", (title.strip()[:120] or "Untitled sheet", now_iso(), sid))
        return self._summary(self._row(sid))

    # ------------------------------------------------------------- columns --
    async def preview(self, sid: str, body: dict[str, Any]) -> dict[str, Any]:
        row = self._row(sid)
        instruction = str(body.get("instruction") or "").strip()
        if not instruction:
            raise ApiError("invalid", "Describe what the column should contain.", status=400)
        fld = map_instruction(instruction)
        notes: list[str] = []
        if fld is None and self.s.provider is not None:
            mapped = await llm_tasks.map_column(self.s.runner(), instruction, {k: v[2] for k, v in FIELDS.items()})
            if mapped and mapped[0]:
                fld = mapped[0]
                notes.append("Interpreted with the language model; the cells are still filled only from verified sources.")
        n = self.s.db.one("SELECT COUNT(*) AS n FROM sheet_rows WHERE sheet_id = ?", (row["id"],))["n"]
        if fld is None:
            return {"instruction": instruction, "title": body.get("title") or instruction[:40], "valueType": body.get("valueType") or "text",
                    "cellDescription": "COGNIS cannot research this reliably from permitted public sources.", "plannedSources": [], "rowCount": n,
                    "notes": ["Supported columns include CEO, board, auditor, revenue and results, employees, founded, website, open positions, LinkedIn page, description, parent company and establishments."],
                    "supported": False}
        title, vtype, desc, sources, mode, _unit = FIELDS[fld]
        if mode == "quick":
            notes.append("Needs website research per company (slower; companies without a verified website show “Not available”).")
        return {"instruction": instruction, "title": body.get("title") or title, "valueType": body.get("valueType") or vtype, "cellDescription": desc,
                "plannedSources": sources, "rowCount": n, "notes": notes, "supported": True}

    async def add_column(self, sid: str, body: dict[str, Any]) -> dict[str, Any]:
        preview = await self.preview(sid, body)
        if not preview["supported"]:
            raise ApiError("invalid", "This column cannot be researched from permitted sources.", status=400, details=preview)
        fld = map_instruction(preview["instruction"])
        if fld is None:
            mapped = await llm_tasks.map_column(self.s.runner(), preview["instruction"], {k: v[2] for k, v in FIELDS.items()}) if self.s.provider else None
            fld = mapped[0] if mapped else None
        row = self._row(sid)
        cols = loads(row["columns_json"], [])
        col = {"id": "c-" + stable_id(sid, preview["instruction"], now_iso(), length=8), "title": preview["title"], "kind": "ai", "valueType": preview["valueType"],
               "instruction": preview["instruction"], "width": 200, "field": fld}
        if FIELDS[fld][5]:
            col["unit"] = FIELDS[fld][5]
        cols.append(col)
        self.s.db.execute("UPDATE sheets SET columns_json = ?, updated_at = ? WHERE id = ?", (dumps(cols), now_iso(), sid))
        for r in self.s.db.all("SELECT row_id, cells_json FROM sheet_rows WHERE sheet_id = ?", (sid,)):
            cells = loads(r["cells_json"], {})
            cells[col["id"]] = {"status": "pending", "value": None, "evidence": []}
            self.s.db.execute("UPDATE sheet_rows SET cells_json = ? WHERE sheet_id = ? AND row_id = ?", (dumps(cells), sid, r["row_id"]))
        return {k: v for k, v in col.items() if k != "field"}

    def update_column(self, sid: str, cid: str, patch: dict[str, Any]) -> dict[str, Any]:
        row = self._row(sid)
        cols = loads(row["columns_json"], [])
        col = next((c for c in cols if c["id"] == cid), None)
        if col is None:
            raise ApiError("not_found", "Column not found.", status=404)
        if patch.get("title"):
            col["title"] = str(patch["title"])[:80]
        if patch.get("width") is not None:
            col["width"] = max(60, min(int(patch["width"]), 800))
        if patch.get("frozen") is not None:
            col["frozen"] = bool(patch["frozen"])
        self.s.db.execute("UPDATE sheets SET columns_json = ?, updated_at = ? WHERE id = ?", (dumps(cols), now_iso(), sid))
        return {k: v for k, v in col.items() if k != "field"}

    def remove_column(self, sid: str, cid: str) -> None:
        row = self._row(sid)
        cols = [c for c in loads(row["columns_json"], []) if c["id"] != cid or c["kind"] == "identity"]
        self.s.db.execute("UPDATE sheets SET columns_json = ?, updated_at = ? WHERE id = ?", (dumps(cols), now_iso(), sid))

    def reorder(self, sid: str, ids: list[str]) -> None:
        row = self._row(sid)
        cols = loads(row["columns_json"], [])
        order = {cid: i for i, cid in enumerate(ids)}
        cols.sort(key=lambda c: order.get(c["id"], len(order)))
        self.s.db.execute("UPDATE sheets SET columns_json = ?, updated_at = ? WHERE id = ?", (dumps(cols), now_iso(), sid))

    def public_columns(self, sid: str) -> list[dict[str, Any]]:
        return [{k: v for k, v in c.items() if k != "field"} for c in loads(self._row(sid)["columns_json"], [])]

    # ------------------------------------------------------------ research --
    async def research(self, sid: str, body: dict[str, Any]) -> dict[str, Any]:
        row = self._row(sid)
        st = self.streams.setdefault(sid, SheetStream())
        if st.task and not st.task.done() and st.batch:
            return st.batch.status()
        cols = loads(row["columns_json"], [])
        wanted = set(body.get("columnIds") or [])
        targets = [c for c in cols if c["kind"] != "identity" and (not wanted or c["id"] in wanted) and (c.get("field") or STANDARD_FIELD.get(c["id"]))]
        rows = self.s.db.all("SELECT row_id, org_number FROM sheet_rows WHERE sheet_id = ? ORDER BY position", (sid,))
        st.events = []
        st.batch = Batch(run_id="batch-" + stable_id(sid, now_iso(), length=8), total=len(rows) * len(targets))
        st.task = asyncio.create_task(self._run(sid, st, [(r["row_id"], r["org_number"]) for r in rows], targets))
        return st.batch.status()

    def _emit(self, sid: str, st: SheetStream, kind: str, **payload: Any) -> None:
        st.seq += 1
        st.events.append({"type": kind, "seq": st.seq, **payload})
        st.changed.set()

    async def _run(self, sid: str, st: SheetStream, rows: list[tuple[str, str]], targets: list[dict[str, Any]]) -> None:
        batch = st.batch
        assert batch is not None
        sem = asyncio.Semaphore(4)
        needs_web = any(FIELDS.get(c.get("field") or STANDARD_FIELD.get(c["id"], ""), ("", "", "", [], "registry", None))[4] == "quick" for c in targets)

        async def one(row_id: str, org: str) -> None:
            async with sem:
                batch.running += len(targets)
                for c in targets:
                    self._emit(sid, st, "cell.updated", rowId=row_id, columnId=c["id"], cell={"status": "researching", "value": None, "evidence": []})
                try:
                    record = repo.latest_record(self.s.db, org)
                    if record is None or (needs_web and record.get("mode") == "registry"):
                        record = await self.s.research(org, mode="quick" if needs_web else "registry")
                        name = "Company website" if needs_web else "Brønnøysundregistrene"
                        batch.usage[name] = batch.usage.get(name, 0) + 1
                    profile = self.s.profile_for(record) if record.get("identity") else None
                    cells = {c["id"]: _cell_from_record(record, profile, c.get("field") or STANDARD_FIELD.get(c["id"], "")) for c in targets}
                    self._save_cells(sid, row_id, cells)
                    for cid, cell in cells.items():
                        public = {k: v for k, v in cell.items() if k != "_sources"}
                        self._emit(sid, st, "cell.updated", rowId=row_id, columnId=cid, cell=public)
                    batch.done += len(targets)
                except Exception as exc:  # one row never stops the batch
                    log.exception("sheet row failed", extra={"org_number": org})
                    batch.failed += len(targets)
                    batch.errors.append({"rowId": row_id, "columnId": targets[0]["id"] if targets else "", "message": f"Research failed ({type(exc).__name__})."})
                    for c in targets:
                        self._emit(sid, st, "cell.updated", rowId=row_id, columnId=c["id"], cell={"status": "failed", "value": None, "evidence": [], "note": "Research failed for this row."})
                finally:
                    batch.running -= len(targets)
                    self._emit(sid, st, "batch.progress", batch=batch.status())

        try:
            await asyncio.gather(*(one(r, o) for r, o in rows))
            batch.state = "completed"
        except asyncio.CancelledError:
            batch.state = "failed"
            raise
        finally:
            self._touch(sid)
            self._emit(sid, st, "batch.completed", batch=batch.status())

    def _save_cells(self, sid: str, row_id: str, cells: dict[str, Any]) -> None:
        r = self.s.db.one("SELECT cells_json FROM sheet_rows WHERE sheet_id = ? AND row_id = ?", (sid, row_id))
        current = loads(r["cells_json"], {}) if r else {}
        current.update(cells)
        self.s.db.execute("UPDATE sheet_rows SET cells_json = ? WHERE sheet_id = ? AND row_id = ?", (dumps(current), sid, row_id))

    async def events(self, sid: str, last_seq: int) -> AsyncIterator[str]:
        self._row(sid)
        st = self.streams.setdefault(sid, SheetStream())
        if not st.events and st.batch is None:
            self._emit(sid, st, "batch.completed", batch=Batch(run_id="idle", total=0, state="idle").status())
        first = st.events[0]["seq"] if st.events else 0
        sent = max(last_seq, first - 1)
        idle = 0
        while True:
            for event in [e for e in st.events if e["seq"] > sent]:
                sent = event["seq"]
                yield f"id: {event['seq']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                if event["type"] == "batch.completed":
                    return
            st.changed.clear()
            try:
                await asyncio.wait_for(st.changed.wait(), timeout=15)
                idle = 0
            except TimeoutError:
                idle += 15
                yield ": keep-alive\n\n"
                if idle > 900:
                    return


def _cell_from_record(record: dict[str, Any], profile: dict[str, Any] | None, fld: str) -> dict[str, Any]:
    from .profile_builder import Builder

    if record.get("identity") is None:
        return {"status": "not_available", "value": None, "evidence": [], "note": "The organisation number was not found in Enhetsregisteret."}
    claims = [c for c in record.get("claims") or [] if c["field"] == fld]
    b = Builder(record)
    if fld == "municipality":
        claims = [c for c in record.get("claims") or [] if c["field"] == "municipality"]
    if not claims:
        ab = next((a for a in record.get("absences") or [] if a["field"] == fld), None)
        status = {"blocked": "blocked", "ambiguous": "ambiguous", "failed": "failed"}.get((ab or {}).get("availability"), "not_available")
        note = (ab or {}).get("note") or "Not established in the searched sources."
        return {"status": status, "value": None, "evidence": [], "note": note, "updatedAt": record.get("completed_at")}
    if fld in ("revenue", "operating_result", "annual_result", "equity", "total_assets", "debt"):
        c = max(claims, key=lambda x: x.get("reporting_period") or "")
        f = b.money_fact(f"sheet.{fld}", fld, c, period=c.get("period_label"))
        display = f"{f['displayValue']} ({c.get('period_label')})"
    elif fld == "board_member":
        names = [c["value"] for c in claims]
        merged = dict(claims[0])
        merged["evidence_ids"] = list(dict.fromkeys(e for c in claims for e in c.get("evidence_ids") or []))
        f = b.fact(f"sheet.{fld}", fld, merged, value=", ".join(names))
        display = ", ".join(names)
    else:
        c = claims[0]
        value = c["value"]
        if fld == "registration_status":
            value = (c.get("attributes") or {}).get("label") or value
        if fld == "business_description":
            value = (c.get("attributes") or {}).get("translation") or value
        if fld == "municipality":
            value = title_case_no(str(value))
        f = b.fact(f"sheet.{fld}", fld, c, value=value)
        display = format_int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)
    sources = {e["sourceId"]: b.sources.sources.get(e["sourceId"]) for e in f["evidence"] if b.sources.sources.get(e["sourceId"])}
    first_src = next(iter(sources.values()), None)
    out = {"status": "verified", "value": f["value"], "display": display, "evidenceState": f["evidenceState"], "evidence": f["evidence"],
           "sourceName": (first_src or {}).get("name"), "updatedAt": record.get("completed_at"), "_sources": sources}
    if f.get("currency"):
        out["currency"] = f["currency"]
    if fld in ("revenue", "operating_result", "annual_result", "equity", "total_assets", "debt") and f.get("note"):
        out["note"] = f["note"]
    return out
