"""One announcement, many sources: group duplicates so an event appears once, with every source that reported it.

Two items describe the same announcement when they fall within a few days of each other and their headlines say the same thing (shared
distinctive words, shared figures), or when they are the same procurement notice. The company's own wording is kept as the headline.
"""
from __future__ import annotations

import re
from datetime import date

from ..core.util import fold

DATE_WINDOW_DAYS = 3  # news coverage usually follows the company's own release within a day or two

_STOP = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "with", "by", "at", "as", "from", "its", "is", "are", "has", "have", "will", "new", "says", "said", "after", "over",
    "og", "i", "på", "av", "til", "med", "en", "et", "den", "det", "som", "har", "er", "fra", "om", "ved", "nye", "ny", "nytt", "etter", "skal", "blir",
    "press", "release", "announces", "announced", "announcement", "kunngjør", "melder", "pressemelding", "nyhet", "news",
}
_TOKEN = re.compile(r"[\w$€£%]+(?:[.,]\d+)?", re.UNICODE)


def headline_tokens(title: str, drop: set[str] | None = None) -> set[str]:
    out: set[str] = set()
    for raw in _TOKEN.findall(fold(title)):
        tok = raw.strip(".,")
        if len(tok) < 2 or tok in _STOP or (drop and tok in drop):
            continue
        out.add(tok[:-1] if len(tok) > 5 and tok.endswith("s") else tok)  # contracts ≈ contract
    return out


def _days_apart(a: str, b: str) -> int:
    try:
        return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)
    except ValueError:
        return 10_000


def similarity(a: set[str], b: set[str]) -> tuple[float, float, int]:
    """(Jaccard, containment of the shorter in the longer, number of shared words)."""
    if not a or not b:
        return 0.0, 0.0, 0
    shared = a & b
    return len(shared) / len(a | b), len(shared) / min(len(a), len(b)), len(shared)


def same_announcement(a_title: str, a_date: str, b_title: str, b_date: str, *, company_words: set[str] | None = None) -> bool:
    """Do two headlines, dated within a few days of each other, report the same announcement?"""
    if _days_apart(a_date, b_date) > DATE_WINDOW_DAYS:
        return False
    ta, tb = headline_tokens(a_title, company_words), headline_tokens(b_title, company_words)
    jac, contain, shared = similarity(ta, tb)
    if fold(a_title) == fold(b_title):
        return True
    figures_a = {t for t in ta if any(c.isdigit() for c in t)}
    figures_b = {t for t in tb if any(c.isdigit() for c in t)}
    if figures_a and figures_b and not (figures_a & figures_b):
        return False  # different amounts or periods: different announcements
    return (jac >= 0.5 and shared >= 3) or (contain >= 0.75 and shared >= 3) or (jac >= 0.34 and shared >= 4)


class _Groups:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        ri, rj = self.find(i), self.find(j)
        if ri != rj:
            self.parent[max(ri, rj)] = min(ri, rj)


def group_duplicates(items: list[dict], *, company_words: set[str] | None = None) -> list[list[int]]:
    """Indices of ``items`` grouped by announcement. Each item needs ``date``, ``title`` and optionally ``notice_id`` (procurement)."""
    g = _Groups(len(items))
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if a.get("notice_id") and a.get("notice_id") == b.get("notice_id"):
                g.union(i, j)
            elif a.get("kind_group") != b.get("kind_group") and "registry" in (a.get("kind_group"), b.get("kind_group")):
                continue  # a register entry is never merged into a press release
            elif same_announcement(a["title"], a["date"], b["title"], b["date"], company_words=company_words):
                g.union(i, j)
    groups: dict[int, list[int]] = {}
    for i in range(len(items)):
        groups.setdefault(g.find(i), []).append(i)
    return list(groups.values())
