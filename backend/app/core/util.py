"""Small deterministic helpers shared by every layer (time, ids, hashing, text)."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, date, datetime
from typing import Any


# ---------------------------------------------------------------- time ----
def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def now_iso() -> str:
    return iso(utc_now())  # type: ignore[return-value]


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    for candidate in (text, text.replace(" ", "T")):
        try:
            dt = datetime.fromisoformat(candidate)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(value))
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def date_only(value: str | None) -> str | None:
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else None


# ---------------------------------------------------------------- hashing --
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_json(value: Any) -> str:
    return sha256_text(canonical_json(value))


def stable_id(*parts: Any, prefix: str = "", length: int = 16) -> str:
    digest = sha256_text("␟".join(str(p) for p in parts))[:length]
    return f"{prefix}{digest}" if prefix else digest


# ---------------------------------------------------------------- text -----
_WS = re.compile(r"\s+")


def clean_ws(text: str | None) -> str:
    return _WS.sub(" ", text or "").strip()


def fold(text: str | None) -> str:
    """Case/diacritic-insensitive comparison key (keeps æøå distinguishable from ae/o/a)."""
    value = unicodedata.normalize("NFKC", text or "").casefold()
    return clean_ws(value)


def truncate(text: str | None, limit: int) -> str:
    value = clean_ws(text)
    return value if len(value) <= limit else value[: max(0, limit - 1)].rstrip() + "…"


_SMALL_WORDS = {"i", "og", "på", "av", "for", "til", "ved", "de", "la", "le", "des"}


def title_case_no(value: str | None) -> str:
    """Title-case a Norwegian place or legal name written in upper case by the registry.

    "NORD-AURDAL" → "Nord-Aurdal", "SANDE I VESTFOLD" → "Sande i Vestfold".
    Mixed-case input is returned unchanged.
    """
    if not value:
        return ""
    text = clean_ws(value)
    if text != text.upper():
        return text
    words = []
    for index, word in enumerate(text.lower().split(" ")):
        if index > 0 and word in _SMALL_WORDS:
            words.append(word)
            continue
        words.append("-".join(part[:1].upper() + part[1:] for part in word.split("-")))
    return " ".join(words)


def digits_only(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


_CURRENCY_CODE = re.compile(r"^[A-Z]{3}$")


def normalize_currency(code: Any) -> str | None:
    """The currency a filing states (Regnskapsregisteret ``valuta``) as an upper-case ISO-4217-shaped code.

    ``None`` when it is missing or malformed. The register's own value is the only authority: nothing here ever
    falls back to NOK (or any other currency), because an assumed label next to a real amount is a false statement.
    """
    if not isinstance(code, str):
        return None
    text = code.strip().upper()
    return text if _CURRENCY_CODE.match(text) else None


def format_money(value: float | int | None, currency: str | None) -> str:
    """Compact amount labelled with the currency it was *filed* in: ``USD 67.96B``, ``−NOK 12.4M``.

    No conversion is ever applied. Without a known currency only the bare number is returned.
    """
    if value is None:
        return "—"
    v = float(value)
    sign = "−" if v < 0 else ""
    v = abs(v)
    if v >= 1e9:
        text = f"{v / 1e9:.2f}B"
    elif v >= 1e6:
        text = f"{v / 1e6:.1f}M"
    elif v >= 1e3:
        text = f"{v / 1e3:.0f}k"
    else:
        text = f"{v:.0f}"
    code = normalize_currency(currency)
    return f"{sign}{code} {text}" if code else f"{sign}{text}"


MIXED_UNIT = "mixed currencies"
NOT_STATED_UNIT = "currency not stated"


def currency_unit(currencies: list[str | None]) -> str:
    """The unit label for a set of per-fact currencies: the single code they share, else an explicit "mixed"/"not stated" label.

    Each fact keeps its own currency; this only labels a whole series/section/row. Amounts are never converted between currencies.
    """
    stated = list(dict.fromkeys(c for c in currencies if c))
    if not stated:
        return NOT_STATED_UNIT
    if len(stated) == 1 and all(currencies):
        return stated[0]
    return MIXED_UNIT


def stated_currencies(currencies: list[str | None]) -> list[str]:
    return list(dict.fromkeys(c for c in currencies if c))


def format_int(value: float | int | None) -> str:
    if value is None:
        return "—"
    return f"{int(round(value)):,}".replace(",", " ")


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
