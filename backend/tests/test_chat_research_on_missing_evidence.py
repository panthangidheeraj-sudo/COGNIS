"""Chat answers from saved evidence first; when that cannot answer, it runs ONE bounded, question-focused lookup (``chat_lookup.py``) — never the full research
pipeline — and the configured model (Groq in production; a capturing fake here) writes only from the dated extracts that lookup returns. The evidence checks are
unchanged: every figure, citation and URL must be in the cited evidence, and a failed or empty lookup is reported as exactly that.

Offline: the register, Tavily, the news outlet and the company website are fixtures; no real network and no real model.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import pytest

from app.config import Settings
from app.testing.fixtures import FixtureNetwork, company_page
from tests.test_regulatory_and_chat import AUTO, CapturingProvider, make_client, tavily

ACCOUNTS = f"https://data.brreg.no/regnskapsregisteret/regnskap/{AUTO}"
Q_RESULTS = "What are the latest annual financial results, including revenue and the reporting period?"
ARTICLE = "https://e24.no/naeringsliv/autobjorn-resultat"
ARTICLE_HTML = company_page(
    "Autobjørn AS med sterkt år",
    '<article><time datetime="2026-03-02">2. mars 2026</time><h1>Autobjørn AS med sterkt år</h1>'
    "<p>Autobjørn AS økte driftsinntektene til 21,8 millioner kroner i 2025, viser selskapets årsregnskap.</p>"
    "<p>Abonner på nyhetsbrevet vårt for flere saker.</p></article>",
)


class CitingProvider(CapturingProvider):
    """A model that answers from the evidence it is given: it cites the item that holds ``needle`` and repeats that item's own figure."""

    def __init__(self, needle: str, sentence: str) -> None:
        super().__init__(None)
        self.needle, self.sentence = needle, sentence

    async def chat(self, messages, *, max_tokens=800, temperature=0.0, json_mode=False, task=""):  # noqa: ANN001, ANN201
        from app.providers.llm_base import LLMResponse

        self.calls += 1
        self.messages = messages
        block = next((m["content"] for m in messages if m["role"] == "user" and "<<EVIDENCE" in m["content"]), "")
        n = next((int(m.group(1)) for m in re.finditer(r"^\[(\d+)\] (.*)$", block, re.M) if self.needle in m.group(2)), None)
        if task != "chat" or n is None:
            return LLMResponse(text=json.dumps({"answer": "The evidence does not say.", "cited": []}), model=self.model)
        return LLMResponse(text=json.dumps({"answer": self.sentence.format(n=n), "cited": [n]}), model=self.model)


def build(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch, *, provider: Any = None, accounts_down: bool = True, key: str | None = "tvly-test",
          hits: list[str] | None = None, status: int = 200):  # noqa: ANN201
    settings.tavily_api_key = key
    if accounts_down:
        net.fail(ACCOUNTS, "503", times=3)  # the accounts register is down while the quick registry check runs: the saved record has no figures
    net.add_site("e24.no", {"/naeringsliv/autobjorn-resultat": ARTICLE_HTML})
    calls: list[dict] = []
    net.handlers.append(tavily([ARTICLE, "https://example.com/autobjorn"] if hits is None else hits, calls, status=status))
    client, svc = make_client(net, settings, provider or CapturingProvider(None))
    modes: list[str] = []
    real = svc.research

    async def spy(org: str, **kw: Any):  # noqa: ANN202
        modes.append(str(kw.get("mode")))
        return await real(org, **kw)

    monkeypatch.setattr(svc, "research", spy)
    return client, svc, modes, calls


def stream_stages(text: str) -> list[dict]:
    return [json.loads(b.split("data: ", 1)[1]) for b in text.strip().split("\n\n") if b.startswith("event: progress")]


