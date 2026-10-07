"""Input/output helpers for the evaluator contract (organisation lists, bulk snapshots, JSONL)."""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from ..core.util import now_iso
from ..identity.normalization import normalize_org_number

BULK_CSV_URL = "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv"
BULK_JSON_URL = "https://data.brreg.no/enhetsregisteret/api/enheter/lastned"


class InputError(ValueError):
    pass


def _open_text(path: Path) -> io.TextIOBase:
    if path.suffix == ".gz":
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8-sig")
    return path.open("r", encoding="utf-8-sig")  # tolerate a BOM (Excel / Windows exports)


def _base_suffix(path: Path) -> str:
    return Path(path.stem).suffix if path.suffix == ".gz" else path.suffix


def read_organisation_inputs(path: str | Path) -> list[dict[str, Any]]:
    """JSON (list or {organisation_numbers|organisations}), JSONL (objects or strings) or text (one per line)."""
    source = Path(path)
    if not source.exists():
        raise InputError(f"Input file not found: {source}")
    with _open_text(source) as handle:
        text = handle.read()
    suffix = _base_suffix(source)
    values: list[Any]
    if suffix == ".json":
        body = json.loads(text)
        values = body if isinstance(body, list) else (body.get("organisation_numbers") or body.get("organisations") or body.get("companies") or [])
    elif suffix == ".jsonl":
        values = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        values = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
    records = []
    for value in values:
        raw = value.get("organisation_number") or value.get("organisasjonsnummer") or value.get("orgnr") if isinstance(value, dict) else value
        org = normalize_org_number(raw)
        if len(org) != 9:
            raise InputError(f"Invalid Norwegian organisation number: {value!r}")
        record: dict[str, Any] = {"organisation_number": org}
        if isinstance(value, dict):
            for key in ("evaluation_split", "sample_slice", "name"):
                if value.get(key) is not None:
                    record[key] = value[key]
        records.append(record)
    orgs = [r["organisation_number"] for r in records]
    if len(orgs) != len(set(orgs)):
        raise InputError("Organisation-number input contains duplicates")
    return records


def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}" if prefix else str(k), v, out)
    elif isinstance(value, list) and all(isinstance(v, str) for v in value):
        out[prefix] = ", ".join(v for v in value if v)
    else:
        out[prefix] = value


def normalise_bulk_row(row: dict[str, Any]) -> dict[str, Any]:
    """Universe JSONL row, BRREG CSV row or nested BRREG JSON entity → flat row understood by ``identity_from_bulk``."""
    flat: dict[str, Any] = {}
    _flatten("", row, flat)
    org = normalize_org_number(flat.get("organisation_number") or flat.get("organisasjonsnummer"))
    flat["organisation_number"] = org
    return flat


def _iter_json_array(handle: io.TextIOBase, chunk: int = 1 << 20) -> Iterator[dict[str, Any]]:
    """Stream objects from a (possibly huge) JSON array without loading it whole."""
    decoder = json.JSONDecoder()
    buf = ""
    started = False
    while True:
        data = handle.read(chunk)
        buf += data
        if not started:
            buf = buf.lstrip()
            if not buf:
                if not data:
                    return
                continue
            if buf[0] != "[":
                raise InputError("JSON bulk file must be an array of entities")
            buf = buf[1:]
            started = True
        while True:
            buf = buf.lstrip().lstrip(",").lstrip()
            if not buf or buf[0] == "]":
                break
            try:
                obj, end = decoder.raw_decode(buf)
            except ValueError:
                break  # need more data
            yield obj
            buf = buf[end:]
        if not data:
            return


def iter_bulk(path: str | Path) -> Iterator[dict[str, Any]]:
    source = Path(path)
    suffix = _base_suffix(source)
    with _open_text(source) as handle:
        if suffix == ".csv":
            sample = handle.read(4096)
            handle.seek(0)
            delimiter = ";" if sample.count(";") > sample.count(",") else ","
            for row in csv.DictReader(handle, delimiter=delimiter):
                yield normalise_bulk_row(row)
        elif suffix == ".jsonl":
            for line in handle:
                if line.strip():
                    yield normalise_bulk_row(json.loads(line))
        elif suffix == ".json":
            for obj in _iter_json_array(handle):
                if isinstance(obj, dict):
                    yield normalise_bulk_row(obj)
        else:
            raise InputError(f"Unsupported bulk format: {source.name} (use .csv, .jsonl or .json, optionally .gz)")


def load_bulk(path: str | Path | None, wanted: Iterable[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Return ({org: row} for wanted orgs, metadata). A missing bulk file is allowed (live register only)."""
    if not path:
        return {}, {"bulk": None}
    source = Path(path)
    if not source.exists():
        raise InputError(f"Bulk snapshot not found: {source}")
    digest = hashlib.sha256()
    with source.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    wanted_set = set(wanted)
    found: dict[str, dict[str, Any]] = {}
    scanned = 0
    for row in iter_bulk(source):
        scanned += 1
        org = row.get("organisation_number")
        if org in wanted_set and org not in found:
            found[org] = row
            if len(found) == len(wanted_set):
                break
    suffix = _base_suffix(source)
    meta = {
        "bulk": source.name,
        "source_url": BULK_CSV_URL if suffix == ".csv" else BULK_JSON_URL,
        "content_sha256": digest.hexdigest(),
        "retrieved_at": now_iso(),
        "rows_scanned": scanned,
        "selected": len(found),
        "missing": sorted(wanted_set - set(found))[:50],
    }
    return found, meta


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")
    tmp.replace(target)


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    with _open_text(source) as handle:
        return [json.loads(line) for line in handle if line.strip()]
