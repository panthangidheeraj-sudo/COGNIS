"""Candidates → the activity timeline: validated, consolidated, judged and ranked.

A *candidate* is one dated statement that already passed the publication gate (a newsroom item, a procurement notice, a register entry…).
This module decides which candidates can be shown at all, merges duplicates, and gives each remaining event its tier, score and reasons.

Nothing is invented and nothing unsupported is shown: a candidate without a valid date, a source URL and an evidence excerpt is excluded
(and counted), and a news-like candidate whose evidence does not contain its own headline is excluded as unsupported.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from ..core.util import fold
from ..extraction.boilerplate import is_boilerplate
from .consolidate import group_duplicates, headline_tokens
from .significance import MAJOR, RELEVANT, ROUTINE, Amount, Judgement, RevenueContext, judge, judge_registry

SOURCE_TYPES = ("investor_relations", "company_newsroom", "public_procurement", "official_registry", "secondary_news")
AUTHORITY = {t: i for i, t in enumerate(SOURCE_TYPES)}  # lower = preferred as the headline source
TIER_ORDER = {MAJOR: 0, RELEVANT: 1, ROUTINE: 2}
MAX_EVENTS = 150
REGISTRY_TYPE = {"establishment": "location"}  # every other register entry is a "registration"


@dataclass
class Candidate:
    id: str
    date: str
    title: str
    origin: str  # one of SOURCE_TYPES
    evidence: list[dict[str, Any]]
    description: str | None = None
    url: str | None = None  # the announcement itself (may differ from the page the text was read on)
    registry_kind: str | None = None  # registration | founded | establishment | subsidiary | name_change | group
    type_hint: str | None = None
    notice_id: str | None = None
    amount: Amount | None = None
    check_headline: bool = False  # news-like: the stored excerpt must contain the headline


@dataclass
class Excluded:
    title: str
    date: str | None
    reason: str
    origin: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title[:160], "date": self.date, "reason": self.reason, **({"sourceType": self.origin} if self.origin else {})}


@dataclass
class Timeline:
    events: list[dict[str, Any]] = field(default_factory=list)
    excluded: list[Excluded] = field(default_factory=list)
    omitted: int = 0  # routine events beyond MAX_EVENTS (never silent: reported)
    consolidated: int = 0  # duplicate reports merged into another event

    def counts(self) -> dict[str, int]:
        return {t: sum(1 for e in self.events if e["significance"] == t) for t in (MAJOR, RELEVANT, ROUTINE)}


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", fold(text)).strip()


def unsupported_reason(c: Candidate, today: date) -> str | None:
    """Why a candidate cannot be shown, or None. Every event needs a real date, a source URL and the evidence excerpt it was read from."""
    try:
        day = date.fromisoformat(c.date)
    except (TypeError, ValueError):
        return "no valid date"
    if day > today + timedelta(days=1):
        return "dated in the future, so not an event that has happened"
    if len(re.sub(r"\W", "", c.title or "")) < 8:
        return "no usable headline"
    if is_boilerplate(c.title):
        return "the headline is page navigation or boilerplate text, not an announcement"
    if not c.evidence:
        return "no supporting evidence is stored"
    if not any(str(ev.get("url") or "").startswith(("http://", "https://")) for ev in c.evidence) and not str(c.url or "").startswith(("http://", "https://")):
        return "no source URL"
    spans = [str(ev.get("excerpt") or "") for ev in c.evidence]
    if not any(s.strip() for s in spans):
        return "no evidence excerpt is stored"
    if c.check_headline:
        head = _norm(c.title)[:48]
        if head and not any(head in _norm(s) for s in spans):
            return "the stored evidence does not contain the headline"
    return None


def _source_entries(c: Candidate) -> list[dict[str, Any]]:
    """The places that state this announcement: one entry per distinct URL its evidence was read from (falling back to the announcement link)."""
    entries: dict[str | None, dict[str, Any]] = {}
    for ev in c.evidence:
        url = ev.get("url") or None
        entry = entries.setdefault(url, {"sourceIds": [], "sourceType": c.origin, "url": url, "title": c.title, "date": c.date})
        if ev.get("sourceId") and ev["sourceId"] not in entry["sourceIds"]:
            entry["sourceIds"].append(ev["sourceId"])
    if not entries:
        entries[c.url] = {"sourceIds": [], "sourceType": c.origin, "url": c.url, "title": c.title, "date": c.date}
    return list(entries.values())


def build_timeline(candidates: list[Candidate], *, today: date, revenue: RevenueContext | None = None, company_words: set[str] | None = None) -> Timeline:
    out = Timeline()
    valid: list[Candidate] = []
    for c in candidates:
        reason = unsupported_reason(c, today)
        if reason:
            out.excluded.append(Excluded(c.title or "(no headline)", c.date if re.match(r"^\d{4}-\d{2}-\d{2}$", c.date or "") else None, reason, c.origin))
        else:
            valid.append(c)
    items = [{"title": c.title, "date": c.date, "notice_id": c.notice_id, "kind_group": "registry" if c.registry_kind else "news"} for c in valid]
    drop = company_words or set()
    for members in group_duplicates(items, company_words=drop):
        group = [valid[i] for i in members]
        primary = sorted(group, key=lambda c: (AUTHORITY.get(c.origin, 9), -len(c.description or ""), c.date))[0]
        evidence: list[dict[str, Any]] = []
        seen_ev: set[str] = set()
        for c in [primary, *[g for g in group if g is not primary]]:
            for ev in c.evidence:
                if ev.get("id") not in seen_ev:
                    seen_ev.add(ev.get("id"))
                    evidence.append(ev)
        sources: list[dict[str, Any]] = []
        seen_src: set[str | None] = set()
        for c in [primary, *[g for g in group if g is not primary]]:
            for entry in _source_entries(c):
                if entry["url"] not in seen_src:
                    seen_src.add(entry["url"])
                    sources.append(entry)
        description = primary.description or next((c.description for c in sorted(group, key=lambda c: -len(c.description or "")) if c.description), None)
        origins = {c.origin for c in group}
        if primary.registry_kind:
            j: Judgement = judge_registry(primary.registry_kind, primary.date, today=today)
            ev_type = REGISTRY_TYPE.get(primary.registry_kind, "registration")
        else:
            j = judge(primary.title, description, primary.date, source_type=primary.origin, today=today, type_hint=primary.type_hint,
                      amount=primary.amount or next((c.amount for c in group if c.amount), None), revenue=revenue, corroborating_types=len(origins))
            ev_type = j.category
        reasons = list(j.reasons)
        if len(sources) > 1:
            reasons.append(f"The same announcement was found in {len(sources)} places; shown once, with all its sources")
        out.consolidated += len(group) - 1
        event: dict[str, Any] = {
            "id": primary.id, "date": primary.date, "type": ev_type, "title": primary.title, "significance": j.tier, "score": j.score, "reasons": reasons,
            "sourceType": primary.origin, "sourceIds": sorted({sid for s in sources for sid in s["sourceIds"]}), "evidence": evidence, "sources": sources,
        }
        if description:
            event["description"] = description
        url = primary.url or next((ev.get("url") for ev in primary.evidence if ev.get("url")), None)
        if url:
            event["url"] = url
        if len(group) > 1:
            event["duplicates"] = len(group) - 1
        out.events.append(event)
    # rank: tier, then score, then recency; keep everything important when there are very many events
    ranked = sorted(out.events, key=lambda e: (TIER_ORDER[e["significance"]], -e["score"], _neg_date(e["date"])))
    if len(ranked) > MAX_EVENTS:
        out.omitted = len(ranked) - MAX_EVENTS
        ranked = ranked[:MAX_EVENTS]
    for i, e in enumerate(ranked, 1):
        e["rank"] = i
    out.events = sorted(ranked, key=lambda e: (e["date"], -e["rank"]), reverse=True)
    return out


def _neg_date(day: str) -> int:
    try:
        return -date.fromisoformat(day).toordinal()
    except ValueError:
        return 0


def company_words(legal_name: str | None) -> set[str]:
    """Words of the company's own name, ignored when comparing headlines (every headline mentions the company)."""
    return headline_tokens(legal_name or "")
