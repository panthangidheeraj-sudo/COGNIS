"""HTTP client: retry policy, classification, budget enforcement and cache semantics."""
from __future__ import annotations

import asyncio

import httpx

from app.net.http import HttpClient
from app.runtime.budgets import BudgetLimits, CompanyBudget, RunBudget
from app.storage.cache import ResponseCache
from app.storage.db import Database


def _client(handler, **kw) -> HttpClient:  # noqa: ANN001
    return HttpClient(transport=httpx.MockTransport(handler), sleep=lambda _s: asyncio.sleep(0), **kw)


def _fetch(handler, url: str = "https://api.example.no/x", **kw):  # noqa: ANN001, ANN202
    budget = kw.pop("budget", None)
    cache = kw.pop("cache", None)

    async def go():  # noqa: ANN202
        async with _client(handler, cache=cache) as http:
            return await http.fetch(url, connector="test", budget=budget, **kw)

    return asyncio.run(go())


def test_retries_429_then_succeeds() -> None:
    calls = []

    def handler(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": "0"}) if len(calls) == 1 else httpx.Response(200, json={"ok": True})

    res = _fetch(handler, expect="json")
    assert res.ok and res.retries == 1 and len(calls) == 2


def test_retry_after_longer_than_budget_is_not_waited_for() -> None:
    calls = []

    def handler(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": "3600"})

    res = _fetch(handler)
    assert res.classification == "rate_limited" and len(calls) == 1


def test_5xx_retried_bounded() -> None:
    calls = []

    def handler(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503)

    res = _fetch(handler)
    assert res.classification == "server_error" and len(calls) == 3  # 1 + RETRY_ATTEMPTS(2)


def test_client_errors_not_retried() -> None:
    for status, cls in ((400, "client_error"), (401, "blocked"), (403, "blocked"), (404, "not_found"), (410, "gone")):
        calls = []

        def handler(_r: httpx.Request, status: int = status, calls: list = calls) -> httpx.Response:
            calls.append(1)
            return httpx.Response(status)

        res = _fetch(handler)
        assert res.classification == cls and len(calls) == 1, status


def test_timeout_classified_and_retried() -> None:
    calls = []

    def handler(r: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=r)

    res = _fetch(handler)
    assert res.classification == "timeout" and len(calls) == 3


def test_budget_exhausted_sends_nothing() -> None:
    calls = []

    def handler(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200)

    run = RunBudget(BudgetLimits(max_requests=1))
    assert _fetch(handler, budget=run, optional=False).ok
    res = _fetch(handler, url="https://api.example.no/y", budget=run, optional=False)
    assert res.classification == "budget_exhausted" and len(calls) == 1


def test_optional_work_stops_at_headroom() -> None:
    run = RunBudget(BudgetLimits(max_requests=10, headroom=0.5))
    company = CompanyBudget(run, max_requests=100, max_seconds=60, max_llm_calls=2, max_searches=1)
    granted = sum(1 for _ in range(10) if company.reserve(connector="x", optional=True))
    assert granted == 5
    assert company.reserve(connector="x", optional=False)  # mandatory identity work may use the reserve


def test_cache_keeps_original_retrieval_time() -> None:
    db = Database(":memory:")
    cache = ResponseCache(db)
    calls = []

    def handler(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"n": len(calls)})

    first = _fetch(handler, cache=cache, expect="json", cache_ttl=3600)
    second = _fetch(handler, cache=cache, expect="json", cache_ttl=3600)
    assert len(calls) == 1
    assert second.from_cache and second.retrieved_at == first.retrieved_at and second.content_sha256 == first.content_sha256
    fresh = _fetch(handler, cache=cache, expect="json", use_cache=False)
    assert not fresh.from_cache and len(calls) == 2


def test_invalid_json_classified() -> None:
    res = _fetch(lambda _r: httpx.Response(200, text="<html>not json</html>", headers={"content-type": "text/html"}), expect="json")
    assert res.classification == "invalid_content"


def test_failed_post_is_never_cached_or_replayed() -> None:
    """A wrong model/key (404) on an LLM call must not be served from cache once the cause is fixed."""
    state = {"status": 404, "calls": 0}

    def handler(_r: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        return httpx.Response(state["status"], json={"error": {"message": "x"}} if state["status"] == 404 else {"ok": True})

    cache = ResponseCache(Database(":memory:"))

    async def go():  # noqa: ANN202
        async with _client(handler, cache=cache) as http:
            first = await http.fetch("https://api.example.no/chat", connector="llm", method="POST", json_body={"a": 1}, cache_ttl=3600, expect="json")
            state["status"] = 200
            second = await http.fetch("https://api.example.no/chat", connector="llm", method="POST", json_body={"a": 1}, cache_ttl=3600, expect="json")
            third = await http.fetch("https://api.example.no/chat", connector="llm", method="POST", json_body={"a": 1}, cache_ttl=3600, expect="json")
            return first, second, third

    first, second, third = asyncio.run(go())
    assert first.classification == "not_found" and second.ok and not second.from_cache
    assert third.ok and third.from_cache and state["calls"] == 2  # successes are still cached


def test_failed_paid_call_is_not_billed() -> None:
    budget = RunBudget(BudgetLimits(max_requests=10, max_cost_usd=1.0, max_runtime_seconds=60))

    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    res = _fetch(handler, method="POST", json_body={}, cost_usd=0.01, budget=budget)
    assert res.classification == "not_found"
    snap = budget.snapshot()
    assert snap["third_party_cost_usd"] == 0 and snap["requests"] == 1  # the request counts, the money does not


def test_provider_error_message_and_model_listing() -> None:
    from app.config import get_settings
    from app.errors import LLMOutputError
    from app.providers.openai_compat import OpenAICompatibleProvider

    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "llama-3.3-70b-versatile"}, {"id": "whisper-large-v3"}]})
        return httpx.Response(404, json={"error": {"message": "The model `nope` does not exist or you do not have access to it.", "code": "model_not_found"}})

    async def go():  # noqa: ANN202
        async with _client(handler) as http:
            prov = OpenAICompatibleProvider(name="groq", base_url="https://api.example.no/openai/v1", api_key="k", model="nope", http=http, settings=get_settings())
            try:
                await prov.chat([{"role": "user", "content": "hi"}], task="ping")
            except LLMOutputError as exc:
                return str(exc), await prov.list_models()
            raise AssertionError("expected an error")

    message, (ids, problem) = asyncio.run(go())
    assert "model_not_found" in message and "does not exist" in message
    assert ids == ["llama-3.3-70b-versatile", "whisper-large-v3"] and problem == ""


