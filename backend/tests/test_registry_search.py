"""Enhetsregisteret company search: the real failure is reported, transient failures are retried, and Data Sheets can continue (explicitly, and
labelled) from companies COGNIS has already verified. Nothing is invented and a failed search never looks like an empty or successful one."""
from __future__ import annotations

import asyncio
import logging
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.connectors import brreg
from app.net.http import FetchResult, HttpClient
from app.storage import repository as repo

SEARCH = "https://data.brreg.no/enhetsregisteret/api/enheter?"
AUTO, BJORN, SANDNES = "810359862", "810363142", "810034882"  # two in Oslo, one in Sandnes (offline fixtures)
OSLO = {"key": "municipality", "label": "Municipality", "value": "Oslo", "display": "Oslo"}


@dataclass
class App:
    client: TestClient
    svc: Any
    net: Any
    settings: Any

    def searches(self) -> list[str]:
        return [u for u in self.net.requests if u.startswith(SEARCH)]

    def store(self, *orgs: str) -> None:
        """Verify companies the normal way (a registry lookup), so they are stored exactly as in real use."""
        for org in orgs:
            assert self.client.get(f"/api/companies/{org}").status_code == 200

    def sheets(self) -> list[dict]:
        return self.client.get("/api/sheets").json()


@pytest.fixture
def app(net, settings):  # noqa: ANN001, ANN201
    from app.api.main import create_app
    from app.api.services import Services
    from app.providers.fake_provider import FakeProvider
    from app.storage.db import Database

    svc = Services(settings, db=Database(":memory:"), transport=net.transport(), provider=FakeProvider(), use_provider=True)
    with TestClient(create_app(svc)) as c:
        yield App(c, svc, net, settings)


def _create(app: App, **extra: Any) -> httpx.Response:
    return app.client.post("/api/sheets", json={"title": "Test", "criteria": [], "text": "AUTOBJ", **extra})


# ----------------------------------------------------------------- retries --
def test_transient_server_errors_are_retried_until_the_register_answers(app: App) -> None:
    app.net.fail(SEARCH, "503", times=2)
    res = _create(app)
    assert res.status_code == 200 and res.json()["rowCount"] == 1
    assert len(app.searches()) == 3  # two failures + the success
    assert "discovery" not in res.json()  # a retried search is an ordinary registry search


def test_a_timeout_that_clears_is_retried(app: App) -> None:
    app.net.fail(SEARCH, "timeout", times=1)
    assert _create(app).status_code == 200 and len(app.searches()) == 2


def test_rate_limiting_is_retried_and_honours_retry_after(app: App) -> None:
    app.net.fail(SEARCH, "429", times=1)  # the fixture answers Retry-After: 0
    assert _create(app).status_code == 200 and len(app.searches()) == 2


def test_the_number_of_retries_is_configurable(app: App) -> None:
    app.settings.registry_search_retries = 1
    app.net.fail(SEARCH, "503")
    res = _create(app)
    assert res.status_code == 503 and res.json()["details"]["attempts"] == 2 and len(app.searches()) == 2


# -------------------------------------------------- the real cause is shown --
def test_a_persistent_server_error_reports_status_attempts_and_cause(app: App) -> None:
    app.net.fail(SEARCH, "503")
    res = _create(app)
    body = res.json()
    assert res.status_code == 503 and body["code"] == "unavailable"
    d = body["details"]
    assert d["reason"] == "server_error" and d["httpStatus"] == 503 and d["retryable"] is True
    assert d["attempts"] == app.settings.registry_search_retries + 1 == len(app.searches())
    assert "HTTP 503" in body["message"] and body["message"] != "Company search in Enhetsregisteret is unavailable right now."
    assert d["source"] == "enhetsregisteret" and isinstance(d["elapsedMs"], int)
    assert app.sheets() == []  # a failed search creates no sheet and no rows


def test_a_timeout_is_named_as_a_timeout(app: App) -> None:
    app.net.fail(SEARCH, "timeout")
    d = _create(app).json()["details"]
    assert d["reason"] == "timeout" and "did not answer in time" in d["cause"] and "ReadTimeout" in d["detail"]


