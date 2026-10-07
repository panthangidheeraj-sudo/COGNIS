#!/usr/bin/env python3
"""One-command run: research every organisation number in --input and write envelopes to --output.

    python scripts/run_agent.py --input orgs.txt --output out/envelopes.jsonl [--bulk enheter.csv]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from _bootstrap import bootstrap


def main() -> None:
    p = argparse.ArgumentParser(description="COGNIS / Signalpost company research agent")
    p.add_argument("--input", required=True, help="Organisation numbers (txt, json or jsonl)")
    p.add_argument("--output", required=True, help="Envelope JSONL output")
    p.add_argument("--bulk", help="Optional Brreg bulk snapshot")
    p.add_argument("--report", help="Run report JSON (default: next to --output)")
    p.add_argument("--profiles-output", help="Profiles JSONL (default: next to --output)")
    p.add_argument("--previous-profiles")
    p.add_argument("--run-id")
    p.add_argument("--workers", type=int)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--fresh", action="store_true")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()
    bootstrap(quiet=args.quiet)

    from app.competition.batch import BatchConfig, run_batch
    from app.competition.io import InputError

    out = Path(args.output)
    cfg = BatchConfig(organisations=args.input, output=args.output, bulk=args.bulk, run_id=args.run_id, previous_profiles=args.previous_profiles,
                      report=args.report or str(out.with_name(out.stem + "-report.json")),
                      profiles_output=args.profiles_output or str(out.with_name(out.stem + "-profiles.jsonl")), workers=args.workers, resume=args.resume, fresh=args.fresh)
    try:
        report = asyncio.run(run_batch(cfg))
    except InputError as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    print(json.dumps({"run_id": report["run_id"], "companies": report["emitted_envelopes"], "requests": report["operations"]["requests"],
                      "cost_usd": report["operations"]["third_party_cost_usd"], "elapsed_seconds": report["elapsed_seconds"],
                      "validation_passed": report["validation"]["passed"], "output": args.output}, indent=2))
    raise SystemExit(0 if report["validation"]["passed"] else 1)


if __name__ == "__main__":
    main()
