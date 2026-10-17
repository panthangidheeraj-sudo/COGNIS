"""The active company is never changed by an ordinary word. Regression for: "Summarise Equinor ASA's latest annual financial results. Include the reporting period, …"
switched the chat from EQUINOR ASA to a company registered as INCLUDE (832749842) because the register has an exact match for the sentence-opening word "Include",
then refused to answer because the question mentioned Equinor. Offline tests: the register lookup is a spy, the model and the network are fakes."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.api import chat
from app.api.chat import other_company_in
from app.api.chat_intent import capitalised_names
from app.config import Settings
from app.testing.fixtures import FIXTURE_DIR, FixtureNetwork
from tests.test_chat_reliability import SECOND, _resolver
from tests.test_regulatory_and_chat import AUTO, CapturingProvider, make_client

EQUINOR = "923609016"
INCLUDE = "832749842"  # a registered company called INCLUDE: the register has an exact match for the ordinary word
EQUINOR_QUESTION = ("Summarise Equinor ASA's latest annual financial results. Include the reporting period, revenue, net income, and source links. "
                    "Clearly distinguish consolidated group accounts from company-only accounts, and identify anything you cannot verify.")


def register_equinor(net: FixtureNetwork) -> None:
    """An offline "EQUINOR ASA": the AUTOBJØRN fixtures under another number and name (no website, so no site fixture is needed)."""
    d = Path(FIXTURE_DIR) / "brreg"
    ent = json.loads((d / f"{AUTO}_enhet.json").read_text(encoding="utf-8"))
    ent.update({"navn": "EQUINOR ASA", "organisasjonsnummer": EQUINOR, "organisasjonsform": {"kode": "ASA", "beskrivelse": "Allmennaksjeselskap"}})
    ent.pop("hjemmeside", None)
    acc = copy.deepcopy(json.loads((d / f"{AUTO}_regnskap.json").read_text(encoding="utf-8")))
    for a in acc:
        a["virksomhet"]["organisasjonsnummer"] = EQUINOR
    net.register_company(EQUINOR, entity=ent, accounts=acc)


class Spy:
    """Stands in for the register search: records every name looked up and 'finds' a company for any ordinary word."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def __call__(self, query: str, auto_pick: bool = True):  # noqa: ANN202
        self.queries.append(query)
        return INCLUDE, []


