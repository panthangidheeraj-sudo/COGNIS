"""Executive brief, change explanations and Q&A — compiled from saved evidence only.

Deterministic first: every line restates a verified profile fact with its
evidence. The LLM (when configured) may add a clearly labelled synthesis whose
numbers must appear in the observed facts; otherwise ``synthesis`` is null.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from ..agent import llm_tasks
from ..core.util import format_int, format_money, now_iso
from ..extraction.boilerplate import is_boilerplate
from ..identity.model import CanonicalIdentity
from .question_router import route_question

CHANGE_PRIORITY = ["leadership", "status", "financial", "filing", "ownership", "location", "address", "hiring", "employees", "event", "website"]
CAVEAT = "AI synthesis of the sources above. It is not a verified fact, and the evidence does not establish cause and effect on its own."


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso)
    if not m:
        return iso
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{int(m.group(3)):02d} {months[int(m.group(2)) - 1]} {m.group(1)}"


def _m(fact: dict[str, Any]) -> str:
    """An amount in the currency its own filing states (never an assumed NOK)."""
    return format_money(fact["value"], fact.get("currency"))


def _comparable(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Two amounts may be compared (change, growth) only when both are stated in the same currency; no conversion is ever applied."""
    return bool(a.get("currency")) and a.get("currency") == b.get("currency")


def _no_conversion(prev: dict[str, Any], prev_period: str) -> str:
    return f" ({prev_period} was filed in {prev.get('currency') or 'an unstated currency'}; no currency conversion is applied)"


def _pct(v: float) -> str:
    return f"{v:.1f}%"