def test_tls_and_dns_failures_are_told_apart(app: App) -> None:
    app.net.fail(SEARCH, "tls")
    tls = _create(app).json()["details"]
    assert tls["reason"] == "network" and "certificate" in tls["cause"].lower() and "CERTIFICATE_VERIFY_FAILED" in tls["detail"]
    app.net.clear_failures()
    app.net.fail(SEARCH, "dns")
    dns = _create(app).json()["details"]
    assert "could not be resolved" in dns["cause"] and "getaddrinfo" in dns["detail"]


def test_a_rejected_request_is_not_retried_and_quotes_the_registers_message(app: App) -> None:
    app.net.fail(SEARCH, "400")
    res = _create(app)
    d = res.json()["details"]
    assert d["reason"] == "client_error" and d["httpStatus"] == 400 and d["retryable"] is False and d["attempts"] == 1
    assert "Invalid value for parameter fraAntallAnsatte" in d["cause"] and "Invalid value for parameter fraAntallAnsatte" in res.json()["message"]
    assert len(app.searches()) == 1  # retrying a request the register rejected can only fail again


def test_an_access_refusal_is_reported_as_such_and_not_retried(app: App) -> None:
    app.net.fail(SEARCH, "403")
    d = _create(app).json()["details"]
    assert d["reason"] == "blocked" and d["retryable"] is False and "does not bypass access controls" in d["cause"] and len(app.searches()) == 1


def test_a_web_page_instead_of_json_is_reported(app: App) -> None:
    app.net.fail(SEARCH, "html")
    d = _create(app).json()["details"]
    assert d["reason"] == "invalid_content" and "not valid JSON" in d["cause"] and "text/html" in d["cause"]


def test_json_in_the_wrong_shape_is_a_failure_not_an_empty_result(app: App) -> None:
    app.net.fail(SEARCH, "badshape")
    res = _create(app)
    assert res.status_code == 503 and res.json()["details"]["reason"] == "unexpected_response" and app.sheets() == []


def test_an_empty_answer_from_a_working_register_is_still_success(app: App) -> None:
    res = app.client.post("/api/companies/discover", json={"text": "zzzz-no-such-company", "filters": {}, "page": 1, "pageSize": 10})
    assert res.status_code == 200 and res.json()["items"] == [] and res.json()["total"] == 0 and "source" not in res.json()


def test_a_failure_is_not_cached_so_a_retry_reaches_the_register_again(app: App) -> None:
    app.net.fail(SEARCH, "503")
    assert _create(app).status_code == 503
    app.net.clear_failures()
    again = _create(app)
    assert again.status_code == 200 and again.json()["rowCount"] == 1


def test_the_failure_is_logged_with_its_cause(app: App) -> None:
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    log = logging.getLogger("cognis.services")
    handler = Capture()
    log.addHandler(handler)
    try:
        app.net.fail(SEARCH, "503")
        _create(app)
    finally:
        log.removeHandler(handler)
    hits = [r for r in records if r.getMessage() == "enhetsregisteret search failed"]
    assert hits and hits[0].levelno == logging.WARNING
    ctx = hits[0].ctx  # type: ignore[attr-defined]
    assert ctx["reason"] == "server_error" and ctx["http_status"] == 503 and ctx["attempts"] == app.settings.registry_search_retries + 1
    assert "navn" in ctx["params"] and "key" not in str(ctx).lower().replace("kommunenummer", "")


def test_an_overlong_name_search_is_shortened_instead_of_rejected(app: App) -> None:
    long_text = " ".join(["AUTOBJ"] * 80)  # 559 characters; the register takes at most 180
    res = app.client.post("/api/companies/discover", json={"text": long_text, "filters": {}, "page": 1, "pageSize": 5})
    assert res.status_code == 200
    navn = urllib.parse.parse_qs(urllib.parse.urlsplit(app.searches()[-1]).query)["navn"][0]
    assert 0 < len(navn) <= 180


# --------------------------------------------------------------- fallback --
def test_nothing_to_fall_back_to_is_said_plainly(app: App) -> None:
    app.net.fail(SEARCH, "503")
    d = _create(app, fallback="verified").json()["details"]
    assert d["fallback"]["available"] is False and d["fallback"]["count"] == 0 and "not verified any companies" in d["fallback"]["note"]
    assert app.sheets() == []


