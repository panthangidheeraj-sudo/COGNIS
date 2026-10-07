"""URL safety (SSRF), redirects, secret redaction and secret-leak checks."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest

from app.errors import UnsafeUrlError
from app.net.http import HttpClient
from app.security.redaction import contains_secret, redact, redact_headers
from app.security.urls import check_resolved_host, check_url_syntax

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("url", [
    "http://localhost/admin", "http://127.0.0.1/", "http://10.0.0.5/", "http://192.168.1.1/", "http://172.16.0.1/", "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/", "http://metadata.google.internal/", "file:///etc/passwd", "ftp://example.com/", "gopher://example.com/", "http://user:pass@example.com/",
    "http://example.com:22/", "http://intranet/", "http://printer.local/", "http://100.64.1.1/", "javascript:alert(1)", "http://0.0.0.0/",
])
def test_unsafe_urls_rejected(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        check_url_syntax(url)


@pytest.mark.parametrize("url", ["https://www.brreg.no/", "https://data.brreg.no/enhetsregisteret/api/enheter/810359862", "http://example.no:8080/x"])
def test_public_urls_allowed(url: str) -> None:
    check_url_syntax(url)


def test_dns_to_private_address_rejected() -> None:
    async def resolver(_host: str) -> list[str]:
        return ["93.184.216.34", "10.1.2.3"]  # one private address is enough to refuse

    with pytest.raises(UnsafeUrlError):
        asyncio.run(check_resolved_host("rebind.example.com", resolver))


def test_redirect_to_private_address_is_refused() -> None:
    """A public page redirecting to an internal address must not be followed (re-checked per hop)."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "public.example.no":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
        return httpx.Response(200, text="secret metadata")

    async def go() -> object:
        async with HttpClient(transport=httpx.MockTransport(handler)) as http:
            return await http.fetch("https://public.example.no/", connector="test")

    res = asyncio.run(go())
    assert res.classification == "unsafe_url"
    assert all("169.254" not in u for u in seen)


def test_response_size_limit() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 50_000, headers={"content-type": "text/html"})

    async def go() -> object:
        async with HttpClient(transport=httpx.MockTransport(handler)) as http:
            return await http.fetch("https://big.example.no/", connector="test", max_bytes=10_000)

    assert asyncio.run(go()).classification == "too_large"


def test_redaction() -> None:
    text = "GET https://x.no/?api_key=abc123secret&q=1 Authorization: Bearer abcdefghijklmnop gsk_ABCDEFGHIJKLMNOPQRSTUV"
    out = redact(text)
    assert "abc123secret" not in out and "abcdefghijklmnop" not in out and "gsk_ABCDEFGHIJKLMNOPQRSTUV" not in out
    assert redact_headers({"Authorization": "Bearer x", "X-Subscription-Token": "t", "Accept": "a"}) == {"Authorization": "[REDACTED]", "X-Subscription-Token": "[REDACTED]",
                                                                                                    "Accept": "a"}


def test_env_example_has_placeholders_only() -> None:
    text = (BACKEND / ".env.example").read_text(encoding="utf-8")
    assert not contains_secret(text)
    for line in text.splitlines():
        if line.strip().startswith(("GROQ_API_KEY=", "TAVILY_API_KEY=", "LLM_API_KEY=", "PROFF_API_KEY=", "DOFFIN_API_KEY=")):
            assert line.split("=", 1)[1].strip() in ("", "your-key-here", "replace-me"), line


def test_no_secret_reaches_logs_db_or_records(settings, net, caplog) -> None:  # noqa: ANN001
    """With a (fake) Groq key configured, the key never appears in logs, stored tool calls, records or envelopes."""
    from app.agent.orchestrator import Orchestrator, ResearchOptions
    from app.competition.envelope import build_envelope
    from app.config import override_settings
    from app.providers.openai_compat import OpenAICompatibleProvider
    from app.runtime.budgets import BudgetLimits, RunBudget
    from app.storage import repository as repo
    from app.storage.db import Database

    key = "gsk_TESTSECRETKEY0123456789abcdef"
    s = settings.model_copy(update={"llm_provider": "groq", "groq_api_key": key, "groq_model": "test-model"})
    override_settings(s)
    seen_auth: list[str] = []

    def llm(request: httpx.Request) -> httpx.Response | None:
        if request.url.host == "api.groq.com":
            seen_auth.append(request.headers.get("authorization", ""))
            return httpx.Response(500, json={"error": {"message": f"echo {request.headers.get('authorization')}"}})
        return None

    net.handlers.append(llm)
    db = Database(":memory:")

    async def go() -> dict:
        async with HttpClient(transport=net.transport(), recorder=repo.tool_call_recorder(db), sleep=lambda _s: asyncio.sleep(0)) as http:
            provider = OpenAICompatibleProvider(name="groq", base_url=s.groq_base_url, api_key=key, model="test-model", http=http, settings=s)
            orch = Orchestrator(http=http, run_budget=RunBudget(BudgetLimits(max_requests=200)), provider=provider, settings=s)
            return await orch.research("810359862", run_id="leak", options=ResearchOptions(mode="deep", include_geo=False))

    net.add_site("autobjorn.no", __import__("app.testing.fixtures", fromlist=["verified_site"]).verified_site("AUTOBJØRN A/S", "810359862"))
    with caplog.at_level(logging.DEBUG):
        record = asyncio.run(go())
    repo.save_record(db, record)
    assert seen_auth and seen_auth[0] == f"Bearer {key}"  # the key is sent to the provider…
    blob = json.dumps(record) + json.dumps(build_envelope(record, run_id="leak")) + caplog.text
    blob += json.dumps([dict(r) for r in db.all("SELECT * FROM tool_calls")]) + json.dumps([dict(r) for r in db.all("SELECT research_json FROM profile_versions")])
    assert key not in blob  # …and nowhere else
