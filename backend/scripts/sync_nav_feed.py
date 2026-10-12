#!/usr/bin/env python3
"""Build or refresh the local index of NAV Arbeidsplassen job ads (free, official feed).

    python scripts/sync_nav_feed.py                 # one bounded sync (NAV_SYNC_MAX_PAGES / NAV_SYNC_MAX_SECONDS)
    python scripts/sync_nav_feed.py --until-done    # repeat until the index has caught up with the feed

Uses NAV_FEED_TOKEN when set, otherwise NAV's public token. The API server also refreshes the index in the
background. Prints a summary; never prints the token.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from _bootstrap import bootstrap


async def _run(until_done: bool, max_rounds: int) -> dict:
    from app.config import get_settings
    from app.connectors.nav import sync_feed
    from app.net.http import HttpClient
    from app.storage import repository as repo
    from app.storage.db import get_db

    s = get_settings()
    db = get_db()
    reports = []
    async with HttpClient(recorder=repo.tool_call_recorder(db)) as http:
        for _ in range(max_rounds if until_done else 1):
            report = await sync_feed(http, db, s)
            reports.append(report)
            print(json.dumps({k: report.get(k) for k in ("status", "pages", "active_upserts", "inactive_masked", "seconds", "index", "error")}, ensure_ascii=False), flush=True)
            if report.get("status") != "partial":
                break
    return reports[-1] if reports else {}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--until-done", action="store_true")
    p.add_argument("--max-rounds", type=int, default=40)
    args = p.parse_args()
    bootstrap(quiet=True)
    report = asyncio.run(_run(args.until_done, args.max_rounds))
    raise SystemExit(0 if report.get("status") in ("up_to_date", "partial") else 1)


if __name__ == "__main__":
    main()