def _item(iid: str, text: str, evidence: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    return {"id": iid, "text": text, "evidence": evidence, "status": "verified", **{k: v for k, v in kw.items() if v is not None}}


def _series(p: dict[str, Any], key: str) -> dict[str, Any] | None:
    return next((s for s in p["financials"]["series"] if s["key"] == key), None)


def brief_from_profile(p: dict[str, Any]) -> dict[str, Any]:
    c = p["company"]
    ident = p["identity"]
    researched = c.get("researchState") != "not_researched"
    sections = []

    what = []
    if p.get("description"):
        what.append(_item("what-desc", str(p["description"]["value"]), p["description"]["evidence"], factId=p["description"]["id"]))
    if ident.get("industry") and ident["industry"]["status"] == "verified":
        what.append(_item("what-ind", f"Registered industry: {ident['industry']['value']}.", ident["industry"]["evidence"], factId=ident["industry"]["id"]))
    if ident.get("legalForm") and ident.get("founded"):
        what.append(_item("what-form", f"{ident['legalForm']['value']}, founded {str(ident['founded']['value'])[:4]}" + (f", registered in {c['municipality']}." if c.get("municipality") else "."),
                          ident["legalForm"]["evidence"] + ident["founded"]["evidence"], factId=ident["founded"]["id"]))
    sections.append({"id": "what", "title": "What the company does", "items": what, "emptyText": "No verified description."})

    scale = []
    emp = next((k for k in p["keyMetrics"] if k["field"] == "overview.employees"), None)
    if emp and emp["status"] == "verified" and emp["value"] is not None:
        scale.append(_item("scale-emp", f"{format_int(emp['value'])} employees registered in Enhetsregisteret.", emp["evidence"], label="Employees", value=format_int(emp["value"]),
                           factId=emp["id"]))
    sites = next((k for k in p["keyMetrics"] if k["field"] == "overview.locations"), None)
    if sites and sites["status"] == "verified" and sites["value"]:
        scale.append(_item("scale-sites", f"{sites['value']} registered establishment{'' if sites['value'] == 1 else 's'} (underenheter).", sites["evidence"], label="Establishments",
                           factId=sites["id"]))
    sections.append({"id": "scale", "title": "Scale", "items": scale, "emptyText": "No verified size information."})

    fin = []
    rev = _series(p, "revenue")
    if rev and rev["points"]:
        last = rev["points"][-1]
        prev = rev["points"][-2] if len(rev["points"]) > 1 else None
        text = f"Revenue {_m(last['fact'])} in {last['period']}"
        if prev and prev["fact"]["value"]:
            if _comparable(last["fact"], prev["fact"]):
                g = (last["fact"]["value"] - prev["fact"]["value"]) / abs(prev["fact"]["value"]) * 100
                text += f", {'up' if g >= 0 else 'down'} {_pct(abs(g))} from {_m(prev['fact'])} in {prev['period']}"
            else:
                text += _no_conversion(prev["fact"], prev["period"])
        fin.append(_item("fin-rev", text + ".", last["fact"]["evidence"], label="Revenue", value=_m(last["fact"]), reportingPeriod=last["period"],
                         factId=last["fact"]["id"], evidenceState=last["fact"]["evidenceState"]))
    for key, label in (("operating_result", "Operating result"), ("annual_result", "Annual result")):
        s = _series(p, key)
        if s and s["points"]:
            last = s["points"][-1]
            fin.append(_item(f"fin-{key}", f"{label} {_m(last['fact'])} in {last['period']}.", last["fact"]["evidence"], label=label,
                             value=_m(last["fact"]), reportingPeriod=last["period"], factId=last["fact"]["id"]))
    eqr = next((r for r in p["financials"].get("ratios") or [] if r["key"] == "equity_ratio"), None)
    if eqr:
        eq = _series(p, "equity")
        fin.append(_item("fin-eqr", f"Equity ratio {_pct(eqr['value'])} ({eqr['formula']}, {eqr['period']}).", eq["points"][-1]["fact"]["evidence"] if eq and eq["points"] else [],
                         label="Equity ratio", value=_pct(eqr["value"]), reportingPeriod=eqr["period"]))
    sections.append({"id": "financials", "title": "Latest financial position", "items": fin, "emptyText": p["financials"].get("message") or "No filed annual accounts found."})

    lead = []
    people = p["people"]["people"]
    ceo = next((x for x in people if x["role"] == "CEO"), None)
    if ceo:
        lead.append(_item("lead-ceo", f"{ceo['name']} is the registered CEO (daglig leder).", ceo["fact"]["evidence"], label="CEO", value=ceo["name"], factId=ceo["fact"]["id"]))
    chair = next((x for x in people if x["role"] == "Chair of the board"), None)
    if chair:
        lead.append(_item("lead-chair", f"{chair['name']} chairs the board.", chair["fact"]["evidence"], label="Chair", value=chair["name"], factId=chair["fact"]["id"]))
    board = [x for x in people if x["roleGroup"] == "board"]
    if len(board) > 1:
        lead.append(_item("lead-board", f"{len(board)} board roles are registered.", [e for x in board for e in x["fact"]["evidence"][:1]], label="Board"))
    sections.append({"id": "leadership", "title": "Leadership", "items": lead, "emptyText": "Leadership not verified in the searched sources." if researched else "Not researched yet."})

    locs = []
    reg = ident.get("registeredAddress")
    if reg and reg.get("value"):
        locs.append(_item("loc-reg", f"Registered business address: {reg['value']}. An operating headquarters is not separately verified.", reg["evidence"],
                          label="Registered address", factId=reg["id"]))
    munis = sorted({loc["municipality"] for loc in p["locations"]["locations"] if loc["kind"] == "operating" and loc.get("municipality")})
    if munis:
        locs.append(_item("loc-all", f"Registered establishments in {', '.join(munis)}.", [e for loc in p["locations"]["locations"] if loc["kind"] == "operating" for e in loc["fact"]["evidence"][:1]],
                          label="Establishments"))
    sections.append({"id": "locations", "title": "Locations", "items": locs})

    hiring = []
    h = p["hiring"]
    if h.get("totalCurrent"):
        cats = ", ".join(f"{x['name']} {x['count']}" for x in h["categories"][:3])
        where = ", ".join(x["name"] for x in h["locations"][:3])
        hiring.append(_item("hire", f"{h['totalCurrent']} verified current opening{'' if h['totalCurrent'] == 1 else 's'} ({cats}) in {where}." + (f" {h['message']}" if h.get("message") else ""),
                            [e for j in h["jobs"] if j["state"] == "current" for e in j["evidence"]][:4], label="Open positions", value=str(h["totalCurrent"])))
    sections.append({"id": "hiring", "title": "Hiring", "items": hiring, "emptyText": "Not researched yet." if h["status"] == "pending" else
                     (h.get("message") or "No verified openings found in the sources checked. This does not mean the company is not hiring.")})

    ch_items = []
    for x in sorted([x for x in p["changes"]["changes"] if x["material"]], key=lambda x: CHANGE_PRIORITY.index(x["category"]) if x["category"] in CHANGE_PRIORITY else 99)[:5]:
        detail = f" ({x['previous']} → {x['current']})" if x.get("previous") and x.get("current") else (f": {x['current']}" if x.get("current") else "")
        ch_items.append(_item(f"ch-{x['id']}", f"{x.get('headline') or x['label']}{detail} · detected {_fmt_date(x['detectedAt'])}.", x["evidence"], label=x["label"]))
    since = p["changes"].get("since")
    sections.append({"id": "changes", "title": "Major recent changes", "items": ch_items, "emptyText": "Not researched yet." if p["changes"]["status"] == "pending" else
                     (f"No verified material changes were detected since the previous research on {_fmt_date(since)}." if since else p["changes"].get("message"))})

    gaps = [f"{k['label']}: {k['text']}" for k in p["knowns"] if k["status"] in ("unknown", "blocked")]
    gaps += [a["note"] for a in c["coverage"]["areas"] if a["status"] != "complete" and a.get("note")]
    source_ids = list(dict.fromkeys(e["sourceId"] for s in sections for i in s["items"] for e in i["evidence"]))
    out = {"orgNumber": c["orgNumber"], "companyName": c["legalName"], "statusLabel": c.get("statusLabel") or c["status"], "generatedAt": now_iso(),
           "researchedAt": c.get("lastResearchedAt"), "coverage": c["coverage"], "sections": sections, "gaps": list(dict.fromkeys(gaps)), "sourceIds": source_ids,
           "sourceIndex": p["sourceIndex"]}
    if c.get("municipality"):
        out["location"] = f"{c['municipality']}, Norway"
    if p.get("artifactId"):
        out["artifactId"] = p["artifactId"]
    return out


async def explain(p: dict[str, Any], subject: dict[str, Any], runner: llm_tasks.LLMRunner | None, *, origin: str = "saved_evidence") -> dict[str, Any]:
    observed: list[dict[str, Any]] = []
    reported: list[dict[str, Any]] = []
    gaps: list[str] = []
    question = "What explains this change?"
    changes = p["changes"]["changes"]

    def obs(oid: str, text: str, evidence: list[dict[str, Any]]) -> None:
        observed.append({"id": oid, "text": text, "evidence": evidence})

    if subject.get("kind") == "metric":
        s = _series(p, subject.get("metric") or "")
        a = next((x for x in (s or {}).get("points", []) if x["period"] == subject.get("fromPeriod")), None)
        b = next((x for x in (s or {}).get("points", []) if x["period"] == subject.get("toPeriod")), None)
        question = f"What explains the change in {(s or {}).get('label', subject.get('metric', 'the metric')).lower()} from {subject.get('fromPeriod')} to {subject.get('toPeriod')}?"
        if s and a and b and a["fact"]["value"] is not None and b["fact"]["value"] is not None:
            av, bv = a["fact"]["value"], b["fact"]["value"]
            same = _comparable(a["fact"], b["fact"])
            pct = (bv - av) / abs(av) * 100 if av and same else None
            obs("obs-metric", f"{s['label']} was {_m(a['fact'])} in {a['period']} and {_m(b['fact'])} in {b['period']}"
                + (f" ({'+' if pct >= 0 else '−'}{_pct(abs(pct))})." if pct is not None else (" (different currencies; no conversion or change is computed)." if not same else ".")),
                a["fact"]["evidence"][:1] + b["fact"]["evidence"][:1])
            for key in ("operating_result", "annual_result", "total_assets"):
                if key == subject.get("metric"):
                    continue
                ss = _series(p, key)
                x = next((pt for pt in (ss or {}).get("points", []) if pt["period"] == subject.get("fromPeriod")), None)
                y = next((pt for pt in (ss or {}).get("points", []) if pt["period"] == subject.get("toPeriod")), None)
                if ss and x and y:
                    obs(f"obs-{key}", f"{ss['label']} went from {_m(x['fact'])} to {_m(y['fact'])} over the same periods.",
                        x["fact"]["evidence"][:1] + y["fact"]["evidence"][:1])
            y0, y1 = int(re.sub(r"\D", "", subject.get("fromPeriod") or "0")[:4] or 0), int(re.sub(r"\D", "", subject.get("toPeriod") or "0")[:4] or 0)
            for e in p["activity"]["events"]:
                if e["type"] in ("acquisition", "contract", "location", "funding", "partnership", "restructuring") and e["significance"] != "routine" and y0 <= int(e["date"][:4]) <= y1 + 1:
                    obs(f"obs-{e['id']}", f"{_fmt_date(e['date'])}: {e['title']}.", e["evidence"])
        else:
            gaps.append("Filed figures for both periods are not available.")
    else:
        ch = next((x for x in changes if x["id"] == subject.get("changeId")), None)
        if ch is None:
            gaps.append("This change is no longer part of the saved research.")
        else:
            question = f"What explains: {ch.get('headline') or ch['label']}?"
            obs("obs-change", f"{ch['label']}: {(ch.get('previous') + ' → ') if ch.get('previous') else ''}{ch.get('current') or ''} (detected {_fmt_date(ch['detectedAt'])}).", ch["evidence"])
            related = {"employees": ["hiring", "location"], "hiring": ["employees", "location"], "location": ["hiring", "employees"]}.get(ch["category"], [])
            for r in changes:
                if r["id"] != ch["id"] and r["category"] in related:
                    obs(f"obs-{r['id']}", f"{r.get('headline') or r['label']} (detected {_fmt_date(r['detectedAt'])}).", r["evidence"])
            if ch["category"] == "financial":
                s = _series(p, "revenue")
                if s and len(s["points"]) >= 2:
                    a, b = s["points"][-2], s["points"][-1]
                    obs("obs-rev", f"Filed revenue: {_m(a['fact'])} ({a['period']}) → {_m(b['fact'])} ({b['period']}).",
                        a["fact"]["evidence"][:1] + b["fact"]["evidence"][:1])
    # Company-reported statements: dated news items from the verified website within the window.
    for i, e in enumerate(x for x in p["activity"]["events"] if x["significance"] != "routine" and x["sourceIds"] and any(s.startswith("web-") for s in x["sourceIds"])):
        if i >= 3:
            break
        reported.append({"id": f"rep-{i}", "text": e["title"], "sourceId": e["sourceIds"][0], "quote": (e["evidence"][0].get("excerpt") if e["evidence"] else e["title"]),
                         "evidence": e["evidence"]})
    if not reported:
        gaps.append("No source in the saved evidence states a reason for this change.")
    synthesis = None
    if runner is not None and runner.enabled and observed:
        text = await llm_tasks.explain_synthesis(runner, question, [o["text"] for o in observed], [r["quote"] or r["text"] for r in reported])
        if text:
            synthesis = {"text": text, "basis": [o["id"] for o in observed] + [r["id"] for r in reported], "caveat": CAVEAT}
    if synthesis is None and len(observed) >= 2:
        first = observed[0]["text"].rstrip(".")
        rest = " and ".join(o["text"].rstrip(".") for o in observed[1:3])
        synthesis = {"text": f"{first}. This coincides with: {rest}. No source links these facts directly, so this is a co-occurrence, not an explanation.",
                     "basis": [o["id"] for o in observed], "caveat": CAVEAT}
    if p["changes"].get("since") and subject.get("kind") == "change":
        gaps.append(f"Only changes detected since the previous research on {_fmt_date(p['changes']['since'])} were considered.")
    return {"subject": subject, "question": question, "observed": observed, "reported": reported, "synthesis": synthesis, "gaps": gaps, "origin": origin,
            "generatedAt": now_iso()}


# --------------------------------------------------------------------- ask --
def _cite(p: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for e in evidence:
        if e["sourceId"] in seen:
            continue
        seen.add(e["sourceId"])
        out.append({"evidence": e, "sourceName": (p["sourceIndex"].get(e["sourceId"]) or {}).get("name", e["sourceId"])})
        if len(out) >= 3:
            break
    return out


def _all_facts(p: dict[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for f in p["identity"].values():
        if isinstance(f, dict) and f.get("status") == "verified":
            facts.append(f)
    for f in p["keyMetrics"]:
        if f.get("status") == "verified":
            facts.append(f)
    for s in p["financials"]["series"]:
        facts.extend(pt["fact"] for pt in s["points"])
    facts.extend(x["fact"] for x in p["people"]["people"])
    facts.extend(loc["fact"] for loc in p["locations"]["locations"])
    if p.get("description"):
        facts.append(p["description"])
    seen: set[str] = set()
    return [f for f in facts if not (f["id"] in seen or seen.add(f["id"]))]


def _fact_text(f: dict[str, Any]) -> str:
    v = f.get("displayValue") or (format_money(f["value"], f.get("currency")) if f.get("currency") and isinstance(f["value"], (int, float)) else f["value"])
    return f"{f['label']}: {v}" + (f" ({f['reportingPeriod']})" if f.get("reportingPeriod") else "")


SOURCE_LABEL = {"investor_relations": "the company's investor-relations page", "company_newsroom": "the company's newsroom", "public_procurement": "an official procurement notice",
                "official_registry": "an official registry", "secondary_news": "press coverage"}
BUSINESS_TYPES = {"contract", "acquisition", "funding", "results", "partnership", "discovery", "project", "production", "regulatory", "restructuring", "leadership", "announcement"}
STOP = {"what", "which", "does", "this", "that", "with", "have", "about", "company", "their", "there", "show", "tell", "give", "from", "when", "many", "much", "the", "and", "for", "are", "how"}


def _scope(fact: dict[str, Any]) -> str:
    """The accounting scope exactly as the filing states it (``regnskapstype``); nothing is inferred when it is not stated."""
    for e in fact.get("evidence") or []:
        m = re.search(r"regnskapstype\s+([A-Za-zÆØÅæøå]+)", str(e.get("excerpt") or ""))
        if m:
            kind = m.group(1).upper()
            return {"SELSKAP": "company-only (parent) annual accounts", "KONSERN": "consolidated (group) annual accounts"}.get(kind, f"annual accounts of type {m.group(1)}")
    return "accounting scope not stated by the source"


def _span(period: str | None) -> str:
    return period.replace("/", " to ") if period else ""


def _financial_blocks(p: dict[str, Any], route: Any, add: Any, gaps: list[str]) -> None:
    keys = route.metrics or (["revenue"] if route.wants_period else ["revenue", "operating_result", "annual_result"])
    shown: list[dict[str, Any]] = []
    for key in keys:
        s = _series(p, key)
        label = {"revenue": "Revenue", "operating_result": "Operating result", "annual_result": "Annual result", "total_assets": "Total assets", "equity": "Equity", "debt": "Total debt", "cash": "Cash and bank deposits"}.get(key, key)
        if not s or not s["points"]:
            gaps.append(f"{label}: not found in the filed annual accounts" + (f" ({p['financials'].get('message')})" if p["financials"].get("message") and not p["financials"].get("series") else "") + ".")
            continue
        pt = s["points"][-1]
        fact = pt["fact"]
        text = f"{label}: {_m(fact)} for {pt['period']}"
        if fact.get("reportingPeriod"):
            text += f" (reporting period {_span(fact['reportingPeriod'])})"
        text += f" — {_scope(fact)}"
        if not fact.get("currency"):
            text += "; the filing does not state a currency"
        text += "."
        used = [fact]
        if route.wants_comparison and len(s["points"]) > 1:
            prev = s["points"][-2]
            text += f" Previous year: {_m(prev['fact'])} for {prev['period']}."
            used.append(prev["fact"])
        add(text, used)
        shown.append(fact)
    if route.wants_period and shown:
        periods = {f.get("reportingPeriod") for f in shown}
        if len(periods) == 1:
            f0 = shown[0]
            add(f"Reporting period: {_span(f0.get('reportingPeriod')) or 'not stated'} ({p['financials'].get('latestPeriod') or 'latest filed year'}), the most recent annual accounts on record.", [f0])
        else:
            gaps.append("The latest figures come from different reporting periods; each line states its own period.")
    if shown and all(_scope(f).startswith("company-only") for f in shown):
        gaps.append("These are company-only accounts. Consolidated group figures are not available here and are never inferred from them." if route.wants_scope
                    else "Figures are from the company's own (non-consolidated) accounts; group totals, if the company has subsidiaries, may differ and are not inferred.")


def _announcement_blocks(p: dict[str, Any], route: Any, today: date, origin: str, add_event: Any, gaps: list[str]) -> str | None:
    """Dated announcements inside the requested window. Returns a limitation sentence when none qualify."""
    act = p.get("activity") or {}
    days = route.window_days or 365
    start = today - timedelta(days=days)
    wanted = set().union(*(t for _l, t in route.categories)) if route.categories else BUSINESS_TYPES
    picked = []
    for e in act.get("events") or []:
        if e.get("type") not in wanted or e.get("sourceType") == "official_registry" or e.get("significance") in ("routine", "minor"):
            continue
        if is_boilerplate(e.get("title")):
            continue
        try:
            day = date.fromisoformat(e["date"])
        except (KeyError, ValueError):
            continue
        if not (start <= day <= today) or not e.get("evidence"):
            continue
        picked.append(e)
    picked.sort(key=lambda e: (e.get("rank") if isinstance(e.get("rank"), int) else 9999, e["date"]))
    for e in picked[:8]:
        add_event(e)
    window = route.window_text or "the last 12 months"
    noun = " / ".join(label for label, _t in route.categories) if route.categories else "business announcements"
    unread = [f"{c.get('name')} ({c.get('status')}{': ' + c['note'] if c.get('note') else ''})" for c in act.get("sourcesChecked") or [] if c.get("status") not in ("read", "ok", "available")]
    if unread:
        gaps.append("Sources that could not be fully read: " + "; ".join(unread[:5]) + ".")
    if act.get("status") in ("not_available", "partial") and act.get("message"):
        gaps.append(str(act["message"]))
    for label, types in route.categories:
        if picked and not any(e["type"] in types for e in picked):
            gaps.append(f"No {label} announcement dated within {window} was found in the evidence on record.")
    if picked:
        return None
    live = "Use “Research more (live sources)” to check the company's newsroom and press coverage now." if origin == "saved_evidence" else "Live sources were queried for this question and returned nothing verifiable."
    return (f"No {noun} dated within {window} were found in the evidence on record for this company. That is not evidence that none were made — "
            f"only that none could be verified from the sources read. {live}")


def _limitation_text(route: Any, origin: str) -> str:
    live = ("“Research more (live sources)” can check for anything that has since been announced, but it cannot reveal what has not been published."
            if origin == "saved_evidence" else "Live public sources were checked as well and cannot verify this either.")
    return (f"This cannot be answered from public sources. Confidential, unannounced or future matters (“{route.limit_reason}”) are not published, so COGNIS cannot verify them and will not "
            f"infer or guess them. Only what the company, a registry or the press has already made public can be verified. {live}")


def _relevant_facts(facts: list[dict[str, Any]], question: str) -> list[dict[str, Any]]:
    """Facts whose own label shares a meaningful word with the question — never 'whatever is saved'."""
    words = {w for w in re.findall(r"[^\W\d_]{4,}", question.casefold()) if w not in STOP}
    out = []
    for f in facts:
        label = f"{f.get('label', '')} {f.get('field', '')}".casefold()
        if any(w[:5] in label for w in words) and not (isinstance(f.get("value"), str) and is_boilerplate(f["value"])):
            out.append(f)
    return out


async def answer(p: dict[str, Any], question: str, runner: llm_tasks.LLMRunner | None, *, origin: str = "saved_evidence", today: date | None = None) -> dict[str, Any]:
    route = route_question(question)
    today = today or date.today()
    blocks: list[dict[str, Any]] = []
    gaps: list[str] = []
    limitation: str | None = None
    name = p["company"]["legalName"]
    n = 0

    def block(text: str, facts: list[dict[str, Any]], *, evidence: list[dict[str, Any]] | None = None, detail: str | None = None) -> None:
        nonlocal n
        n += 1
        ev = evidence if evidence is not None else [e for f in facts for e in f["evidence"]]
        b: dict[str, Any] = {"id": f"b{n}", "text": text, "factIds": [f["id"] for f in facts], "citations": _cite(p, ev)}
        period = next((f.get("reportingPeriod") for f in facts if f.get("reportingPeriod")), None)
        if period:
            b["reportingPeriod"] = period
        if detail:
            b["detail"] = detail
        blocks.append(b)

    def event_block(e: dict[str, Any]) -> None:
        desc = str(e.get("description") or "").strip()
        text = f"{_fmt_date(e['date'])} — {e['title']}."
        if desc and not is_boilerplate(desc) and desc.casefold()[:40] != str(e["title"]).casefold()[:40]:
            text += f" {desc[:240]}"
        url = e.get("url") or next((x.get("url") for x in e.get("evidence") or [] if x.get("url")), None)
        text += f" Source: {SOURCE_LABEL.get(e.get('sourceType'), 'a public source')}."
        block(text, [], evidence=list(e.get("evidence") or []), detail=url)

    kinds = route.kinds
    facts = [f for f in _all_facts(p) if not (isinstance(f.get("value"), str) and is_boilerplate(f["value"]))]
    if "limitation" in kinds:
        limitation = _limitation_text(route, origin)
    else:
        if "financial" in kinds:
            if p["financials"].get("series"):
                _financial_blocks(p, route, block, gaps)
            else:
                gaps.append(p["financials"].get("message") or "No filed annual accounts were found, so revenue and results are unknown.")
        if "announcements" in kinds:
            missing = _announcement_blocks(p, route, today, origin, event_block, gaps)
            if missing and blocks:
                gaps.append(missing)
            elif missing:
                limitation = missing
        if "people" in kinds:
            for x in p["people"]["people"][:8]:
                block(f"{x['name']} — {x['role']}.", [x["fact"]])
            if not p["people"]["people"]:
                gaps.append(p["people"].get("message") or "No registered roles were found.")
        if "locations" in kinds:
            for loc in p["locations"]["locations"][:6]:
                block(f"{loc['label']}: {loc['address']}{', ' + loc['municipality'] if loc.get('municipality') else ''}.", [loc["fact"]])
            if not p["locations"]["locations"]:
                gaps.append(p["locations"].get("message") or "No registered locations were found.")
        if "hiring" in kinds:
            h = p["hiring"]
            if h["totalCurrent"] is None:
                gaps.append(h.get("message") or "No verified openings found in the sources checked. This does not mean the company is not hiring.")
            else:
                f = next((k for k in p["keyMetrics"] if k["field"] == "overview.openPositions"), None)
                block(f"{h['totalCurrent']} verified current opening{'' if h['totalCurrent'] == 1 else 's'} found." + (f" {h['message']}" if h.get("message") else "") + (" " + "; ".join(j["title"] for j in h["jobs"][:5]) if h["jobs"] else ""),
                      [f] if f else [])
        if "changes" in kinds:
            for c in p["changes"]["changes"][:5]:
                n += 1
                blocks.append({"id": f"b{n}", "text": f"{c['label']}: {c.get('previous') + ' → ' if c.get('previous') else ''}{c.get('current') or ''} (detected {_fmt_date(c['detectedAt'])}).", "citations": _cite(p, c["evidence"])})
            if not p["changes"]["changes"]:
                gaps.append(p["changes"].get("message") or "No changes were detected since the previous research.")
        if "gaps" in kinds:
            gaps.extend(f"{k['label']}: {k['text']}" for k in p["knowns"] if k["status"] in ("unknown", "blocked"))
        if "overview" in kinds:
            desc = p.get("description")
            if desc and not is_boilerplate(str(desc["value"])):
                block(str(desc["value"]), [desc])
            else:
                gaps.append("No company-stated description could be verified: the website text found was page navigation, not a description.")
            rev = _series(p, "revenue")
            if rev and rev["points"]:
                last = rev["points"][-1]
                block(f"Revenue {_m(last['fact'])} in {last['period']} ({_scope(last['fact'])}).", [last["fact"]])
            ceo = next((x for x in p["people"]["people"] if x["role"] == "CEO"), None)
            if ceo:
                block(f"{ceo['name']} is the registered CEO.", [ceo["fact"]])
            emp = next((k for k in p["keyMetrics"] if k["field"] == "overview.employees" and k["status"] == "verified"), None)
            if emp:
                block(f"The register lists {format_int(emp['value'])} employees.", [emp])
        if "other" in kinds:
            related = _relevant_facts(facts, question)
            if related and runner is not None and runner.enabled:
                ident = CanonicalIdentity(org_number=p["company"]["orgNumber"], legal_name=name)
                by_id = {f["id"]: f for f in related}
                for b in await llm_tasks.answer_question(runner, ident, question, [(f["id"], _fact_text(f)) for f in related[:40]]) or []:
                    block(b["text"], [by_id[i] for i in b["fact_ids"] if i in by_id])
            elif related:
                for f in related[:5]:
                    block(_fact_text(f) + ".", [f])
            if not blocks:
                live = " “Research more (live sources)” can look for it." if origin == "saved_evidence" else " Live sources were checked and returned nothing verifiable."
                limitation = f"The verified evidence on record does not address this question, so it is not answered from unrelated company facts.{live}"
    if not blocks and not limitation and not gaps:
        limitation = "The evidence on record does not answer this question."
    for k in p["knowns"]:
        if k["status"] in ("unknown", "blocked") and re.search(r"(?<!\w)" + re.escape(k["label"].split()[0].casefold()), question.casefold()):
            gaps.append(f"{k['label']}: {k['text']}")
    out = {"id": f"ans-{p['company']['orgNumber']}-{abs(hash(question)) % 10**8}", "question": question, "origin": origin, "blocks": blocks, "generatedAt": now_iso()}
    if limitation:
        out["limitation"] = limitation
    if gaps:
        out["gaps"] = list(dict.fromkeys(gaps))
    return out


def answer_from_summary(p: dict[str, Any], prompt: str | None) -> dict[str, Any]:
    """The research-completion answer: the evidence-grounded summary, sentence by sentence."""
    blocks = []
    summary = p.get("summary")
    facts = {f["id"]: f for f in _all_facts(p)}
    if summary:
        ev = []
        for f in facts.values():
            ev.extend(e for e in f["evidence"] if e["id"] in summary["evidenceIds"])
        blocks.append({"id": "b1", "text": summary["text"], "citations": _cite(p, ev), "factIds": [f["id"] for f in facts.values() if any(e["id"] in summary["evidenceIds"] for e in f["evidence"])][:12]})
    gaps = [f"{k['label']}: {k['text']}" for k in p["knowns"] if k["status"] in ("unknown", "blocked")]
    return {"id": f"ans-{p['company']['orgNumber']}-summary", "question": prompt or "Company brief", "origin": "fresh_research", "blocks": blocks,
            **({"gaps": gaps} if gaps else {}), "generatedAt": now_iso()}
