#!/usr/bin/env python3
"""Benchmark: runtime, requests and cost per company (offline by default, --live for real sources).

    python scripts/benchmark.py --count 50
    python scripts/benchmark.py --live --count 20
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import time

from _bootstrap import BACKEND_ROOT, bootstrap


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--live", action="store_true")
    p.add_argument("--count", type=int, default=50)
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()
    bootstrap(quiet=True)
    from app.competition.batch import BatchConfig, run_batch
    from app.config import get_settings, override_settings
    from app.storage.db import Database

    out = BACKEND_ROOT / "out" / "benchmark"
    out.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(x) for x in (BACKEND_ROOT / "tests" / "fixtures" / "entry-companies.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    rows = random.Random(args.seed).sample(rows, min(args.count, len(rows)))
    (out / "orgs.txt").write_text("\n".join(r["organisation_number"] for r in rows), encoding="utf-8")
    settings = get_settings()
    transport = provider = None
    if not args.live:
        from app.providers.fake_provider import FakeProvider
        from app.testing.fixtures import FixtureNetwork, build_synthetic_universe

        settings = settings.model_copy(update={"llm_provider": "fake", "brreg_account_copies_min_interval_seconds": 0})
        override_settings(settings)
        net = FixtureNetwork()
        build_synthetic_universe(net, rows, seed=args.seed)
        transport, provider = net.transport(), FakeProvider()
    t0 = time.time()
    report = asyncio.run(run_batch(BatchConfig(organisations=str(out / "orgs.txt"), output=str(out / "envelopes.jsonl"), run_id=f"bench-{int(t0)}",
                                               transport=transport, provider=provider, use_provider_override=not args.live, db=Database(":memory:"),
                                               workers=args.workers, fresh=True), settings))
    elapsed = time.time() - t0
    ops = report["operations"]
    result = {"mode": "live" if args.live else "offline", "companies": len(rows), "elapsed_seconds": round(elapsed, 2),
              "companies_per_minute": round(len(rows) / max(elapsed, 1e-6) * 60, 1), "requests": ops["requests"], "requests_per_company": ops["requests_per_company"],
              "cost_usd": ops["third_party_cost_usd"], "cost_per_company_usd": ops["cost_per_company_usd"], "llm_calls": ops["llm_calls"],
              "company_runtime_ms": ops["company_runtime_ms"], "requests_by_connector": ops["requests_by_connector"],
              "projected_100_company_minutes": round(elapsed / len(rows) * 100 / 60, 1), "validation_passed": report["validation"]["passed"]}
    (out / "benchmark.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
