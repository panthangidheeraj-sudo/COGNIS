"""Deterministic multi-year financial trends from published annual-account claims.

Only comparable figures are compared: the same accounting basis (company accounts or consolidated group accounts — never mixed), full twelve-month
financial years, and one filing currency (no conversion is ever applied). A year that cannot be compared is listed in ``excluded`` with the reason, never
silently dropped or patched. Percentage changes are only given when the earlier figure is positive (a change from a loss or from zero has no meaningful
percentage). No model is involved: every sentence is built from the claims and carries the evidence ids of the years it quotes.

Employees are not trended: the register reports only the current headcount, so there is no per-year series to compare.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date
from typing import Any

from ..core.util import format_money

METRICS: tuple[tuple[str, str, str], ...] = (
    ("revenue", "Revenue", "revenue"),
    ("operating_result", "Operating profit", "operating profit"),
    ("annual_result", "Net income", "net income"),
)
FULL_YEAR_DAYS = (350, 380)


def _span(period: str | None) -> tuple[date, date] | None:
    if not period or "/" not in period:
        return None
    try:
        start, end = (date.fromisoformat(x) for x in period.split("/", 1))
    except ValueError:
        return None
    return (start, end) if end > start else None


def _pct(old: float, new: float) -> float | None:
    if old is None or old <= 0:
        return None
    return round((new - old) / old * 100, 1)


def _series(claims: list[Any], field: str, eid: Callable[[Any], str]) -> dict[str, Any] | None:
    rows = [c for c in claims if c.field == field and getattr(c, "availability", "available") == "available" and isinstance(c.value, (int, float)) and not isinstance(c.value, bool)]
    if not rows:
        return None
    excluded: list[dict[str, Any]] = []
    usable: list[dict[str, Any]] = []
    for c in rows:
        span = _span(c.reporting_period)
        if span is None:
            excluded.append({"period": c.reporting_period, "reason": "the reporting period is not stated as a start and end date"})
            continue
        days = (span[1] - span[0]).days + 1
        if not FULL_YEAR_DAYS[0] <= days <= FULL_YEAR_DAYS[1]:
            excluded.append({"period": c.reporting_period, "reason": f"not a twelve-month period ({days} days), so not comparable with full years"})
            continue
        usable.append({"year": span[1].year, "period": c.reporting_period, "label": c.period_label, "value": float(c.value), "currency": c.currency, "evidence_id": eid(c)})
    by_year: dict[int, dict[str, Any]] = {}
    for row in sorted(usable, key=lambda r: r["period"]):
        if row["year"] in by_year:
            excluded.append({"period": by_year[row["year"]]["period"], "reason": f"two filings end in {row['year']}; the later one is used"})
        by_year[row["year"]] = row
    if not by_year:
        return {"series": [], "excluded": excluded, "currency": None}
    latest = by_year[max(by_year)]
    currency = latest["currency"]
    series = []
    for year in sorted(by_year):
        row = by_year[year]
        if row["currency"] != currency:
            excluded.append({"period": row["period"], "reason": f"filed in {row['currency'] or 'an unstated currency'}, not {currency or 'an unstated currency'}; amounts are never converted"})
            continue
        series.append(row)
    return {"series": series, "excluded": excluded, "currency": currency}


def _changes(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for a, b in zip(series, series[1:], strict=False):
        gap = b["year"] - a["year"]
        out.append({"from_year": a["year"], "to_year": b["year"], "absolute": round(b["value"] - a["value"], 2), "percent": _pct(a["value"], b["value"]),
                    "years_apart": gap, "note": None if gap == 1 else f"{gap - 1} year(s) between these filings are not available"})
    return out


def _direction(series: list[dict[str, Any]]) -> str:
    values = [r["value"] for r in series]
    if len(values) < 2:
        return "single_year"
    steps = [b - a for a, b in zip(values, values[1:], strict=False)]
    if all(s > 0 for s in steps):
        return "up"
    if all(s < 0 for s in steps):
        return "down"
    if all(s == 0 for s in steps):
        return "flat"
    return "mixed"


def _statement(name: str, noun: str, series: list[dict[str, Any]], currency: str | None, direction: str, basis: str) -> str:
    first, last = series[0], series[-1]
    prefix = "Group (consolidated) " + noun if basis == "consolidated" else name
    if len(series) == 1:
        return f"{prefix} for FY{last['year']} was {format_money(last['value'], currency)}; only one year of accounts is available, so no trend can be shown."
    years = ", ".join(f"FY{r['year']} {format_money(r['value'], currency)}" for r in series)
    pct = _pct(first["value"], last["value"])
    delta = last["value"] - first["value"]
    word = {"up": "rose every year", "down": "fell every year", "flat": "was unchanged", "mixed": "moved up and down"}[direction]
    tail = f" (a change of {format_money(delta, currency)}" + (f", {'+' if pct >= 0 else '−'}{abs(pct):.1f}%" if pct is not None else ", no percentage as the starting figure is not positive") + f" between FY{first['year']} and FY{last['year']})"
    missing = [y for y in range(first["year"], last["year"] + 1) if y not in {r["year"] for r in series}]
    gap = f" FY{', FY'.join(str(y) for y in missing)} could not be compared." if missing else ""
    return f"{prefix} {word}: {years}{tail}.{gap}"


def build_trends(claims: Iterable[Any], eid: Callable[[Any], str]) -> dict[str, Any] | None:
    """Trend block for ``record["trends"]`` or None when no metric has at least one comparable year."""
    claims = list(claims)
    metrics: dict[str, Any] = {}
    for key, name, noun in METRICS:
        chosen = None
        for basis, field in (("company", key), ("consolidated", f"consolidated_{key}")):
            s = _series(claims, field, eid)
            if s and s["series"] and (chosen is None or len(s["series"]) > len(chosen[1]["series"])):
                chosen = (basis, s)
        if chosen is None:
            continue
        basis, s = chosen
        series = s["series"]
        direction = _direction(series)
        metrics[key] = {"label": name, "basis": basis, "currency": s["currency"], "series": series, "changes": _changes(series), "direction": direction,
                        "excluded": s["excluded"], "statement": _statement(name, noun, series, s["currency"], direction, basis),
                        "evidence_ids": [r["evidence_id"] for r in series if r["evidence_id"]]}
    if not metrics:
        return None
    return {"method": "deterministic", "metrics": metrics, "years": sorted({r["year"] for m in metrics.values() for r in m["series"]}),
            "text": " ".join(m["statement"] for m in metrics.values())}
