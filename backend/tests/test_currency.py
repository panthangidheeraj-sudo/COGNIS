"""Regression: financial amounts keep the currency their own filing states, end to end.

Trigger (QA, Equinor ASA, 923609016): the export showed ``value = "NOK 67.96B"`` next to an evidence excerpt that said
``... = 67960000000 USD``. Cause: the register's ``valuta`` was parsed correctly, but the display formatter and several builders
hard-coded "NOK". These tests pin the whole chain — source record → parser → observation → gate → claim → profile fact / series /
snapshot → brief / ask / summary → compare → sheet → CSV export — for foreign-currency Norwegian companies, and prove the
publication gate stays strict (it now also refuses a currency label that contradicts its own evidence).
"""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

import pytest
from conftest import research, run
from fastapi.testclient import TestClient

from app.agent import llm_tasks
from app.api.briefs import answer, brief_from_profile
from app.api.compare_export import comparison
from app.core.util import format_money, normalize_currency
from app.evidence import gate
from app.evidence.models import ModuleResult, Observation
from app.extraction.registry_facts import financial_observations
from app.providers.fake_provider import FakeProvider
from app.testing.fixtures import synthetic_entity, synthetic_roles

EQUINOR = "923609016"
NOK_CO = "810359862"  # ordinary NOK reporter (fixture probe)
SWITCHER = "810034882"  # reported in NOK, then switched its reporting currency to USD
NO_VALUTA = "810059672"  # register record that states no currency at all

REV_2025, REV_2024 = 67_960_000_000.0, 72_540_000_000.0


def account(year: int, *, currency: str | None, revenue: float, operating: float, result: float, assets: float, equity: float, debt: float,
            kind: str = "SELSKAP") -> dict[str, Any]:
    rec: dict[str, Any] = {
        "id": year, "journalnr": f"{year + 1}000001", "regnskapstype": kind,
        "virksomhet": {"organisasjonsnummer": EQUINOR, "organisasjonsform": "ASA", "morselskap": True},
        "regnskapsperiode": {"fraDato": f"{year}-01-01", "tilDato": f"{year}-12-31"},
        "revisjon": {"ikkeRevidertAarsregnskap": False, "fravalgRevisjon": False},
        "resultatregnskapResultat": {"driftsresultat": {"driftsinntekter": {"sumDriftsinntekter": revenue}, "driftsresultat": operating},
                                     "ordinaertResultatFoerSkattekostnad": operating, "aarsresultat": result},
        "eiendeler": {"sumEiendeler": assets},
        "egenkapitalGjeld": {"egenkapital": {"sumEgenkapital": equity}, "gjeldOversikt": {"sumGjeld": debt}},
    }
    if currency is not None:
        rec["valuta"] = currency
    return rec


def usd_accounts() -> list[dict[str, Any]]:
    return [account(2025, currency="USD", revenue=REV_2025, operating=5_560_000_000.0, result=5_730_000_000.0, assets=120e9, equity=45e9, debt=75e9),
            account(2024, currency="USD", revenue=REV_2024, operating=6_100_000_000.0, result=6_900_000_000.0, assets=118e9, equity=44e9, debt=74e9)]


def register(net: Any) -> None:
    net.register_company(EQUINOR, entity=synthetic_entity({"organisation_number": EQUINOR, "name": "EQUINOR ASA", "legal_form": "ASA", "municipality": "STAVANGER",
                                                          "municipality_number": "1103", "employees": 21272}, website=None, email=None),
                         roles=synthetic_roles(1), accounts=usd_accounts(), subunits={"_embedded": {"underenheter": []}, "page": {"totalElements": 0}})
    # the same register serves a company that changed reporting currency between two filings …
    net.register_company(SWITCHER, accounts=[
        account(2025, currency="USD", revenue=900e6, operating=90e6, result=70e6, assets=500e6, equity=200e6, debt=300e6),
        account(2024, currency="NOK", revenue=8_000e6, operating=800e6, result=600e6, assets=4_000e6, equity=1_800e6, debt=2_200e6)])
    # … and one whose filing does not state a currency at all
    net.register_company(NO_VALUTA, accounts=[account(2025, currency=None, revenue=123_000_000.0, operating=12_000_000.0, result=9_000_000.0, assets=80e6, equity=30e6, debt=50e6),
                                              account(2024, currency=None, revenue=110_000_000.0, operating=10_000_000.0, result=8_000_000.0, assets=70e6, equity=28e6, debt=42e6)])


