"""Tavily search connector: request shape, parsing, fallbacks, run-level circuit breaker, secret handling."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from app.config import get_settings, override_settings
from app.connectors.base import ConnectorContext
from app.connectors.search import NON_COMPANY_DOMAINS, web_search
from app.net.http import HttpClient
from app.runtime.budgets import unlimited_budget
from app.security.redaction import contains_secret, redact

KEY = "tvly-test-key-0000000000"


def _search(handler, *, key: str | None = KEY, calls: int = 1, query: str = '"923609016"'):  # noqa: ANN001, ANN202
    settings = get_settings().model_copy(update={"tavily_api_key": key})
    override_settings(settings)

    async def go():  # noqa: ANN202
        async with HttpClient(transport=httpx.MockTransport(handler), sleep=lambda _s: asyncio.sleep(0)) as http:
            ctx = ConnectorContext(org_number="923609016", http=http, budget=unlimited_budget(), run_id="t", settings=settings, fresh=True)
            return [await web_search(ctx, f"{query} {i}") for i in range(calls)], http

    return asyncio.run(go())


def test_request_shape_and_parsing() -> None:
    seen: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        return httpx.Response(200, json={"results": [{"title": "Equinor", "url": "https://www.equinor.com/", "content": "Energy", "score": 0.93},
                                                     {"title": "No url", "content": "x"}], "usage": {"credits": 1}})

    [(mod, hits)], _ = _search(handler)
    req = seen[0]
    body = json.loads(req.content)
    assert req.method == "POST" and str(req.url) == "https://api.tavily.com/search"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert body["search_depth"] == "basic" and body["include_raw_content"] is False and body["include_answer"] is False
    assert body["country"] == "norway" and "proff.no" in body["exclude_domains"] and len(body["exclude_domains"]) <= 150
    assert mod.state == "available" and mod.value["credits"] == 1
    assert [h.url for h in hits] == ["https://www.equinor.com/"] and hits[0].domain == "equinor.com" and hits[0].score == 0.93


def test_optional_parameters_are_dropped_when_rejected() -> None:
    bodies: list[dict] = []

    def handler(r: httpx.Request) -> httpx.Response:
        body = json.loads(r.content)
        bodies.append(body)
        if "country" in body:
            return httpx.Response(422, json={"detail": {"error": "invalid country"}})
        return httpx.Response(200, json={"results": [{"title": "A", "url": "https://a.no/", "content": ""}]})

    [(mod, hits)], _ = _search(handler)
    assert len(bodies) == 2 and "country" not in bodies[1] and "exclude_domains" not in bodies[1] and bodies[1]["query"] == bodies[0]["query"]
    assert mod.state == "available" and len(hits) == 1


def test_invalid_key_stops_further_searches_in_the_run() -> None:
    calls: list[int] = []

    def handler(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401, json={"detail": {"error": "Unauthorized: missing or invalid API key."}})

    results, http = _search(handler, calls=3)
    assert len(calls) == 1  # the 2nd and 3rd search never reach the network
    assert results[0][0].state == "blocked" and "401" in (results[0][0].note or "")
    assert results[2][0].state == "blocked" and "TAVILY_API_KEY" in (results[2][0].note or "") and "search" in http.tripped


def test_plan_limit_pauses_search_without_retrying() -> None:
    calls: list[int] = []

    def handler(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(432, json={"detail": {"error": "plan limit"}})

    results, _ = _search(handler, calls=2)
    assert len(calls) == 1 and "credit limit" in (results[0][0].note or "") and results[1][0].state == "blocked"


def test_no_key_means_search_is_off() -> None:
    results, _ = _search(lambda _r: httpx.Response(500), key=None)
    assert results[0][0].state == "not_applicable" and "TAVILY_API_KEY" in (results[0][0].note or "") and results[0][1] == []


def test_tavily_key_is_redacted_everywhere() -> None:
    override_settings(get_settings().model_copy(update={"tavily_api_key": KEY}))
    assert KEY not in redact(f"Authorization: Bearer {KEY} and key={KEY}")
    assert contains_secret(f"x {KEY} y")
    assert "tvly-abcdefghijklmnop" not in redact("tvly-abcdefghijklmnop")  # key-shaped tokens are scrubbed even when not configured


def test_directory_list_fits_tavily_limit() -> None:
    assert len(NON_COMPANY_DOMAINS) <= 150


def _hit(title: str, url: str, desc: str = ""):  # noqa: ANN202
    from app.connectors.search import SearchHit

    return SearchHit(title, url, desc, 1, "q")


def test_prescreen_keeps_only_hits_that_name_the_company() -> None:
    from app.connectors.search import hit_matches_company

    name = "ARKITEKTFIRMA JON VIKØREN AS"
    assert hit_matches_company(_hit("Arkitektfirma Jon Vikøren AS – Hjem", "https://arkjv.no/"), name)  # full name in the title
    assert hit_matches_company(_hit("Kontakt oss", "https://vikoren-arkitekt.no/"), name)  # distinctive word inside the domain
    assert hit_matches_company(_hit("Jon Vikøren, arkitektfirma i Vik", "https://example.no/"), name)  # all distinctive words in the snippet
    assert not hit_matches_company(_hit("Sodir - Norwegian Offshore Directorate", "https://www.sodir.no/", "Oil and gas"), "LILLENES MASKIN AS")
    assert not hit_matches_company(_hit("Anything at all", "https://example.no/"), "HOLDING AS")  # nothing distinctive to match on


def test_unrelated_search_hits_are_not_fetched_and_are_reported(net, settings) -> None:  # noqa: ANN001
    from conftest import research, run

    from app.competition.envelope import build_envelope

    AUTO = "810359862"
    override_settings(settings.model_copy(update={"tavily_api_key": KEY}))
    entity = json.loads((Path(__file__).parent / "fixtures" / "brreg" / f"{AUTO}_enhet.json").read_text(encoding="utf-8"))
    entity.pop("hjemmeside", None)
    entity.pop("epostadresse", None)
    net.add_json(f"https://data.brreg.no/enhetsregisteret/api/enheter/{AUTO}", entity)

    def tavily(request: httpx.Request) -> httpx.Response | None:
        if request.url.host != "api.tavily.com":
            return None
        return httpx.Response(200, json={"results": [{"url": "https://totally-unrelated-example.no/", "title": "Garden tools", "content": "Spades and rakes", "score": 0.5}]})

    net.handlers.append(tavily)
    rec = run(research(net, AUTO))
    assert not any("totally-unrelated-example" in u for u in net.requests if "tavily" not in u)  # never fetched
    attempt = next(a for a in rec["site_attempts"] if a["domain"] == "totally-unrelated-example.no")
    assert attempt["decision"] == "screened_out" and attempt["origin"] == "search"
    assert "Web search found no result that names the company" in (rec["modules"]["website"].get("note") or "")
    env = build_envelope(rec, run_id="t")
    assert any(a["decision"] == "screened_out" for a in env["website_attempts"])
