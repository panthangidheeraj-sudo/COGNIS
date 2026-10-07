#!/usr/bin/env python3
"""100-company smoke test.

Offline (default): 100 real universe rows with synthetic register/website responses and injected
failures (timeouts, 429, 5xx, robots blocks, parked and wrong-company sites, missing records).
Live (--live):     the same 100 organisation numbers against the real sources (run on your machine).

    python scripts/smoke_test.py                 # offline, ~seconds
    python scripts/smoke_test.py --live          # real network; writes out/smoke-live/

Checks: one terminal envelope per input, contract/evidence integrity, no wrong-company website
publication (offline scenarios), idempotent re-run, budgets respected. Writes a Markdown report.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from pathlib import Path

from _bootstrap import BACKEND_ROOT, bootstrap


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--live", action="store_true", help="Use the real network instead of the offline fixture network")
    p.add_argument("--count", type=int, default=100)
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--universe", default=str(BACKEND_ROOT / "tests" / "fixtures" / "entry-companies.jsonl"))
    p.add_argument("--out", default=None)
    p.add_argument("--workers", type=int, default=None)
    args = p.parse_args()
    bootstrap(quiet=True)

    from app.competition.batch import BatchConfig, run_batch
    from app.config import get_settings, override_settings
    from app.storage.db import Database

    out = Path(args.out or (BACKEND_ROOT / "out" / ("smoke-live" if args.live else "smoke")))
    out.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in Path(args.universe).read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = random.Random(args.seed).sample(rows, min(args.count, len(rows)))
    (out / "organisations.txt").write_text("\n".join(r["organisation_number"] for r in rows), encoding="utf-8")
    with (out / "bulk.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    transport = provider = None
    scenarios: dict[str, dict] = {}
    settings = get_settings()
    if not args.live:
        from app.providers.fake_provider import FakeProvider
        from app.testing.fixtures import FixtureNetwork, build_synthetic_universe

        settings = settings.model_copy(update={"llm_provider": "fake", "brreg_account_copies_min_interval_seconds": 0, "retry_base_delay_seconds": 0})
        override_settings(settings)
        net = FixtureNetwork()
        scenarios = build_synthetic_universe(net, rows, seed=args.seed)
        transport, provider = net.transport(), FakeProvider()
    db = Database(Path(settings.data_dir) / "smoke-live.sqlite") if args.live else Database(":memory:")  # DATA_DIR keeps SQLite out of synced folders

    def cfg(run_id: str, previous: str | None = None) -> BatchConfig:
        return BatchConfig(organisations=str(out / "organisations.txt"), bulk=str(out / "bulk.jsonl"), output=str(out / f"{run_id}-envelopes.jsonl"),
                           profiles_output=str(out / f"{run_id}-profiles.jsonl"), report=str(out / f"{run_id}-report.json"), run_id=run_id, expected_count=len(rows),
                           previous_profiles=previous, transport=transport, provider=provider, use_provider_override=not args.live, db=db, workers=args.workers)

    t0 = time.time()
    first = asyncio.run(run_batch(cfg("smoke-1"), settings))
    t1 = time.time()
    second = asyncio.run(run_batch(cfg("smoke-2", previous=str(out / "smoke-1-profiles.jsonl")), settings))
    t2 = time.time()
    envs = [json.loads(line) for line in (out / "smoke-1-envelopes.jsonl").read_text(encoding="utf-8").splitlines()]

    problems: list[str] = []
    if not first["validation"]["passed"]:
        problems.append(f"validation failed: {first['validation']['checks']}")
    if second["change_detection"]["total_changes"] and not args.live:
        problems.append(f"re-run detected {second['change_detection']['total_changes']} change(s) on identical data")
    wrong = []
    if scenarios:
        for env in envs:
            kind = scenarios[env["organisation_number"]]["kind"]
            published = any(c["field"] == "official_website" and c["availability"] == "available" for c in env["claims"])
            if kind in ("wrong_company_site", "parked_site", "robots_blocked_site", "timeout_site") and published:
                wrong.append(f"{env['organisation_number']} ({kind})")
            if kind in ("verified_site", "email_domain_site") and not published:
                problems.append(f"{env['organisation_number']}: verified site not found ({kind})")
    if wrong:
        problems.append("WRONG-COMPANY OR UNVERIFIED WEBSITE PUBLISHED: " + ", ".join(wrong))

    ops = first["operations"]
    lines = [
        f"# Smoke test — {'live network' if args.live else 'offline fixtures'}", "",
        f"- Companies: **{len(envs)}** (expected {len(rows)}) · validation **{'passed' if first['validation']['passed'] else 'FAILED'}**",
        f"- First run: {t1 - t0:.1f} s · requests {ops['requests']} · cost ${ops['third_party_cost_usd']:.4f} · LLM calls {ops['llm_calls']}",
        f"- Per company runtime p50 {ops['company_runtime_ms']['p50']} ms · p95 {ops['company_runtime_ms']['p95']} ms",
        f"- Re-run (cache + change detection): {t2 - t1:.1f} s · requests {second['operations']['requests']} · changes {second['change_detection']['total_changes']}",
        f"- Entity states: {first['entity_states']}", "", "## Coverage (companies with an available claim)", "",
        *(f"- {k}: {v}/{len(envs)}" for k, v in first["coverage"]["companies_with_field"].items()), "", "## Module states", "",
        *(f"- {m}: {s}" for m, s in first["module_states"].items()), "", "## Identity", "",
        f"- Verified websites: {first['identity']['verified_websites']} · ambiguous: {first['identity']['ambiguous_websites']}",
        f"- Rejected observations by reason: {first['identity']['rejected_observations']}",
        f"- Website candidates by origin / decision: {first['identity']['website_attempts']['by_origin_and_decision']}",
        *(f"  - {n}× {why}" for why, n in first["identity"]["website_attempts"]["top_reasons"].items()), "",
        "## Problems", "", *(f"- {x}" for x in problems or ["none"]),
    ]
    if scenarios:
        from collections import Counter

        lines += ["", "## Offline scenarios", "", *(f"- {k}: {v}" for k, v in Counter(s["kind"] for s in scenarios.values()).items())]
    (out / "smoke-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    raise SystemExit(1 if problems else 0)


if __name__ == "__main__":
    sys.exit(main())