def test_reasoning_models_get_effort_settings_and_token_headroom() -> None:
    import json

    from app.config import get_settings
    from app.providers.openai_compat import OpenAICompatibleProvider

    seen: list[dict] = []

    def handler(r: httpx.Request) -> httpx.Response:
        body = json.loads(r.content)
        seen.append(body)
        if body["model"] == "vendor/picky" and "reasoning_effort" in body:
            return httpx.Response(400, json={"error": {"message": "unknown parameter"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}, "model": body["model"]})

    async def go():  # noqa: ANN202
        async with _client(handler) as http:
            for model in ("openai/gpt-oss-120b", "llama-3.1-8b-instant"):
                await OpenAICompatibleProvider(name="groq", base_url="https://api.example.no/v1", api_key="k", model=model, http=http, settings=get_settings()).chat(
                    [{"role": "user", "content": model}], max_tokens=60, json_mode=True)

    asyncio.run(go())
    gpt, plain = seen
    assert gpt["reasoning_effort"] == "low" and gpt["include_reasoning"] is False and gpt["max_tokens"] == 60 + 768 and gpt["response_format"] == {"type": "json_object"}
    assert "reasoning_effort" not in plain and plain["max_tokens"] == 60


def test_refused_reasoning_option_is_retried_without_it(monkeypatch) -> None:  # noqa: ANN001
    import json

    from app.config import get_settings
    from app.providers.openai_compat import OpenAICompatibleProvider

    calls: list[dict] = []

    def handler(r: httpx.Request) -> httpx.Response:
        body = json.loads(r.content)
        calls.append(body)
        if "include_reasoning" in body:
            return httpx.Response(400, json={"error": {"message": "unsupported"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}], "model": "openai/gpt-oss-120b"})

    async def go():  # noqa: ANN202
        async with _client(handler) as http:
            return await OpenAICompatibleProvider(name="groq", base_url="https://api.example.no/v1", api_key="k", model="openai/gpt-oss-120b", http=http,
                                                  settings=get_settings()).chat([{"role": "user", "content": "x"}], json_mode=True)

    res = asyncio.run(go())
    assert res.text == "{}" and len(calls) == 2 and "include_reasoning" not in calls[1]


def test_refused_model_stops_further_llm_calls_in_the_run() -> None:
    from app.config import get_settings
    from app.errors import LLMOutputError
    from app.providers.openai_compat import OpenAICompatibleProvider

    calls: list[int] = []

    def handler(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404, json={"error": {"message": "The model `x` does not exist", "code": "model_not_found"}})

    async def go():  # noqa: ANN202
        errors = []
        async with _client(handler) as http:
            prov = OpenAICompatibleProvider(name="groq", base_url="https://api.example.no/v1", api_key="k", model="x", http=http, settings=get_settings())
            for i in range(3):
                try:
                    await prov.chat([{"role": "user", "content": str(i)}])
                except LLMOutputError as exc:
                    errors.append(str(exc))
        return errors

    errors = asyncio.run(go())
    assert len(calls) == 1 and len(errors) == 3
    assert "model_not_found" in errors[0] and "skipped" in errors[1] and "GROQ_MODEL" in errors[2]
