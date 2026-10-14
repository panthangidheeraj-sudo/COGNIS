"""Recent-activity intelligence: classification, ranking, duplicate consolidation and the rules that keep unsupported claims out.

Pure unit tests of ``app.events`` (no network). The end-to-end behaviour — newsroom discovery, robots.txt, source limitations, the saved record →
profile — is covered in ``test_activity.py``.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from app.events.consolidate import group_duplicates, same_announcement
from app.events.dates import find_dates, first_date
from app.events.significance import MAJOR, RELEVANT, ROUTINE, Amount, RevenueContext, find_amounts, judge, judge_registry
from app.events.timeline import Candidate, build_timeline, company_words, unsupported_reason

TODAY = date(2026, 10, 12)


def ago(days: int) -> str:
    return (TODAY - timedelta(days=days)).isoformat()


def tier(title: str, description: str | None = None, *, days: int = 10, source: str = "company_newsroom", **kw: Any) -> str:
    return judge(title, description, ago(days), source_type=source, today=TODAY, **kw).tier


def ev(i: int, url: str = "https://www.firma.no/nyheter", excerpt: str = "x", source_id: str = "web-1") -> dict[str, Any]:
    return {"id": f"ev-{i}", "sourceId": source_id, "url": url, "excerpt": excerpt}


def cand(i: int, title: str, days: int, origin: str = "company_newsroom", *, excerpt: str | None = None, url: str = "https://www.firma.no/nyheter", **kw: Any) -> Candidate:
    return Candidate(id=f"c{i}", date=ago(days), title=title, origin=origin, evidence=[ev(i, url, excerpt if excerpt is not None else title)], url=url, **kw)


def registry(i: int, kind: str, days: int, title: str | None = None) -> Candidate:
    return Candidate(id=f"r{i}", date=ago(days), title=title or f"Establishment opened: AVD {i}", origin="official_registry", registry_kind=kind,
                     evidence=[ev(1000 + i, "https://data.brreg.no/enhetsregisteret/api/underenheter", f"underenhet {i}", "subunits")])


# ----------------------------------------------------------------------------- dates --
def test_dates_are_read_in_norwegian_and_english_formats() -> None:
    found = [d.iso for d in find_dates("Publisert 14. august 2026, oppdatert 03.09.2025. Also 5 Aug 2024, August 5, 2024 and 2026-01-02.")]
    assert found == ["2026-08-14", "2025-09-03", "2024-08-05", "2024-08-05", "2026-01-02"]
    assert first_date("Pressemelding 20.06.2026 kl. 08:00").iso == "2026-06-20"
    assert first_date("no date in this text") is None
    assert first_date("31.02.2026") is None  # impossible dates are not repaired


# ------------------------------------------------------------------- classification --
@pytest.mark.parametrize("title,expected", [
    ("AUTOBJØRN signerer rammeavtale verdt 120 millioner kroner med Statens vegvesen", MAJOR),
    ("Wins NOK 2.4 billion contract with Equinor", MAJOR),
    ("Acquires Biler Nord AS for NOK 300 million", MAJOR),
    ("Autobjørn kjøper konkurrent for 300 millioner kroner", MAJOR),
    ("Q2 2026 results: revenue up 14 percent", MAJOR),
    ("Resultater for andre kvartal 2026", MAJOR),
    ("Oil discovery in the North Sea", MAJOR),
    ("Appoints new CEO", MAJOR),
    ("Ny finansdirektør i selskapet", MAJOR),
    ("Strategic partnership and joint venture to develop offshore wind", MAJOR),
    ("Final investment decision for the Alpha project", MAJOR),
    ("Signs cooperation agreement with Acme", RELEVANT),
    ("Opens new office in Bergen", RELEVANT),
    ("Appoints new Head of Marketing", RELEVANT),
    ("Launches new product line", RELEVANT),
    ("Invitation to presentation of second quarter results", ROUTINE),
    ("Invitasjon til webinar om elbil", ROUTINE),
    ("Julehilsen fra oss alle", ROUTINE),
])
def test_headlines_are_classified_by_what_they_announce(title: str, expected: str) -> None:
    assert tier(title) == expected


def test_an_invitation_to_a_results_presentation_is_not_results() -> None:
    assert tier("Invitation to presentation of second quarter results") == ROUTINE
    assert tier("Second quarter results: operating profit up 12 percent", source="investor_relations") == MAJOR


def test_a_contract_without_material_weight_is_not_major() -> None:
    small = judge("Signs service agreement with local customer", None, ago(5), source_type="company_newsroom", today=TODAY)
    big = judge("Signs service agreement worth NOK 900 million", None, ago(5), source_type="company_newsroom", today=TODAY)
    assert small.tier != MAJOR and big.tier == MAJOR and big.score > small.score


def test_amounts_are_relative_to_revenue_in_the_same_currency_only() -> None:
    rev_nok = RevenueContext(1_000_000_000.0, "NOK")
    other = RevenueContext(1_000_000_000.0, "USD")
    amount = Amount(150_000_000.0, "NOK", "NOK 150 million")
    with_rev = judge("Signs contract", None, ago(5), source_type="company_newsroom", today=TODAY, amount=amount, revenue=rev_nok)
    other_cur = judge("Signs contract", None, ago(5), source_type="company_newsroom", today=TODAY, amount=amount, revenue=other)
    assert with_rev.score > other_cur.score  # 15 % of revenue counts only against revenue stated in the same currency
    assert not any("revenue" in r.lower() for r in other_cur.reasons)  # nothing is converted or compared across currencies


def test_amounts_never_guess_a_currency() -> None:
    assert find_amounts("Wins NOK 2.4 billion contract") == [Amount(2_400_000_000.0, "NOK", "NOK 2.4 billion")]
    assert find_amounts("contract worth EUR 50 million")[0].currency == "EUR"
    assert find_amounts("kontrakt verdt 120 millioner kroner")[0].currency is None  # "kroner" is not a currency code: nothing is assumed
    assert find_amounts("verdt 10 mill. kr")[0].currency is None
    assert find_amounts("a $5 million order")[0].currency is None  # "$" is ambiguous (USD, CAD, AUD …)


def test_recency_changes_the_score_but_not_the_kind_of_event() -> None:
    recent = judge("Wins NOK 500 million contract", None, ago(3), source_type="company_newsroom", today=TODAY)
    old = judge("Wins NOK 500 million contract", None, ago(2000), source_type="company_newsroom", today=TODAY)
    assert recent.category == old.category == "contract" and recent.score > old.score


def test_every_judgement_explains_itself() -> None:
    j = judge("Wins NOK 2.4 billion contract with Equinor", None, ago(2), source_type="company_newsroom", today=TODAY)
    assert j.reasons and any("amount" in r.lower() for r in j.reasons) and any("2026-10" in r for r in j.reasons)


# ------------------------------------------------------------------------ registry --
@pytest.mark.parametrize("kind", ["registration", "founded", "establishment", "subsidiary", "name_change", "group", "procurement_buyer"])
def test_register_entries_can_never_be_major(kind: str) -> None:
    for days in (0, 30, 400, 9000):
        j = judge_registry(kind, ago(days), today=TODAY)
        assert j.tier != MAJOR and j.score <= 49


def test_new_establishments_are_routine_even_when_recent() -> None:
    assert judge_registry("establishment", ago(2), today=TODAY).tier == ROUTINE


# ---------------------------------------------------------------------- the real issue --
def test_52_establishments_do_not_become_52_major_events() -> None:
    """The reported problem: 52 of 60 events were 'major', nearly all routine establishment registrations."""
    news = [cand(1, "Signs framework agreement worth NOK 400 million with the Norwegian Defence Materiel Agency", 20),
            cand(2, "Strategic partnership with Kongsberg to develop autonomous vessels", 45),
            cand(3, "Second quarter results: revenue up 14 percent", 60, "investor_relations"),
            cand(4, "Appoints new CFO", 90),
            cand(5, "Invitation to webinar", 15),
            cand(6, "Opens new office in Bergen", 70)]
    establishments = [registry(i, "establishment", 5 + i * 11) for i in range(52)]
    tl = build_timeline([*news, *establishments], today=TODAY)
    counts = tl.counts()
    assert len(tl.events) == 58
    assert counts[MAJOR] == 4 and counts[RELEVANT] == 1 and counts[ROUTINE] == 53  # 4 real developments, not 52
    assert all(e["significance"] == ROUTINE for e in tl.events if e["sourceType"] == "official_registry")  # register entries stay available, as routine


def test_major_contracts_and_partnerships_rank_above_routine_registrations() -> None:
    cands = [registry(i, "establishment", 3 + i) for i in range(10)]  # all more recent than the announcements
    cands += [cand(100, "Signs contract worth NOK 1.2 billion with Equinor", 120), cand(101, "Strategic partnership and joint venture to build offshore wind farms", 200)]
    tl = build_timeline(cands, today=TODAY)
    order = sorted(tl.events, key=lambda e: e["rank"])
    assert [e["id"] for e in order[:2]] == ["c100", "c101"]
    first_registry = min(e["rank"] for e in tl.events if e["sourceType"] == "official_registry")
    assert max(e["rank"] for e in tl.events if e["id"] in ("c100", "c101")) < first_registry
    assert [e["significance"] for e in order[:2]] == [MAJOR, MAJOR]


def test_events_are_returned_newest_first_and_ranked_by_significance() -> None:
    tl = build_timeline([cand(1, "Wins NOK 700 million contract", 100), cand(2, "Opens new office in Oslo", 2), cand(3, "Webinar on electric vehicles", 1)], today=TODAY)
    assert [e["date"] for e in tl.events] == sorted((e["date"] for e in tl.events), reverse=True)
    assert {e["id"]: e["rank"] for e in tl.events} == {"c1": 1, "c2": 2, "c3": 3}


# ------------------------------------------------------------------- consolidation --
def test_the_same_announcement_from_several_places_is_one_event() -> None:
    title = "Autobjørn signs framework agreement worth NOK 120 million with Statens vegvesen"
    a = cand(1, title, 10, "company_newsroom", url="https://www.autobjorn.no/nyheter/kontrakt")
    b = cand(2, title, 10, "company_newsroom", url="https://www.autobjorn.no/feed.xml")
    c = cand(3, "Autobjørn signs NOK 120 million framework agreement with Statens vegvesen", 9, "secondary_news", url="https://e24.no/naeringsliv/autobjorn-avtale")
    tl = build_timeline([a, b, c], today=TODAY, company_words=company_words("AUTOBJØRN AS"))
    assert len(tl.events) == 1 and tl.consolidated == 2
    event = tl.events[0]
    assert event["duplicates"] == 2 and len(event["sources"]) == 3 and len(event["evidence"]) == 3
    assert event["sourceType"] == "company_newsroom"  # the company's own words outrank press coverage
    assert {s["url"] for s in event["sources"]} == {"https://www.autobjorn.no/nyheter/kontrakt", "https://www.autobjorn.no/feed.xml", "https://e24.no/naeringsliv/autobjorn-avtale"}
    assert any("3 places" in r for r in event["reasons"])


def test_investor_relations_outranks_newsroom_and_press_as_the_primary_source() -> None:
    title = "Second quarter 2026 results: operating revenue up 14 percent"
    tl = build_timeline([cand(1, title, 30, "secondary_news", url="https://e24.no/q2"), cand(2, title, 30, "company_newsroom"), cand(3, title, 30, "investor_relations", url="https://www.firma.no/investor/q2")],
                        today=TODAY)
    assert len(tl.events) == 1 and tl.events[0]["sourceType"] == "investor_relations" and tl.events[0]["url"] == "https://www.firma.no/investor/q2"


def test_the_same_procurement_notice_from_ted_and_doffin_is_one_event() -> None:
    a = Candidate(id="t1", date=ago(40), title="Public contract awarded: Rammeavtale kjøretøy — buyer: Statens vegvesen", origin="public_procurement", type_hint="contract", notice_id="2026-123456",
                  evidence=[ev(1, "https://ted.europa.eu/notice/2026-123456", "award", "ted")])
    b = Candidate(id="t2", date=ago(40), title="Contract award notice: vehicles framework agreement (Doffin)", origin="public_procurement", type_hint="contract", notice_id="2026-123456",
                  evidence=[ev(2, "https://doffin.no/notices/2026-123456", "award", "doffin_open")])
    tl = build_timeline([a, b], today=TODAY)
    assert len(tl.events) == 1 and tl.events[0]["duplicates"] == 1


def test_different_announcements_are_not_merged() -> None:
    assert not same_announcement("Signs contract worth NOK 100 million with Equinor", ago(5), "Signs contract worth NOK 900 million with Equinor", ago(5))  # different figures
    assert not same_announcement("Appoints new CFO Kari Nordmann", ago(5), "Appoints new CFO Ola Hansen", ago(5))
    assert not same_announcement("Wins contract with Statens vegvesen", ago(5), "Wins contract with Statens vegvesen", ago(300))  # far apart in time
    tl = build_timeline([cand(1, "Opens new office in Bergen", 10), cand(2, "Opens new office in Tromsø", 10)], today=TODAY)
    assert len(tl.events) == 2 and tl.consolidated == 0


def test_register_entries_are_never_merged_with_news() -> None:
    groups = group_duplicates([{"title": "Opens new office in Bergen", "date": ago(3), "notice_id": None, "kind_group": "news"},
                               {"title": "Establishment opened: Opens new office in Bergen", "date": ago(3), "notice_id": None, "kind_group": "registry"}], company_words=set())
    assert sorted(len(g) for g in groups) == [1, 1]


# ------------------------------------------------------------- unsupported claims --
@pytest.mark.parametrize("change,reason", [
    (lambda c: setattr(c, "date", "2026-13-45"), "no valid date"),
    (lambda c: setattr(c, "date", ""), "no valid date"),
    (lambda c: setattr(c, "date", (TODAY + timedelta(days=60)).isoformat()), "future"),
    (lambda c: setattr(c, "title", "Wins"), "headline"),
    (lambda c: setattr(c, "evidence", []), "evidence"),
    (lambda c: setattr(c, "evidence", [{"id": "e", "sourceId": "s", "url": "https://x.example/p", "excerpt": "   "}]), "excerpt"),
    (lambda c: (setattr(c, "evidence", [{"id": "e", "sourceId": "s", "url": "", "excerpt": "Wins contract worth NOK 900 million"}]), setattr(c, "url", None)), "URL"),
    (lambda c: setattr(c, "evidence", [{"id": "e", "sourceId": "s", "url": "https://x.example/p", "excerpt": "A completely different sentence about something else."}]), "headline"),
])
def test_unsupported_candidates_are_excluded_and_counted(change: Any, reason: str) -> None:
    good = cand(2, "Opens new office in Bergen", 5, check_headline=True)
    bad = cand(1, "Wins contract worth NOK 900 million", 5, check_headline=True)
    change(bad)
    assert reason.lower() in (unsupported_reason(bad, TODAY) or "").lower()
    tl = build_timeline([bad, good], today=TODAY)
    assert [e["id"] for e in tl.events] == ["c2"]
    assert len(tl.excluded) == 1 and reason.lower() in tl.excluded[0].reason.lower()


def test_a_supported_candidate_is_accepted() -> None:
    assert unsupported_reason(cand(1, "Wins contract worth NOK 900 million", 5, excerpt="14.09.2026 Wins contract worth NOK 900 million with the Armed Forces", check_headline=True), TODAY) is None


def test_every_event_carries_date_description_source_url_source_type_and_evidence() -> None:
    c = cand(1, "Wins contract worth NOK 900 million", 5, description="Framework agreement for four years.", excerpt="Wins contract worth NOK 900 million")
    event = build_timeline([c, registry(2, "registration", 4000, "Registered in Enhetsregisteret")], today=TODAY).events
    for e in event:
        assert e["date"] and e["title"] and e["sourceType"] and e["evidence"] and e["sources"] and (e.get("url") or e["evidence"][0]["url"])
        assert all(x["url"] for x in e["evidence"]) and all(x["excerpt"] for x in e["evidence"])
    assert next(e for e in event if e["id"] == "c1")["description"] == "Framework agreement for four years."
