"""Event-loop lag watchdog: a stalled batch must be explainable from its own report (diagnostics only, no behaviour change)."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from app.runtime.lag import LoopLagMonitor


def test_a_blocked_loop_is_recorded_as_a_stall() -> None:
    async def scenario() -> dict:
        mon = LoopLagMonitor(interval=0.02, stall_seconds=0.2)
        mon.start()
        await asyncio.sleep(0.1)
        time.sleep(0.5)  # a synchronous call (or a paused process): no timer on the loop can fire meanwhile
        await asyncio.sleep(0.1)
        await mon.stop()
        return mon.report()

    rep = asyncio.run(scenario())
    assert rep["stalls_over_threshold"] == 1 and rep["stalls"][0]["seconds"] >= 0.3
    assert rep["max_ms"] >= 300 and rep["stalled_seconds"] >= 0.3 and rep["threshold_seconds"] == 0.2


def test_a_healthy_loop_reports_no_stall_and_stop_leaves_no_task_behind() -> None:
    async def scenario() -> tuple[dict, int]:
        mon = LoopLagMonitor(interval=0.02, stall_seconds=0.2)
        mon.start()
        await asyncio.sleep(0.3)
        await mon.stop()
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        return mon.report(), len(pending)

    rep, pending = asyncio.run(scenario())
    assert rep["stalls_over_threshold"] == 0 and rep["stalled_seconds"] == 0 and rep["max_ms"] < 200
    assert pending == 0


def test_stalls_are_capped_so_a_report_cannot_grow_without_bound() -> None:
    async def scenario() -> dict:
        mon = LoopLagMonitor(interval=0.01, stall_seconds=0.05, max_stalls=2)
        mon.start()
        for _ in range(4):
            await asyncio.sleep(0.03)
            time.sleep(0.12)
        await mon.stop()
        return mon.report()

    rep = asyncio.run(scenario())
    assert len(rep["stalls"]) == 2 and rep["stalled_seconds"] >= 0.2  # all stalls are summed, only two are listed


def test_batch_report_carries_the_event_loop_lag_block(tmp_path, settings) -> None:  # noqa: ANN001
    from app.competition.batch import BatchConfig, run_batch
    from app.providers.fake_provider import FakeProvider
    from app.storage.db import Database
    from app.testing.fixtures import FixtureNetwork, build_synthetic_universe

    rows = [json.loads(line) for line in (Path(__file__).parent / "fixtures" / "entry-companies.jsonl").read_text(encoding="utf-8").splitlines()[:3]]
    net = FixtureNetwork()
    build_synthetic_universe(net, rows)
    orgs = tmp_path / "orgs.txt"
    orgs.write_text("\n".join(r["organisation_number"] for r in rows), encoding="utf-8")
    cfg = BatchConfig(organisations=str(orgs), output=str(tmp_path / "env.jsonl"), run_id="lag", expected_count=3, transport=net.transport(), provider=FakeProvider(),
                      use_provider_override=True, db=Database(":memory:"), workers=2)
    report = asyncio.run(run_batch(cfg, settings))
    lag = report["event_loop_lag"]
    assert report["validation"]["passed"]
    assert {"max_ms", "stalls_over_threshold", "stalled_seconds", "threshold_seconds", "stalls"} <= set(lag)
    assert lag["stalls_over_threshold"] == 0 and lag["threshold_seconds"] == 3.0


# ----------------------------------------------------------------------- stall diagnostics --
def _blocking_sleep_for_the_test(seconds: float) -> None:
    time.sleep(seconds)


def _busy_loop_for_the_test(seconds: float) -> int:
    end, n = time.perf_counter() + seconds, 0
    while time.perf_counter() < end:
        n += 1
    return n


def _stall(block, *, seconds: float = 0.6, stall_seconds: float = 0.2) -> dict:  # noqa: ANN001
    async def scenario() -> dict:
        mon = LoopLagMonitor(interval=0.02, stall_seconds=stall_seconds)
        mon.start()
        await asyncio.sleep(0.1)
        block(seconds)
        await asyncio.sleep(0.1)
        await mon.stop()
        return mon.report()

    rep = asyncio.run(scenario())
    assert rep["stalls_over_threshold"] == 1
    return rep["stalls"][0]


def test_the_stall_record_names_the_function_that_blocked_the_loop() -> None:
    stall = _stall(_blocking_sleep_for_the_test)
    assert stall["stack"], stall
    assert "_blocking_sleep_for_the_test" in stall["top_frame"]  # the innermost frame is the blocking call's own function
    assert any("test_loop_lag.py" in frame for frame in stall["stack"])  # …and the stack leads back to the code that called it
    assert not any(frame.startswith(("/", "C:")) for frame in stall["stack"])  # paths are project-relative, not machine-specific


def test_a_sleeping_block_is_not_mistaken_for_computation() -> None:
    stall = _stall(_blocking_sleep_for_the_test)
    assert stall["kind"] == "blocked_or_suspended" and stall["cpu_share"] < 0.3 and stall["cpu_seconds"] < 0.2


def test_a_computing_block_is_reported_as_cpu_bound_with_its_cpu_time() -> None:
    stall = _stall(_busy_loop_for_the_test)
    assert stall["kind"] == "cpu_bound" and stall["cpu_share"] >= 0.6 and stall["cpu_seconds"] >= 0.3
    assert "_busy_loop_for_the_test" in stall["top_frame"]


def test_a_long_stall_samples_the_stack_more_than_once_but_never_without_bound() -> None:
    stall = _stall(_blocking_sleep_for_the_test, seconds=1.2, stall_seconds=0.2)
    assert 1 <= len(stall.get("top_frames_sampled") or [stall["top_frame"]]) <= 3


def test_a_stall_shorter_than_the_threshold_leaves_no_sample_behind_for_the_next_one() -> None:
    async def scenario() -> dict:
        mon = LoopLagMonitor(interval=0.02, stall_seconds=0.3)
        mon.start()
        await asyncio.sleep(0.1)
        _blocking_sleep_for_the_test(0.1)  # below the threshold: no stall, nothing sampled
        await asyncio.sleep(0.1)
        _busy_loop_for_the_test(0.5)  # a later stall must report its own stack, not an earlier one
        await asyncio.sleep(0.1)
        await mon.stop()
        return mon.report()

    rep = asyncio.run(scenario())
    assert rep["stalls_over_threshold"] == 1 and "_busy_loop_for_the_test" in rep["stalls"][0]["top_frame"]


def test_the_default_threshold_is_three_seconds_and_the_watchdog_thread_stops_with_the_monitor() -> None:
    import threading

    async def scenario() -> tuple[float, int]:
        mon = LoopLagMonitor()
        mon.start()
        await asyncio.sleep(0.05)
        await mon.stop()
        return mon.stall_seconds, sum(1 for t in threading.enumerate() if t.name == "loop-lag-watchdog")

    threshold, threads = asyncio.run(scenario())
    assert threshold == 3.0 and threads == 0