def test_the_error_offers_the_fallback_but_does_not_apply_it_unasked(app: App) -> None:
    app.store(AUTO, BJORN)
    app.net.fail(SEARCH, "503")
    res = _create(app, criteria=[OSLO])
    d = res.json()["details"]
    assert res.status_code == 503 and d["fallback"]["available"] is True and d["fallback"]["count"] == 2
    assert app.sheets() == []  # opt-in only: a failed search does not quietly turn into a different list


def test_fallback_builds_the_sheet_from_verified_companies_only_and_says_so(app: App) -> None:
    app.store(AUTO, BJORN, SANDNES)
    app.net.fail(SEARCH, "503")
    res = _create(app, criteria=[OSLO], fallback="verified")
    assert res.status_code == 200, res.text
    summary = res.json()
    assert summary["rowCount"] == 2 and summary["description"].startswith("Enhetsregisteret search was unavailable")
    disc = summary["discovery"]
    assert disc["kind"] == "verified_companies" and disc["registryAvailable"] is False and disc["reason"] == "server_error" and disc["count"] == 2
    assert disc["at"] and "not a full register search" in disc["note"]
    assert len(app.searches()) == 1  # one quick attempt, no waiting out the retries again
    sheet = app.client.get(f"/api/sheets/{summary['id']}").json()
    assert {r["company"]["orgNumber"] for r in sheet["rows"]} == {AUTO, BJORN}  # Sandnes does not match the Oslo criterion
    stored = {r["org_number"] for r in app.svc.db.all("SELECT org_number FROM companies")}
    assert {r["company"]["orgNumber"] for r in sheet["rows"]} <= stored  # every row is a company COGNIS really holds
    assert app.client.get("/api/sheets").json()[0]["discovery"]["kind"] == "verified_companies"


def test_fallback_rows_keep_the_time_their_data_was_really_retrieved(app: App) -> None:
    app.store(AUTO)
    completed = repo.latest_record(app.svc.db, AUTO)["completed_at"]
    app.net.fail(SEARCH, "503")
    sheet = app.client.get(f"/api/sheets/{_create(app, fallback='verified').json()['id']}").json()
    cell = sheet["rows"][0]["cells"]["company"]
    assert cell["evidence"][0]["retrievedAt"] == completed and cell["updatedAt"] == completed
    assert "stored copy" in cell["evidence"][0]["excerpt"] and cell["status"] == "verified"
    assert sheet["rows"][0]["cells"]["revenue"]["status"] == "pending"  # nothing beyond what is stored is claimed


def test_fallback_applies_the_selected_filters_and_never_widens_them(app: App) -> None:
    app.store(AUTO, BJORN, SANDNES)
    app.net.fail(SEARCH, "503")
    sandnes = {"key": "municipality", "label": "Municipality", "value": "Sandnes", "display": "Sandnes"}
    only = app.client.get(f"/api/sheets/{_create(app, criteria=[sandnes], fallback='verified').json()['id']}").json()
    assert [r["company"]["orgNumber"] for r in only["rows"]] == [SANDNES]
    big = {"key": "employeesMin", "label": "Employees", "value": 5000, "display": "5000+"}
    none = _create(app, criteria=[big], fallback="verified")
    d = none.json()["details"]
    assert none.status_code == 503 and d["fallback"]["available"] is False and "None of the 3 companies" in d["fallback"]["note"]
    small = {"key": "employeesMin", "label": "Employees", "value": 12, "display": "12+"}
    ok = app.client.get(f"/api/sheets/{_create(app, criteria=[small], fallback='verified').json()['id']}").json()
    assert [r["company"]["orgNumber"] for r in ok["rows"]] == [AUTO]  # 12 employees; the 11-employee company and unknowns stay out


def test_fallback_does_not_repeat_a_failure_the_server_just_saw(app: App) -> None:
    app.store(AUTO)
    app.net.fail(SEARCH, "503")
    assert _create(app).status_code == 503
    seen = len(app.searches())
    res = _create(app, fallback="verified")
    assert res.status_code == 200 and len(app.searches()) == seen  # no second wait through the same timeouts
    assert res.json()["discovery"]["reason"] == "server_error"


def test_a_working_register_is_always_preferred_over_the_fallback(app: App) -> None:
    app.store(AUTO)
    res = _create(app, fallback="verified")  # opted in, but the register answers
    assert res.status_code == 200 and "discovery" not in res.json() and len(app.searches()) == 1