@pytest.fixture
def equinor(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    register_equinor(net)
    client, svc = make_client(net, settings, CapturingProvider(None))
    spy = Spy()
    monkeypatch.setattr(svc, "resolve_query", spy)
    with client as c:
        assert c.get(f"/api/companies/{EQUINOR}").json()["company"]["legalName"] == "EQUINOR ASA"
        yield c, svc, spy


def test_the_exact_equinor_question_stays_on_equinor(equinor) -> None:  # noqa: ANN001
    c, _, spy = equinor
    body = c.post(f"/api/companies/{EQUINOR}/chat", json={"question": EQUINOR_QUESTION}).json()
    assert body["company"]["orgNumber"] == EQUINOR and "contextSwitch" not in body
    assert body["kind"] != "clarification" and "different company" not in body["answer"]
    assert not any(INCLUDE in json.dumps(x) for x in (body["sources"], body["citations"]))
    assert spy.queries == []  # no ordinary word was ever looked up as a company


def test_the_exact_equinor_question_keeps_its_thread_and_company(equinor) -> None:  # noqa: ANN001
    c, _, spy = equinor
    tid = c.post("/api/chat/threads", json={"orgNumber": EQUINOR}).json()["id"]
    r = c.post(f"/api/chat/threads/{tid}/ask", json={"question": EQUINOR_QUESTION}).json()
    assert r["threadId"] == tid and "switchedFromThreadId" not in r
    assert r["thread"]["company"]["orgNumber"] == EQUINOR
    assert [t["id"] for t in c.get("/api/chat/threads").json()["threads"]] == [tid]  # still one conversation
    assert spy.queries == []


@pytest.mark.parametrize(
    "question",
    [
        "Include the reporting period, revenue and net income.",
        "Summarise the latest accounts.",
        "Research the company's recent announcements.",
        "Compare its revenue with the previous year.",
        "Clearly state what you cannot verify.",
        "Identify anything you cannot verify.",
        "Provide the source links.",
        "Explain the net income. Describe the equity. Outline the debt.",
        "What is the revenue? Include the period.",
        "Highlight the main risks.",
        "Please list the board. Note the CEO.",
    ],
)
def test_ordinary_sentence_openers_never_switch_company(equinor, question: str) -> None:  # noqa: ANN001
    c, _, spy = equinor
    body = c.post(f"/api/companies/{EQUINOR}/chat", json={"question": question}).json()
    assert body["company"]["orgNumber"] == EQUINOR and "contextSwitch" not in body, body["answer"]
    assert spy.queries == [], spy.queries
    assert INCLUDE not in json.dumps(body)


def test_a_bare_registered_name_without_a_clear_reference_is_asked_about_not_adopted(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    register_equinor(net)
    client, svc = make_client(net, settings, CapturingProvider(None))
    _resolver(svc, monkeypatch, {"Hydro": INCLUDE})
    with client as c:
        c.get(f"/api/companies/{EQUINOR}")
        body = c.post(f"/api/companies/{EQUINOR}/chat", json={"question": "How did the Hydro numbers develop last year?"}).json()
    assert body["kind"] == "clarification" and body["company"]["orgNumber"] == EQUINOR and "contextSwitch" not in body
    assert "switch to" in body["answer"] and body["citations"] == [] and body["sources"] == []  # asked, not guessed; nothing from either company is used


def test_a_clear_reference_still_switches_and_never_mixes_evidence(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    register_equinor(net)
    client, svc = make_client(net, settings, CapturingProvider(None))
    _resolver(svc, monkeypatch, {"Sandnes": SECOND})
    with client as c:
        c.get(f"/api/companies/{EQUINOR}")
        by_name = c.post(f"/api/companies/{EQUINOR}/chat", json={"question": "What about Sandnes Elektriske AS revenue?"}).json()
        by_number = c.post(f"/api/companies/{EQUINOR}/chat", json={"question": f"What is the revenue of {SECOND}?"}).json()
    for body in (by_name, by_number):
        assert body["contextSwitch"]["to"]["orgNumber"] == SECOND and body["company"]["orgNumber"] == SECOND
        assert EQUINOR not in json.dumps([body["answer"], body["citations"], body["sources"]]) and "EQUINOR" not in body["answer"].upper().replace("NOTHING FROM EQUINOR", "")


def test_a_named_second_company_in_a_comparison_is_still_refused_not_mixed(equinor) -> None:  # noqa: ANN001
    c, _, _ = equinor
    body = c.post(f"/api/companies/{EQUINOR}/chat", json={"question": "Compare Equinor ASA with Polarlys Medtech AS"}).json()
    assert body["kind"] == "clarification" and "never mixes" in body["answer"] and body["citations"] == []


# --- the building blocks -------------------------------------------------------------------------
def test_openers_are_not_candidates_but_names_and_cued_names_are() -> None:
    names = capitalised_names(EQUINOR_QUESTION, limit=5, skip_openers=True)
    assert names == ["Equinor ASA"]
    assert capitalised_names("Include the period. Clearly state it.", skip_openers=True) == []
    assert capitalised_names("What about Hydro?", skip_openers=True) == ["Hydro"]  # mid-sentence: a name
    assert capitalised_names("Hydro Energy revenue?", skip_openers=True) == ["Hydro Energy"]  # an opener followed by another name word is a name
    assert capitalised_names("Hydro revenue?") == ["Hydro"]  # a thread that has no company yet still resolves a bare name


def test_a_suffixed_name_loses_the_instruction_word_in_front_of_it() -> None:
    assert other_company_in("Summarise Hydro ASA's results", {"orgNumber": EQUINOR, "legalName": "EQUINOR ASA"}) == "Hydro ASA"
    assert other_company_in(EQUINOR_QUESTION, {"orgNumber": EQUINOR, "legalName": "EQUINOR ASA"}) is None
    assert other_company_in(f"And {SECOND}?", {"orgNumber": EQUINOR, "legalName": "EQUINOR ASA"}) == SECOND


def test_module_still_exports_the_helpers_it_uses() -> None:
    assert chat._CAP_STOP and "include" in chat._CAP_STOP  # noqa: SLF001
