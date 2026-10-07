#!/usr/bin/env python3
"""Live check of everything that depends on `.env` (keys, models, network). Prints no secrets.

    python scripts/live_check.py            # writes out/live-check.md and out/live-check.json

Sections: configuration · register reachability · LLM (Groq / OpenAI-compatible) · web search ·
end-to-end deep research on three real companies · the API with real data (status, profile,
brief, ask, interpret, research run with live events).
"""
from __future__ import annotations

import asyncio
import json
import time
import traceback
from typing import Any

from _bootstrap import BACKEND_ROOT, bootstrap

COMPANIES = [("923609016", "large listed group (ASA)"), ("810359862", "small company with a website"), ("985589003", "micro company from the universe")]


def main() -> None:
    bootstrap(quiet=True)
    from app.config import get_settings, validate_configuration
    from app.security.redaction import contains_secret, redact

    s = get_settings()
    out = BACKEND_ROOT / "out"
    out.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"started": time.strftime("%Y-%m-%d %H:%M:%S")}
    lines: list[str] = ["# COGNIS live check", ""]

    def section(title: str) -> None:
        lines.extend(["", f"## {title}", ""])
        print(f"\n== {title}", flush=True)

    def say(text: str) -> None:
        lines.append(f"- {text}")
        print(f"   {text}", flush=True)

    # ---------------------------------------------------------------- 1 config
    section("1. Configuration (.env)")
    try:
        warnings = validate_configuration(s)
        cfg = {"run_mode": s.run_mode, "llm_provider": s.llm_provider, "llm_enabled": s.llm_enabled, "groq_key_present": bool(s.groq_api_key),
               "groq_model": s.groq_model, "llm_min_interval_seconds": s.llm_min_interval_seconds, "search_enabled": s.search_enabled,
               "tavily_key_present": bool(s.tavily_api_key), "data_dir": str(s.data_dir), "warnings": warnings}
        report["config"] = cfg
        for k, v in cfg.items():
            say(f"{k}: {v}")
        if "onedrive" in str(s.data_dir).lower():
            say("NOTE: DATA_DIR is inside OneDrive — set DATA_DIR in .env to a local folder (see RUNBOOK A3)")
    except Exception as exc:  # configuration errors are reported, not raised
        report["config_error"] = str(exc)
        say(f"CONFIGURATION ERROR: {exc}")

    asyncio.run(_network_checks(s, report, section, say))
    try:
        _api_checks(report, section, say)
    except Exception as exc:
        report["api_error"] = f"{type(exc).__name__}: {exc}"
        say(f"API CHECK FAILED: {type(exc).__name__}: {redact(str(exc))[:300]}")
        traceback.print_exc()

    report["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    md = "\n".join(lines) + "\n"
    blob = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if contains_secret(md) or contains_secret(blob):  # belt and braces: never write a key to disk
        md, blob = redact(md), redact(blob)
    (out / "live-check.md").write_text(md, encoding="utf-8")
    (out / "live-check.json").write_text(blob, encoding="utf-8")
    print(f"\nWrote {out / 'live-check.md'}")


async def _network_checks(s: Any, report: dict[str, Any], section: Any, say: Any) -> None:
    from pydantic import BaseModel

    from app.agent.orchestrator import Orchestrator, ResearchOptions
    from app.competition.envelope import build_envelope, validate_envelope
    from app.connectors.base import ConnectorContext
    from app.connectors.search import web_search
    from app.net.http import HttpClient
    from app.providers.llm_base import structured
    from app.providers.registry import build_provider
    from app.runtime.budgets import BudgetLimits, CompanyBudget, RunBudget, unlimited_budget
    from app.security.redaction import redact

    async with HttpClient() as http:
        # ------------------------------------------------------- 2 register
        section("2. Brønnøysund register reachability")
        t = time.monotonic()
        res = await http.fetch("https://data.brreg.no/enhetsregisteret/api/enheter/923609016", connector="brreg", accept="application/json", expect="json",
                               use_cache=False)
        report["brreg"] = {"classification": res.classification, "status": res.status, "ms": int((time.monotonic() - t) * 1000)}
        say(f"enheter/923609016 → {res.classification} (HTTP {res.status}) in {report['brreg']['ms']} ms"
            + (f" · name: {(res.json() or {}).get('navn')}" if res.ok else f" · {res.error}"))

        # ------------------------------------------------------------ 3 LLM
        section("3. Language model")
        provider = build_provider(http, s)
        if provider is None:
            say("No LLM configured (LLM_PROVIDER / key / model) — the agent uses deterministic fallbacks.")
            report["llm"] = {"enabled": False}
        else:
            class Ping(BaseModel):
                ok: bool
                word: str

            budget = CompanyBudget(unlimited_budget(), max_requests=50, max_seconds=120, max_llm_calls=5, max_searches=0)
            t = time.monotonic()
            try:
                out = await structured(provider.with_budget(budget), [
                    {"role": "system", "content": "Reply with JSON only."},
                    {"role": "user", "content": 'Return {"ok": true, "word": "COGNIS"} exactly.'}], Ping, max_tokens=120, task="ping")
                report["llm"] = {"enabled": True, "ok": out.ok and out.word == "COGNIS", "ms": int((time.monotonic() - t) * 1000), "model": getattr(provider, "model", None)}
                say(f"{provider.name} / {getattr(provider, 'model', '?')}: structured JSON {'OK' if report['llm']['ok'] else 'returned unexpected content'} in {report['llm']['ms']} ms")
            except Exception as exc:
                report["llm"] = {"enabled": True, "ok": False, "error": redact(str(exc))[:400]}
                say(f"LLM call FAILED: {report['llm']['error']}")
                lister = getattr(provider, "list_models", None)
                if lister is not None:
                    ids, problem = await lister()
                    report["llm"]["models_listing"] = {"problem": problem, "count": len(ids)}
                    if problem:
                        say(f"Could not list the models for this key: {problem}")
                        say("404 here usually means a wrong GROQ_BASE_URL (must be https://api.groq.com/openai/v1); 401/403 means the key is invalid or blocked.")
                    else:
                        chat = [m for m in ids if not any(x in m for x in ("whisper", "tts", "guard", "orpheus", "embed", "transcribe"))]
                        say(f"Models this key can use ({len(ids)}): {', '.join(ids)}")
                        preferred = next((m for m in ("llama-3.3-70b-versatile", "openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.1-8b-instant") if m in chat), chat[0] if chat else None)
                        if preferred:
                            report["llm"]["suggested_model"] = preferred
                            say(f"Put this line in .env, save, and re-run:  GROQ_MODEL={preferred}")
                else:
                    say("Check the model name and that the key is active.")

        # --------------------------------------------------------- 4 search
        section("4. Web search (Tavily)")
        if not s.search_enabled:
            say("Not configured (TAVILY_API_KEY empty) — discovery uses the register's website and e-mail domain only.")
            report["search"] = {"enabled": False}
        else:
            ctx = ConnectorContext(org_number="923609016", http=http, budget=unlimited_budget(), run_id="live-check", settings=s, fresh=True)
            mod, hits = await web_search(ctx, '"923609016"')
            credits = (mod.value or {}).get("credits") if isinstance(mod.value, dict) else None
            report["search"] = {"enabled": True, "state": mod.state, "http_status": mod.http_status, "hits": len(hits), "domains": [h.domain for h in hits[:5]], "credits_used": credits, "note": mod.note}
            say(f"Tavily search → {mod.state}, {len(hits)} hits; top domains: {', '.join(report['search']['domains']) or '—'}"
                + (f" · credits used: {credits}" if credits is not None else "") + (f" · {mod.note}" if mod.note else ""))
            if mod.state not in ("available", "not_available"):
                say("Tavily did not answer normally. 401 = key wrong/missing 'tvly-'; 432/433 = plan credits used up; otherwise check the network.")

        # ---------------------------------------------------- 5 end-to-end
        section("5. End-to-end deep research (live sources, LLM if configured)")
        orch = Orchestrator(http=http, run_budget=RunBudget(BudgetLimits(max_requests=300, max_cost_usd=1.0, max_runtime_seconds=900)), provider=provider)
        report["companies"] = []
        for org, label in COMPANIES:
            t = time.monotonic()
            try:
                rec = await orch.research(org, run_id="live-check", options=ResearchOptions(mode="deep", include_geo=True))
            except Exception as exc:  # research never raises, but be explicit
                say(f"{org} ({label}): EXCEPTION {type(exc).__name__}")
                continue
            env = build_envelope(rec, run_id="live-check")
            problems = validate_envelope(env)
            available = [c for c in env["claims"] if c["availability"] == "available"]
            web = rec.get("website") or {}
            desc = next((c for c in rec["claims"] if c["field"] == "business_description"), None)
            row = {
                "org": org, "label": label, "name": (rec.get("identity") or {}).get("legal_name"), "entity_state": rec["entity_state"],
                "seconds": round(time.monotonic() - t, 1), "requests": rec["operations"].get("requests"), "llm_calls": (rec["operations"].get("llm") or {}).get("calls"),
                "claims_available": len(available), "claims_total": len(env["claims"]), "envelope_problems": problems,
                "website": {"domain": web.get("domain"), "verified": web.get("verified"), "signals": (web.get("audit") or {}).get("signals"),
                            "decision": (web.get("audit") or {}).get("decision")},
                "site_attempts": [{k: a.get(k) for k in ("domain", "origin", "decision", "score", "conflicts")} for a in rec.get("site_attempts") or []],
                "summary_method": (rec.get("summary") or {}).get("method"), "summary": (rec.get("summary") or {}).get("text"),
                "description_method": desc["extraction_method"] if desc else None, "planner": [t_.get("planner") for t_ in rec.get("trace") or [] if t_.get("planner")],
                "llm_errors": [e for e in rec.get("errors") or [] if str(e.get("stage", "")).startswith("llm")],
                "other_errors": [e for e in rec.get("errors") or [] if not str(e.get("stage", "")).startswith("llm")],
                "module_states": {k: v.get("state") for k, v in (rec.get("modules") or {}).items()},
            }
            report["companies"].append(row)
            say(f"**{row['name']}** ({org}, {label}): {row['entity_state']} · {row['claims_available']} available claims · {row['requests']} requests · "
                f"{row['llm_calls']} LLM calls · {row['seconds']} s · envelope {'valid' if not problems else 'PROBLEMS: ' + '; '.join(problems[:3])}")
            say(f"   website: {row['website']['domain'] or '—'} → {row['website']['decision'] or 'none'} {row['website']['signals'] or ''}")
            say(f"   summary: {row['summary_method']} · description: {row['description_method'] or 'none'} · planner: {row['planner'] or 'not used'}")
            if row["llm_errors"]:
                say(f"   LLM issues: {row['llm_errors'][:2]}")
            if row["other_errors"]:
                say(f"   other issues: {row['other_errors'][:2]}")
            if row["summary"]:
                say(f"   “{row['summary'][:400]}”")


def _api_checks(report: dict[str, Any], section: Any, say: Any) -> None:
    from fastapi.testclient import TestClient

    from app.api.main import create_app

    section("6. API with real data (in-process, uses DATA_DIR)")
    with TestClient(create_app()) as c:
        st = c.get("/api/status").json()
        say(f"/status: backend {st['backend']} · sources: " + ", ".join(f"{x['name'].split(' (')[0]}={x['status']}" for x in st["sources"][:9]))
        p = c.get("/api/companies/923609016")
        say(f"/companies/923609016 → HTTP {p.status_code} · {p.json().get('company', {}).get('legalName') if p.status_code == 200 else p.json()}")
        run = c.post("/api/research/runs", json={"query": "Equinor", "mode": "quick"}).json()
        if run.get("status") == "ambiguous":
            say(f"/research/runs 'Equinor' → ambiguous ({len(run['ambiguity']['candidates'])} candidates) — resolving by org number instead (never guesses)")
            run = c.post("/api/research/runs", json={"orgNumber": "923609016", "query": "923609016", "mode": "quick"}).json()
        if "id" not in run:
            say(f"/research/runs → {run}")
            report["api"] = {"run_error": run}
            return
        events = []
        with c.stream("GET", f"/api/research/runs/{run['id']}/events?lastSeq=0") as stream:
            for line in stream.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
                    if events[-1]["type"] in ("run.completed", "run.failed"):
                        break
        last = events[-1] if events else {}
        say(f"research run → {last.get('type')} after {len(events)} events · facts confirmed {sum(1 for e in events if e['type'] == 'fact.confirmed')}"
            + (f" · coverage {last['coverage']['complete']}/5" if last.get("coverage") else f" · {last.get('message', '')}"))
        brief = c.get("/api/companies/923609016/brief")
        say(f"/brief → HTTP {brief.status_code} · sections with items: {sum(1 for x in brief.json().get('sections', []) if x['items'])}/7")
        ans = c.post("/api/research/ask", json={"orgNumber": "923609016", "question": "Who is the CEO and what was the latest revenue?", "fresh": False}).json()
        say(f"/research/ask → {len(ans.get('blocks', []))} cited blocks: " + " | ".join(b["text"][:120] for b in ans.get("blocks", [])[:3]))
        it = c.post("/api/companies/interpret", json={"text": "software companies in Bergen with more than 50 employees"}).json()
        say("/companies/interpret → " + ", ".join(f"{f['key']}={f['display']}" for f in it.get("filters", [])))
        disc = c.post("/api/companies/discover", json={"text": "software companies in Bergen with more than 50 employees", "interpret": True, "filters": {},
                                                     "sort": "relevance", "page": 1, "pageSize": 5}).json()
        say(f"/companies/discover → {disc.get('total')} matches; first: " + ", ".join(x["legalName"] for x in disc.get("items", [])[:3]))
        report["api"] = {"run_events": len(events), "run_final": last.get("type"), "brief_status": brief.status_code, "ask_blocks": len(ans.get("blocks", [])),
                         "discover_total": disc.get("total")}


if __name__ == "__main__":
    main()
