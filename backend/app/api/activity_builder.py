"""The Recent activity section: saved facts → validated, consolidated, ranked events + an honest account of what could and could not be read.

Reads the saved research record only. Ranking, de-duplication and exclusion rules live in ``app/events``; this module maps record facts onto
candidates and writes the section's source-limitation text. Missing or unreadable sources are reported as limitations — never as "no events".
"""
from __future__ import annotations

from datetime import date
from typing import Any

from ..core.util import stable_id
from ..events.significance import Amount, RevenueContext
from ..events.timeline import Candidate, build_timeline, company_words
from .sources import STATIC_SOURCES, website_source

CHECKED_STATUS = {"available": "read", "not_available": "not_found", "blocked": "blocked", "failed": "failed", "not_applicable": "not_run", "ambiguous": "failed"}
NEWS_KINDS = ("newsroom", "investor_relations", "feed", "news_search")
KIND_NAME = {"newsroom": "Company newsroom", "investor_relations": "Investor relations", "feed": "News feed (RSS/Atom)", "news_search": "News coverage search",
             "registry": "Enhetsregisteret", "procurement": "Public procurement notices"}


def _amount(attrs: dict[str, Any]) -> Amount | None:
    raw, cur = attrs.get("total_value"), attrs.get("total_value_currency")
    try:
        value = float(str(raw).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None
    cur = str(cur).upper() if cur and len(str(cur)) == 3 else None
    return Amount(value, cur, f"{cur or ''} {raw}".strip()) if value > 0 else None


def _today(builder: Any) -> date:
    """Events are judged as of the day the research was completed, so a saved record reads the same every time it is opened."""
    try:
        return date.fromisoformat(str(builder.researched_at)[:10])
    except (TypeError, ValueError):
        return date.today()


def _revenue(financials: dict[str, Any]) -> RevenueContext | None:
    series = next((s for s in financials.get("series") or [] if s.get("key") == "revenue"), None)
    if not series or not series.get("points"):
        return None
    fact = series["points"][-1]["fact"]
    cur, val = fact.get("currency"), fact.get("value")
    return RevenueContext(float(val), cur) if cur and isinstance(val, (int, float)) and val > 0 else None


def _candidates(b: Any) -> list[Candidate]:
    out: list[Candidate] = []

    def add(kind: str, claim: dict[str, Any], day: str | None, title: str, origin: str, **kw: Any) -> None:
        out.append(Candidate(id=f"{b.org}-ev-" + stable_id(kind, day or "", title, claim.get("key_suffix") or "", length=10), date=(day or "")[:10], title=title, origin=origin,
                             evidence=b.evidence_for(claim), **kw))

    for c in b.by_field.get("news_item") or []:
        a = c.get("attributes") or {}
        origin = a.get("origin") or ("investor_relations" if a.get("page_kind") == "investors" else "company_newsroom")
        add("news", c, c.get("as_of") or a.get("date"), str(c["value"]), origin, description=a.get("summary") or None, url=a.get("url"), check_headline=True)
    for c in b.by_field.get("procurement_award") or []:
        a = c.get("attributes") or {}
        buyer = f" — buyer: {a['buyer_name']}" if a.get("buyer_name") else ""
        desc = " · ".join(x for x in (a.get("notice_type_label"), f"notice {a.get('notice_id')}" if a.get("notice_id") else None, a.get("coverage")) if x) or None
        add("award", c, c.get("as_of"), f"Public contract awarded: {c['value']}{buyer}", "public_procurement", description=desc, type_hint="contract", notice_id=a.get("notice_id"),
            amount=_amount(a))
    for c in b.by_field.get("procurement_notice_as_buyer") or []:
        a = c.get("attributes") or {}
        desc = " · ".join(x for x in (a.get("notice_type_label"), f"notice {a.get('notice_id')}" if a.get("notice_id") else None, a.get("coverage")) if x) or None
        add("buyer", c, c.get("as_of"), f"Procurement published as buyer: {c['value']}", "public_procurement", description=desc, type_hint="contract", notice_id=a.get("notice_id"),
            registry_kind="procurement_buyer")
    reg = b.first("registration_date")
    if reg:
        add("reg", reg, reg["value"], "Registered in Enhetsregisteret", "official_registry", registry_kind="registration")
    founded = b.first("founded_date")
    if founded and (not reg or founded["value"] != reg["value"]):
        add("founded", founded, founded["value"], "Company founded", "official_registry", registry_kind="founded")
    parent = b.first("parent_company")
    if parent and parent.get("effective_from"):
        share = (parent.get("attributes") or {}).get("share")
        add("group", parent, parent["effective_from"], f"Became part of the {parent['value']} group", "official_registry", registry_kind="group",
            description=f"Ownership basis: {share}" if share else None)
    for c in b.by_field.get("subsidiary") or []:
        if c.get("effective_from"):
            add("sub", c, c["effective_from"], f"Subsidiary registered: {c['value']}", "official_registry", registry_kind="subsidiary")
    for c in b.by_field.get("registered_establishment") or []:
        if c.get("effective_from"):
            add("est", c, c["effective_from"], f"Establishment opened: {(c.get('attributes') or {}).get('name') or c['value']}", "official_registry", registry_kind="establishment")
    for c in b.by_field.get("former_name") or []:
        if c.get("effective_to"):
            add("name", c, c["effective_to"], f"Name changed from {c['value']}", "official_registry", registry_kind="name_change")
    return out


def _module_check(b: Any, name: str, kind: str, label: str, source_id: str | None) -> dict[str, Any] | None:
    mod = b.modules.get(name)
    if not mod:
        return None
    state = mod.get("state") or "not_available"
    entry: dict[str, Any] = {"id": name, "kind": kind, "name": label, "status": CHECKED_STATUS.get(state, "failed"), "note": mod.get("note") or ""}
    if mod.get("url"):
        entry["url"] = mod["url"]
    if source_id:
        entry["sourceId"] = source_id
    return entry


def sources_checked(b: Any) -> list[dict[str, Any]]:
    """What was looked at for this section and what came of it, from the saved record."""
    out: list[dict[str, Any]] = []
    news = b.r.get("news") or {}
    web = b.website or {}
    if news.get("newsroom"):
        for i, s in enumerate(news["newsroom"].get("sources") or []):
            out.append({"id": f"newsroom-{i}", "kind": s.get("kind") or "newsroom", "name": KIND_NAME.get(s.get("kind") or "newsroom", "Company newsroom"), "status": s.get("status") or "failed",
                        "note": s.get("note") or "", **({"url": s["url"]} if s.get("url") else {}), **({"items": s["items"]} if s.get("items") is not None else {}),
                        **({"sourceId": f"web-{b.org}"} if b.domain else {})})
        if not news["newsroom"].get("sources"):
            nr_state = news["newsroom"].get("state")
            status = CHECKED_STATUS[nr_state] if nr_state in ("not_applicable", "blocked", "failed") else ("not_found" if web.get("verified") else "not_run")
            out.append({"id": "newsroom", "kind": "newsroom", "name": KIND_NAME["newsroom"], "status": status,
                        "note": news["newsroom"].get("note") or ""})
    elif not b.researched:
        pass
    elif not web.get("verified"):
        out.append({"id": "newsroom", "kind": "newsroom", "name": KIND_NAME["newsroom"], "status": "not_run",
                    "note": "No identity-verified website, so no company newsroom or investor-relations page could be read."})
    else:  # a record saved before newsroom discovery existed: only what the site crawl itself reached
        pages = [p for p in web.get("pages") or [] if p.get("kind") in ("news", "investors")]
        read = [p for p in pages if p.get("status") == "ok"]
        if read:
            for p in read:
                out.append({"id": f"newsroom-{p['kind']}", "kind": "investor_relations" if p["kind"] == "investors" else "newsroom", "name": KIND_NAME["investor_relations" if p["kind"] == "investors" else "newsroom"],
                            "status": "read", "url": p.get("url"), "note": "Read during the website crawl.", "sourceId": f"web-{b.org}"})
        else:
            out.append({"id": "newsroom", "kind": "newsroom", "name": KIND_NAME["newsroom"], "status": "not_found",
                        "note": "No newsroom or investor-relations page was reached on the verified website in this research."})
    search = (news.get("search") or {}) if news else {}
    if search:
        state = search.get("state") or "not_applicable"
        out.append({"id": "news_search", "kind": "news_search", "name": KIND_NAME["news_search"], "status": CHECKED_STATUS.get(state, "failed"), "note": search.get("note") or "",
                    **({"items": search["accepted"]} if search.get("accepted") is not None else {})})
    elif b.researched and news:
        out.append({"id": "news_search", "kind": "news_search", "name": KIND_NAME["news_search"], "status": "not_run", "note": "News coverage search was not part of this research."})
    for entry in (_module_check(b, "registry_live", "registry", "Enhetsregisteret", "brreg"), _module_check(b, "locations", "registry", "Registered establishments", "subunits"),
                  _module_check(b, "procurement_ted", "procurement", "TED — EU procurement notices", "ted"),
                  _module_check(b, "procurement_doffin", "procurement", "Doffin open data", "doffin_open")):
        if entry:
            out.append(entry)
    return out


def _limitation_text(checks: list[dict[str, Any]]) -> tuple[str | None, bool]:
    """(sentence about company-announcement sources that could not be read, whether any company announcement source was read)."""
    news = [c for c in checks if c["kind"] in NEWS_KINDS]
    company = [c for c in news if c["kind"] != "news_search"]
    company_read = any(c["status"] == "read" for c in company)
    # a press search that is not configured or found nothing is only a limitation when no company source was read either
    problems = [c for c in news if c["status"] in ("blocked", "failed", "not_found", "not_run") and not (c["kind"] == "news_search" and c["status"] in ("not_run", "not_found") and company_read)]
    if not problems:
        return None, company_read
    parts = []
    for c in problems:
        what = {"blocked": "blocked", "failed": "could not be read", "not_found": "not found", "not_run": "not checked"}[c["status"]]
        note = f" ({c['note'].rstrip('.')})" if c.get("note") else ""
        parts.append(f"{c['name']}{' ' + c['url'] if c.get('url') and c['kind'] in ('newsroom', 'investor_relations', 'feed') else ''} — {what}{note}")
    return "; ".join(parts), company_read


def build_activity(b: Any, financials: dict[str, Any]) -> dict[str, Any]:
    cands = _candidates(b)
    tl = build_timeline(cands, today=_today(b), revenue=_revenue(financials), company_words=company_words(b.legal_name))
    checks = sources_checked(b) if b.researched else []
    searched = [c["sourceId"] for c in checks if c.get("sourceId") and c["status"] == "read"]
    for sid in searched:
        if sid.startswith("web-") and b.domain:
            b.sources.add(website_source(b.org, b.domain))
        elif sid in STATIC_SOURCES:
            b.sources.add(STATIC_SOURCES[sid])
    base: dict[str, Any] = {"events": tl.events, "counts": tl.counts(), "consolidated": tl.consolidated}
    if checks:
        base["sourcesChecked"] = checks
    if tl.excluded:
        base["excluded"] = {"count": len(tl.excluded), "items": [e.to_dict() for e in tl.excluded[:20]]}
    if tl.omitted:
        base["omitted"] = tl.omitted
    if searched:
        base["searchedSourceIds"] = list(dict.fromkeys(searched))
    limits, company_read = _limitation_text(checks) if checks else (None, False)
    announcements = [e for e in tl.events if e["sourceType"] in ("company_newsroom", "investor_relations", "secondary_news")]
    if tl.events:
        msg = None
        if limits and not announcements:
            msg = (f"No company announcements could be read, so only register and procurement events are shown. {limits}. "
                   "Missing announcements are not evidence that none were made.")
        elif limits:
            msg = f"Some announcement sources could not be read: {limits}. Events from those sources may be missing; that is not evidence that nothing happened."
        if tl.omitted:
            msg = ((msg + " ") if msg else "") + f"{tl.omitted} lowest-ranked routine event(s) are not listed."
        return {"status": "partial" if (limits and not announcements) or (limits and not company_read) else "available", **({"message": msg} if msg else {}), **base}
    if not b.researched:
        return {"status": "pending", "message": "Not researched yet. Run research to gather this area from public sources.", **base}
    blocked = [c for c in checks if c["kind"] in NEWS_KINDS and c["status"] == "blocked"]
    text = "No dated public events were found in the sources that could be read."
    if limits:
        text += f" {limits}."
    text += " This does not mean that nothing happened."
    return {"status": "blocked" if blocked and not company_read else "not_available", "message": text, **base}
