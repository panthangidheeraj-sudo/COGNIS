#!/usr/bin/env python3
"""Signalpost evaluator batch contract (starter-kit compatible arguments).

    python scripts/run_competition_batch.py --organisations orgs.jsonl --bulk enheter.csv \
        --output out/envelopes.jsonl --profiles-output out/profiles.jsonl --report out/run-report.json \
        --run-id my-run --expected-count 100

Exactly one terminal envelope per input organisation number is written to --output.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from _bootstrap import bootstrap


def main() -> None:
    p = argparse.ArgumentParser(description="Evaluator-owned Signalpost batch contract")
    p.add_argument("--organisations", required=True, help="JSON, JSONL or text list of organisation numbers")
    p.add_argument("--bulk", help="Frozen Brreg snapshot (CSV, universe JSONL or JSON; .gz allowed). Optional: the live register is used either way")
    p.add_argument("--output", required=True, help="Terminal envelope JSONL")
    p.add_argument("--profiles-output", help="Starter-compatible profiles JSONL (for --previous-profiles next time)")
    p.add_argument("--report", help="Run report JSON")
    p.add_argument("--run-id", help="Run id (reuse with --resume to continue an interrupted run)")
    p.add_argument("--expected-count", type=int, default=None)
    p.add_argument("--previous-profiles", help="Profiles JSONL from an earlier run, for change detection")
    p.add_argument("--max-requests", type=int)
    p.add_argument("--max-cost-usd", type=float)
    p.add_argument("--max-runtime-seconds", type=float)
    p.add_argument("--budget-headroom", type=float)
    p.add_argument("--workers", type=int)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--fresh", action="store_true", help="Bypass the response cache")
    p.add_argument("--quiet", action="store_true")
    # Accepted for starter compatibility; module selection is automatic.
    p.add_argument("--modules", help=argparse.SUPPRESS)
    p.add_argument("--checkpoint-every", type=int, help=argparse.SUPPRESS)
    args = p.parse_args()
    bootstrap(quiet=args.quiet)

    from app.competition.batch import BatchConfig, run_batch
    from app.competition.io import InputError

    cfg = BatchConfig(organisations=args.organisations, output=args.output, bulk=args.bulk, profiles_output=args.profiles_output, report=args.report,
                      run_id=args.run_id, expected_count=args.expected_count, previous_profiles=args.previous_profiles, max_requests=args.max_requests,
                      max_cost_usd=args.max_cost_usd, max_runtime_seconds=args.max_runtime_seconds, budget_headroom=args.budget_headroom, workers=args.workers,
                      resume=args.resume, fresh=args.fresh)
    try:
        report = asyncio.run(run_batch(cfg))
    except InputError as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    summary = {k: report[k] for k in ("run_id", "expected_count", "emitted_envelopes", "elapsed_seconds", "operations", "entity_states", "validation")}
    summary["coverage"] = report["coverage"]["companies_with_field"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["validation"]["passed"] else 1)


if __name__ == "__main__":
    main()
