"""Hiring checks stay fast and honest when a source is slow or down.

Root causes covered here:
* timeouts were per phase (connect / each read) with no overall deadline, and a DNS lookup had no limit at all — a server that trickled bytes, or a
  name that never resolved, could hold one request for minutes;
* every NAV call retried and re-asked a source that had already proved unreachable;
* a hiring source that could not be read ended the step as a plain success.

No test touches the real network; slow servers are simulated in-process.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import pytest
from test_free_sources import AUTO, NAV, run
from test_free_sources import network as ads_network
from test_hiring_data import hiring, posting, settings_with, site

from app.agent.orchestrator import Orchestrator, ResearchOptions
from app.config import Settings, get_settings
from app.connectors import jobs as jobs_conn
from app.connectors import nav
from app.net.cooldown import Cooldowns
from app.net.http import HttpClient
from app.providers.fake_provider import FakeProvider
from app.runtime.budgets import BudgetLimits, RunBudget
from app.storage.db import Database
from app.testing.fixtures import FixtureNetwork

URL = "https://slow.example.com/data"


def _no_sleep(_s: float) -> Any:
    return asyncio.sleep(0)


def _quiet_nav(monkeypatch: pytest.MonkeyPatch) -> None:
    """A working NAV feed in which no ad belongs to the company: NAV was checked and has nothing."""
    import test_free_sources as t

    monkeypatch.setattr(t, "ADS", {"x-1": t._ad("x-1", "Sveiser", orgnr=t.OTHER_ORG, employer="Helt Annet AS"), "a-later-inactive": t.ADS["a-later-inactive"]})


# ------------------------------------------------------------- hard deadlines --
class Trickle(httpx.AsyncByteStream):
    """A server that answers one byte at a time, forever: no single read ever times out, so only a wall-clock cap can stop it."""

    async def __aiter__(self):  # noqa: ANN204
        for _ in range(10_000):
            await asyncio.sleep(0.03)
            yield b"x"


def test_a_response_that_trickles_in_forever_is_cut_off_at_the_deadline() -> None:
    async def go() -> tuple[Any, float]:
        transport = httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": "text/plain"}, stream=Trickle()))
        async with HttpClient(transport=transport, sleep=_no_sleep) as http:
            started = time.monotonic()
            res = await http.fetch(URL, connector="test", timeout=0.3, retry_attempts=0)
            return res, time.monotonic() - started

    res, took = run(go())
    assert res.classification == "timeout" and "no complete response within" in (res.error or "")
    assert took < 2.0, f"the request was not bounded ({took:.1f} s)"


def test_a_host_name_that_never_resolves_is_cut_off(settings: Settings) -> None:
    settings.dns_timeout_seconds = 0.2

    async def never(_host: str) -> list[str]:
        await asyncio.sleep(30)
        return ["93.184.216.34"]

    async def go() -> tuple[Any, float]:
        async with HttpClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="ok")), resolver=never, sleep=_no_sleep) as http:
            started = time.monotonic()
            res = await http.fetch(URL, connector="test", retry_attempts=0)
            return res, time.monotonic() - started

    res, took = run(go())
    assert res.classification == "timeout" and "did not resolve within" in (res.error or "")
    assert took < 2.0


def test_the_default_deadline_applies_when_the_caller_sets_none(settings: Settings) -> None:
    settings.http_total_timeout_seconds = 0.2

    async def go() -> Any:
        transport = httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": "text/plain"}, stream=Trickle()))
        async with HttpClient(transport=transport, sleep=_no_sleep) as http:
            return await http.fetch(URL, connector="test", retry_attempts=0)

    assert run(go()).classification == "timeout"


def test_a_fast_response_is_unaffected_by_the_deadline() -> None:
    async def go() -> Any:
        async with HttpClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True})), sleep=_no_sleep) as http:
            return await http.fetch(URL, connector="test", timeout=0.5, expect="json")

    res = run(go())
    assert res.ok and res.json() == {"ok": True}


# ------------------------------------------------------------------ cooldown --
def test_cooldown_opens_after_the_threshold_expires_and_clears_on_success() -> None:
    now = [100.0]
    cd = Cooldowns(clock=lambda: now[0])
    assert cd.cooling("nav") is None
    assert not cd.failure("nav", threshold=2, seconds=60, classification="timeout", reason="timeout")  # one failure is not an outage yet
    assert cd.failure("nav", threshold=2, seconds=60, classification="timeout", reason="timeout")
    cooling = cd.cooling("nav")
    assert cooling is not None and cooling.classification == "timeout" and 59 < cooling.seconds_left <= 60
    now[0] += 61
    assert cd.cooling("nav") is None  # expires by itself
    cd.failure("nav", threshold=1, seconds=60, classification="network", reason="network")
    assert cd.cooling("nav") is not None
    cd.success("nav")
    assert cd.cooling("nav") is None


# ------------------------------------------------- an unreachable NAV is not re-asked --
def _nav_calls(net: FixtureNetwork, needle: str = "") -> int:
    return len([u for u in net.requests if u.startswith(NAV) and needle in u])


async def _runs_after_sync(net: FixtureNetwork, fail: str, *, runs: int = 2, reset_token: bool = False, wait_between: float = 0.0) -> tuple[list[dict[str, Any]], list[int]]:
    db = Database(":memory:")
    records: list[dict[str, Any]] = []
    counts: list[int] = []
    async with HttpClient(transport=net.transport(), sleep=_no_sleep) as http:
        await nav.sync_feed(http, db, get_settings())
        if reset_token:
            nav.TOKEN.public = None
        net.fail(fail, "timeout")
        orch = Orchestrator(http=http, run_budget=RunBudget(BudgetLimits(max_requests=500)), provider=FakeProvider(), db=db)
        for i in range(runs):
            if i and wait_between:
                await asyncio.sleep(wait_between)
            records.append(await orch.research(AUTO, run_id=f"r{i}", options=ResearchOptions(mode="deep", include_geo=False)))
            counts.append(_nav_calls(net, "/api/v1/feedentry/") + _nav_calls(net, "/api/publicToken"))
    return records, counts


def test_nav_that_timed_out_is_not_asked_again_for_the_next_company() -> None:
    net, _calls, _ = ads_network()
    net.add_site("autobjorn.no", site())
    records, counts = run(_runs_after_sync(net, f"{NAV}/api/v1/feedentry"))
    first_entry_calls = len([u for u in net.requests if "/api/v1/feedentry/" in u])
    assert first_entry_calls >= 1
    assert counts[1] == counts[0], "the second research must not send any further NAV request while NAV is cooling down"
    second = records[1]["modules"]["nav_jobs"]
    assert second["state"] == "failed" and "not evidence that the company is not hiring" in second["note"]
    assert hiring(records[1])["outcome"] == "source_unavailable"


def test_each_nav_request_is_retried_at_most_once() -> None:
    net, _calls, _ = ads_network()
    net.add_site("autobjorn.no", site())
    run(_runs_after_sync(net, f"{NAV}/api/v1/feedentry", runs=1))
    entry_calls = len([u for u in net.requests if "/api/v1/feedentry/" in u])
    assert entry_calls <= 2 * (get_settings().nav_retry_attempts + 1), "two candidates at most (each with one retry), then NAV is skipped"


def test_a_token_endpoint_that_is_down_is_asked_once_per_cooldown() -> None:
    net, _calls, _ = ads_network()
    net.add_site("autobjorn.no", site())
    records, _counts = run(_runs_after_sync(net, f"{NAV}/api/publicToken", reset_token=True))
    token_calls = _nav_calls(net, "/api/publicToken")
    # one initial request + its single retry; the second research and the remaining candidates do not ask again
    assert token_calls <= 1 + 1 + 1  # +1: the successful token request made while the index was synced
    assert hiring(records[0])["outcome"] == hiring(records[1])["outcome"] == "source_unavailable"


def test_nav_is_asked_again_after_the_cooldown(settings: Settings) -> None:
    settings.nav_unavailable_cooldown_seconds = 0.05
    net, _calls, _ = ads_network()
    net.add_site("autobjorn.no", site())
    _records, counts = run(_runs_after_sync(net, f"{NAV}/api/v1/feedentry", wait_between=0.2))
    assert counts[1] > counts[0], "after the cooldown NAV is tried again (it may have recovered)"


# ---------------------------------------------- company careers pages are bounded too --
def test_slow_company_careers_pages_do_not_hold_the_run_and_never_read_as_no_openings(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_with(settings, jobs_step_timeout_seconds=0.05)

    async def never(*_a: Any, **_k: Any) -> Any:
        await asyncio.sleep(30)

    monkeypatch.setattr(jobs_conn, "collect_jobs", never)
    _quiet_nav(monkeypatch)
    net, _calls, _ = ads_network()
    net.add_site("autobjorn.no", site([posting("Bilselger")]))
    started = time.monotonic()
    rec, events = run(_with_events(net))
    assert time.monotonic() - started < 20
    h = hiring(rec)
    assert h["outcome"] == "source_unavailable" and h["totalCurrent"] is None
    assert "Company careers pages" in h["message"] and "timed out" in h["message"] and "not evidence" in h["message"]
    assert not [c for c in rec["claims"] if c["field"] == "open_positions_count"], "a zero is never published when a source could not be read"
    assert _jobs_event(events)[0] == "step_failed"


def test_openings_confirmed_by_nav_survive_slow_careers_pages_with_a_caveat(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_with(settings, jobs_step_timeout_seconds=0.05)

    async def never(*_a: Any, **_k: Any) -> Any:
        await asyncio.sleep(30)

    monkeypatch.setattr(jobs_conn, "collect_jobs", never)
    net, _calls, _ = ads_network()  # NAV lists verified openings for the company
    net.add_site("autobjorn.no", site())
    rec, _events = run(_with_events(net))
    h = hiring(rec)
    assert h["outcome"] == "verified" and h["totalCurrent"] and h["totalCurrent"] > 0
    assert "Company careers pages" in h["message"] and "further openings" in h["message"]


# ------------------------- unavailable, none verified and confirmed look different --
async def _with_events(net: FixtureNetwork, *, nav_fail: str | None = None) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]:
    db = Database(":memory:")
    events: list[tuple[str, dict[str, Any]]] = []
    async with HttpClient(transport=net.transport(), sleep=_no_sleep) as http:
        await nav.sync_feed(http, db, get_settings())
        if nav_fail:
            net.fail(nav_fail, "timeout")
        orch = Orchestrator(http=http, run_budget=RunBudget(BudgetLimits(max_requests=500)), provider=FakeProvider(), db=db)
        rec = await orch.research(AUTO, run_id="ev", options=ResearchOptions(mode="deep", include_geo=False), on_event=lambda kind, data: events.append((kind, data)))
    return rec, events


def _jobs_event(events: list[tuple[str, dict[str, Any]]]) -> tuple[str, dict[str, Any]]:
    return next((kind, data) for kind, data in events if data.get("key") == "jobs" and kind in ("step_completed", "step_failed", "step_blocked"))


def test_source_unavailable_is_a_failed_step_not_a_success() -> None:
    net, _calls, _ = ads_network()
    net.add_site("autobjorn.no", site(body="<h1>Ledige stillinger</h1><p>Vi har ingen ledige stillinger akkurat nå.</p>"))
    rec, events = run(_with_events(net, nav_fail=f"{NAV}/api/v1/feedentry"))
    kind, data = _jobs_event(events)
    assert kind == "step_failed" and data.get("retryable") is True
    assert "not evidence" in data["message"] and "NAV Arbeidsplassen" in data["message"]
    assert hiring(rec)["outcome"] == "source_unavailable"
    assert not any(k == "step_completed" and d.get("key") == "jobs" for k, d in events), "the step must not also be reported as completed"


def test_no_verified_openings_is_a_neutral_result_not_a_failure_and_not_a_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _quiet_nav(monkeypatch)
    net, _calls, _ = ads_network()
    net.add_site("autobjorn.no", site())
    rec, events = run(_with_events(net))
    kind, data = _jobs_event(events)
    assert kind == "step_completed" and data["outcome"] == "not_available"
    assert "does not mean the company is not hiring" in data["message"]
    h = hiring(rec)
    assert h["outcome"] == "none_found" and h["totalCurrent"] is None


def test_confirmed_openings_are_a_verified_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _quiet_nav(monkeypatch)
    net, _calls, _ = ads_network()
    net.add_site("autobjorn.no", site([posting("Bilselger"), posting("Selger")]))
    rec, events = run(_with_events(net))
    kind, data = _jobs_event(events)
    assert kind == "step_completed" and data["outcome"] == "verified" and data["facts"] >= 2
    h = hiring(rec)
    assert h["outcome"] == "verified" and h["totalCurrent"] == 2
