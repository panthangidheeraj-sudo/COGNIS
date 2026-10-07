"""FastAPI application: the COGNIS frontend contract (API_CONTRACT.md) plus research/competition endpoints.

Run:  uvicorn app.api.main:app --port 8000      (the Vite dev server proxies /api → :8000)
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from ..config import get_settings, validate_configuration
from ..errors import ApiError
from ..logging_setup import configure_logging, get_logger
from ..storage import repository as repo
from . import briefs, discover, library
from .compare_export import comparison, export, metrics, system_status
from .services import Services

log = get_logger("api")
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


def create_app(services: Services | None = None) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        configure_logging()
        for warning in validate_configuration(settings):
            log.warning(warning)
        app.state.services = services or Services(settings)
        yield
        await app.state.services.aclose()

    app = FastAPI(title="COGNIS backend", version=settings.version, lifespan=lifespan, docs_url=None if settings.competition else "/docs", redoc_url=None)
    origins = settings.cors_origin_list() if callable(settings.cors_origin_list) else settings.cors_origin_list
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(exc.to_body(), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", []) if x != "body")
        return JSONResponse({"code": "invalid", "message": f"Invalid request{(' (' + where + ')') if where else ''}."}, status_code=422)

    @app.exception_handler(Exception)
    async def crash(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return JSONResponse({"code": "unavailable", "message": "Something went wrong on the server. Please try again."}, status_code=500)

    r = APIRouter(prefix=settings.api_prefix)

    def S(request: Request) -> Services:  # noqa: N802
        return request.app.state.services

    # ------------------------------------------------------------- system --
    @r.get("/status")
    async def status(request: Request) -> dict[str, Any]:
        return system_status(S(request))

    @r.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        s = S(request)
        return {"status": "ok", "version": settings.version, "run_mode": settings.run_mode, "schema_version": s.db.schema_version(), "llm": s.provider is not None}

    @r.get("/metrics")
    async def get_metrics(request: Request) -> dict[str, Any]:
        return metrics(S(request))

    @r.get("/search")
    async def search(request: Request, q: str = "") -> dict[str, Any]:
        return await discover.global_search(S(request), q)

    # ----------------------------------------------------------- companies --
    @r.post("/companies/discover")
    async def companies_discover(request: Request, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        return await discover.discover(S(request), body)

    @r.post("/companies/interpret")
    async def companies_interpret(request: Request, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        return await discover.interpret(S(request), str(body.get("text") or ""))

    @r.get("/companies/recent")
    async def companies_recent(request: Request) -> list[dict[str, Any]]:
        s = S(request)
        out = []
        for row in s.db.all("SELECT org_number FROM recent_companies ORDER BY viewed_at DESC LIMIT 12"):
            summary = s.summary_for(row["org_number"])
            if summary:
                out.append(summary)
        return out

    @r.get("/companies/{org}")
    async def company(request: Request, org: str) -> dict[str, Any]:
        s = S(request)
        return await s.profile(s.clean_org(org))

    @r.get("/companies/{org}/brief")
    async def company_brief(request: Request, org: str) -> dict[str, Any]:
        s = S(request)
        return briefs.brief_from_profile(await s.profile(s.clean_org(org)))

    @r.post("/companies/{org}/explain")
    async def company_explain(request: Request, org: str, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        s = S(request)
        org = s.clean_org(org)
        origin = "saved_evidence"
        if body.get("fresh"):
            await s.research(org, mode="quick")
            origin = "fresh_research"
        subject = body.get("subject") or {}
        if subject.get("kind") not in ("change", "metric"):
            raise ApiError("invalid", "subject.kind must be 'change' or 'metric'.", status=400)
        return await briefs.explain(await s.profile(org), subject, s.runner(), origin=origin)

    @r.get("/companies/{org}/evidence")
    async def company_evidence(request: Request, org: str) -> dict[str, Any]:
        s = S(request)
        record = await s.ensure_record(s.clean_org(org))
        return {"organisation_number": record["organisation_number"], "evidence": record.get("evidence") or [], "claims": record.get("claims") or [],
                "absences": record.get("absences") or []}

    @r.get("/companies/{org}/changes")
    async def company_changes(request: Request, org: str) -> dict[str, Any]:
        s = S(request)
        org = s.clean_org(org)
        return {"organisation_number": org, "changes": repo.changes_for(s.db, org), "versions": repo.record_versions(s.db, org)}

    @r.get("/companies/{org}/sources")
    async def company_sources(request: Request, org: str) -> dict[str, Any]:
        s = S(request)
        record = await s.ensure_record(s.clean_org(org))
        return {"organisation_number": record["organisation_number"], "modules": record.get("modules") or {}, "site_attempts": record.get("site_attempts") or [],
                "trace": record.get("trace") or [], "researched_at": record.get("completed_at"), "mode": record.get("mode")}

    # ------------------------------------------------------------ research --
    @r.post("/research/runs")
    async def research_start(request: Request, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        return await S(request).runs.start(body)

    @r.get("/research/runs/{run_id}")
    async def research_get(request: Request, run_id: str) -> dict[str, Any]:
        return S(request).runs.get(run_id)

    @r.post("/research/runs/{run_id}/confirm")
    async def research_confirm(request: Request, run_id: str, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        return await S(request).runs.confirm(run_id, list(body.get("stepKeys") or []))

    @r.post("/research/runs/{run_id}/cancel")
    async def research_cancel(request: Request, run_id: str) -> dict[str, Any]:
        return await S(request).runs.cancel(run_id)

    @r.post("/research/runs/{run_id}/pause")
    async def research_pause(request: Request, run_id: str) -> dict[str, Any]:
        S(request).runs.unsupported("Pausing research")
        return {}

    @r.post("/research/runs/{run_id}/retry")
    async def research_retry(request: Request, run_id: str) -> dict[str, Any]:
        S(request).runs.unsupported("Retrying individual steps")
        return {}

    @r.get("/research/runs/{run_id}/events")
    async def research_events(request: Request, run_id: str, lastSeq: int = Query(0)) -> StreamingResponse:  # noqa: N803
        s = S(request)
        s.runs.get(run_id)  # 404 before opening the stream
        return StreamingResponse(s.runs.events(run_id, lastSeq), media_type="text/event-stream", headers=SSE_HEADERS)

    @r.post("/research/ask")
    async def research_ask(request: Request, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        s = S(request)
        org = s.clean_org(str(body.get("orgNumber") or ""))
        question = str(body.get("question") or "").strip()
        if not question:
            raise ApiError("invalid", "Ask a question.", status=400)
        origin = "saved_evidence"
        before = set((await s.ensure_record(org)).get("modules") or {})
        new_sources: list[str] = []
        if body.get("fresh"):
            rec = await s.research(org, mode="quick")
            origin = "fresh_research"
            new_sources = sorted(set(rec.get("modules") or {}) - before)
        ans = await briefs.answer(await s.profile(org), question, s.runner(), origin=origin)
        if body.get("fresh"):
            ans["newSourceIds"] = new_sources
        return ans

    @r.post("/research/company")
    async def research_company(request: Request, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        """Evaluator-style single-company research: returns the OUTPUT_CONTRACT envelope."""
        from ..competition.envelope import build_envelope

        s = S(request)
        org = s.clean_org(str(body.get("organisation_number") or body.get("orgNumber") or ""))
        mode = body.get("mode") if body.get("mode") in ("quick", "deep", "competition") else "competition"
        record = await s.research(org, mode=mode, fresh=bool(body.get("fresh")))
        return build_envelope(record, run_id=record.get("run_id") or "api", changes=record.get("changes") or [])

    @r.post("/research/batch")
    async def research_batch(request: Request, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        from ..agent.orchestrator import new_run_id
        from ..competition.batch import BatchConfig, run_batch

        s = S(request)
        orgs = [s.clean_org(str(o)) for o in body.get("organisation_numbers") or []]
        if not orgs:
            raise ApiError("invalid", "organisation_numbers must list at least one organisation number.", status=400)
        if len(orgs) > 1000:
            raise ApiError("invalid", "At most 1000 organisation numbers per batch.", status=400)
        run_id = str(body.get("run_id") or new_run_id("batch"))
        out_dir = Path(settings.data_dir) / "batches" / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        inp = out_dir / "organisations.txt"
        inp.write_text("\n".join(orgs), encoding="utf-8")
        cfg = BatchConfig(organisations=str(inp), output=str(out_dir / "envelopes.jsonl"), profiles_output=str(out_dir / "profiles.jsonl"), report=str(out_dir / "report.json"),
                          run_id=run_id, db=s.db)
        task = asyncio.create_task(run_batch(cfg, settings))
        request.app.state.__dict__.setdefault("batches", {})[run_id] = task
        return {"run_id": run_id, "status": "running", "companies": len(orgs), "report_url": f"{settings.api_prefix}/runs/{run_id}"}

    @r.get("/runs/{run_id}")
    async def run_report(request: Request, run_id: str) -> dict[str, Any]:
        from ..storage.db import loads

        row = S(request).db.one("SELECT * FROM research_runs WHERE run_id = ?", (run_id,))
        if row is None:
            raise ApiError("not_found", "Run not found.", status=404)
        return {"run_id": run_id, "status": row["status"], "started_at": row["started_at"], "finished_at": row["finished_at"], "input_count": row["input_count"],
                "completed_count": row["completed_count"], "requests": row["requests"], "cost_usd": row["cost_usd"], "report": loads(row["report_json"])}

    # ------------------------------------------------------------- library --
    @r.get("/library")
    async def library_list(request: Request, q: str | None = None, type: str = "all", sort: str = "updated", page: int = 1, pageSize: int = 24,  # noqa: A002,N803
                           tag: str | None = None, includeArchived: bool = False) -> dict[str, Any]:  # noqa: N803
        return library.list_library(S(request), q=q, type_=type, sort=sort, page=page, page_size=pageSize, tag=tag, include_archived=includeArchived)

    @r.get("/library/recent")
    async def library_recent(request: Request) -> list[dict[str, Any]]:
        items = library.all_summaries(S(request), include_archived=False)
        items.sort(key=lambda x: x.get("viewedAt") or x["updatedAt"], reverse=True)
        return items[:8]

    @r.get("/library/capabilities")
    async def library_capabilities() -> dict[str, Any]:
        return library.CAPABILITIES

    @r.get("/library/by-org/{org}")
    async def library_by_org(request: Request, org: str) -> Any:
        s = S(request)
        found = library.by_org(s, s.clean_org(org))
        return JSONResponse(found) if found is not None else JSONResponse(None)

    @r.post("/library/from-run/{run_id}")
    async def library_from_run(request: Request, run_id: str) -> dict[str, Any]:
        s = S(request)
        run = s.runs.get(run_id)
        if run.get("status") != "completed" or not run.get("artifactId"):
            raise ApiError("invalid", "Only completed research runs can be saved.", status=400)
        return library.summary_by_id(s, run["artifactId"])

    @r.get("/library/{aid}/assessment")
    async def library_assessment(request: Request, aid: str) -> dict[str, Any]:
        return await library.assessment(S(request), aid)

    @r.get("/library/{aid}/versions/compare")
    async def library_compare_versions(request: Request, aid: str, from_: str = Query(..., alias="from"), to: str = Query(...)) -> dict[str, Any]:
        return library.compare_versions(S(request), aid, from_, to)

    @r.get("/library/{aid}/versions/{vid}")
    async def library_version(request: Request, aid: str, vid: str) -> dict[str, Any]:
        return library.get_artifact(S(request), aid, vid)

    @r.get("/library/{aid}")
    async def library_get(request: Request, aid: str) -> dict[str, Any]:
        return library.get_artifact(S(request), aid)

    @r.patch("/library/{aid}")
    async def library_patch(request: Request, aid: str, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        return library.patch_artifact(S(request), aid, body)

    @r.post("/library/{aid}/duplicate")
    async def library_duplicate(request: Request, aid: str) -> dict[str, Any]:
        return library.duplicate_artifact(S(request), aid)

    @r.post("/reports")
    async def reports(request: Request, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        s = S(request)
        kind = body.get("kind") if body.get("kind") in ("company_brief", "deep_report", "comparison_report", "market_overview") else "company_brief"
        return await library.create_report(s, s.clean_org(str(body.get("orgNumber") or "")), kind, list(body.get("sections") or []))

    # -------------------------------------------------------------- sheets --
    @r.get("/sheets")
    async def sheets_list(request: Request) -> list[dict[str, Any]]:
        return S(request).sheets.list()

    @r.post("/sheets/interpret")
    async def sheets_interpret(request: Request, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        return await discover.interpret(S(request), str(body.get("text") or ""))

    @r.post("/sheets")
    async def sheets_create(request: Request, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        return await S(request).sheets.create(body)

    @r.get("/sheets/{sid}")
    async def sheets_get(request: Request, sid: str) -> dict[str, Any]:
        sheet = S(request).sheets.get(sid)
        sheet["columns"] = [{k: v for k, v in c.items() if k != "field"} for c in sheet["columns"]]
        return sheet

    @r.patch("/sheets/{sid}")
    async def sheets_rename(request: Request, sid: str, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        return S(request).sheets.rename(sid, str(body.get("title") or ""))

    @r.post("/sheets/{sid}/columns/preview")
    async def sheets_preview(request: Request, sid: str, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        return await S(request).sheets.preview(sid, body)

    @r.post("/sheets/{sid}/columns")
    async def sheets_add_column(request: Request, sid: str, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        return await S(request).sheets.add_column(sid, body)

    @r.put("/sheets/{sid}/columns/order")
    async def sheets_order(request: Request, sid: str, body: dict[str, Any] = Body(default_factory=dict)) -> Response:  # noqa: B008
        S(request).sheets.reorder(sid, list(body.get("columnIds") or []))
        return Response(status_code=204)

    @r.patch("/sheets/{sid}/columns/{cid}")
    async def sheets_update_column(request: Request, sid: str, cid: str, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        return S(request).sheets.update_column(sid, cid, body)

    @r.delete("/sheets/{sid}/columns/{cid}")
    async def sheets_delete_column(request: Request, sid: str, cid: str) -> Response:
        S(request).sheets.remove_column(sid, cid)
        return Response(status_code=204)

    @r.post("/sheets/{sid}/research")
    async def sheets_research(request: Request, sid: str, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        return await S(request).sheets.research(sid, body)

    @r.get("/sheets/{sid}/events")
    async def sheets_events(request: Request, sid: str, lastSeq: int = Query(0)) -> StreamingResponse:  # noqa: N803
        s = S(request)
        s.sheets.get(sid)
        return StreamingResponse(s.sheets.events(sid, lastSeq), media_type="text/event-stream", headers=SSE_HEADERS)

    # ------------------------------------------------------------- compare --
    @r.get("/compare")
    async def compare(request: Request, orgs: str = "") -> dict[str, Any]:
        s = S(request)
        numbers = list(dict.fromkeys(s.clean_org(o) for o in orgs.split(",") if o.strip()))
        if not 2 <= len(numbers) <= 5:
            raise ApiError("invalid", "Compare needs 2–5 organisation numbers.", status=400)
        profiles = await asyncio.gather(*(s.profile(o) for o in numbers))
        out = comparison(list(profiles))
        out.pop("orgNumbers", None)
        return out

    # ----------------------------------------------------------- watchlist --
    @r.get("/watchlist")
    async def watchlist_get(request: Request) -> dict[str, Any]:
        return library.watchlist(S(request))

    @r.post("/watchlist/items")
    async def watchlist_add(request: Request, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        from ..core.util import now_iso

        s = S(request)
        org = s.clean_org(str(body.get("orgNumber") or ""))
        await s.ensure_record(org)
        s.db.execute("INSERT OR IGNORE INTO watchlist(org_number, added_at, last_checked_at) VALUES (?,?,?)", (org, now_iso(), now_iso()))
        return library.watchlist(s)

    @r.delete("/watchlist/items/{org}")
    async def watchlist_remove(request: Request, org: str) -> dict[str, Any]:
        s = S(request)
        s.db.execute("DELETE FROM watchlist WHERE org_number = ?", (s.clean_org(org),))
        return library.watchlist(s)

    @r.post("/watchlist/checked")
    async def watchlist_checked(request: Request) -> dict[str, Any]:
        from ..core.util import now_iso

        s = S(request)
        s.db.execute("UPDATE signals SET seen = 1 WHERE org_number IN (SELECT org_number FROM watchlist)")
        s.db.execute("UPDATE watchlist SET last_checked_at = ?", (now_iso(),))
        return library.watchlist(s)

    @r.get("/signals")
    async def signals(request: Request) -> list[dict[str, Any]]:
        return library.signal_feed(S(request))

    # ------------------------------------------------------------- exports --
    @r.post("/exports")
    async def exports(request: Request, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        return await export(S(request), body)

    @r.get("/exports/{eid}/download")
    async def export_download(request: Request, eid: str) -> FileResponse:
        row = S(request).db.one("SELECT * FROM exports WHERE id = ?", (eid,))
        if row is None or not Path(row["path"]).exists():
            raise ApiError("not_found", "This export is no longer available.", status=404)
        base = (Path(settings.data_dir) / "exports").resolve()
        path = Path(row["path"]).resolve()
        if base not in path.parents:
            raise ApiError("not_found", "This export is no longer available.", status=404)
        return FileResponse(path, media_type=row["content_type"], filename=row["filename"])

    # --------------------------------------------------------------- debug --
    if settings.enable_debug_endpoints and not settings.competition:
        @r.get("/debug/record/{org}")
        async def debug_record(request: Request, org: str) -> dict[str, Any]:
            s = S(request)
            record = repo.latest_record(s.db, s.clean_org(org))
            if record is None:
                raise ApiError("not_found", "No stored record.", status=404)
            return record

    app.include_router(r)
    return app


app = create_app()
