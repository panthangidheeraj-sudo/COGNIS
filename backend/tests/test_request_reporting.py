"""Request reporting: the shared NAV-index refresh is reported on its own, so ``requests_per_company`` describes the companies and nothing else."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from test_free_sources import nav_handler

from app.competition.batch import BatchConfig, run_batch
from app.providers.fake_provider import FakeProvider
from app.storage.db import Database
from app.testing.fixtures import FixtureNetwork, build_synthetic_universe


def _batch(tmp_path, settings, *, count: int, nav_sync: bool = True) -> tuple[dict, list[dict]]:  # noqa: ANN001
    rows = [json.loads(line) for line in (Path(__file__).parent / "fixtures" / "entry-companies.jsonl").read_text(encoding="utf-8").splitlines()[:count]]
    net = FixtureNetwork()
    build_synthetic_universe(net, rows)
    calls: list[str] = []
    net.handlers += [nav_handler(calls)]
    orgs = tmp_path / "orgs.txt"
    orgs.write_text("\n".join(r["organisation_number"] for r in rows), encoding="utf-8")
    out = tmp_path / "env.jsonl"
    settings.enable_nav_jobs = nav_sync
    cfg = BatchConfig(organisations=str(orgs), output=str(out), run_id="req", expected_count=count, transport=net.transport(), provider=FakeProvider(),
                      use_provider_override=True, db=Database(":memory:"), workers=2)
    report = asyncio.run(run_batch(cfg, settings))
    return report, [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]


def test_nav_sync_requests_are_not_charged_to_the_company(tmp_path, settings) -> None:  # noqa: ANN001
    report, envelopes = _batch(tmp_path, settings, count=1)
    ops = report["operations"]
    own = envelopes[0]["operations"]["requests"]
    assert ops["shared_index_requests"] > 0 and ops["shared_index_requests_by_connector"].get("nav_feed")  # the refresh happened and is visible
    assert ops["company_requests"] == own  # exactly what the envelope says the company made
    assert ops["requests_per_company"] == float(own)  # one company: not diluted or inflated by the shared refresh
    assert "nav_feed" not in envelopes[0]["operations"]["requests_by_connector"]


def test_total_requests_stay_visible_and_add_up(tmp_path, settings) -> None:  # noqa: ANN001
    report, _ = _batch(tmp_path, settings, count=1)
    ops = report["operations"]
    assert ops["requests"] == ops["company_requests"] + ops["shared_index_requests"]
    assert ops["requests_by_connector"].get("nav_feed", 0) >= ops["shared_index_requests_by_connector"]["nav_feed"]


def test_without_a_nav_refresh_there_are_no_shared_requests(tmp_path, settings) -> None:  # noqa: ANN001
    report, _ = _batch(tmp_path, settings, count=1, nav_sync=False)
    ops = report["operations"]
    assert ops["shared_index_requests"] == 0 and ops["shared_index_requests_by_connector"] == {}
    assert ops["requests"] == ops["company_requests"]


def test_requests_per_company_is_the_mean_of_company_requests_only(tmp_path, settings) -> None:  # noqa: ANN001
    report, envelopes = _batch(tmp_path, settings, count=3)
    ops = report["operations"]
    assert ops["company_requests"] == sum(e["operations"]["requests"] for e in envelopes)
    assert ops["requests_per_company"] == round(ops["company_requests"] / 3, 2)
