"""Multi-year financial trends: comparable periods and bases only, one currency, correct changes, honest gaps, no model involved."""
from __future__ import annotations

from types import SimpleNamespace

from app.agent.trends import build_trends


def claim(field: str, year: int, value: float, *, currency: str | None = "NOK", start: str | None = None, end: str | None = None) -> SimpleNamespace:
    start = start or f"{year}-01-01"
    end = end or f"{year}-12-31"
    return SimpleNamespace(field=field, value=value, availability="available", reporting_period=f"{start}/{end}", period_label=f"FY{year}", currency=currency,
                           primary=SimpleNamespace(id=f"ev-{field}-{year}"))


def eid(c: SimpleNamespace) -> str:
    return c.primary.id


def revenue_series(*pairs: tuple[int, float], **kw) -> list[SimpleNamespace]:  # noqa: ANN003
    return [claim("revenue", y, v, **kw) for y, v in pairs]


def test_three_years_give_correct_absolute_and_percent_change_with_evidence() -> None:
    t = build_trends(revenue_series((2023, 100.0), (2024, 120.0), (2025, 90.0)), eid)
    m = t["metrics"]["revenue"]
    assert [r["year"] for r in m["series"]] == [2023, 2024, 2025]
    assert m["changes"][0] == {"from_year": 2023, "to_year": 2024, "absolute": 20.0, "percent": 20.0, "years_apart": 1, "note": None}
    assert m["changes"][1]["absolute"] == -30.0 and m["changes"][1]["percent"] == -25.0
    assert m["direction"] == "mixed" and m["evidence_ids"] == ["ev-revenue-2023", "ev-revenue-2024", "ev-revenue-2025"]
    assert "FY2023" in m["statement"] and "FY2025" in m["statement"]


def test_a_missing_year_is_reported_not_interpolated() -> None:
    t = build_trends(revenue_series((2022, 100.0), (2024, 150.0)), eid)
    m = t["metrics"]["revenue"]
    assert [r["year"] for r in m["series"]] == [2022, 2024]
    assert m["changes"][0]["years_apart"] == 2 and "1 year(s)" in m["changes"][0]["note"]
    assert "FY2023 could not be compared" in m["statement"]


def test_mixed_currencies_are_never_converted_or_compared() -> None:
    claims = [claim("revenue", 2023, 100.0, currency="SEK"), claim("revenue", 2024, 200.0, currency="NOK"), claim("revenue", 2025, 300.0, currency="NOK")]
    m = build_trends(claims, eid)["metrics"]["revenue"]
    assert m["currency"] == "NOK" and [r["year"] for r in m["series"]] == [2024, 2025]
    assert any("SEK" in x["reason"] and "never converted" in x["reason"] for x in m["excluded"])


def test_a_short_or_unstated_period_is_not_compared_with_full_years() -> None:
    claims = revenue_series((2023, 100.0), (2025, 120.0)) + [claim("revenue", 2024, 40.0, start="2024-09-01", end="2024-12-31")]
    claims.append(SimpleNamespace(field="revenue", value=5.0, availability="available", reporting_period=None, period_label=None, currency="NOK", primary=SimpleNamespace(id="x")))
    m = build_trends(claims, eid)["metrics"]["revenue"]
    assert [r["year"] for r in m["series"]] == [2023, 2025]
    reasons = " ".join(x["reason"] for x in m["excluded"])
    assert "not a twelve-month period" in reasons and "start and end date" in reasons


def test_no_percentage_from_a_zero_or_negative_base() -> None:
    claims = [claim("operating_result", 2023, -50.0), claim("operating_result", 2024, 100.0)]
    m = build_trends(claims, eid)["metrics"]["operating_result"]
    assert m["changes"][0]["absolute"] == 150.0 and m["changes"][0]["percent"] is None
    assert "no percentage" in m["statement"] and m["label"] == "Operating profit"


def test_company_and_consolidated_accounts_are_never_mixed() -> None:
    claims = revenue_series((2024, 100.0), (2025, 110.0)) + [claim("consolidated_revenue", 2023, 900.0), claim("consolidated_revenue", 2024, 950.0), claim("consolidated_revenue", 2025, 990.0)]
    m = build_trends(claims, eid)["metrics"]["revenue"]
    assert m["basis"] == "consolidated" and [r["value"] for r in m["series"]] == [900.0, 950.0, 990.0]  # one basis, the one with the longer comparable series
    assert "Group (consolidated)" in m["statement"]


def test_single_year_gives_no_trend_claim_and_nothing_is_invented() -> None:
    t = build_trends(revenue_series((2025, 100.0)), eid)
    m = t["metrics"]["revenue"]
    assert m["changes"] == [] and m["direction"] == "single_year" and "no trend can be shown" in m["statement"]
    assert build_trends([], eid) is None
    assert build_trends([claim("equity", 2025, 1.0)], eid) is None  # other fields are not trended


def test_net_income_and_text_are_deterministic() -> None:
    claims = [claim("annual_result", 2023, 10.0), claim("annual_result", 2024, 15.0)] + revenue_series((2023, 100.0), (2024, 110.0))
    a, b = build_trends(claims, eid), build_trends(list(reversed(claims)), eid)
    assert a == b and "Net income rose every year" in a["text"] and a["method"] == "deterministic"
    assert a["years"] == [2023, 2024]
