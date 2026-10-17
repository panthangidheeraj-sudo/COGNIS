"""One conversation = one thread on the server, however many messages it holds. Several consecutive messages (including the exact question that used to switch the
company to "INCLUDE" and open a new conversation) stay in the same thread, keep its company and history, and are restored when the thread is loaded again."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.testing.fixtures import FixtureNetwork
from tests.test_chat_company_context import EQUINOR, EQUINOR_QUESTION, INCLUDE, Spy, register_equinor
from tests.test_regulatory_and_chat import CapturingProvider, make_client


@pytest.fixture
def equinor_client(net: FixtureNetwork, settings: Settings, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    register_equinor(net)
    client, svc = make_client(net, settings, CapturingProvider(None))
    spy = Spy()
    monkeypatch.setattr(svc, "resolve_query", spy)
    with client as c:
        yield c, svc, spy


@pytest.mark.parametrize("stream", [False, True])
def test_three_consecutive_messages_share_one_thread_and_are_restored(equinor_client, stream: bool) -> None:  # noqa: ANN001
    c, svc, spy = equinor_client
    created = c.post("/api/chat/threads", json={"id": "thread-keep-0001"}).json()
    assert created["id"] == "thread-keep-0001"
    questions = [EQUINOR, EQUINOR_QUESTION, "What is the equity?"]  # the organisation number, then the exact question that used to hop to INCLUDE, then a follow-up
    for q in questions:
        path = "/api/chat/threads/thread-keep-0001/ask" + ("/stream" if stream else "")
        r = c.post(path, json={"question": q})
        assert r.status_code == 200
        assert "event: error" not in r.text
        if not stream:
            body = r.json()
            assert body["threadId"] == "thread-keep-0001" and "switchedFromThreadId" not in body
            assert body["thread"]["company"]["orgNumber"] == EQUINOR

    listed = c.get("/api/chat/threads").json()["threads"]
    assert [t["id"] for t in listed] == ["thread-keep-0001"]  # one conversation, not one per message
    assert listed[0]["company"]["orgNumber"] == EQUINOR and listed[0]["messageCount"] == 6
    assert INCLUDE not in str(listed) and spy.queries == []

    # "reload": the stored thread alone gives the full history, in order, with the same company
    again = c.get("/api/chat/threads/thread-keep-0001").json()
    assert [m["content"] for m in again["messages"] if m["role"] == "user"] == questions
    assert [m["role"] for m in again["messages"]] == ["user", "assistant"] * 3
    assert again["company"]["orgNumber"] == EQUINOR
    # and the model of the next turn would see these earlier turns, not another conversation's
    history = svc.chat_threads.history_for("thread-keep-0001", max_messages=20, max_chars=1500)
    assert [m["content"] for m in history if m["role"] == "user"] == questions


def test_a_thread_started_with_only_a_number_keeps_its_id_across_answers(equinor_client) -> None:  # noqa: ANN001
    c, _, _ = equinor_client
    c.post("/api/chat/threads", json={"id": "thread-keep-0002"})
    first = c.post("/api/chat/threads/thread-keep-0002/ask", json={"question": EQUINOR}).json()
    second = c.post("/api/chat/threads/thread-keep-0002/ask", json={"question": EQUINOR_QUESTION}).json()
    assert first["threadId"] == second["threadId"] == "thread-keep-0002"
    assert len(c.get("/api/chat/threads").json()["threads"]) == 1


def test_creating_the_same_thread_twice_returns_the_same_thread(equinor_client) -> None:  # noqa: ANN001
    c, _, _ = equinor_client
    a = c.post("/api/chat/threads", json={"id": "thread-keep-0003"}).json()
    b = c.post("/api/chat/threads", json={"id": "thread-keep-0003"}).json()
    assert a["id"] == b["id"] and len(c.get("/api/chat/threads").json()["threads"]) == 1
