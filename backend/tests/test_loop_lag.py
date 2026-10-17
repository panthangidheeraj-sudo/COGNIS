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
    assert lag["stalls_over_threshold"] == 0 and lag["threshold_seconds"] == 5.0
