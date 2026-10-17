"""Financial comparison between reporting periods, computed from the filed annual accounts in the saved record — never from a model.

Rules (the whole point is to compare only what is comparable):

* A metric is matched by *meaning* (revenue, operating result, annual result, assets, equity, total liabilities, cash), by *accounting scope* (company-only ``SELSKAP`` vs
  consolidated group ``KONSERN`` are never mixed), by *currency* (as the filing states it; an unstated currency is never assumed) and by period length
  (twelve-month periods only).
* Absolute change = latest − previous. Percentage change = absolute change ÷ |previous| × 100, and only when the previous value is not zero. A change in
  sign (profit → loss) is reported as such, with the percentage marked as not meaningful.
* The ranking criterion is stated, never implied: percentage change (default; comparable across metrics of different size) or absolute monetary change
  (when the question asks for amounts). They are not interchangeable and the answer says which one it used.
* Metrics with evidence for only one period, other currencies or other scopes are listed with the reason they were left out.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..core.util import format_money
from ..extraction.financial_metrics import unavailable_reason

# claim field → (key, label)
METRIC_FIELDS: tuple[tuple[str, str], ...] = (
    ("revenue", "Revenue"),
    ("operating_result", "Operating result"),
    ("annual_result", "Annual (net) result"),
    ("total_assets", "Total assets"),
    ("equity", "Equity"),
    ("total_liabilities", "Total liabilities"),
    ("cash_and_bank", "Cash and bank deposits"),
)
SCOPE_LABEL = {"company": "company-only (parent) accounts", "group": "consolidated group accounts"}


@dataclass
class Point:
    period: str  # "FY2025"
    start: str | None
    end: str | None
    value: float
    currency: str | None
    scope: str  # company | group
    url: str | None
    document_title: str | None
    retrieved_at: str | None
    claim_span: str | None
    journal: str | None = None


@dataclass
class Row:
    key: str
    label: str
    scope: str
    currency: str
    latest: Point
    previous: Point
    absolute: float
    percent: float | None
    note: str | None = None

    @property
    def formula(self) -> str:
        cur = self.currency
        a, b = self.latest.value, self.previous.value
        diff = f"{_money(a, cur)} − {_money(b, cur)} = {signed_money(self.absolute, cur)}"
        if self.percent is None:
            return diff + "; percentage change not meaningful (" + (self.note or "previous value is zero") + ")"
        return diff + f"; ({_signed_plain(self.absolute, cur)} ÷ {_money(abs(b), cur)}) × 100 = {_pct(self.percent)}"


@dataclass
class Comparison:
    rows: list[Row] = field(default_factory=list)
    omitted: list[str] = field(default_factory=list)  # one human line per metric that could not be compared, with the reason
    rank_by: str = "percent"
    periods: tuple[str, str] | None = None  # (previous, latest)
    scope_note: str | None = None

    def ranked(self) -> list[Row]:
        if self.rank_by == "amount":
            return sorted(self.rows, key=lambda r: -abs(r.absolute))
        return sorted(self.rows, key=lambda r: (r.percent is None, -abs(r.percent or 0.0), -abs(r.absolute)))

    @property
    def criterion(self) -> str:
        if self.rank_by == "amount":
            return "absolute monetary change (largest change in amount first; figures in different currencies are not ranked against each other)"
        return "percentage change (largest relative change first, because the figures differ greatly in size; absolute amounts are shown alongside)"


def _money(v: float, currency: str | None) -> str:
    return format_money(v, currency) if currency else f"{v:,.0f}"


def signed_money(v: float, currency: str | None) -> str:
    return ("−" if v < 0 else "+") + _money(abs(v), currency)


def _signed_plain(v: float, currency: str | None) -> str:
    return ("−" if v < 0 else "") + _money(abs(v), currency)


def _months(start: str | None, end: str | None) -> int | None:
    try:
        a, b = date.fromisoformat(start or ""), date.fromisoformat(end or "")
    except ValueError:
        return None
    return round(((b - a).days + 1) / 30.4)


def _points_from_record(record: dict[str, Any]) -> dict[tuple[str, str], list[Point]]:
    """(metric key, scope) → points, straight from the claims and their evidence."""
    ev_by_id = {e["id"]: e for e in record.get("evidence") or [] if isinstance(e, dict) and e.get("id")}
    out: dict[tuple[str, str], list[Point]] = {}
    for c in record.get("claims") or []:
        field_name = str(c.get("field") or "")
        scope = "company"
        base = field_name
        if field_name.startswith("consolidated_"):
            scope, base = "group", field_name[len("consolidated_"):]
        if base not in {k for k, _ in METRIC_FIELDS}:
            continue
        value = c.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        interval = str(c.get("reporting_period") or "")
        start, _, end = interval.partition("/")
        if not end:
            start, end = None, interval or None
        ev = next((ev_by_id[i] for i in c.get("evidence_ids") or [] if i in ev_by_id), None) or {}
        attrs = c.get("attributes") or {}
        out.setdefault((base, scope), []).append(Point(
            period=str(c.get("period_label") or (f"FY{end[:4]}" if end else "")), start=start, end=end, value=float(value), currency=c.get("currency") or None, scope=scope,
            url=ev.get("source_url"), document_title=ev.get("document_title"), retrieved_at=ev.get("retrieved_at"), claim_span=ev.get("claim_span"), journal=attrs.get("journal_number")))
    return out


def compare_periods(record: dict[str, Any], *, rank_by: str = "percent", metrics: list[str] | None = None, latest_year: int | None = None, previous_year: int | None = None) -> Comparison:
    """Latest vs previous reporting period for every metric that has comparable evidence in both."""
    cmp = Comparison(rank_by=rank_by)
    pts = _points_from_record(record)
    wanted = {k for k, _ in METRIC_FIELDS} if not metrics else {m for m in metrics}
    label_of = dict(METRIC_FIELDS)
    # scope preference: company-only is what the profile shows; consolidated is compared separately, never merged
    scopes_present = {s for (_, s) in pts}
    if len(scopes_present) > 1:
        cmp.scope_note = "Both company-only and consolidated group accounts were filed; each is compared only with itself."
    chosen: set[str] = set()
    for key in sorted(wanted - set(label_of)):  # asked for, but not a line in the filed accounts (debt, net debt): stated, never substituted
        cmp.omitted.append(unavailable_reason(key) or f"{key.replace('_', ' ').capitalize()} is not a line in the filed annual accounts.")
    for key, label in METRIC_FIELDS:
        if key not in wanted:
            continue
        for scope in ("company", "group"):
            series = pts.get((key, scope))
            if not series:
                continue
            by_end: dict[str, Point] = {}
            for p in series:
                if p.end and _months(p.start, p.end) in (None, 11, 12, 13):
                    by_end[p.end] = p  # one point per period end; a later duplicate never doubles it
            ends = sorted(by_end)
            if latest_year is not None:
                ends = [e for e in ends if int(e[:4]) <= latest_year]
            if len(ends) < 2:
                cmp.omitted.append(f"{label} ({SCOPE_LABEL[scope]}): only {len(ends)} reporting period has a filed value, so there is nothing to compare.")
                continue
            latest = by_end[ends[-1]]
            if previous_year is not None:
                prev_end = next((e for e in reversed(ends[:-1]) if int(e[:4]) == previous_year), None)
                if prev_end is None:
                    cmp.omitted.append(f"{label} ({SCOPE_LABEL[scope]}): no filed value for {previous_year}.")
                    continue
                previous = by_end[prev_end]
            else:
                previous = by_end[ends[-2]]
            if (latest.currency or None) != (previous.currency or None):
                cmp.omitted.append(f"{label} ({SCOPE_LABEL[scope]}): the two periods are stated in different currencies ({previous.currency or 'not stated'} and {latest.currency or 'not stated'}), so they are not compared.")
                continue
            if not latest.currency:
                cmp.omitted.append(f"{label} ({SCOPE_LABEL[scope]}): the filing does not state a currency, so the figures are not compared.")
                continue
            absolute = latest.value - previous.value
            note = None
            if previous.value == 0:
                percent = None
                note = "previous value is zero"
            elif (previous.value < 0) != (latest.value < 0) and latest.value != 0:
                percent = None
                note = "the value changed sign"
            else:
                percent = absolute / abs(previous.value) * 100
            cmp.rows.append(Row(key, label_of[key], scope, latest.currency, latest, previous, absolute, percent, note))
            chosen.add(scope)
    # report only one scope in the headline when both exist for the same metric? No: rows keep their scope label; nothing is merged.
    if cmp.rows:
        cmp.periods = (cmp.rows[0].previous.period, cmp.rows[0].latest.period)
    missing = [label for key, label in METRIC_FIELDS if key in wanted and not any(k == key for (k, _) in pts)]
    if missing and not metrics:
        cmp.omitted.append("No filed value was found for: " + ", ".join(missing) + ".")
    return cmp


def _pct(v: float) -> str:
    return ("−" if v < 0 else "+") + f"{abs(v):.2f}%"


def percent_text(row: Row) -> str:
    return "not meaningful" if row.percent is None else _pct(row.percent)


def mentions_year(text: str) -> list[int]:
    return [int(y) for y in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", text)]
