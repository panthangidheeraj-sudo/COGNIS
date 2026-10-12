#!/usr/bin/env python3
"""Import DFØ's open Doffin dataset (one or more yearly files) for the procurement enrichment.

Download the files from data.norge.no ("Kunngjøringer av offentlige anskaffelser", publisher DFØ), then:

    python scripts/import_doffin_open_data.py path/to/doffin-2024.csv path/to/doffin-2025.csv
    python scripts/import_doffin_open_data.py file.csv --dry-run          # show which columns were recognised
    python scripts/import_doffin_open_data.py file.csv --period 2024 --map winner_org="Leverandør org.nr"

A notice is linked to a company only through an organisation-number column whose role is known (buyer or
supplier). Re-importing a file replaces that file's rows. Facts are shown with the dataset period.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import bootstrap


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--period", help="dataset period label, e.g. 2024 (default: span of publication dates in the file)")
    p.add_argument("--map", action="append", default=[], metavar="FIELD=HEADER",
                   help="map a column explicitly; fields: notice_id, title, notice_type, published, buyer_name, buyer_org, winner_name, winner_org")
    p.add_argument("--dry-run", action="store_true", help="parse and report only; store nothing")
    args = p.parse_args()
    bootstrap(quiet=True)
    from app.connectors.doffin_open_data import import_file
    from app.storage.db import get_db

    explicit = {}
    for item in args.map:
        field, _, header = item.partition("=")
        explicit[field.strip()] = header.strip().strip('"')
    db = get_db()
    failed = False
    for path in args.files:
        if not path.exists():
            print(f"{path}: not found")
            failed = True
            continue
        report = import_file(db, path, period=args.period, explicit=explicit, dry_run=args.dry_run)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        failed = failed or not report["linkable_notices"]
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
