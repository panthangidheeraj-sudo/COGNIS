"""Discover enrichment: targeted, bounded lookups for the revenue, employees and openings a result card is missing.

Deterministic: the fixture network stands in for Enhetsregisteret, Regnskapsregisteret, NAV's feed and the company websites.
What is proved: values come only from the source that states them and pass the same gate as research; a missing value says *why* and is never a
zero; an unreachable source is "unavailable", never "none"; and the lookups stay bounded (batch size, concurrency, per-company time and request
caps, cache, no web search, no language model, nothing saved as research).
"""
from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from conftest import run
from fastapi.testclient import TestClient
from test_free_sources import network as nav_network
from test_hiring_data import settings_with

from app.api.main import create_app
from app.api.services import Services
from app.config import Settings
from app.connectors import nav
from app.identity.normalization import org_checksum_ok
from app.net.http import HttpClient
from app.providers.fake_provider import FakeProvider
from app.storage import repository as repo
from app.storage.db import Database
from app.testing.fixtures import FixtureNetwork, verified_site

AUTO = "810359862"
NAME = "AUTOBJØRN A/S"
ACCOUNTS = f"https://data.brreg.no/regnskapsregisteret/regnskap/{AUTO}"


def valid_org(start: int) -> str:
    n = start
    while not org_checksum_ok(str(n)):
        n += 1
    return str(n)


BARE = valid_org(912345670)  # a registered company with no website, no employee count and no filed accounts


class Delay(httpx.AsyncBaseTransport):
    """Adds a delay to requests for some hosts (a slow site) and records how many requests run at once."""

    def __init__(self, inner: httpx.AsyncBaseTransport, hosts: dict[str, float]) -> None:
        self.inner, self.hosts = inner, hosts

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        delay = self.hosts.get(request.url.host or "", 0.0)
        if delay:
            await asyncio.sleep(delay)
        return await self.inner.handle_async_request(request)


def build(settings: Settings, *, nav_synced: bool = False, site: dict[str, str] | None = None, slow: dict[str, float] | None = None) -> tuple[Any, Services, FixtureNetwork]:
    net = nav_network()[0] if nav_synced else FixtureNetwork()
    if not nav_synced:
        net.load_brreg_probes()
    net.add_site("autobjorn.no", site or verified_site(NAME, AUTO, jobs=["Bilselger", "Mekaniker"]))
    net.register_company(BARE, entity={"organisasjonsnummer": BARE, "navn": "TOMT TESTSELSKAP AS", "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
                                       "harRegistrertAntallAnsatte": False, "forretningsadresse": {"kommune": "OSLO", "kommunenummer": "0301"}})
    db = Database(":memory:")
    if nav_synced:  # the job-ad index is built from NAV's feed first, as in production
        async def sync() -> None:
            async with HttpClient(transport=net.transport(), sleep=lambda _s: asyncio.sleep(0)) as http:
                await nav.sync_feed(http, db, settings)
        run(sync())
    transport = net.transport() if not slow else Delay(net.transport(), slow)
    svc = Services(settings, db=db, transport=transport, provider=FakeProvider(), use_provider=True)
    return TestClient(create_app(svc)), svc, net


def enrich(client: TestClient, *orgs: str, **body: Any) -> dict[str, dict[str, Any]]:
    res = client.post("/api/companies/enrich", json={"orgNumbers": list(orgs), **body})
    assert res.status_code == 200, res.text
    return {item["orgNumber"]: item for item in res.json()["items"]}


@pytest.fixture
def api(settings: Settings):  # noqa: ANN201
    client, svc, net = build(settings)
    with client:
        yield SimpleNamespace(client=client, svc=svc, net=net)


# --------------------------------------------------------------------------------------------------------------- verified values --
def test_missing_card_figures_come_from_the_sources_that_state_them(api: Any) -> None:
    card = api.client.post("/api/companies/discover", json={"text": "AUTOBJØRN"}).json()["items"][0]
    assert card["orgNumber"] == AUTO and card["revenue"] is None and card["openPositions"] is None  # what the search pipeline itself verifies
    fields = enrich(api.client, AUTO)[AUTO]["fields"]

    rev = fields["revenue"]
    assert rev["state"] == "verified" and rev["currency"] == "NOK" and rev["period"] == "FY2025" and rev["value"] > 0
    assert rev["sources"] == [{"name": "Regnskapsregisteret", "state": "checked", "url": ACCOUNTS, "retrievedAt": rev["sources"][0]["retrievedAt"]}]
    assert "regnskapsperiode 2025-01-01–2025-12-31" in rev["evidence"] and "NOK" in rev["evidence"]  # the filing's own line, with its currency

    emp = fields["employees"]
    assert emp["state"] == "verified" and emp["value"] == 12 and emp["sources"][0]["name"] == "Enhetsregisteret"

    jobs = fields["openPositions"]
    assert jobs["state"] == "verified" and jobs["value"] == 2
    by = {s["name"]: s for s in jobs["sources"]}
    assert by["Company careers page"]["state"] == "checked" and by["Company careers page"]["url"].endswith("/karriere")
    assert by["NAV Arbeidsplassen"]["state"] == "not_checked" and jobs["lowerBound"] is True  # NAV was not checked, so "at least 2"
    assert "there may be more" in jobs["note"]


