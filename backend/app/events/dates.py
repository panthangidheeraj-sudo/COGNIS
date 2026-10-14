"""Dates as printed on newsroom pages ("14. august 2026", "Aug 14, 2026", "14.08.2026", "2026-08-14") → ISO ``YYYY-MM-DD``."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

MONTHS: dict[str, int] = {
    # Norwegian
    "januar": 1, "februar": 2, "mars": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "okt": 10, "nov": 11, "des": 12,
    # English
    "january": 1, "february": 2, "march": 3, "may": 5, "june": 6, "july": 7, "october": 10, "december": 12, "oct": 10, "dec": 12,
}
_MONTH_RX = "|".join(sorted((re.escape(m) for m in MONTHS), key=len, reverse=True))

_ISO = re.compile(r"(?<!\d)(20\d{2}|19\d{2})-(\d{2})-(\d{2})(?!\d)")
_DMY_DOTS = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(20\d{2}|19\d{2})(?!\d)")
_D_MONTH_Y = re.compile(rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?\.?\s+({_MONTH_RX})\.?,?\s+(20\d{{2}}|19\d{{2}})(?!\d)", re.I)
_MONTH_D_Y = re.compile(rf"(?<![\w])({_MONTH_RX})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}}|19\d{{2}})(?!\d)", re.I)


@dataclass(frozen=True)
class FoundDate:
    iso: str
    text: str  # exactly as printed
    start: int
    end: int


def _make(y: int, m: int, d: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def find_dates(text: str) -> list[FoundDate]:
    """Every calendar date written in ``text``, in reading order, each with the wording it was printed in."""
    found: list[FoundDate] = []
    for m in _ISO.finditer(text or ""):
        iso = _make(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso:
            found.append(FoundDate(iso, m.group(0), m.start(), m.end()))
    for m in _DMY_DOTS.finditer(text or ""):
        iso = _make(int(m.group(3)), int(m.group(2)), int(m.group(1)))  # day.month.year (never month-first)
        if iso:
            found.append(FoundDate(iso, m.group(0), m.start(), m.end()))
    for m in _D_MONTH_Y.finditer(text or ""):
        iso = _make(int(m.group(3)), MONTHS[m.group(2).casefold()], int(m.group(1)))
        if iso:
            found.append(FoundDate(iso, m.group(0), m.start(), m.end()))
    for m in _MONTH_D_Y.finditer(text or ""):
        iso = _make(int(m.group(3)), MONTHS[m.group(1).casefold()], int(m.group(2)))
        if iso:
            found.append(FoundDate(iso, m.group(0), m.start(), m.end()))
    found.sort(key=lambda f: f.start)
    out: list[FoundDate] = []
    for f in found:  # overlapping readings of the same characters: keep the first
        if not out or f.start >= out[-1].end:
            out.append(f)
    return out


def first_date(text: str) -> FoundDate | None:
    dates = find_dates(text)
    return dates[0] if dates else None
