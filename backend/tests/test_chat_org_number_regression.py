"""Regression: a thread with no company yet, asked with just an organisation number, failed with ``TypeError: 'set' object is not subscriptable``
(``org_numbers_in`` returns a set; ``_pick_company`` indexed it). The stream ended in "The answer could not be produced." and the log only said "TypeError".
Also: stream failures must be diagnosable from the log (code locations) without leaking secrets or values."""
from __future__ import annotations

import io
import json
import logging

import pytest

from app.config import Settings
from app.logging_setup import JsonFormatter
from app.testing.fixtures import FixtureNetwork
from tests.test_regulatory_and_chat import AUTO, OTHER, CapturingProvider, make_client


def events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        out.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))
    return out


@pytest.fixture
def client(net: FixtureNetwork, settings: Settings):  # noqa: ANN201
    c, svc = make_client(net, settings, CapturingProvider(None))
    with c as cc:
        yield cc, svc


@pytest.mark.parametrize("typed", [AUTO, "810 359 862", "Autobjørn, 810359862", "NO 810 359 862 MVA"])
def test_a_bare_organisation_number_selects_the_company_on_the_stream(client, typed: str) -> None:  # noqa: ANN001
    c, _ = client
    tid = c.post("/api/chat/threads", json={}).json()["id"]
    r = c.post(f"/api/chat/threads/{tid}/ask/stream", json={"question": typed})
    assert r.status_code == 200
    kinds = [e for e, _ in events(r.text)]
    assert kinds[-1] == "result" and "error" not in kinds, r.text
    assert (c.get(f"/api/chat/threads/{tid}").json()["company"] or {}).get("orgNumber") == AUTO  # the thread is now about that verified company


def test_the_same_number_works_without_streaming(client) -> None:  # noqa: ANN001
    c, _ = client
    tid = c.post("/api/chat/threads", json={}).json()["id"]
    r = c.post(f"/api/chat/threads/{tid}/ask", json={"question": AUTO})
    assert r.status_code == 200, r.text


def test_two_organisation_numbers_are_never_guessed(client) -> None:  # noqa: ANN001
    c, _ = client
    tid = c.post("/api/chat/threads", json={}).json()["id"]
    r = c.post(f"/api/chat/threads/{tid}/ask/stream", json={"question": f"{AUTO} and {OTHER}"})
    event, data = events(r.text)[-1]
    assert event == "result"
    reply = data["reply"] if "reply" in data else data
    text = json.dumps(reply)
    assert "more than one organisation number" in text and "clarification" in text
    assert c.get(f"/api/chat/threads/{tid}").json()["company"] is None  # no company was chosen for the user


def test_an_invalid_check_digit_is_reported_not_crashed(client) -> None:  # noqa: ANN001
    c, _ = client
    tid = c.post("/api/chat/threads", json={}).json()["id"]
    r = c.post(f"/api/chat/threads/{tid}/ask/stream", json={"question": "123456789"})
    assert [e for e, _ in events(r.text)][-1] == "result"


def test_a_failed_stream_logs_code_locations_but_no_secret_or_prompt(client, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    c, svc = client
    secret = "gsk_ABCDEFGHIJKLMNOPQRSTUVWX1234"

    async def boom(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        raise TypeError(f"bad operand while handling the prompt 'my private question' with key {secret}")

    monkeypatch.setattr(svc.chat_threads, "ask", boom)
    tid = c.post("/api/chat/threads", json={}).json()["id"]
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("cognis.api")
    logger.addHandler(handler)
    try:
        r = c.post(f"/api/chat/threads/{tid}/ask/stream", json={"question": "my private question"})
    finally:
        logger.removeHandler(handler)
    assert [e for e, _ in events(r.text)] == ["error"]
    line = next(json.loads(x) for x in buf.getvalue().splitlines() if "chat stream failed" in x)
    assert line["msg"] == "chat stream failed: TypeError"
    assert any("test_chat_org_number_regression.py" in w and "boom" in w for w in line["where"])  # where it happened
    assert secret not in buf.getvalue()  # redacted
    assert all(":\\" not in w and not w.startswith("/") for w in line["where"])  # locations only, no home-directory paths
