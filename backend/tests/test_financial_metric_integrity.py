"""Financial metrics are what their source says they are, and stay in their accounting scope.

The case behind these tests: an Equinor FY2025 answer showed "standalone total debt USD 64.25 billion" — exactly total assets (103.43) minus equity (39.18).
Regnskapsregisteret's ``sumGjeld`` ("sum gjeld") is TOTAL LIABILITIES; COGNIS had stored it as ``debt`` labelled "Total debt". The same figure was also given
for the consolidated accounts, while Equinor's own key figures report gross interest-bearing debt of USD 31.222 billion for the group.

Rules pinned here:
* ``sumGjeld`` is total liabilities — labelled so everywhere — and is never shown as debt, interest-bearing debt or net debt; its value comes from that field,
  never from assets minus equity;
* debt / interest-bearing debt / net debt have no register field: a question about them is answered from a source that states that measure, or as unavailable;
* standalone (SELSKAP) and consolidated (KONSERN) lines are separate; a missing group line is never filled from the standalone accounts, and an answer that gives
  a standalone value as the group's is rejected;
* research saved by earlier versions (field ``debt``) is read back under the correct name.

Offline: the register, Tavily and the company page are fixtures; the model is scripted. No live API call is made.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.api import fincompare, sheets
from app.api.chat import Item, provenance_problems
from app.api.question_router import route_question
from app.config import Settings
from app.extraction import financial_metrics as fm
from app.storage import repository as repo
from app.storage.db import Database
from app.testing.fixtures import FIXTURE_DIR, FixtureNetwork, company_page
from tests.test_chat_research_on_missing_evidence import CitingProvider
from tests.test_regulatory_and_chat import AUTO, CapturingProvider, make_client, tavily

EQ = "923609016"
ACCOUNTS = f"https://data.brreg.no/regnskapsregisteret/regnskap/{EQ}"
KEY_FIGURES = "https://www.equinor.com/investors/key-figures"
Q_RESULTS = "What were the latest annual financial results, standalone and consolidated, including total liabilities?"
Q_DEBT = "What were Equinor's total debt and net debt in the latest annual financial results?"


def _account(kind: str, *, revenue: float, assets: float, equity: float, liabilities: float | None) -> dict[str, Any]:
    d = Path(FIXTURE_DIR) / "brreg"
    base = copy.deepcopy(next(a for a in json.loads((d / f"{AUTO}_regnskap.json").read_text(encoding="utf-8")) if a["regnskapsperiode"]["tilDato"].startswith("2025")))
    base.update({"regnskapstype": kind, "valuta": "USD", "id": 1000 + len(kind)})
    base["virksomhet"]["organisasjonsnummer"] = EQ
    base["resultatregnskapResultat"]["driftsresultat"]["driftsinntekter"]["sumDriftsinntekter"] = revenue
    base["eiendeler"]["sumEiendeler"] = assets
    base["egenkapitalGjeld"]["egenkapital"]["sumEgenkapital"] = equity
    if liabilities is None:
        base["egenkapitalGjeld"]["gjeldOversikt"].pop("sumGjeld", None)
    else:
        base["egenkapitalGjeld"]["gjeldOversikt"]["sumGjeld"] = liabilities
    return base


def register(net: FixtureNetwork, *, group_liabilities: float | None = 80.0e9, standalone_liabilities: float = 64.25e9, website: bool = False) -> None:
    d = Path(FIXTURE_DIR) / "brreg"
    ent = json.loads((d / f"{AUTO}_enhet.json").read_text(encoding="utf-8"))
    ent.update({"navn": "EQUINOR ASA", "organisasjonsnummer": EQ, "organisasjonsform": {"kode": "ASA", "beskrivelse": "Allmennaksjeselskap"}})
    if website:
        ent["hjemmeside"] = "www.equinor.com"
    else:
        ent.pop("hjemmeside", None)
    accounts = [_account("SELSKAP", revenue=60.0e9, assets=103.43e9, equity=39.18e9, liabilities=standalone_liabilities),
                _account("KONSERN", revenue=100.0e9, assets=130.0e9, equity=50.0e9, liabilities=group_liabilities)]
    net.register_company(EQ, entity=ent, accounts=accounts, filing_years=[])


def build(net: FixtureNetwork, settings: Settings, provider: Any, *, key: str | None = None, page: bool = False, **kw: Any):  # noqa: ANN201
    settings.tavily_api_key = key
    register(net, website=page, **kw)
    net.fail(ACCOUNTS, "503", times=3)  # the quick registry check cannot read the accounts: the question's own lookup reads them
    if page:
        net.add_site("www.equinor.com", {"/investors/key-figures": company_page(
            "Key figures — Equinor", "<h1>Key figures 2025</h1><p>Equinor ASA reported gross interest-bearing debt of USD 31.222 billion at year-end 2025 for the group, "
            "as stated in its key figures.</p><p>Read our privacy policy and cookie notice.</p>")})
        net.add_site("equinor.com", {})
    net.handlers.append(tavily([KEY_FIGURES] if page else [], []))
    client, _svc = make_client(net, settings, provider)
    return client


def ask(client: Any, question: str) -> dict:
    with client as c:
        c.get(f"/api/companies/{EQ}")
        return c.post(f"/api/companies/{EQ}/chat", json={"question": question}).json()


def prompt_of(provider: CapturingProvider) -> str:
    return next(m["content"] for m in provider.messages if m["role"] == "user" and "<<EVIDENCE" in m["content"])


def line_with(prompt: str, marker: str) -> str:
    return next(line for line in prompt.splitlines() if marker in line)


# ---------------------------------------------------------------------------------- metric mapping --
def test_sum_gjeld_is_total_liabilities_and_never_called_debt(net: FixtureNetwork, settings: Settings) -> None:
    provider = CapturingProvider({"answer": "x", "cited": []})
    ask(build(net, settings, provider), Q_RESULTS)
    prompt = prompt_of(provider)
    company = line_with(prompt, "[standalone company accounts]")
    group = line_with(prompt, "[consolidated group accounts]")
    assert "Total liabilities FY2025: USD 64.25B (value: 64250000000)" in company
    assert "Consolidated total liabilities FY2025: USD 80.00B (value: 80000000000)" in group
    for line in (company, group):
        assert not re.search(r"\bdebt\b", line, re.I)  # the register's sum gjeld is never labelled debt


def test_the_value_comes_from_the_filed_field_not_from_assets_minus_equity(net: FixtureNetwork, settings: Settings) -> None:
    provider = CapturingProvider({"answer": "x", "cited": []})
    ask(build(net, settings, provider, standalone_liabilities=50.0e9), Q_RESULTS)  # deliberately NOT assets − equity (64.25B)
    prompt = prompt_of(provider)
    assert "Total liabilities FY2025: USD 50.00B (value: 50000000000)" in line_with(prompt, "[standalone company accounts]")
    assert "64250000000" not in prompt and "64.25" not in prompt  # nothing is derived from other lines


# ------------------------------------------------------------------------------------------ scope --
def test_a_missing_group_line_is_never_filled_from_the_standalone_accounts(net: FixtureNetwork, settings: Settings) -> None:
    provider = CapturingProvider({"answer": "x", "cited": []})
    ask(build(net, settings, provider, group_liabilities=None), Q_RESULTS)
    group = line_with(prompt_of(provider), "[consolidated group accounts]")
    assert "liabilities" not in group.lower() and "64.25" not in group and "64250000000" not in group
    assert "Consolidated total assets FY2025: USD 130.00B" in group  # the group's own lines are still there


def test_a_standalone_value_given_as_the_groups_is_rejected_even_when_a_group_item_is_cited(net: FixtureNetwork, settings: Settings,
                                                                                            caplog: pytest.LogCaptureFixture) -> None:
    class Mixed(CapturingProvider):
        async def chat(self, messages, **kw):  # noqa: ANN001, ANN003, ANN201
            from app.providers.llm_base import LLMResponse

            self.messages = messages
            block = prompt_of(self)
            n = {k: next(int(x[1:x.index("]")]) for x in block.splitlines() if k in x) for k in ("[consolidated group accounts]", "[standalone company accounts]")}
            g, c = n.values()
            text = f"Consolidated total liabilities for FY2025 were USD 64.25 billion [{g}][{c}]."
            return LLMResponse(text=json.dumps({"answer": text, "cited": [g, c]}), model="capture-1")

    body = ask(build(net, settings, Mixed(None)), Q_RESULTS)
    assert body["kind"] != "model"
    assert any("gives a figure as consolidated" in r.getMessage() for r in caplog.records if "chat answer rejected" in r.getMessage())


# ------------------------------------------------------------------------------------------- debt --
def test_total_liabilities_presented_as_debt_is_rejected(net: FixtureNetwork, settings: Settings, caplog: pytest.LogCaptureFixture) -> None:
    provider = CitingProvider("[standalone company accounts]", "Standalone total debt for FY2025 was USD 64.25 billion in the annual accounts [{n}].")
    body = ask(build(net, settings, provider), Q_RESULTS)
    assert body["kind"] != "model"
    assert not re.search(r"debt[^.\n]{0,80}64\.25", body["answer"], re.I)
    assert any("presents a figure as debt" in r.getMessage() for r in caplog.records if "chat answer rejected" in r.getMessage())


def test_a_debt_question_without_a_debt_source_says_unavailable(net: FixtureNetwork, settings: Settings) -> None:
    body = ask(build(net, settings, CapturingProvider(None)), Q_DEBT)  # register only: no source states debt
    text = f"{body['answer']} {body.get('provenanceNote') or ''}"
    assert "does not report total (interest-bearing) debt or net debt" in text
    assert not re.search(r"debt[^.\n]{0,80}(?:64\.25|64,25|64250)", body["answer"], re.I)  # total liabilities is never offered as the debt figure


def test_a_company_stated_debt_figure_is_used_under_its_own_name(net: FixtureNetwork, settings: Settings) -> None:
    provider = CitingProvider("gross interest-bearing debt", "Equinor ASA reported gross interest-bearing debt of USD 31.222 billion at year-end 2025 for the group [{n}].")
    body = ask(build(net, settings, provider, key="tvly-test", page=True), Q_DEBT)
    assert body["kind"] == "model", body["answer"]
    [cite] = body["citations"]
    assert cite["url"] == KEY_FIGURES and cite["sourceClass"] == "company_disclosure" and cite["origin"] == "fresh"
    assert "31.222" in body["answer"] and "64.25" not in body["answer"]
    assert fm.UNAVAILABLE_NOTE not in (body.get("provenanceNote") or "")  # a source states the measure asked for


# ------------------------------------------------------------------------------------------ units --
def _items() -> list[Item]:
    return [
        Item(1, "fact", "[standalone company accounts] Total liabilities FY2025: USD 64.25B (value: 64250000000)", "Annual accounts FY2025", ACCOUNTS, None, None, "official_register",
             period="FY2025", currency="USD", scope="standalone company"),
        Item(2, "fact", "[consolidated group accounts] Consolidated total liabilities FY2025: USD 80.00B (value: 80000000000)", "Annual accounts FY2025", ACCOUNTS, None, None,
             "official_register", period="FY2025", currency="USD", scope="consolidated group"),
        Item(3, "fact", "Key figures: gross interest-bearing debt of USD 31.222 billion at year-end 2025", "Key figures — Equinor", KEY_FIGURES, None, None, "company_disclosure"),
    ]


@pytest.mark.parametrize(("text", "bad"), [
    ("Total debt was USD 64.25 billion in FY2025 [1].", True),
    ("Net debt was USD 64.25 billion [1].", True),
    ("Interest-bearing debt: USD 64.25B [1][3].", True),  # a debt source is cited, but it does not state THIS figure
    ("Gross interest-bearing debt was USD 31.222 billion at year-end 2025 [3].", False),
    ("Total liabilities were USD 64.25 billion in FY2025 [1].", False),
    ("Debt is not reported in the filed accounts; total liabilities were USD 64.25 billion [1].", False),
    ("Consolidated total liabilities were USD 64.25 billion [1][2].", True),  # the standalone value given as the group's
    ("Consolidated total liabilities were USD 80.00 billion [2]. Standalone total liabilities were USD 64.25 billion [1].", False),
    ("• Consolidated: total liabilities USD 64.25 billion [2]", True),  # bullet lines are checked one by one
])
def test_metric_and_scope_rules(text: str, bad: bool) -> None:
    assert bool(provenance_problems(text, _items())) is bad, provenance_problems(text, _items())


def test_definitions_keep_the_four_measures_apart() -> None:
    for metric in ("total_liabilities", "debt", "interest_bearing_debt", "net_debt"):
        assert metric in fm.DEFINITIONS
    assert fm.REGISTER_FIELDS.isdisjoint(fm.NOT_IN_REGISTER)
    assert fm.unavailable_reason("total_liabilities") is None
    assert all(fm.unavailable_reason(m) == fm.UNAVAILABLE_NOTE for m in ("debt", "interest_bearing_debt", "net_debt"))
    assert fm.label_of("consolidated_total_liabilities") == "Consolidated total liabilities"


def test_questions_about_debt_and_liabilities_are_routed_to_different_metrics() -> None:
    assert route_question("What is the total debt?").metrics == ["debt"]
    assert route_question("What is the net debt?").metrics == ["debt"]
    assert route_question("What are the total liabilities?").metrics == ["total_liabilities"]
    assert route_question("Hva er sum gjeld?").metrics == ["total_liabilities"]
    assert route_question("Hva er rentebærende gjeld?").metrics == ["debt"]


def test_a_comparison_of_debt_says_it_is_not_in_the_filed_accounts() -> None:
    rec = {"claims": [{"field": "total_liabilities", "value": v, "currency": "USD", "reporting_period": f"{y}-01-01/{y}-12-31", "period_label": f"FY{y}", "evidence_ids": [],
                       "attributes": {}} for y, v in ((2024, 60e9), (2025, 64.25e9))], "evidence": []}
    cmp = fincompare.compare_periods(rec, metrics=["debt"])
    assert cmp.rows == [] and fm.UNAVAILABLE_NOTE in " ".join(cmp.omitted)
    assert [r.key for r in fincompare.compare_periods(rec, metrics=["total_liabilities"]).rows] == ["total_liabilities"]


def test_sheet_columns_never_map_debt_to_total_liabilities() -> None:
    assert sheets.map_instruction("Total liabilities") == "total_liabilities"
    assert sheets.map_instruction("Sum gjeld") == "total_liabilities"
    assert sheets.map_instruction("Total debt") != "total_liabilities"
    assert sheets.map_instruction("Net debt") != "total_liabilities"
    cell = sheets._cell_from_record({"identity": {"orgNumber": EQ}, "claims": [], "completed_at": "2026-10-01"}, None, "debt")  # a column saved by an older version
    assert cell["status"] == "not_available" and cell["note"] == fm.UNAVAILABLE_NOTE


def test_research_saved_by_an_older_version_is_read_back_under_the_correct_name() -> None:
    db = Database(":memory:")
    legacy = {"organisation_number": EQ, "run_id": "old", "mode": "registry", "completed_at": "2026-09-01T00:00:00Z", "identity": {"org_number": EQ, "legal_name": "EQUINOR ASA"},
              "modules": {}, "evidence": [], "absences": [{"field": "debt", "note": "No filed annual accounts state total debt."}],
              "claims": [{"field": f, "key": f"{EQ}|{f}||2025-01-01/2025-12-31", "availability": "verified", "label": "Total debt", "value": v, "currency": "USD", "reporting_period": "2025-01-01/2025-12-31", "period_label": "FY2025",
                          "evidence_ids": [], "attributes": {}} for f, v in (("debt", 64.25e9), ("consolidated_debt", 80.0e9), ("short_term_debt", 10e9), ("long_term_debt", 54.25e9))]}
    repo.save_record(db, legacy)
    rec = repo.latest_record(db, EQ)
    fields = {c["field"]: (c["value"], c["label"]) for c in rec["claims"]}
    assert fields == {"total_liabilities": (64.25e9, "Total liabilities"), "consolidated_total_liabilities": (80.0e9, "Consolidated total liabilities"),
                      "current_liabilities": (10e9, "Current liabilities"), "non_current_liabilities": (54.25e9, "Non-current liabilities")}
    assert rec["absences"][0] == {"field": "total_liabilities", "note": "No filed annual accounts state total liabilities."}
    assert {c["key"] for c in rec["claims"]} >= {f"{EQ}|total_liabilities||2025-01-01/2025-12-31"}


def test_the_profile_shows_total_liabilities_and_no_debt_series(net: FixtureNetwork, settings: Settings) -> None:
    settings.tavily_api_key = None
    register(net)
    client, _ = make_client(net, settings, CapturingProvider(None))
    with client as c:
        fin = c.get(f"/api/companies/{EQ}").json()["financials"]
    keys = {s["key"]: s for s in fin["series"]}
    assert "debt" not in keys
    tl = keys["total_liabilities"]
    assert tl["label"] == "Total liabilities" and tl["points"][-1]["fact"]["value"] == 64.25e9  # the company-only line: the profile never mixes in the group's
