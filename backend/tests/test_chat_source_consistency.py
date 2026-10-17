"""The answer, its source list and "Sources checked for this answer" must agree with the evidence actually retrieved.

* A financial figure is cited to the document it comes from: its reporting period and its accounting scope (standalone company accounts vs consolidated group
  accounts are separate items, never merged).
* A link is labelled for what it is: the filed copy of the annual accounts ONLY when Regnskapsregisteret lists one for that year; otherwise the register's data
  record the figures were read from, which is never called the filing.
* An answer that says a listed filing link is unavailable, that calls a data record the filing, or that gives a standalone figure as consolidated (or the
  reverse) is rejected by the same validator that checks figures and citations — nothing is loosened.
* "Sources checked for this answer" lists only sources that were really read; when none were, the payload says why.

Offline: register, Tavily and pages are fixtures; the model is a scripted fake. No live API call is made.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.api.chat import Item, link_kind_for, provenance_note, provenance_problems, verify_answer
from app.api.chat_lookup import filing_link
from app.config import Settings
from app.testing.fixtures import FIXTURE_DIR, FixtureNetwork
from tests.test_chat_research_on_missing_evidence import CitingProvider
from tests.test_regulatory_and_chat import AUTO, CapturingProvider, make_client, tavily

EQ = "923609016"
ACCOUNTS = f"https://data.brreg.no/regnskapsregisteret/regnskap/{EQ}"
COPY_2024 = f"https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{EQ}/2024"
Q = "What were the latest annual financial results, standalone and consolidated, with links to the filings?"


def register_group_company(net: FixtureNetwork) -> None:
    """An offline "EQUINOR ASA" with standalone accounts for FY2024 and FY2025 and consolidated accounts for FY2025. The register lists a filed copy for 2024 only."""
    d = Path(FIXTURE_DIR) / "brreg"
    ent = json.loads((d / f"{AUTO}_enhet.json").read_text(encoding="utf-8"))
    ent.update({"navn": "EQUINOR ASA", "organisasjonsnummer": EQ, "organisasjonsform": {"kode": "ASA", "beskrivelse": "Allmennaksjeselskap"}})
    ent.pop("hjemmeside", None)
    acc = [a for a in copy.deepcopy(json.loads((d / f"{AUTO}_regnskap.json").read_text(encoding="utf-8"))) if a["regnskapsperiode"]["tilDato"][:4] in ("2024", "2025")]
    for a in acc:
        a["virksomhet"]["organisasjonsnummer"] = EQ
    group = copy.deepcopy(next(a for a in acc if a["regnskapsperiode"]["tilDato"].startswith("2025")))
    group["regnskapstype"] = "KONSERN"
    group["id"] = 999
    group["resultatregnskapResultat"]["driftsresultat"]["driftsinntekter"]["sumDriftsinntekter"] = 31000000.0
    net.register_company(EQ, entity=ent, accounts=[*acc, group], filing_years=["2024"])


def build(net: FixtureNetwork, settings: Settings, provider: Any, *, accounts_down: bool = True, key: str | None = "tvly-test", status: int = 200):  # noqa: ANN201
    settings.tavily_api_key = key
    register_group_company(net)
    if accounts_down:
        net.fail(ACCOUNTS, "503", times=3)  # the quick registry check cannot read the accounts: the targeted lookup reads them for the question
    calls: list[dict] = []
    net.handlers.append(tavily(["https://example.com/equinor"], calls, status=status))
    client, _svc = make_client(net, settings, provider)
    return client, calls


def ask(client: Any, question: str = Q) -> dict:
    with client as c:
        c.get(f"/api/companies/{EQ}")
        return c.post(f"/api/companies/{EQ}/chat", json={"question": question}).json()


# ------------------------------------------------------------------------------------- evidence --
def test_standalone_and_consolidated_figures_are_separate_items_with_their_own_period_and_link(net: FixtureNetwork, settings: Settings) -> None:
    provider = CapturingProvider({"answer": "x", "cited": []})
    client, _ = build(net, settings, provider)
    ask(client)
    prompt = next(m["content"] for m in provider.messages if m["role"] == "user" and "<<EVIDENCE" in m["content"])
    lines = {k: next(line for line in prompt.splitlines() if k in line) for k in (
        "[consolidated group accounts] Consolidated revenue FY2025", "[standalone company accounts] Revenue FY2025", "[standalone company accounts] Revenue FY2024")}
    group, company25, company24 = lines.values()
    assert "31.0M" in group and "21.8M" not in group  # the group figure is only in the group item
    assert "21.8M" in company25 and "31.0M" not in company25
    assert "period FY2025" in group and "period FY2025" in company25 and "period FY2024" in company24
    # FY2025: no filed copy is listed, so the link is the register's data record — and says so; FY2024: the listed filed copy
    assert "NOT a copy of the filing" in group and "NOT a copy of the filing" in company25
    assert "the filed copy of the annual accounts, listed by the register" in company24


def test_citations_carry_complete_metadata_and_an_honest_link_kind(net: FixtureNetwork, settings: Settings) -> None:
    provider = CitingProvider("[standalone company accounts] Revenue FY2024", "Standalone company revenue in the annual accounts for FY2024 was NOK 26.5M [{n}].")
    client, _ = build(net, settings, provider)
    body = ask(client)
    assert body["kind"] == "model"
    [cite] = body["citations"]
    assert cite["url"] == COPY_2024 and cite["linkKind"] == "filing_document" and cite["recordUrl"] == ACCOUNTS  # direct link + where the figures were read
    assert cite["reportingPeriod"] == "FY2024" and cite["accountingScope"] == "standalone company" and cite["currency"] == "NOK" and cite["retrievedAt"]
    assert "filed copy listed by Regnskapsregisteret" in cite["title"]
    assert "Direct links to the filed annual accounts are given for FY2024" in body["provenanceNote"]


def test_a_register_record_is_never_labelled_as_the_filing(net: FixtureNetwork, settings: Settings) -> None:
    provider = CitingProvider("[consolidated group accounts] Consolidated revenue FY2025", "Consolidated group revenue in the annual accounts for FY2025 was NOK 31.0M [{n}].")
    client, _ = build(net, settings, provider)
    body = ask(client)
    [cite] = body["citations"]
    assert cite["linkKind"] == "register_record" and cite["url"] == ACCOUNTS and not cite.get("recordUrl")
    assert "the register lists no filed copy for FY2025, so there is no direct link to the filing" in cite["title"] and "filed copy listed" not in cite["title"]
    assert "No direct link to a filed copy was established for FY2025" in body["provenanceNote"]


# ------------------------------------------------------------------------------ the model's claims --
@pytest.mark.parametrize(("needle", "sentence", "why"), [
    # says the direct link is unavailable while the evidence lists the filed copy
    ("[standalone company accounts] Revenue FY2024", "Standalone revenue for FY2024 was NOK 26.5M [{n}]. A direct filing URL could not be verified [{n}].", "filing link is unavailable"),
    # calls the register's data record the filing
    ("[consolidated group accounts] Consolidated revenue FY2025", "The filed copy of the FY2025 consolidated group accounts shows revenue of NOK 31.0M [{n}].", "calls a source the filed accounts"),
    # gives a standalone figure as consolidated
    ("[standalone company accounts] Revenue FY2025", "Consolidated group revenue for FY2025 was NOK 21.8M [{n}].", "gives a figure as consolidated"),
    # gives a consolidated figure as standalone
    ("[consolidated group accounts] Consolidated revenue FY2025", "Standalone company revenue for FY2025 was NOK 31.0M [{n}].", "gives a figure as standalone"),
])
def test_inconsistent_claims_about_links_or_scope_are_rejected(net: FixtureNetwork, settings: Settings, caplog: pytest.LogCaptureFixture, needle: str, sentence: str, why: str) -> None:
    client, _ = build(net, settings, CitingProvider(needle, sentence))
    body = ask(client)
    assert body["kind"] != "model"  # never shown as a validated model answer
    assert "could not be verified" not in body["answer"] and "filed copy of the FY2025" not in body["answer"]
    assert any(why in r.getMessage() for r in caplog.records if "chat answer rejected" in r.getMessage())


def test_a_correctly_scoped_answer_is_accepted_and_both_scopes_are_noted(net: FixtureNetwork, settings: Settings) -> None:
    class TwoScopes(CapturingProvider):
        async def chat(self, messages, **kw):  # noqa: ANN001, ANN003, ANN201
            from app.providers.llm_base import LLMResponse

            self.messages = messages
            block = next((m["content"] for m in messages if m["role"] == "user" and "<<EVIDENCE" in m["content"]), "")
            n = {k: next(int(line[1:line.index("]")]) for line in block.splitlines() if k in line) for k in ("[consolidated group accounts] Consolidated revenue FY2025", "[standalone company accounts] Revenue FY2025")}
            g, c = n.values()
            text = (f"For FY2025, consolidated group revenue in the annual accounts was NOK 31.0M [{g}]. "
                    f"Standalone company revenue in the annual accounts for FY2025 was NOK 21.8M [{c}]. No direct link to the filed FY2025 accounts was found [{c}].")
            return LLMResponse(text=json.dumps({"answer": text, "cited": [g, c]}), model="capture-1")

    client, _ = build(net, settings, TwoScopes(None))
    body = ask(client)
    assert body["kind"] == "model"
    scopes = {c["accountingScope"] for c in body["citations"]}
    assert scopes == {"consolidated group", "standalone company"}
    assert "separate filings" in body["provenanceNote"]


# ------------------------------------------------------------------------- "Sources checked" --
def test_sources_checked_lists_only_sources_really_read(net: FixtureNetwork, settings: Settings) -> None:
    client, calls = build(net, settings, CapturingProvider({"answer": "x", "cited": []}))
    body = ask(client)
    checked = body["search"]["checked"]
    assert calls and checked
    assert all(r.get("kind") != "search" and r["state"] != "skipped" for r in checked)  # no search calls, no unopened results
    assert {r["url"] for r in checked} >= {ACCOUNTS, f"https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{EQ}/aar"}
    assert "https://example.com/equinor" not in {r.get("url") for r in checked}
    assert body["search"]["web"] == {**body["search"]["web"], "searches": len(calls), "notOpened": len(calls)}  # counted, not listed


def test_sources_checked_is_empty_with_a_reason_when_nothing_was_checked(net: FixtureNetwork, settings: Settings) -> None:
    client, calls = build(net, settings, CapturingProvider({"answer": "x", "cited": []}), accounts_down=False)
    body = ask(client, "What is the revenue?")  # answered from saved research: no lookup at all
    assert calls == [] and body["search"]["state"] == "not_used" and not body["search"].get("checked")
    assert body["search"]["note"]


def test_a_failed_lookup_lists_what_was_tried_and_says_why_nothing_was_read(net: FixtureNetwork, settings: Settings) -> None:
    net.fail(ACCOUNTS, "503", times=20)
    client, _ = build(net, settings, CapturingProvider({"answer": "x", "cited": []}), accounts_down=False, status=432)
    body = ask(client)
    assert body["search"]["state"] == "unavailable" and not any(c.get("reportingPeriod") for c in body["citations"])  # no figure without its filing
    rows = {r["url"]: r["state"] for r in body["search"]["checked"]}
    assert rows[ACCOUNTS] == "unavailable"  # tried and could not be read: listed, with its state
    assert "could not be read" in body["search"]["note"] and "no paid fallback" in body["search"]["note"]


# ------------------------------------------------------------------------------------- units --
def test_link_kinds() -> None:
    assert link_kind_for(COPY_2024) == "filing_document"
    assert link_kind_for(ACCOUNTS) == "register_record"
    assert link_kind_for(f"https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{EQ}/aar") == "register_record"  # the list of copies is not a filing
    assert link_kind_for("https://www.equinor.com/investors/annual-reports") == "web_page"
    assert link_kind_for(None) is None
    url, kind, title = filing_link(EQ, "FY2023", "standalone company", {"2024": COPY_2024}, ACCOUNTS)
    assert (url, kind) == (ACCOUNTS, "register_record") and "lists no filed copy for FY2023" in title
    assert "could not be checked" in filing_link(EQ, "FY2023", None, {}, ACCOUNTS, copies_known=False)[2]
    url, kind, title = filing_link(EQ, "FY2024", "standalone company", {"2024": COPY_2024}, ACCOUNTS)
    assert (url, kind) == (COPY_2024, "filing_document") and "filed copy" in title


def _items() -> list[Item]:
    return [
        Item(1, "fact", "Revenue FY2024: NOK 26.5M (value: 26480515)", "Annual accounts FY2024 — filed copy", COPY_2024, None, "2026-10-16", "official_register", period="FY2024",
             currency="NOK", scope="standalone company", link_kind="filing_document", record_url=ACCOUNTS),
        Item(2, "fact", "Revenue FY2025: NOK 31.0M (value: 31000000)", "Annual accounts FY2025 — consolidated group figures (data record)", ACCOUNTS, None, "2026-10-16", "official_register",
             period="FY2025", currency="NOK", scope="consolidated group"),
    ]


def test_provenance_rules_directly() -> None:
    items = _items()
    assert provenance_problems("The direct link to the filing cannot be verified [1].", items)
    assert provenance_problems("The filing URLs could not be verified.", items)  # uncited, but a filed copy IS listed
    assert provenance_problems("The filed copy shows revenue of NOK 31.0M for FY2025 [2].", items)
    assert provenance_problems("Standalone revenue was NOK 31.0M in FY2025 [2].", items)
    assert provenance_problems("Consolidated revenue was NOK 26.5M in FY2024 [1].", items)
    assert not provenance_problems("Standalone revenue was NOK 26.5M in FY2024 [1]. Consolidated revenue was NOK 31.0M in FY2025 [2].", items)
    assert not provenance_problems("No direct link to a filed copy was found for FY2025 [2].", [items[1]])  # true when no copy is listed
    text, used, problems = verify_answer("The direct link to the filing could not be verified [1].", [1], items, question="q", history=[])
    assert problems  # part of the same validator that checks figures and citations


def test_provenance_note_is_decided_from_the_sources() -> None:
    note = provenance_note(_items())
    assert "Direct links to the filed annual accounts are given for FY2024" in note
    assert "No direct link to a filed copy was established for FY2025" in note
    assert "separate filings" in note
    assert provenance_note([Item(1, "event", "x", "t", "https://e24.no/a", "2026-01-01", None, "secondary_reporting")]) is None