def test_the_enriched_revenue_is_exactly_what_research_publishes(api: Any) -> None:
    looked_up = enrich(api.client, AUTO)[AUTO]["fields"]["revenue"]
    run_ = api.client.post("/api/research/runs", json={"query": AUTO, "mode": "quick"}).json()
    with api.client.stream("GET", f"/api/research/runs/{run_['id']}/events?lastSeq=0") as stream:
        for line in stream.iter_lines():
            if line.startswith("data: ") and json.loads(line[6:])["type"] in ("run.completed", "run.failed"):
                break
    researched = api.client.get(f"/api/companies/{AUTO}").json()["company"]["revenue"]
    assert (looked_up["value"], looked_up["currency"], looked_up["period"]) == (researched["value"], researched["currency"], researched["period"])


def test_enrichment_is_not_research_and_saves_nothing(api: Any) -> None:
    enrich(api.client, AUTO, BARE)
    assert repo.latest_record(api.svc.db, AUTO) is None and repo.latest_record(api.svc.db, BARE) is None
    assert not [i for i in api.client.get("/api/library").json()["items"] if i.get("orgNumber") in (AUTO, BARE)]
    assert api.svc.provider.calls == 0  # no language model


def test_nav_ads_verified_to_this_organisation_are_counted_with_the_careers_page(settings: Settings) -> None:
    client, _svc, _net = build(settings, nav_synced=True)
    with client:
        limited = enrich(client, AUTO)[AUTO]["fields"]["openPositions"]
    by = {s["name"]: s for s in limited["sources"]}
    assert by["NAV Arbeidsplassen"]["state"] == "checked" and by["Company careers page"]["state"] == "checked"
    assert limited["state"] == "verified" and limited["value"] > 2  # NAV ads verified to this exact organisation are added (duplicates merged)
    # NAV names more candidate ads than the lookup reads by default: the count is then a lower bound, and the card says so
    assert limited["lowerBound"] is True and "could not be read within the lookup limit" in by["NAV Arbeidsplassen"]["note"]

    settings_with(settings, enrich_nav_max_reads=settings.nav_max_candidates_per_company)
    client, _svc, _net = build(settings, nav_synced=True)
    with client:
        full = enrich(client, AUTO)[AUTO]["fields"]["openPositions"]
    assert full["state"] == "verified" and full["value"] >= limited["value"] and "lowerBound" not in full  # every source fully checked


# ------------------------------------------------------------------------------------------------------------- honest absences --
def test_a_missing_value_says_why_and_is_never_a_zero(settings: Settings) -> None:
    client, _svc, _net = build(settings, nav_synced=True)
    with client:
        fields = enrich(client, BARE)[BARE]["fields"]
    for name in ("revenue", "employees", "openPositions"):
        assert "value" not in fields[name], name
    assert fields["revenue"]["state"] == "not_reported" and "not a revenue of zero" in fields["revenue"]["note"]
    assert fields["employees"]["state"] == "not_reported" and "not a verified zero" in fields["employees"]["note"]
    jobs = fields["openPositions"]
    assert jobs["state"] == "none_found" and "does not mean the company is not hiring" in jobs["note"]
    assert {s["name"]: s["state"] for s in jobs["sources"]} == {"NAV Arbeidsplassen": "checked", "Company careers page": "not_checked"}


def test_no_job_source_checked_is_not_checked_not_none(api: Any) -> None:
    jobs = enrich(api.client, BARE)[BARE]["fields"]["openPositions"]
    assert jobs["state"] == "not_checked" and "not evidence that the company has no openings" in jobs["note"]


# -------------------------------------------------------------------------------------------------------------- source failures --
def test_an_unreachable_register_of_accounts_is_unavailable_and_is_retried_after_a_short_wait(api: Any, settings: Settings) -> None:
    api.net.fail(ACCOUNTS, "503")
    rev = enrich(api.client, AUTO)[AUTO]["fields"]["revenue"]
    assert rev["state"] == "unavailable" and "says nothing about the company's revenue" in rev["note"] and "value" not in rev
    api.net.clear_failures()
    again = enrich(api.client, AUTO)[AUTO]
    assert again.get("cached") is True and again["fields"]["revenue"]["state"] == "unavailable"  # not retried in a loop...
    settings_with(settings, enrich_retry_after_seconds=0)
    api.svc.enricher._cache.clear()
    assert enrich(api.client, AUTO)[AUTO]["fields"]["revenue"]["state"] == "verified"  # ...but on a later visit


