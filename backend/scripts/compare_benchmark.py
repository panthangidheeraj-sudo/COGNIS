"""Before/after comparison of two batch reports (``*-report.json``).

    python scripts/compare_benchmark.py --before out/v21-keyless/envelopes-report.json --after out/v21b-keyless/envelopes-report.json [--markdown out/compare.md]

Reads files only; no network, no database. A field a report does not have (older schema) is shown as ``n/a`` and never guessed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

NA = "n/a"


def _get(d: Any, path: str, default: Any = NA) -> Any:
    for part in path.split("."):
        if not isinstance(d, dict) or part not in d:
            return default
        d = d[part]
    return d


def _company_requests(rep: dict[str, Any]) -> Any:
    """New reports state the company-level count; old ones mixed the shared NAV index requests into the total."""
    direct = _get(rep, "operations.company_requests")
    if direct != NA:
        return direct
    total, nav = _get(rep, "operations.requests"), _get(rep, "operations.requests_by_connector.nav_feed", 0)
    if isinstance(total, int) and isinstance(nav, int):
        return f"{total - nav} (derived: total minus nav_feed)"
    return NA


ROWS: list[tuple[str, Any]] = [
    ("run elapsed (s)", lambda r: _get(r, "elapsed_seconds")),
    ("requests, run total", lambda r: _get(r, "operations.requests")),
    ("requests, company-level", _company_requests),
    ("requests, shared NAV index", lambda r: _get(r, "operations.shared_index_requests", _get(r, "operations.requests_by_connector.nav_feed"))),
    ("requests_per_company (reported)", lambda r: _get(r, "operations.requests_per_company")),
    ("per_company_max_requests (setting)", lambda r: _get(r, "settings.per_company_max_requests")),
    ("company runtime p50 (ms)", lambda r: _get(r, "operations.company_runtime_ms.p50")),
    ("NAV sync (s)", lambda r: _get(r, "free_source_indexes.nav_job_ads.seconds")),
    ("NAV sync pages", lambda r: _get(r, "free_source_indexes.nav_job_ads.pages")),
    ("NAV sync active upserts", lambda r: _get(r, "free_source_indexes.nav_job_ads.active_upserts")),
    ("loop lag max (ms)", lambda r: _get(r, "event_loop_lag.max_ms")),
    ("loop stalls over threshold", lambda r: _get(r, "event_loop_lag.stalls_over_threshold")),
    ("loop stall threshold (s)", lambda r: _get(r, "event_loop_lag.threshold_seconds")),
    ("claims available", lambda r: _get(r, "verification.claims.available")),
    ("news published", lambda r: _get(r, "verification.news.items_published")),
    ("news rejected/unusable (total)", lambda r: _get(r, "verification.news.candidates_rejected_or_unusable")),
    ("news rejected examples stored", lambda r: _get(r, "verification.news.rejected_examples_stored")),
    ("news merged as duplicates", lambda r: _get(r, "verification.news.candidates_merged_as_duplicates")),
    ("social candidates", lambda r: _get(r, "verification.social_profiles.candidates")),
    ("social accepted", lambda r: _get(r, "verification.social_profiles.accepted")),
    ("social accepted, linked from company site", lambda r: _get(r, "verification.social_profiles.accepted_linked_from_company_site")),
    ("social accepted, platform-verified", lambda r: _get(r, "verification.social_profiles.accepted_platform_verified")),
    ("social accepted, by declaration", lambda r: _get(r, "verification.social_profiles.accepted_by_declaration")),
    ("errors", lambda r: _get(r, "errors")),
    ("validation passed", lambda r: _get(r, "validation.passed")),
]


def _delta(a: Any, b: Any) -> str:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        d = b - a
        return f"{d:+.2f}".rstrip("0").rstrip(".") if isinstance(d, float) else f"{d:+d}"
    return "" if a == b else "changed"


def compare_reports(before: dict[str, Any], after: dict[str, Any]) -> list[tuple[str, Any, Any, str]]:
    out = []
    for label, fn in ROWS:
        a, b = fn(before), fn(after)
        out.append((label, a, b, _delta(a, b)))
    return out


def stalls(rep: dict[str, Any]) -> list[dict[str, Any]]:
    return list(_get(rep, "event_loop_lag.stalls", []) or [])


def render(rows: list[tuple[str, Any, Any, str]], before: dict[str, Any], after: dict[str, Any]) -> str:
    lines = ["| metric | before | after | change |", "|---|---|---|---|"]
    lines += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in rows]
    lines += ["", "### Event-loop stalls", ""]
    for name, rep in (("before", before), ("after", after)):
        st = stalls(rep)
        if not st:
            lines.append(f"* {name}: none over the threshold")
        for s in st:
            kind = s.get("kind", NA)
            lines.append(f"* {name}: {s.get('seconds')} s ending {s.get('ended_at')}; kind={kind}; cpu_share={s.get('cpu_share', NA)}; top_frame={s.get('top_frame', NA)}")
            for fr in (s.get("stack") or [])[-6:]:
                lines.append(f"    * {fr}")
            if s.get("note"):
                lines.append(f"    * note: {s['note']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--before", required=True, type=Path)
    ap.add_argument("--after", required=True, type=Path)
    ap.add_argument("--markdown", type=Path, help="also write the table to this file")
    args = ap.parse_args(argv)
    before = json.loads(args.before.read_text(encoding="utf-8"))
    after = json.loads(args.after.read_text(encoding="utf-8"))
    text = render(compare_reports(before, after), before, after)
    sys.stdout.write(text)
    if args.markdown:
        args.markdown.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
