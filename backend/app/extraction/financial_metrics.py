"""What each financial metric IS, so one measure is never shown as another.

Regnskapsregisteret (the Norwegian annual-accounts register) files a balance-sheet line ``egenkapitalGjeld.gjeldOversikt.sumGjeld`` ("sum gjeld"). That is
TOTAL LIABILITIES: every obligation on the balance sheet — interest-bearing borrowings, but also trade payables, tax payable, provisions, lease and
decommissioning obligations and the like. It equals total assets minus equity. It is NOT:

* **total debt** / **gross interest-bearing debt** — borrowings only (bonds, bank loans, lease liabilities as the company defines them); companies report it
  in their own key figures, and the register does not file it;
* **net debt** — interest-bearing debt minus cash and liquid investments; a company-defined, usually non-GAAP measure that the register does not file either.

COGNIS therefore stores "sum gjeld" as ``total_liabilities`` (with ``current_liabilities`` and ``non_current_liabilities`` for its two parts) and has no
register field for debt, interest-bearing debt or net debt. A question about those is answered from a source that states the measure under that name (for
example the company's own key figures), or as unavailable — never by relabelling total liabilities, and never by computing assets minus equity.

Earlier versions stored "sum gjeld" under the misleading names ``debt`` / ``short_term_debt`` / ``long_term_debt``. ``upgrade_record`` renames those in a
saved record when it is read, so old research shows the correct metric too (the values and evidence are unchanged; only the name and label were wrong).
"""
from __future__ import annotations

from typing import Any

# metric → (label, definition). Only metrics with a register field have a source in the filed accounts.
DEFINITIONS: dict[str, tuple[str, str]] = {
    "total_liabilities": ("Total liabilities", "All liabilities on the balance sheet (sum gjeld): interest-bearing and non-interest-bearing obligations together."),
    "current_liabilities": ("Current liabilities", "Liabilities due within a year (kortsiktig gjeld)."),
    "non_current_liabilities": ("Non-current liabilities", "Liabilities due after more than a year (langsiktig gjeld)."),
    "debt": ("Total (interest-bearing) debt", "Borrowings only: bonds, bank loans and similar interest-bearing obligations, as the company defines them."),
    "interest_bearing_debt": ("Gross interest-bearing debt", "Interest-bearing borrowings before cash is deducted, as the company defines them."),
    "net_debt": ("Net debt", "Interest-bearing debt minus cash and liquid investments, as the company defines it (usually a non-GAAP measure)."),
}
REGISTER_FIELDS = {"total_liabilities", "current_liabilities", "non_current_liabilities"}
NOT_IN_REGISTER = {"debt", "interest_bearing_debt", "net_debt"}

UNAVAILABLE_NOTE = ("Regnskapsregisteret does not report total (interest-bearing) debt or net debt. It reports total liabilities (sum gjeld), a broader measure that "
                    "also includes non-interest-bearing obligations, so it is not shown as debt. A debt figure needs a source that states it under that name, "
                    "such as the company's own key figures.")

LEGACY_FIELDS = {"debt": "total_liabilities", "short_term_debt": "current_liabilities", "long_term_debt": "non_current_liabilities"}
LEGACY_FIELDS.update({f"consolidated_{old}": f"consolidated_{new}" for old, new in list(LEGACY_FIELDS.items())})


def label_of(field: str) -> str:
    base = field.removeprefix("consolidated_")
    label = DEFINITIONS.get(base, (base.replace("_", " ").capitalize(), ""))[0]
    return f"Consolidated {label[0].lower()}{label[1:]}" if field.startswith("consolidated_") else label


def unavailable_reason(metric: str) -> str | None:
    """Why a metric the question asked for cannot come from the filed accounts, or None when it can."""
    return UNAVAILABLE_NOTE if metric in NOT_IN_REGISTER else None


def upgrade_record(record: dict[str, Any] | None) -> dict[str, Any] | None:
    """Rename the old, wrong metric names in a saved record (in place) and return it. Values and evidence are untouched."""
    if not isinstance(record, dict):
        return record
    for c in record.get("claims") or []:
        new = LEGACY_FIELDS.get(str(c.get("field")))
        if new:
            old = c["field"]
            c["field"] = new
            c["label"] = label_of(new)
            if isinstance(c.get("key"), str):
                c["key"] = c["key"].replace(f"|{old}|", f"|{new}|")
    for a in record.get("absences") or []:
        new = LEGACY_FIELDS.get(str(a.get("field")))
        if new:
            a["field"] = new
            if a.get("note") == "No filed annual accounts state total debt.":
                a["note"] = "No filed annual accounts state total liabilities."
    return record