# ------------------------------------------------------------------------------------------- 1 · reuse --
def test_saved_evidence_is_reused_and_nothing_is_looked_up(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CitingProvider("NOK 21.8M", "Revenue in the filed annual accounts for FY2025 was NOK 21.8M [{n}].")
    client, _, modes, calls = build(net, settings, monkeypatch, provider=provider, accounts_down=False)
    with client as c:
        c.get(f"/api/companies/{AUTO}")
        body = c.post(f"/api/companies/{AUTO}/chat", json={"question": "What is the revenue?"}).json()
    assert calls == [] and "deep" not in modes  # no search, no research pipeline
    assert body["search"]["state"] == "not_used" and body["origin"] == "saved"
    assert body["kind"] == "model" and body["citations"] and all(c["origin"] == "saved" for c in body["citations"])


# ------------------------------------------------------------------------ 2 · targeted lookup, not deep --
def test_missing_evidence_triggers_one_targeted_lookup_and_never_the_research_pipeline(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent.orchestrator import Orchestrator

    runs: list[str] = []
    real_research = Orchestrator.research

    async def orch_spy(self, org, **kw):  # noqa: ANN001, ANN202
        runs.append(kw.get("options").mode if kw.get("options") else "?")
        return await real_research(self, org, **kw)

    monkeypatch.setattr(Orchestrator, "research", orch_spy)
    client, _, modes, calls = build(net, settings, monkeypatch)
    with client as c:
        c.get(f"/api/companies/{AUTO}")
        saved = {x["area"]: x["status"] for x in c.get(f"/api/companies/{AUTO}/chat/context").json()["coverage"]}
        started = time.monotonic()
        r = c.post(f"/api/companies/{AUTO}/chat/stream", json={"question": Q_RESULTS})
        took = time.monotonic() - started
    assert saved["financials"] != "verified"  # the premise: nothing on record answered the question
    assert modes == ["registry"] and runs == ["registry"]  # only the quick registry check of the first visit; chat started no research run
    assert len(calls) == 1 and "AUTOBJ" in calls[0]["query"] and "revenue" in calls[0]["query"]  # one search, about this question
    assert "autobjorn.no" in calls[0]["include_domains"] and "e24.no" in calls[0]["include_domains"]  # permitted domains only
    result = json.loads(r.text.split("event: result\ndata: ", 1)[1].split("\n\n", 1)[0])
    assert result["search"]["state"] == "used" and result["origin"] == "fresh"
    assert any(x["url"] == ARTICLE and x["publishedAt"] == "2026-03-02" for x in result["citations"])
    assert any(x["reportingPeriod"] == "FY2025" and "brreg" in x["url"] for x in result["citations"])
    checked = {x.get("url"): x["state"] for x in result["search"]["checked"]}
    assert "https://example.com/autobjorn" not in checked  # not a permitted source: never fetched, so never listed as a source that was checked
    assert checked[ARTICLE] == "used" and result["search"]["web"]["notOpened"] >= 1 and result["search"]["web"]["searches"] == 1
    assert took < 10


def test_progress_is_a_few_real_stages_with_source_details_separate(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, _, _ = build(net, settings, monkeypatch)
    with client as c:
        c.get(f"/api/companies/{AUTO}")
        tid = c.post("/api/chat/threads", json={"orgNumber": AUTO}).json()["id"]
        r = c.post(f"/api/chat/threads/{tid}/ask/stream", json={"question": Q_RESULTS})
    events = stream_stages(r.text)
    stages = [e["stage"] for e in events]
    assert stages[0] == "understand" and "research" in stages and stages[-1] == "answer"
    last = len(stages) - 1 - stages[::-1].index("evidence")
    assert stages.index("evidence") < stages.index("research") < last < stages.index("answer")  # saved evidence, then current sources, then the answer: in the order it happens
    sources = [e["source"] for e in events if e["stage"] == "source"]
    assert sources and all({"name", "state"} <= set(s) for s in sources)  # per-source detail travels separately from the stages
    assert not any(e["stage"] == "research" and e["label"].startswith("Checking ") and "current sources" not in e["label"] for e in events)  # no connector-by-connector list
    assert "event: result" in r.text and "event: error" not in r.text


# ---------------------------------------------------------------------- 3 · Groq receives the sources --
def test_the_model_receives_the_dated_source_extracts(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CapturingProvider({"answer": "x", "cited": []})
    client, _, _, _ = build(net, settings, monkeypatch, provider=provider)
    with client as c:
        c.get(f"/api/companies/{AUTO}")
        c.post(f"/api/companies/{AUTO}/chat", json={"question": Q_RESULTS})
    prompt = next(m["content"] for m in provider.messages if m["role"] == "user" and "<<EVIDENCE" in m["content"])
    article = next(line for line in prompt.splitlines() if "21,8 millioner" in line)
    assert "published 2026-03-02" in article and "read for this question" in article and "Press report" in article
    filing = next(line for line in prompt.splitlines() if "period FY2025" in line and "Official register" in line)
    assert "currency NOK" in filing and "Revenue FY2025" in filing
    assert "Abonner" not in prompt  # boilerplate is not passed on
    assert "Check of current sources for this question: used" in prompt


# --------------------------------------------------------------------- 4 · citations survive validation --
def test_a_supported_answer_keeps_its_source_links_and_dates(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CitingProvider("21,8 millioner", "E24 reported on 2026-03-02 that Autobjørn AS increased its operating revenue to 21,8 millioner kroner in 2025 [{n}].")
    client, _, _, _ = build(net, settings, monkeypatch, provider=provider)
    with client as c:
        c.get(f"/api/companies/{AUTO}")
        body = c.post(f"/api/companies/{AUTO}/chat", json={"question": Q_RESULTS}).json()
    assert body["kind"] == "model" and body["model"] == "capture-1"
    [cite] = body["citations"]
    assert cite["url"] == ARTICLE and cite["publishedAt"] == "2026-03-02" and cite["origin"] == "fresh" and cite["sourceClass"] == "secondary_reporting"
    assert re.search(r"\[\d\]", body["answer"])


def test_an_unsupported_answer_is_still_rejected_after_a_lookup(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CapturingProvider({"answer": "Net income was NOK 999 million in 2031 [1].", "cited": [1]})
    client, _, _, _ = build(net, settings, monkeypatch, provider=provider)
    with client as c:
        c.get(f"/api/companies/{AUTO}")
        body = c.post(f"/api/companies/{AUTO}/chat", json={"question": Q_RESULTS}).json()
    assert "999" not in body["answer"] and "2031" not in body["answer"]
    assert body["kind"] != "model"
    assert body["kind"] == "evidence_only" and body["citations"]  # the sources found are still shown, quoted, with their own numbers


# ------------------------------------------------------------------------ 5 · failures are reported --
def test_a_refused_search_is_reported_as_unavailable_not_as_nothing_found(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    net.fail(ACCOUNTS, "503", times=10)  # the register stays down too
    client, _, modes, calls = build(net, settings, monkeypatch, status=432, accounts_down=False)
    with client as c:
        c.get(f"/api/companies/{AUTO}")
        body = c.post(f"/api/companies/{AUTO}/chat", json={"question": Q_RESULTS}).json()
    assert len(calls) == 1 and "deep" not in modes  # no retry loop, no paid fallback, no research pipeline
    assert body["search"]["state"] == "unavailable" and "no paid fallback" in body["search"]["note"]
    assert "Regnskapsregisteret could not be read" in body["search"]["note"]
    assert body["citations"] == [] and "21" not in body["answer"]  # nothing is invented
    assert "Research page" in body["answer"]  # and a useful next action is offered


def test_a_search_that_finds_nothing_usable_says_so(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, _, calls = build(net, settings, monkeypatch, accounts_down=False, hits=["https://e24.no/finnes-ikke"])
    with client as c:
        c.get(f"/api/companies/{AUTO}")
        body = c.post(f"/api/companies/{AUTO}/chat", json={"question": "What is its carbon capture strategy for 2030?"}).json()
    assert 1 <= len(calls) <= settings.chat_max_searches
    assert body["kind"] == "limitation" and body["citations"] == []
    assert body["search"]["state"] == "no_results" and "not evidence that the information does not exist" in body["search"]["note"]
    assert any(x["state"] == "unreadable" for x in body["search"]["checked"])  # the page that could not be read is listed, with the reason


def test_without_a_search_key_only_the_official_register_is_used(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, modes, calls = build(net, settings, monkeypatch, key=None)
    with client as c:
        c.get(f"/api/companies/{AUTO}")
        body = c.post(f"/api/companies/{AUTO}/chat", json={"question": Q_RESULTS}).json()
    assert calls == [] and "deep" not in modes
    assert body["search"]["state"] == "used" and "not configured" in body["search"]["note"]
    assert body["citations"] and all("brreg" in c["url"] for c in body["citations"])


def test_a_slow_lookup_is_cut_off_and_never_looks_successful(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.connectors import search

    async def slow(*a: Any, **k: Any):  # noqa: ANN202
        await asyncio.sleep(5)
        return None, []

    monkeypatch.setattr(search, "web_search", slow)
    settings.chat_lookup_timeout_seconds = 0.6
    client, _, _, _ = build(net, settings, monkeypatch, accounts_down=False)
    with client as c:
        c.get(f"/api/companies/{AUTO}")
        started = time.monotonic()
        body = c.post(f"/api/companies/{AUTO}/chat", json={"question": "What is its carbon capture strategy for 2030?"}).json()
        took = time.monotonic() - started
    assert took < 4
    assert body["search"]["state"] == "timeout" and "stopped after" in body["search"]["note"]
    assert body["origin"] == "saved" and body["citations"] == []


# ----------------------------------------------------------------------- bounded spending, threads --
def test_the_same_question_does_not_spend_a_second_search(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, _, calls = build(net, settings, monkeypatch)
    with client as c:
        c.get(f"/api/companies/{AUTO}")
        first = c.post(f"/api/companies/{AUTO}/chat", json={"question": Q_RESULTS}).json()
        again = c.post(f"/api/companies/{AUTO}/chat", json={"question": Q_RESULTS}).json()
    assert len(calls) == 1
    assert first["search"]["state"] == again["search"]["state"] == "used" and again["search"]["lookup"]["cached"] is True


def test_check_for_new_information_in_a_thread_re_asks_the_same_message_once(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, modes, calls = build(net, settings, monkeypatch, accounts_down=False)
    with client as c:
        c.get(f"/api/companies/{AUTO}")
        tid = c.post("/api/chat/threads", json={"orgNumber": AUTO}).json()["id"]
        first = c.post(f"/api/chat/threads/{tid}/ask", json={"question": "What is the revenue?"}).json()
        uid = first["userMessage"]["id"]
        assert calls == []  # answered from saved evidence
        again = c.post(f"/api/chat/threads/{tid}/ask", json={"question": "What is the revenue?", "retryOf": uid, "fresh": True}).json()
        stored = c.get(f"/api/chat/threads/{tid}").json()
    assert len(calls) == 1 and "deep" not in modes and again["assistantMessage"]["payload"]["origin"] == "fresh"
    roles = [m["role"] for m in stored["messages"]]
    assert roles == ["user", "assistant", "assistant"]  # the question is stored once; the new answer follows the old one
    assert stored["messages"][0]["id"] == uid and len(c.get("/api/chat/threads").json()["threads"]) == 1
