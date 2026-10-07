#!/usr/bin/env python3
"""Replay evaluator-owned old/new source bytes through production normalisers and the change detector.

    python scripts/run_refresh_replay.py --manifest tests/fixtures/refresh-snapshots.json --output out/refresh-demo.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from _bootstrap import bootstrap


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    bootstrap(quiet=True)
    from app.competition.refresh import replay

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    report = asyncio.run(replay(manifest))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "events"}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["qualification_passed"] else 1)


if __name__ == "__main__":
    main()
