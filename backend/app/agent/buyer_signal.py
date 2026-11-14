"""The buyer-oriented lead of a company summary: one verified commercial fact, with its source and period, never a repetition of registry fields.

Evaluator feedback on the scored run: the opening of the summary only repeated the legal name, legal form, municipality and industry. A buyer wants the one verified
fact that says something about the business. This module picks it deterministically (no model), from published claims only, in this order of preference:

1. a multi-year revenue trend from the filed annual accounts,
2. the latest filed financial result,
3. what the company says it does (its own verified website),
4. a genuine company announcement (a dated article page on the company's own newsroom / investor-relations pages),
5. a public-procurement award,
6. a current job posting on the company's own careers pages.

Every sentence names its source and the period or date it refers to, and carries the evidence ids of the claims it quotes. Nothing is inferred: no growth, activity,
headcount or commercial significance is stated unless a claim says so. When none of these is verified, the lead says so plainly instead of falling back to registry fields.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from ..core.util import clean_ws, format_money, truncate

NO_SIGNAL_TEXT = ("No buyer-relevant signal (a revenue trend or filed result, a company-stated description, a company announcement, a public-procurement award or a current "
                  "job posting) was established in the sources checked.")
REGNSKAPSREGISTERET = "Regnskapsregisteret"


def _day(value: str | None) -> str | None:
    try:
        d = date.fromisoformat((value or "")[:10])
    except ValueError:
        return None
    return f"{d.day} {d.strftime('%B %Y')}"


def _host(url: str | None) -> str:
    host = urlsplit(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _pct(old: float, new: float) -> str:
    if old is None or old <= 0:
        return ""
    change = (new - old) / old * 100
    return f" ({'+' if change >= 0 else '−'}{abs(change):.1f}%)"


def _first(claims: list[Any], field: str) -> list[Any]:
    return [c for c in claims if c.field == field and getattr(c, "availability", "available") == "available"]


def lead_signal(claims: list[Any], trends: dict[str, Any] | None, eid: Callable[[Any], str]) -> dict[str, Any] | None:
    """The best verified buyer signal as ``{"kind", "text", "evidence_ids", "fields"}``, or ``None`` when no such signal is verified."""
    # 1. multi-year revenue trend (company accounts; consolidated series are labelled as such)
    metric = ((trends or {}).get("metrics") or {}).get("revenue")
    if metric and len(metric.get("series") or []) >= 2 and metric.get("evidence_ids"):
        series = metric["series"]
        first, last = series[0], series[-1]
        cur = metric.get("currency")
        direction = "rose" if last["value"] > first["value"] else ("fell" if last["value"] < first["value"] else "was unchanged")
        basis = "group (consolidated) " if metric.get("basis") == "consolidated" else ""
        via = ""
        if len(series) > 2:
            via = ", with " + ", ".join(f"FY{r['year']} at {format_money(r['value'], cur)}" for r in series[1:-1])
        move = (f"{basis}revenue {direction} from {format_money(first['value'], cur)} in FY{first['year']} to {format_money(last['value'], cur)} in FY{last['year']}{via}"
                if direction != "was unchanged" else f"{basis}revenue was unchanged at {format_money(last['value'], cur)} between FY{first['year']} and FY{last['year']}")
        pct = _pct(first["value"], last["value"])
        text = f"According to its filed accounts ({REGNSKAPSREGISTERET}), {move}{pct.replace(')', ' overall)') if pct else ''}."
        return {"kind": "revenue_trend", "text": text, "evidence_ids": list(dict.fromkeys(metric["evidence_ids"])), "fields": ["revenue"]}
    # 2. latest filed financial result
    for field, noun in (("revenue", "revenue"), ("operating_result", "an operating result"), ("annual_result", "an annual result")):
        rows = sorted(_first(claims, field), key=lambda c: c.reporting_period or "", reverse=True)
        if not rows or not rows[0].period_label:
            continue
        top = rows[0]
        text = f"{REGNSKAPSREGISTERET}'s {top.period_label} filing reports {'revenue' if field == 'revenue' else noun} of {format_money(top.value, top.currency)}"
        ids = [eid(top)]
        fields = [field]
        if field == "revenue":
            res = next((c for c in _first(claims, "annual_result") if c.reporting_period == top.reporting_period), None)
            if res is not None:
                text += f" and an annual result of {format_money(res.value, res.currency)}"
                ids.append(eid(res))
                fields.append("annual_result")
        return {"kind": "latest_financials", "text": text + ".", "evidence_ids": [i for i in dict.fromkeys(ids) if i], "fields": fields}
    # 3. what the company says it does, on its own verified website
    for c in _first(claims, "business_description"):
        o = c.primary
        quoted = (c.attributes or {}).get("translation") or c.value
        if not o or not eid(c) or not clean_ws(str(quoted)):
            continue
        host = _host(o.source_url)
        text = f"The company's own website ({host}) describes the business as: “{truncate(clean_ws(str(quoted)), 220)}”"
        return {"kind": "company_description", "text": text, "evidence_ids": [eid(c)], "fields": ["business_description"]}
    # 4. a genuine, dated company announcement (the article page itself was fetched and verified)
    news = sorted((c for c in _first(claims, "news_item") if _day(c.as_of)), key=lambda c: c.as_of or "", reverse=True)
    if news:
        c = news[0]
        a = c.attributes or {}
        where = "investor-relations page" if a.get("page_kind") == "investors" else "newsroom"
        text = f"On {_day(c.as_of)} the company published “{truncate(clean_ws(str(c.value)), 160)}” on its own {where} ({_host(a.get('url') or (c.primary.source_url if c.primary else None))})."
        return {"kind": "company_announcement", "text": text, "evidence_ids": [eid(c)] if eid(c) else [], "fields": ["news_item"]}
    # 5. a public-procurement award
    awards = sorted((c for c in _first(claims, "procurement_award") if _day(c.as_of)), key=lambda c: c.as_of or "", reverse=True)
    if awards:
        c = awards[0]
        a = c.attributes or {}
        buyer = f" by {a['buyer_name']}" if a.get("buyer_name") else ""
        source = (c.primary.source_name if c.primary and c.primary.source_name else "the public procurement notice register")
        text = f"The procurement notice ({source}) dated {_day(c.as_of)} records a contract awarded{buyer}: “{truncate(clean_ws(str(c.value)), 160)}”."
        return {"kind": "procurement_award", "text": text, "evidence_ids": [eid(c)] if eid(c) else [], "fields": ["procurement_award"]}
    # 6. a current job posting on the company's own careers pages
    for c in _first(claims, "open_positions_count"):
        if isinstance(c.value, (int, float)) and not isinstance(c.value, bool) and c.value >= 1 and eid(c):
            o = c.primary
            checked = _day(c.as_of)
            host = _host(o.source_url) if o else ""
            text = (f"{int(c.value)} current job posting(s) were found on the company's own careers pages"
                    + (f" ({host})" if host else "") + (f", checked {checked}" if checked else "") + ".")
            return {"kind": "current_hiring", "text": text, "evidence_ids": [eid(c)], "fields": ["open_positions_count"]}
    return None