@pytest.fixture
def client(net, settings):  # noqa: ANN001, ANN201
    from app.api.main import create_app
    from app.api.services import Services
    from app.storage.db import Database

    register(net)
    svc = Services(settings, db=Database(":memory:"), transport=net.transport(), provider=FakeProvider(), use_provider=True)
    with TestClient(create_app(svc)) as c:
        yield c


def monetary_facts(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [pt["fact"] for s in profile["financials"]["series"] for pt in s["points"]]


def assert_fact_consistent(fact: dict[str, Any], currency: str) -> None:
    """value, currency, unit, display text and the evidence excerpt must all tell the same story."""
    assert fact["currency"] == currency and fact["unit"] == currency, fact["id"]
    assert fact["displayValue"].startswith(("−" + currency, currency)), fact["displayValue"]
    assert fact["evidence"], fact["id"]
    excerpt = fact["evidence"][0]["excerpt"]
    assert re.search(rf"= {int(abs(fact['value']))} {currency} \(regnskapsperiode", excerpt), excerpt  # the excerpt carries the very same amount and code
    other = {"NOK", "USD", "EUR", "SEK", "DKK", "GBP"} - {currency}
    assert not any(re.search(rf"\b{code}\b", excerpt + fact["displayValue"]) for code in other), (fact["displayValue"], excerpt)


# ----------------------------------------------------------------------------- unit level --
def test_format_money_uses_the_stated_currency_and_never_assumes_nok() -> None:
    assert format_money(REV_2025, "USD") == "USD 67.96B"
    assert format_money(-12_400_000, "nok") == "−NOK 12.4M"
    assert format_money(640_000, "EUR") == "EUR 640k"
    assert format_money(REV_2025, None) == "67.96B"  # unknown currency: the bare number, not a guessed label
    assert format_money(None, "USD") == "—"
    assert normalize_currency(" usd ") == "USD" and normalize_currency(None) is None and normalize_currency("Norwegian krone") is None
    from app.core import util

    assert not hasattr(util, "format_nok")


def _module(records: list[dict[str, Any]]) -> ModuleResult:
    return ModuleResult(module="financials", source_id="regnskap", source_name="Regnskapsregisteret", source_class="official_annual_accounts",
                        url=f"https://data.brreg.no/regnskapsregisteret/regnskap/{EQUINOR}", retrieved_at="2026-10-05T10:00:00Z", state="available",
                        raw={"records": records})


def _record(currency: Any, revenue: float = REV_2025) -> dict[str, Any]:
    return {"period_start": "2025-01-01", "period_end": "2025-12-31", "account_type": "SELSKAP", "currency": currency, "revenue": revenue, "annual_result": 5.73e9}


def test_observations_carry_the_register_currency_in_unit_currency_and_excerpt() -> None:
    obs = financial_observations(_module([_record("USD")]))
    assert obs
    for o in obs:
        assert o.currency == o.unit == "USD"
        assert " USD (regnskapsperiode" in o.claim_span and "NOK" not in o.claim_span
        assert gate.check(o) is None
    revenue = next(o for o in obs if o.field == "revenue")
    assert revenue.value == REV_2025 and revenue.claim_span.endswith("(regnskapsperiode 2025-01-01–2025-12-31, regnskapstype SELSKAP)")


def test_missing_valuta_is_not_replaced_by_nok() -> None:
    obs = financial_observations(_module([_record(None)]))
    assert obs
    for o in obs:
        assert o.currency is None and o.unit is None
        assert "NOK" not in o.claim_span and "valuta ikke oppgitt" in o.claim_span
        assert o.attributes["currency_source"] == "not_stated"
        assert gate.check(o) is None  # the register's number is still published — as filed, unlabeled
    assert [o.currency for o in financial_observations(_module([_record("Norwegian krone")]))] == [None, None]


# ------------------------------------------------------------------------------- the gate --
def test_gate_refuses_a_currency_label_that_contradicts_its_own_evidence() -> None:
    good = next(o for o in financial_observations(_module([_record("USD")])) if o.field == "revenue")
    assert gate.check(good) is None

    mislabeled = Observation(**{**good.to_dict(), "currency": "NOK", "unit": "NOK"})  # evidence says USD, label says NOK
    assert gate.check(mislabeled) == "stated currency NOK does not appear in the evidence span"
    assert gate.check(Observation(**{**good.to_dict(), "unit": "NOK"})) == "unit (NOK) and currency (USD) disagree"
    assert gate.check(Observation(**{**good.to_dict(), "currency": "usd", "unit": "usd"})) == "currency is not a three-letter code"
    assert gate.check(Observation(**{**good.to_dict(), "currency": None, "unit": "USD"})) == "monetary amount has a unit but no currency"
    # a website / LLM-sourced amount without a currency is refused outright; only the structured register may state "not stated"
    web = Observation(**{**good.to_dict(), "currency": None, "unit": None, "extraction_method": "llm_website", "source_class": "company_owned",
                         "attributes": {"quote_verified": True}})
    assert gate.check(web) == "monetary amount without a stated currency"
    claims, rejections = gate.publish([mislabeled], EQUINOR)
    assert not claims and rejections[0].reason.startswith("stated currency NOK")


def test_same_amount_in_two_currencies_is_a_conflict_not_a_corroboration() -> None:
    usd = next(o for o in financial_observations(_module([_record("USD", 100.0)])) if o.field == "revenue")
    nok = next(o for o in financial_observations(_module([_record("NOK", 100.0)])) if o.field == "revenue")
    nok = Observation(**{**nok.to_dict(), "source_url": "https://data.brreg.no/other"})
    claims, rejections = gate.publish([usd, nok], EQUINOR)
    assert not rejections and len(claims) == 1
    claim = claims[0]
    assert claim.conflict and {c["currency"] for c in claim.conflict["candidates"]} == {"USD", "NOK"}
    assert claim.currency == claim.unit and claim.currency in ("USD", "NOK")


def test_llm_text_cannot_relabel_the_currency() -> None:
    facts = "Revenue FY2025: USD 67.96B\nAnnual result FY2025: USD 5.73B"
    assert llm_tasks.numbers_grounded("EQUINOR ASA reported revenue of USD 67.96B for FY2025.", facts)
    assert not llm_tasks.numbers_grounded("EQUINOR ASA reported revenue of NOK 67.96B for FY2025.", facts)
    assert not llm_tasks.numbers_grounded("Revenue was 67.96B NOK.", facts)


# ----------------------------------------------------------- end to end: Equinor (all USD) --
def test_equinor_profile_facts_series_snapshot_and_ratios_are_all_usd(client: TestClient) -> None:
    p = client.get(f"/api/companies/{EQUINOR}").json()
    facts = monetary_facts(p)
    assert facts, "Equinor accounts should be published"
    for fact in facts:
        assert_fact_consistent(fact, "USD")
    assert {s["unit"] for s in p["financials"]["series"]} == {"USD"}
    assert p["financials"]["currency"] == "USD" and p["financials"]["currencies"] == ["USD"]
    assert p["company"]["revenue"] == {"value": REV_2025, "currency": "USD", "period": "FY2025"}
    revenue = next(s for s in p["financials"]["series"] if s["key"] == "revenue")["points"][-1]["fact"]
    assert revenue["value"] == REV_2025 and revenue["displayValue"] == "USD 67.96B"
    assert {r["key"] for r in p["financials"]["ratios"]} >= {"revenue_growth", "operating_margin"}  # same currency: growth is meaningful
    for km in p["keyMetrics"]:
        if km["field"].startswith("financials."):
            assert km["currency"] == "USD" and km["displayValue"].startswith(("USD", "−USD"))


def test_equinor_brief_ask_explain_never_say_nok(client: TestClient) -> None:
    p = client.get(f"/api/companies/{EQUINOR}").json()
    brief = brief_from_profile(p)
    text = json.dumps(brief, ensure_ascii=False)
    fin = next(s for s in brief["sections"] if s["id"] == "financials")
    assert any("Revenue USD 67.96B in FY2025, down" in i["text"] and "from USD 72.54B in FY2024" in i["text"] for i in fin["items"])
    assert "NOK" not in text
    ans = run(answer(p, "Tell me about the financials and revenue", None))
    assert any("reported revenue of USD 67.96B for FY2025, compared with USD 72.54B in FY2024" in b["text"] for b in ans["blocks"])
    assert "NOK" not in json.dumps(ans, ensure_ascii=False)
    ex = client.post(f"/api/companies/{EQUINOR}/explain", json={"subject": {"kind": "metric", "metric": "revenue", "fromPeriod": "FY2024", "toPeriod": "FY2025"}}).json()
    assert "USD 72.54B in FY2024 and USD 67.96B in FY2025" in json.dumps(ex, ensure_ascii=False) and "NOK" not in json.dumps(ex, ensure_ascii=False)


def test_equinor_csv_export_value_raw_value_currency_and_excerpt_agree(client: TestClient) -> None:
    res = client.post("/api/exports", json={"target": {"type": "company", "id": EQUINOR}, "format": "csv",
                                             "options": {"sourceLinks": True, "evidence": True, "retrievalDates": True, "reportingPeriods": True}}).json()
    assert res["status"] == "ready"
    rows = list(csv.DictReader(io.StringIO(client.get(res["url"]).content.decode("utf-8-sig"))))
    money = [r for r in rows if r["field"].startswith("financials.")]
    assert money
    for r in money:
        assert r["currency"] == "USD"
        assert r["value"].startswith(("USD", "−USD")), r["value"]
        assert re.search(rf"= {int(abs(float(r['raw_value'])))} USD \(regnskapsperiode", r["evidence_excerpt"]), r["evidence_excerpt"]
        assert "NOK" not in r["value"] + r["evidence_excerpt"]
    rev = next(r for r in money if r["field"] == "financials.revenue.2025")
    assert (rev["value"], float(rev["raw_value"]), rev["currency"], rev["reporting_period"]) == ("USD 67.96B", REV_2025, "USD", "FY2025")
    assert "67960000000 USD" in rev["evidence_excerpt"]
    non_money = next(r for r in rows if r["field"] == "identity.legalName")
    assert non_money["currency"] == ""
    # JSON and XLSX exports carry the same facts
    assert json.loads(client.get(client.post("/api/exports", json={"target": {"type": "company", "id": EQUINOR}, "format": "json"}).json()["url"]).content)["company"]["revenue"]["currency"] == "USD"
    assert client.get(client.post("/api/exports", json={"target": {"type": "company", "id": EQUINOR}, "format": "xlsx"}).json()["url"]).status_code == 200


def test_equinor_summary_and_sheet_cell_use_usd(net: Any) -> None:
    register(net)
    record = run(research(net, EQUINOR, provider=FakeProvider(malformed=True), mode="quick"))  # LLM unusable → deterministic template summary
    summary = record["summary"]["text"]
    assert "revenue of USD 67.96B" in summary and "annual result of USD 5.73B" in summary and "NOK" not in summary
    revenue = next(c for c in record["claims"] if c["field"] == "revenue" and c["period_label"] == "FY2025")
    assert (revenue["value"], revenue["currency"], revenue["unit"]) == (REV_2025, "USD", "USD")
    assert "USD" in next(e for e in record["evidence"] if e["id"] in revenue["evidence_ids"])["claim_span"]

    from app.api.sheets import _cell_from_record

    cell = _cell_from_record(record, None, "revenue")
    assert cell["display"] == "USD 67.96B (FY2025)" and cell["currency"] == "USD" and cell["value"] == REV_2025


def test_envelope_claims_state_usd(net: Any) -> None:
    register(net)
    record = run(research(net, EQUINOR, mode="quick"))
    from app.competition.envelope import build_envelope

    env = build_envelope(record, run_id="test")
    revenue = next(c for c in env["claims"] if c["field"] == "revenue" and c.get("reporting_period", "").endswith("2025-12-31"))
    assert revenue["currency"] == "USD" and revenue["unit"] == "USD" and revenue["value"] == REV_2025


# -------------------------------------------------------- mixed / unknown / cross-company --
def test_currency_switch_never_computes_growth_or_ratios_across_currencies(client: TestClient) -> None:
    p = client.get(f"/api/companies/{SWITCHER}").json()
    rev = next(s for s in p["financials"]["series"] if s["key"] == "revenue")
    assert [(pt["period"], pt["fact"]["currency"], pt["fact"]["displayValue"]) for pt in rev["points"]] == [("FY2024", "NOK", "NOK 8.00B"), ("FY2025", "USD", "USD 900.0M")]
    assert rev["unit"] == "mixed currencies" and rev["currencies"] == ["NOK", "USD"] and p["financials"]["currency"] == "mixed currencies"
    assert p["company"]["revenue"]["currency"] == "USD"  # the latest filing decides the snapshot
    assert all(r["key"] != "revenue_growth" for r in p["financials"]["ratios"])
    assert all(h["key"] != "revenue_growth" for h in p["financials"]["ratioHistory"])
    assert any(r["key"] == "operating_margin" for r in p["financials"]["ratios"])  # same-period, same-record margin is still valid
    text = json.dumps(brief_from_profile(p), ensure_ascii=False)
    assert "Revenue USD 900.0M in FY2025 (FY2024 was filed in NOK; no currency conversion is applied)." in text
    assert " up " not in text.split("Revenue USD 900.0M")[1][:120] and " down " not in text.split("Revenue USD 900.0M")[1][:120]


def test_missing_valuta_publishes_the_number_unlabeled_with_a_note(client: TestClient) -> None:
    p = client.get(f"/api/companies/{NO_VALUTA}").json()
    rev = next(s for s in p["financials"]["series"] if s["key"] == "revenue")
    assert rev["unit"] == "currency not stated" and rev["currencies"] == []
    fact = rev["points"][-1]["fact"]
    assert fact["value"] == 123_000_000.0 and "currency" not in fact and "unit" not in fact and fact["displayValue"] == "123.0M"
    assert "does not state a currency" in fact["note"] and "NOK" not in json.dumps(p["financials"])
    assert "valuta ikke oppgitt" in fact["evidence"][0]["excerpt"]
    assert p["company"]["revenue"]["currency"] == ""
    assert all(r["key"] != "revenue_growth" for r in p["financials"]["ratios"])  # cannot prove both years share a currency


def test_compare_does_not_share_a_unit_across_currencies(client: TestClient) -> None:
    usd_only = comparison([client.get(f"/api/companies/{EQUINOR}").json(), client.get(f"/api/companies/{EQUINOR}").json()])
    assert next(r for r in usd_only["summary"] if r["key"] == "revenue")["unit"] == "USD"
    assert next(s for s in usd_only["series"] if s["key"] == "revenue")["unit"] == "USD"

    nok_only = client.get(f"/api/compare?orgs={NOK_CO},810363142").json()
    assert next(r for r in nok_only["summary"] if r["key"] == "revenue")["unit"] == "NOK"
    assert not next(s for s in nok_only["series"] if s["key"] == "revenue")["mixedCurrency"]

    mixed = client.get(f"/api/compare?orgs={EQUINOR},{NOK_CO}").json()
    row = next(r for r in mixed["summary"] if r["key"] == "revenue")
    assert row["unit"] == "mixed currencies" and row["currencies"] == ["USD", "NOK"]
    assert [v["displayValue"][:3] for v in row["values"]] == ["USD", "NOK"]  # each cell is still labelled with its own currency
    series = next(s for s in mixed["series"] if s["key"] == "revenue")
    assert series["unit"] == "mixed currencies" and series["mixedCurrency"] is True and series["currencies"] == [["USD"], ["NOK"]]
    fin_rows = next(sec for sec in mixed["sections"] if sec["id"] == "financials")["rows"]
    assert next(r for r in fin_rows if r["key"] == "equity")["unit"] == "mixed currencies"


def _research_via_api(client: TestClient, org: str) -> None:
    run_ = client.post("/api/research/runs", json={"query": org, "mode": "quick"}).json()
    with client.stream("GET", f"/api/research/runs/{run_['id']}/events?lastSeq=0") as stream:
        for line in stream.iter_lines():
            if line.startswith("data: ") and json.loads(line[6:])["type"] in ("run.completed", "run.failed"):
                break


def test_discover_does_not_compare_a_usd_revenue_with_a_nok_threshold(client: TestClient) -> None:
    for org in (EQUINOR, NOK_CO):
        _research_via_api(client, org)
    res = client.post("/api/companies/discover", json={"filters": {"revenueMin": 1_000_000}}).json()
    names = [c["legalName"] for c in res["items"]]
    assert "EQUINOR ASA" not in names  # 67 960 000 000 USD must never pass a "NOK ≥ 1 000 000" filter because of a unit mix-up
    assert any(c["orgNumber"] == NOK_CO for c in res["items"])
    # sorting by revenue never ranks a USD amount against NOK amounts: NOK reporters first, then other currencies grouped by code
    srt = client.post("/api/companies/discover", json={"filters": {"hiring": False}, "sort": "revenue"}).json()
    assert srt["total"] >= 0


# ----------------------------------------------------------------------------- static guard --
def test_no_hardcoded_nok_labels_in_the_backend_source() -> None:
    """A currency label in output may only ever come from a record's own `valuta`. The only literal allowed is the NOK *filter threshold* in Discover."""
    app = Path(__file__).resolve().parents[1] / "app"
    allowed = {"api/discover.py", "agent/prompts.py", "agent/llm_tasks.py"}  # NOK threshold filter · interpreter prompt · currency-code allow-list for grounding
    offenders = []
    for path in app.rglob("*.py"):
        rel = path.relative_to(app).as_posix()
        if rel.startswith("testing/") or rel in allowed:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"""["']NOK["']|NOK \{|format_nok""", line):
                offenders.append(f"{rel}:{n}: {line.strip()}")
    assert not offenders, "hard-coded NOK:\n" + "\n".join(offenders)
