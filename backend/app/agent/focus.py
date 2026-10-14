"""What a research focus or custom question points at on a company's own website.

Deep research uses this to read the pages most likely to answer the question first (a hiring question → the careers page, an announcements question →
newsroom and investor pages). Only page *kinds* come out of here — the question text itself is never sent to a search engine or any other site.
"""
from __future__ import annotations

import re

GENERIC = {"", "company brief", "research this company"}
_BY_ROUTE: dict[str, list[str]] = {
    "announcements": ["news", "investors"],
    "hiring": ["careers"],
    "people": ["team", "about"],
    "locations": ["locations", "about"],
    "overview": ["about", "products"],
    "financial": ["investors"],
}
_EXTRA = (
    (re.compile(r"sustainab|climate|\besg\b|bærekraft|miljø", re.I), "sustainability"),
    (re.compile(r"products?|services?|offer\w*|produkt\w*|tjeneste\w*|løsning\w*", re.I), "products"),
)


def focus_kinds(focus: str | None) -> list[str]:
    text = (focus or "").strip()
    if text.casefold() in GENERIC:
        return []
    from ..api.question_router import route_question  # imported here: the API package imports the orchestrator

    out: list[str] = []
    for kind in route_question(text).kinds:
        out += _BY_ROUTE.get(kind, [])
    for rx, page_kind in _EXTRA:
        if rx.search(text):
            out.append(page_kind)
    return list(dict.fromkeys(out))
