#!/usr/bin/env python3
"""Research one company and print what was published, what was not, and why.

    python scripts/inspect_profile.py 923609016            # live (your network)
    python scripts/inspect_profile.py 810359862 --offline  # recorded fixtures
"""
from __future__ import annotations

import argparse
import asyncio
import json

from _bootstrap import bootstrap


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("org")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--mode", default="deep", choices=["quick", "deep", "competition"])
    p.add_argument("--json", action="store_true", help="Print the full research record as JSON")
    args = p.parse_args()
    bootstrap(quiet=True)
    from app.agent.orchestrator import Orchestrator, ResearchOptions
    from app.config import get_settings
    from app.net.http import HttpClient
    from app.providers.registry import build_provider
    from app.runtime.budgets import unlimited_budget

    async def go() -> dict:
        transport = None
        provider = None
        if args.offline:
            from app.providers.fake_provider import FakeProvider
            from app.testing.fixtures import FixtureNetwork

            net = FixtureNetwork()
            net.load_brreg_probes()
            transport, provider = net.transport(), FakeProvider()
        async with HttpClient(transport=transport) as http:
            prov = provider if args.offline else build_provider(http, get_settings())
            orch = Orchestrator(http=http, run_budget=unlimited_budget(), provider=prov)
            return await orch.research(args.org, run_id="inspect", options=ResearchOptions(mode=args.mode))

    rec = asyncio.run(go())
    if args.json:
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        return
    ident = rec.get("identity") or {}
    print(f"\n{ident.get('legal_name') or '?'} ({rec['organisation_number']}) — entity state {rec['entity_state']}, {rec['operations'].get('requests')} requests, "
          f"{rec['operations'].get('runtime_ms')} ms\n")
    print("PUBLISHED")
    for c in rec["claims"]:
        value = c["value"] if not isinstance(c["value"], (list, dict)) else json.dumps(c["value"], ensure_ascii=False)[:80]
        period = f" [{c['period_label']}]" if c.get("period_label") else ""
        flag = "  ⚠ conflict" if c.get("conflict") else ""
        print(f"  {c['field']:<32} {str(value)[:70]:<70}{period} ({c['source_class']}, conf {c['confidence']}){flag}")
    print("\nNOT ESTABLISHED")
    for a in rec["absences"]:
        print(f"  {a['field']:<32} {a['availability']:<15} {a['note']}")
    print("\nSOURCES")
    for name, m in rec["modules"].items():
        print(f"  {name:<20} {m['state']:<14} {(m.get('note') or '')[:90]}")
    for attempt in rec.get("site_attempts") or []:
        print(f"\nWEBSITE CANDIDATE {attempt['domain']} ({attempt['origin']}): {attempt['decision']} score={attempt['score']} signals={attempt['signals']} "
              f"conflicts={attempt['conflicts']}")
    if rec.get("rejections"):
        print("\nREJECTED BY THE PUBLICATION GATE")
        for r in rec["rejections"][:20]:
            print(f"  {r['field']:<28} {r['reason']}")
    if rec.get("summary"):
        print(f"\nSUMMARY ({rec['summary']['method']})\n  {rec['summary']['text']}")
    if rec.get("errors"):
        print("\nERRORS")
        for e in rec["errors"]:
            print(f"  {e}")


if __name__ == "__main__":
    main()