def test_the_fallback_is_never_taken_on_the_clients_word_alone(app: App) -> None:
    app.store(AUTO)  # the register is healthy: a client claiming otherwise changes nothing
    res = _create(app, fallback="verified", discovery={"kind": "verified_companies", "registryAvailable": False})
    assert res.status_code == 200 and "discovery" not in res.json()


def test_discover_reports_its_source_when_it_falls_back(app: App) -> None:
    app.store(AUTO, BJORN)
    app.net.fail(SEARCH, "503")
    res = app.client.post("/api/companies/discover", json={"filters": {"municipality": "Oslo"}, "fallback": "verified", "page": 1, "pageSize": 20})
    body = res.json()
    assert res.status_code == 200 and body["total"] == 2 and body["source"]["kind"] == "verified_companies"
    assert all(i["verifiedAt"] for i in body["items"])
    plain = app.client.post("/api/companies/discover", json={"filters": {"municipality": "Oslo"}, "page": 1, "pageSize": 20})
    assert plain.status_code == 503 and plain.json()["details"]["fallback"]["count"] == 2


def test_lookups_of_a_single_company_are_unaffected(app: App) -> None:
    app.net.fail(SEARCH, "503")  # only the search endpoint is down
    assert app.client.get(f"/api/companies/{AUTO}").status_code == 200


# ----------------------------------------------- connector and HTTP layer --
def _result(status: int, classification: str, *, body: bytes = b"", error: str | None = None, retries: int = 0, ctype: str = "application/json") -> FetchResult:
    return FetchResult("u", "u", status, classification, body=body, content_type=ctype, error=error, retries=retries)  # type: ignore[arg-type]


def test_describe_failure_covers_every_class() -> None:
    cases = {
        "rate_limited": _result(429, "rate_limited", retries=3),
        "blocked": _result(401, "blocked"),
        "unsafe_url": _result(0, "unsafe_url", error="host does not resolve: data.brreg.no"),
        "budget_exhausted": _result(0, "budget_exhausted", error="budget exhausted"),
        "too_large": _result(200, "too_large"),
        "weird": _result(418, "weird"),
    }
    out = {k: brreg.describe_failure(v) for k, v in cases.items()}
    assert out["rate_limited"].retryable and out["rate_limited"].attempts == 4 and "429" in out["rate_limited"].cause
    assert not out["blocked"].retryable and out["blocked"].http_status == 401
    assert out["unsafe_url"].retryable and "does not resolve" in out["unsafe_url"].cause
    assert not out["budget_exhausted"].retryable and not out["too_large"].retryable
    assert out["weird"].kind == "weird" and "418" in out["weird"].cause and not out["weird"].retryable


def test_describe_failure_quotes_html_error_pages_without_markup_or_secrets() -> None:
    page = b"<html><body><h1>Bad gateway</h1><p>token=abc123secretvalue</p></body></html>"
    f = brreg.describe_failure(_result(400, "client_error", body=page, ctype="text/html", error="HTTP 400"))
    assert "Bad gateway" in f.cause and "<" not in f.cause and "abc123secretvalue" not in f.cause


def test_the_retry_count_can_be_set_per_request() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, text="down")

    async def go(retries: int | None) -> FetchResult:
        async with HttpClient(transport=httpx.MockTransport(handler), sleep=lambda _s: asyncio.sleep(0)) as http:
            return await http.fetch("https://data.brreg.no/enhetsregisteret/api/enheter", connector="brreg_search", retry_attempts=retries, use_cache=False)

    assert asyncio.run(go(0)).retries == 0 and len(calls) == 1
    calls.clear()
    assert asyncio.run(go(4)).retries == 4 and len(calls) == 5


def test_transport_errors_keep_their_underlying_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[Errno 11001] getaddrinfo failed", request=request)

    async def go() -> FetchResult:
        async with HttpClient(transport=httpx.MockTransport(handler), sleep=lambda _s: asyncio.sleep(0)) as http:
            return await http.fetch("https://data.brreg.no/x", connector="brreg_search", retry_attempts=0, use_cache=False)

    res = asyncio.run(go())
    assert res.classification == "network" and "ConnectError" in (res.error or "") and "getaddrinfo failed" in (res.error or "")
