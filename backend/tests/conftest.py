"""Shared test fixtures: offline network, fake LLM, in-memory database. No test touches the real network."""
from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings, override_settings


@pytest.fixture(autouse=True)
def settings(tmp_path: Path) -> Iterator[Settings]:
    s = Settings(_env_file=None, app_env="test", llm_provider="fake", data_dir=tmp_path / "data", brreg_account_copies_min_interval_seconds=0,
                 retry_base_delay_seconds=0, retry_max_delay_seconds=1, tavily_api_key=None, groq_api_key=None)
    override_settings(s)
    yield s
    override_settings(None)


@pytest.fixture
def net():
    from app.testing.fixtures import FixtureNetwork

    n = FixtureNetwork()
    n.load_brreg_probes()
    return n


def run(coro: Any) -> Any:
    return asyncio.run(coro)


async def research(net: Any, org: str, *, provider: Any = "fake", mode: str = "deep", bulk_row: dict | None = None, bulk_meta: dict | None = None,
                   max_requests: int = 500, resolver: Any = None) -> dict[str, Any]:
    from app.agent.orchestrator import Orchestrator, ResearchOptions
    from app.net.http import HttpClient
    from app.providers.fake_provider import FakeProvider
    from app.runtime.budgets import BudgetLimits, RunBudget

    prov = FakeProvider() if provider == "fake" else provider
    async with HttpClient(transport=net.transport(), resolver=resolver, sleep=lambda _s: asyncio.sleep(0)) as http:
        orch = Orchestrator(http=http, run_budget=RunBudget(BudgetLimits(max_requests=max_requests)), provider=prov)
        return await orch.research(org, run_id="test", bulk_row=bulk_row, bulk_meta=bulk_meta, options=ResearchOptions(mode=mode, include_geo=False))


def claims(record: dict[str, Any], field: str) -> list[dict[str, Any]]:
    return [c for c in record["claims"] if c["field"] == field]


def absence(record: dict[str, Any], field: str) -> dict[str, Any] | None:
    return next((a for a in record["absences"] if a["field"] == field), None)
