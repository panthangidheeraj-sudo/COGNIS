"""Deterministic identity normalisation: organisation numbers, names, phones, addresses."""
from __future__ import annotations

import re
import unicodedata

from ..core.util import digits_only, fold

_WEIGHTS = (3, 2, 7, 6, 5, 4, 3, 2)


def org_checksum_ok(org: str) -> bool:
    """Norwegian organisation numbers use a MOD11 check digit (weights 3,2,7,6,5,4,3,2)."""
    if len(org) != 9 or not org.isdigit():
        return False
    total = sum(int(d) * w for d, w in zip(org[:8], _WEIGHTS, strict=True))
    remainder = total % 11
    check = 0 if remainder == 0 else 11 - remainder
    return check != 10 and check == int(org[8])


def normalize_org_number(value: object) -> str:
    """Digits only. Validation (length/checksum) is a separate step so bad input is never silently changed."""
    return digits_only(value)


def format_org_number(org: str) -> str:
    return f"{org[:3]} {org[3:6]} {org[6:]}" if len(org) == 9 else org


# Organisation numbers written on web pages: "923 609 016", "923609016", "NO 923 609 016 MVA", "923.609.016".
_ORG_PATTERN = re.compile(r"(?<![\d+])(\d{3})[\s .]?(\d{3})[\s .]?(\d{3})(?![\d])")
_ORG_CONTEXT = re.compile(r"(org\.?\s*(nr|nummer|no)|organisasjons\s*-?nummer|organization\s+number|organisation\s+number|foretaksregisteret|\bmva\b|\bvat\b|reg\.?\s*nr|company\s+(reg|no))", re.I)


def find_org_numbers(text: str) -> list[tuple[str, bool]]:
    """Return (org_number, in_org_context) for checksum-valid 9-digit numbers found in text."""
    found: dict[str, bool] = {}
    for match in _ORG_PATTERN.finditer(text or ""):
        number = "".join(match.groups())
        if not org_checksum_ok(number):
            continue
        window = text[max(0, match.start() - 45): match.end() + 12]
        context = bool(_ORG_CONTEXT.search(window))
        found[number] = found.get(number, False) or context
    return list(found.items())


LEGAL_SUFFIXES = {
    "as", "asa", "ans", "da", "enk", "sa", "nuf", "ba", "ks", "sf", "iks", "fli", "stiftelse", "aksjeselskap", "allmennaksjeselskap",
    "ltd", "limited", "ab", "oy", "gmbh", "inc", "llc", "a/s", "aps",
}
GENERIC_NAME_TOKENS = {
    "holding", "holdings", "invest", "investment", "investering", "eiendom", "eiendommer", "consulting", "consult", "service", "services",
    "group", "gruppen", "norge", "norway", "norsk", "nordic", "company", "selskap", "drift", "utvikling", "handel", "og", "&", "and",
    "the", "i", "avd", "avdeling", "co", "c/o", "management", "partner", "partners", "solutions", "systems", "teknikk", "bygg", "transport",
}


def _strip_accents_keep_nordic(text: str) -> str:
    out = []
    for ch in unicodedata.normalize("NFD", text):
        if unicodedata.category(ch) == "Mn":
            continue
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


def normalize_name(name: str | None) -> str:
    """Comparison form of a company name: case-folded, suffixes removed, punctuation collapsed."""
    text = fold(name).replace("&", " og ")
    text = re.sub(r"[^\w\sæøå]", " ", text)
    tokens = [t for t in text.split() if t not in LEGAL_SUFFIXES]
    return " ".join(tokens)


def name_tokens(name: str | None) -> list[str]:
    return [t for t in normalize_name(name).split() if t]


def distinctive_tokens(name: str | None) -> list[str]:
    return [t for t in name_tokens(name) if t not in GENERIC_NAME_TOKENS and len(t) >= 3]


def is_generic_name(name: str | None) -> bool:
    """True when a name has fewer than one distinctive token (high same-name collision risk)."""
    return len(distinctive_tokens(name)) == 0


def ascii_fold(text: str) -> str:
    return _strip_accents_keep_nordic(fold(text)).replace("æ", "ae").replace("ø", "o").replace("å", "a")


def name_in_text(name: str | None, text: str | None) -> bool:
    """Exact normalised legal-name occurrence (suffix-insensitive) in page text."""
    target = normalize_name(name)
    if not target or len(target) < 3:
        return False
    haystack = " " + re.sub(r"[^\w\sæøå]", " ", fold(text or "").replace("&", " og ")) + " "
    haystack = re.sub(r"\s+", " ", haystack)
    return f" {target} " in haystack


def normalize_phone(value: str | None) -> str:
    digits = digits_only(value)
    if digits.startswith("0047"):
        digits = digits[4:]
    elif digits.startswith("47") and len(digits) == 10:
        digits = digits[2:]
    return digits if len(digits) == 8 else ""


def phones_in_text(text: str) -> set[str]:
    found = set()
    for match in re.finditer(r"(?:\+47|0047)?[\s ]*((?:\d[\s .-]?){8})(?!\d)", text or ""):
        number = normalize_phone(match.group(0))
        if number:
            found.add(number)
    return found


def normalize_street(value: str | None) -> str:
    text = fold(value)
    text = re.sub(r"\b(gate|gata|gaten)\b", "gate", text)
    text = re.sub(r"\b(vei|veien|veg|vegen)\b", "vei", text)
    text = re.sub(r"[^\w\sæøå]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


WEBMAIL_DOMAINS = {
    "gmail.com", "hotmail.com", "hotmail.no", "outlook.com", "live.com", "live.no", "yahoo.com", "yahoo.no", "online.no", "icloud.com",
    "me.com", "msn.com", "frisurf.no", "start.no", "c2i.net", "getmail.no", "broadpark.no", "lyse.net", "altibox.no", "hotmail.co.uk",
    "protonmail.com", "proton.me", "mail.com", "aol.com", "gmx.com", "gmx.net", "netcom.no", "chello.no", "tele2.no", "bluezone.no",
    "ebnett.no", "haugnett.no", "enivest.net", "tdcadsl.no", "nextgentel.no", "vikenfiber.no", "loqal.no", "telia.no", "telenor.com",
}


def email_domain(value: str | None) -> str:
    if not value or "@" not in value:
        return ""
    return value.rsplit("@", 1)[1].strip().lower().rstrip(".")