def test_a_careers_site_that_cannot_be_read_is_unavailable_not_none(api: Any) -> None:
    api.net.fail("https://www.autobjorn.no", "timeout")
    api.net.fail("https://autobjorn.no", "timeout")
    jobs = enrich(api.client, AUTO)[AUTO]["fields"]["openPositions"]
    assert jobs["state"] == "unavailable" and "not evidence that the company has no openings" in jobs["note"] and "value" not in jobs
    assert {s["name"]: s["state"] for s in jobs["sources"]}["Company careers page"] == "unavailable"


# ----------------------------------------------------------------------------------------------------------------------- bounds --
def test_a_request_is_limited_to_a_small_batch(api: Any, settings: Settings) -> None:
    orgs = [valid_org(910000000 + i * 1000) for i in range(settings.enrich_max_batch + 1)]
    res = api.client.post("/api/companies/enrich", json={"orgNumbers": orgs})
    assert res.status_code == 400 and "At most" in res.json()["message"]


def test_lookups_run_in_parallel_up_to_the_concurrency_limit(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_with(settings, enrich_concurrency=2)
    client, svc, _net = build(settings, slow={"data.brreg.no": 0.05})
    orgs = ["810034882", "810059672", "810324562", AUTO, "810363142"]
    active = peak = 0
    original = svc.enricher._lookup

    async def counted(org: str, fields: list[str]) -> dict[str, Any]:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            return await original(org, fields)
        finally:
            active -= 1

    monkeypatch.setattr(svc.enricher, "_lookup", counted)
    with client:
        t0 = time.monotonic()
        items = enrich(client, *orgs, fields=["revenue"])
        elapsed = time.monotonic() - t0
    assert set(items) == set(orgs) and peak == 2  # parallel, but never more than the limit
    assert elapsed < 5 * 0.05 * 3  # well under one-by-one


def test_a_slow_source_is_cut_off_and_the_other_figures_still_arrive(settings: Settings) -> None:
    settings_with(settings, enrich_company_timeout_seconds=1.5)
    client, _svc, _net = build(settings, slow={"www.autobjorn.no": 3.0, "autobjorn.no": 3.0})
    with client:
        fields = enrich(client, AUTO)[AUTO]["fields"]
    assert fields["openPositions"]["state"] == "unavailable" and "did not finish within" in fields["openPositions"]["note"]
    assert fields["revenue"]["state"] == "verified" and fields["employees"]["state"] == "verified"


def test_no_web_search_is_used_and_every_company_stays_within_its_request_cap(settings: Settings) -> None:
    settings_with(settings, tavily_api_key="tvly-test-0000000000")
    client, svc, net = build(settings)
    with client:
        enrich(client, AUTO, BARE)
    assert not [u for u in net.requests if "tavily" in u]
    calls = svc.db.all("SELECT org_number, COUNT(*) AS n FROM tool_calls WHERE run_id = 'discover-enrich' GROUP BY org_number")
    assert calls and all(r["n"] <= settings.enrich_max_requests_per_company for r in calls)


def test_a_cached_result_makes_no_new_requests(api: Any) -> None:
    enrich(api.client, AUTO)
    api.net.requests.clear()
    again = enrich(api.client, AUTO)[AUTO]
    assert again.get("cached") is True and api.net.requests == []


def test_the_search_rows_are_reused_so_the_register_is_not_asked_twice(api: Any) -> None:
    api.client.post("/api/companies/discover", json={"text": "AUTOBJØRN"})
    api.net.requests.clear()
    enrich(api.client, AUTO, fields=["employees"])
    assert not [u for u in api.net.requests if "/enhetsregisteret/api/enheter/" in u]


# ---------------------------------------------------------------------------------------------- researched companies' openings --
def test_a_researched_card_says_what_the_hiring_research_established(api: Any) -> None:
    api.net.add_site("autobjorn.no", verified_site(NAME, AUTO))  # no openings on the careers page
    run_ = api.client.post("/api/research/runs", json={"query": AUTO, "mode": "quick"}).json()
    with api.client.stream("GET", f"/api/research/runs/{run_['id']}/events?lastSeq=0") as stream:
        for line in stream.iter_lines():
            if line.startswith("data: ") and json.loads(line[6:])["type"] in ("run.completed", "run.failed"):
                break
    card = api.client.post("/api/companies/discover", json={"text": "AUTOBJØRN"}).json()["items"][0]
    assert card["researchState"] == "researched"
    assert card["openPositionsStatus"] in ("none_found", "incomplete", "source_unavailable")  # the card can say "none verified", not "0 openings"
