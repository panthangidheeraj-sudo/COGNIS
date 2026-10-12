"""Free source stack: NAV job ads (exact employer resolution), procurement (TED + Doffin open data), Proff-free capability map,
and no paid API in normal competition mode. No test touches the real network."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from app.config import Settings, override_settings, validate_configuration
from app.connectors import capabilities, nav, procurement
from app.connectors.doffin_open_data import import_file, map_columns, parse_rows
from app.evidence.gate import check
from app.evidence.models import Observation
from app.identity.employer import WorkAddress, exact_legal_name, org_numbers_in, resolve_employer
from app.identity.model import CanonicalIdentity
from app.storage.db import Database
from app.testing.fixtures import FixtureNetwork, verified_site

AUTO = "810359862"  # AUTOBJØRN A/S (fixture), establishments 975014436 (AVD SALG) and 974072599 (AVD VERKSTED)
SALG = "975014436"
OTHER_ORG = "923609016"  # a different organisation (EQUINOR ASA)
LINKED_SUBUNIT = "912345688"  # not in the fixture establishment list; the register says its parent is AUTO
FAKE_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwdWJsaWMtdGVzdCJ9.c2lnbmF0dXJlLXRlc3QtdG9rZW4"
NAV = "https://pam-stilling-feed.nav.no"
ROOT = Path(__file__).resolve().parents[1]


def run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _fresh_token() -> None:
    nav.TOKEN.public = None


# ------------------------------------------------------------------ fixtures --
def _ad(uuid: str, title: str, *, orgnr: str | None, employer: str, business: str | None = None, status: str = "ACTIVE", homepage: str | None = None,
        address: str = "Industriveien 99", postcode: str = "0999", municipal: str = "OSLO", expires: str = "2099-01-31T00:00:00") -> dict[str, Any]:
    return {"uuid": uuid, "status": status, "sistEndret": "2026-10-01T10:00:00",
            "json": {"uuid": uuid, "title": title, "published": "2026-09-25T08:00:00", "updated": "2026-09-30T08:00:00", "expires": expires,
                     "link": f"https://arbeidsplassen.nav.no/stillinger/stilling/{uuid}", "sourceurl": "https://jobs.example/ad", "applicationUrl": "https://apply.example/x",
                     "employer": {"name": employer, "orgnr": orgnr, "homepage": homepage, "description": "…"}, "businessName": business or employer,
                     "workLocations": [{"country": "NORGE", "address": address, "city": municipal, "postalCode": postcode, "county": "OSLO", "municipal": municipal}],
                     "occupationCategories": [{"level1": "Bil, verksted", "level2": "Bilmekaniker"}], "engagementtype": "Fast", "extent": "Heltid", "positioncount": 1,
                     "contactList": [{"name": "Kari Kontakt", "email": "kari@example.no", "phone": "99999999"}]}}


ADS: dict[str, dict[str, Any]] = {
    "a-salg": _ad("a-salg", "Bilselger", orgnr=SALG, employer="AUTOBJØRN AS AVD SALG"),
    "a-main": _ad("a-main", "Mekaniker", orgnr=AUTO, employer="Autobjørn AS"),
    "a-linked": _ad("a-linked", "Lagermedarbeider", orgnr=LINKED_SUBUNIT, employer="Autobjørn Lager"),
    "a-wrong": _ad("a-wrong", "Selger Bergen", orgnr=OTHER_ORG, employer="Autobjørn Bergen AS"),
    "a-nameonly": _ad("a-nameonly", "Dekkskifter", orgnr=None, employer="AUTOBJØRN A/S"),  # exact name + municipality only → ambiguous
    "a-stopped": _ad("a-stopped", "Stoppet annonse", orgnr=AUTO, employer="Autobjørn AS", status="INACTIVE"),
    "a-later-inactive": _ad("a-later-inactive", "Bilpleier", orgnr=AUTO, employer="Autobjørn AS"),
}


def _summary(ad: dict[str, Any], status: str | None = None) -> dict[str, Any]:
    j = ad["json"]
    return {"id": ad["uuid"], "url": f"/api/v1/feedentry/{ad['uuid']}", "title": j["title"], "date_modified": ad["sistEndret"],
            "_feed_entry": {"uuid": ad["uuid"], "status": status or "ACTIVE", "title": j["title"], "businessName": j["businessName"], "municipal": "OSLO",
                            "sistEndret": ad["sistEndret"]}}


def nav_handler(calls: list[str]):
    pages = {
        f"{NAV}/api/v1/feed": {"id": "p1", "items": [_summary(a) for k, a in ADS.items()], "next_url": "/api/v1/feed/p2"},
        f"{NAV}/api/v1/feed/p2": {"id": "p2", "items": [_summary(ADS["a-later-inactive"], "INACTIVE")], "next_url": None},
    }

    def handle(request: httpx.Request) -> httpx.Response | None:
        url = str(request.url)
        if not url.startswith(NAV):
            return None
        calls.append(url)
        if url == f"{NAV}/api/publicToken":
            return httpx.Response(200, text=f"Public token for testing: {FAKE_TOKEN}")
        if request.headers.get("authorization") != f"Bearer {FAKE_TOKEN}":
            return httpx.Response(401, text="unauthorized")
        if url in pages:
            return httpx.Response(200, json=pages[url], headers={"etag": f'"{url[-2:]}"', "last-modified": "Wed, 07 Oct 2026 10:00:00 GMT"})
        if "/api/v1/feedentry/" in url:
            uuid = url.rsplit("/", 1)[1]
            return httpx.Response(200, json=ADS[uuid]) if uuid in ADS else httpx.Response(404, json={})
        return httpx.Response(404, json={})
    return handle


TED_NOTICES = {
    "totalNoticeCount": 3,
    "notices": [
        {"publication-number": "301234-2024", "publication-date": "2024-05-17+02:00", "notice-type": "can-standard",
         "notice-title": {"eng": "Vehicle maintenance services", "nor": "Vedlikehold av kjøretøy"}, "buyer-name": {"nor": ["Oslo kommune"]},
         "buyer-identifier": ["974 820 994"], "winner-name": {"nor": ["AUTOBJØRN A/S"]}, "winner-identifier": ["NO 810 359 862 MVA"],
         "classification-cpv": ["50112000"], "total-value": [1250000], "total-value-cur": ["NOK"],
         "links": {"html": {"ENG": "https://ted.europa.eu/en/notice/-/detail/301234-2024"}}},
        {"publication-number": "400001-2025", "publication-date": "2025-02-03+01:00", "notice-type": "can-standard",
         "notice-title": {"eng": "Car rental"}, "buyer-name": {"nor": ["Bergen kommune"]}, "winner-name": {"nor": ["AUTOBJØRN A/S"]},
         "winner-identifier": ["NO 923 609 016 MVA"]},  # same name, different organisation number → not used
        {"publication-number": "500002-2025", "publication-date": "2025-06-10+02:00", "notice-type": "cn-standard",
         "notice-title": {"eng": "Workshop equipment"}, "buyer-name": {"nor": ["Autobjørn A/S"]}, "buyer-identifier": ["810359862"]},
    ],
}


def ted_handler(bodies: list[Any]):
    def handle(request: httpx.Request) -> httpx.Response | None:
        if str(request.url) != "https://api.ted.europa.eu/v3/notices/search":
            return None
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=TED_NOTICES)
    return handle


def network() -> tuple[FixtureNetwork, list[str], list[Any]]:
    net = FixtureNetwork()
    net.load_brreg_probes()
    net.add_json(f"https://data.brreg.no/enhetsregisteret/api/underenheter/{LINKED_SUBUNIT}", {"organisasjonsnummer": LINKED_SUBUNIT, "overordnetEnhet": AUTO})
    calls: list[str] = []
    bodies: list[Any] = []
    net.handlers += [nav_handler(calls), ted_handler(bodies)]
    return net, calls, bodies


async def research_with_db(net: FixtureNetwork, db: Database, org: str = AUTO, *, mode: str = "deep") -> dict[str, Any]:
    from app.agent.orchestrator import Orchestrator, ResearchOptions
    from app.config import get_settings
    from app.net.http import HttpClient
    from app.providers.fake_provider import FakeProvider
    from app.runtime.budgets import BudgetLimits, RunBudget

    async with HttpClient(transport=net.transport(), sleep=lambda _s: asyncio.sleep(0)) as http:
        await nav.sync_feed(http, db, get_settings())
        orch = Orchestrator(http=http, run_budget=RunBudget(BudgetLimits(max_requests=500)), provider=FakeProvider(), db=db)
        return await orch.research(org, run_id="test", options=ResearchOptions(mode=mode, include_geo=False))


def ident() -> CanonicalIdentity:
    return CanonicalIdentity(org_number=AUTO, legal_name="AUTOBJØRN A/S", legal_form="AS", municipality="OSLO",
                             business_address={"adresse": ["Cecilie Thoresens vei 5-7"], "postnummer": "1153", "kommune": "OSLO"})


ESTABLISHMENTS = [{"organisation_number": SALG, "name": "AUTOBJØRN AS AVD SALG", "address": {"adresse": ["Cecilie Thoresens vei 7"], "postnummer": "1153", "kommune": "OSLO"}},
                  {"organisation_number": "974072599", "name": "AUTOBJØRN AS AVD VERKSTED", "address": {"adresse": ["Cecilie Thoresens vei 7"], "postnummer": "1153"}}]


# ------------------------------------------------------- NAV identity rules --
def test_nav_employer_identity_matching() -> None:
    async def parent(org: str) -> str | None:
        return AUTO if org == LINKED_SUBUNIT else ""

    i = ident()
    main = run(resolve_employer(i, record_org_number="810 359 862", record_name="Autobjørn AS"))
    est = run(resolve_employer(i, record_org_number=SALG, record_name="AUTOBJØRN AS AVD SALG", establishments=ESTABLISHMENTS))
    linked = run(resolve_employer(i, record_org_number=LINKED_SUBUNIT, record_name="Autobjørn Lager", establishments=ESTABLISHMENTS, parent_of=parent))
    by_domain = run(resolve_employer(i, record_org_number=None, record_name="AUTOBJØRN A/S", record_homepage="https://www.autobjorn.no/jobb",
                                     verified_domain="autobjorn.no"))
    by_address = run(resolve_employer(i, record_org_number=None, record_name="Autobjørn AS", establishments=ESTABLISHMENTS,
                                      work_addresses=[WorkAddress(street="Cecilie Thoresens vei 7", postal_code="1153", municipality="OSLO")]))
    assert (main.status, main.basis, main.exact) == ("exact", "org_number", True)
    assert (est.status, est.basis) == ("exact", "registered_establishment")
    assert (linked.status, linked.basis) == ("exact", "subunit_parent")
    assert by_domain.exact and "verified_domain" in by_domain.signals
    assert by_address.exact and "registered_address" in by_address.signals


def test_nav_wrong_company_rejection() -> None:
    async def parent(org: str) -> str | None:
        return ""  # not a sub-unit of anything: a main unit of another organisation

    res = run(resolve_employer(ident(), record_org_number=OTHER_ORG, record_name="Autobjørn Bergen AS", establishments=ESTABLISHMENTS, parent_of=parent))
    assert res.status == "wrong_company" and not res.exact and OTHER_ORG in res.reason
    # an establishment of a different organisation is also the wrong company
    async def other_parent(org: str) -> str | None:
        return OTHER_ORG
    res2 = run(resolve_employer(ident(), record_org_number=LINKED_SUBUNIT, record_name="AUTOBJØRN AS", parent_of=other_parent))
    assert res2.status == "wrong_company" and not res2.exact
    # a lookup that fails is never treated as a match
    async def unknown(org: str) -> str | None:
        return None
    assert run(resolve_employer(ident(), record_org_number=LINKED_SUBUNIT, record_name="Autobjørn", parent_of=unknown)).status == "unresolved"


def test_nav_ambiguous_employer_rejection() -> None:
    i = ident()
    # exact registered name and the same municipality, but no number, no verified website and no registered address → ambiguous
    same_name = run(resolve_employer(i, record_org_number=None, record_name="AUTOBJØRN A/S", work_addresses=[WorkAddress("Industriveien 99", "0999", "OSLO")]))
    assert same_name.status == "ambiguous" and not same_name.exact and "municipality" in same_name.reason
    # a name that only resembles the registered one
    similar = run(resolve_employer(i, record_org_number=None, record_name="Autobjørn Bergen", record_homepage="https://www.autobjorn.no", verified_domain="autobjorn.no"))
    assert similar.status == "ambiguous" and not similar.exact
    # a website that is not the verified one does not confirm anything
    other_site = run(resolve_employer(i, record_org_number=None, record_name="AUTOBJØRN A/S", record_homepage="https://autobjorn-bil.no", verified_domain="autobjorn.no"))
    assert other_site.status == "ambiguous"
    # an invalid number is not a number
    bad = run(resolve_employer(i, record_org_number="810359863", record_name="Noe Annet AS"))
    assert bad.status == "unresolved" and "not a valid organisation number" in bad.reason
    # a generic registered name can never match on name alone
    generic = CanonicalIdentity(org_number="912345696", legal_name="HOLDING AS", legal_form="AS")
    assert run(resolve_employer(generic, record_org_number=None, record_name="Holding AS", record_homepage="https://x.no", verified_domain="x.no")).status == "ambiguous"
    assert exact_legal_name("AUTOBJØRN ASA", i) is False


# ------------------------------------------------------------- NAV feed/index --
def test_nav_feed_sync_and_inactive_job_removal(settings: Settings) -> None:
    net, calls, _ = network()
    db = Database(":memory:")

    async def go() -> dict[str, Any]:
        from app.net.http import HttpClient

        async with HttpClient(transport=net.transport()) as http:
            return await nav.sync_feed(http, db, settings)

    report = run(go())
    index = nav.NavIndex(db)
    assert report["status"] == "up_to_date" and report["pages"] == 2
    assert index.counts()["INACTIVE"] == 1
    # the ad that became inactive is masked: no title or name is kept, and it is no longer a candidate
    row = db.one("SELECT * FROM nav_ads WHERE uuid = 'a-later-inactive'")
    assert row["status"] == "INACTIVE" and row["title"] is None and row["business_name"] is None
    cands = {c["uuid"] for c in index.candidates(["AUTOBJØRN A/S"], limit=50)}
    assert "a-later-inactive" not in cands and {"a-salg", "a-main", "a-wrong"} <= cands
    assert index.inactive(["a-later-inactive", "a-main"]) == {"a-later-inactive"}
    # the first request asks for the six-month window; the token is never written to the index or state
    assert calls[0].endswith("/api/publicToken")
    assert FAKE_TOKEN not in json.dumps([dict(r) for r in db.all("SELECT * FROM nav_feed_state")])
    # a second sync polls the tail page with its validators
    run(go())
    assert nav.NavIndex(db).state()["caught_up"] == 1


def test_nav_research_publishes_only_exact_employers(settings: Settings) -> None:
    net, calls, _ = network()
    net.add_site("autobjorn.no", verified_site("AUTOBJØRN A/S", AUTO, jobs=["Bilselger"]))
    db = Database(":memory:")
    rec = run(research_with_db(net, db))
    posts = [c for c in rec["claims"] if c["field"] == "job_posting"]
    nav_posts = {c["key_suffix"]: c for c in posts if c["source_class"] == "official_job_feed"}
    assert set(nav_posts) == {"nav-a-salg", "nav-a-main", "nav-a-linked"}
    bases = {k: c["attributes"]["identity_basis"] for k, c in nav_posts.items()}
    assert bases == {"nav-a-salg": "registered_establishment", "nav-a-main": "org_number", "nav-a-linked": "subunit_parent"}
    # wrong company, ambiguous name-only, and the ad that NAV reports INACTIVE are never published
    texts = json.dumps(rec["claims"], ensure_ascii=False)
    assert "Selger Bergen" not in texts and "Dekkskifter" not in texts and "Stoppet annonse" not in texts
    cands = {c["uuid"]: c for c in rec["jobs"]["nav"]["candidates"]}
    assert cands["a-wrong"]["status"] == "wrong_company" and cands["a-nameonly"]["status"] == "ambiguous"
    assert "a-stopped" not in cands and nav.NavIndex(db).inactive(["a-stopped"]) == {"a-stopped"}
    # evidence keeps the ad URL and the published/expiry dates; contact persons are never kept
    ev = next(e for e in rec["evidence"] if e["source_class"] == "official_job_feed")
    assert ev["source_url"].startswith("https://arbeidsplassen.nav.no/stillinger/stilling/") and "published 2026-09-25" in ev["claim_span"]
    assert "kari@example.no" not in json.dumps(rec, ensure_ascii=False) and "Kari Kontakt" not in json.dumps(rec, ensure_ascii=False)
    attrs = nav_posts["nav-a-main"]["attributes"]
    assert attrs["posted_at"] == "2026-09-25" and attrs["valid_through"] == "2099-01-31" and attrs["updated_at"].startswith("2026-09-30")
    # one count across company careers and NAV (the shared title "Bilselger" is counted once)
    count = next(c for c in rec["claims"] if c["field"] == "open_positions_count")
    assert count["value"] == 3 and {"jobs", "nav"} <= {e["source_id"] for e in rec["evidence"] if e["id"] in count["evidence_ids"]}


def test_nav_absence_is_not_evidence_and_profile_hides_inactive(settings: Settings) -> None:
    from app.api.profile_builder import build_profile

    net, _, _ = network()
    db = Database(":memory:")
    rec = run(research_with_db(net, db, "810034882"))  # another fixture company: no NAV ad names it
    mod = rec["modules"]["nav_jobs"]
    assert mod["state"] == "available" and "not evidence that the company is not hiring" in mod["note"]
    assert not [c for c in rec["claims"] if c["field"] == "open_positions_count" and c["value"] == 0 and c["source_class"] == "official_job_feed"]

    net2, _, _ = network()
    rec2 = run(research_with_db(net2, Database(":memory:")))
    shown = {j["id"] for j in build_profile(rec2)["hiring"]["jobs"]}
    hidden = {j["id"] for j in build_profile(rec2, inactive_job_ids={"a-main"})["hiring"]["jobs"]}
    assert f"{AUTO}-job-nav-a-main" in shown and f"{AUTO}-job-nav-a-main" not in hidden
    assert "nav" in build_profile(rec2)["hiring"]["searchedSourceIds"]


def test_nav_parsers_tolerate_schema_drift() -> None:
    items, nxt = nav.parse_feed_page({"items": [{"id": "x", "url": "/api/v1/feedentry/x", "_feed_entry": {"uuid": "x", "status": "INACTIVE"}}, {"no": "uuid"}],
                                      "next_url": None})
    assert [(i.uuid, i.status) for i in items] == [("x", "INACTIVE")] and nxt is None
    ad = nav.parse_entry({"uuid": "y", "status": "ACTIVE", "json": {"title": "T", "employer": {"orgnr": "810359862"}, "workLocations": [{"city": "BERGEN"}]}})
    assert ad is not None and ad.employer_orgnr == "810359862" and ad.location() == "Bergen" and ad.page_url().endswith("/y")
    assert nav.parse_entry("garbage") is None and nav.parse_feed_page(None) == ([], None)


def test_nav_token_is_redacted() -> None:
    from app.security.redaction import contains_secret, redact, register_secret

    register_secret(FAKE_TOKEN)
    assert FAKE_TOKEN not in redact(f"GET /feed Authorization: Bearer {FAKE_TOKEN}") and contains_secret(FAKE_TOKEN)


# ------------------------------------------------------------- procurement --
def test_ted_procurement_parsing() -> None:
    matches, cands, total = procurement.parse_ted_notices(TED_NOTICES, ident())
    assert total == 3
    by = {(m.notice_id, m.role): m for m in matches}
    win = by[("301234-2024", "winner")]
    assert win.title == "Vehicle maintenance services" and win.published == "2024-05-17" and win.buyer_name == "Oslo kommune"
    assert win.url == "https://ted.europa.eu/en/notice/-/detail/301234-2024" and win.matched_identifier == "NO 810 359 862 MVA"
    assert win.total_value == "1250000" and win.total_value_currency == "NOK" and win.cpv == ["50112000"]
    assert ("500002-2025", "buyer") in by
    assert procurement.notice_type_label("can-standard") == "Contract award notice" and procurement.notice_type_label("cn-standard") == "Contract notice"
    # language maps, lists and plain strings all flatten; English first
    assert procurement._values({"nor": ["b"], "eng": "a"}) == ["a", "b"] and procurement._first([[" x "]]) == "x"
    assert procurement.parse_ted_notices({"notices": "bad"}, ident()) == ([], [], None)


def test_procurement_source_identity_matching(settings: Settings) -> None:
    matches, cands, _ = procurement.parse_ted_notices(TED_NOTICES, ident())
    ids = {m.notice_id for m in matches}
    # a notice that names the company but states another organisation number is never attached
    assert "400001-2025" not in ids
    assert [(c["notice_id"], c["status"]) for c in cands] == [("400001-2025", "ambiguous")]
    name_only = {"notices": [{"publication-number": "1-2025", "winner-name": ["AUTOBJØRN A/S"], "publication-date": "2025-01-02"}]}
    m2, c2, _ = procurement.parse_ted_notices(name_only, ident())
    assert m2 == [] and c2[0]["status"] == "ambiguous"
    # the gate refuses a procurement observation without an exact resolution
    obs = procurement.match_observation(matches[0], module="procurement_ted", source=procurement.TED_SOURCE, retrieved_at="2026-10-08T10:00:00Z",
                                        content_sha256="x", org=AUTO, coverage="TED")
    assert check(obs) is None
    weak = Observation(**{**obs.__dict__, "identity_score": 0.6})
    assert check(weak) == "third-party record not resolved to this exact organisation"
    no_basis = Observation(**{**obs.__dict__, "attributes": {}})
    assert check(no_basis) == "third-party record not resolved to this exact organisation"
    # the query carries the organisation number in its usual written forms
    q = procurement.ted_query(ident())
    assert "winner-identifier=810359862" in q and "buyer-identifier=NO810359862MVA" in q and '"810 359 862"' in q


def test_research_publishes_ted_awards_as_activity(settings: Settings) -> None:
    from app.api.profile_builder import build_profile

    net, _, bodies = network()
    rec = run(research_with_db(net, Database(":memory:")))
    awards = [c for c in rec["claims"] if c["field"] == "procurement_award"]
    assert [a["key_suffix"] for a in awards] == ["ted-301234-2024"]
    a = awards[0]
    assert a["attributes"]["coverage"] == "TED (EU-published notices)" and a["as_of"] == "2024-05-17" and a["attributes"]["identity_basis"] == "org_number_in_identifier"
    assert [c["key_suffix"] for c in rec["claims"] if c["field"] == "procurement_notice_as_buyer"] == ["ted-500002-2025"]
    assert "not complete Norwegian procurement coverage" in rec["modules"]["procurement_ted"]["note"]
    assert bodies and bodies[0]["fields"] == procurement.TED_FIELDS
    events = build_profile(rec)["activity"]["events"]
    contract = next(e for e in events if e["type"] == "contract" and "Vehicle maintenance" in e["title"])
    assert contract["date"] == "2024-05-17" and contract["sourceIds"] == ["ted"] and "Oslo kommune" in contract["title"]


DOFFIN_CSV = (
    "Doffin referanse;Tittel;Kunngjøringstype;Publiseringsdato;Oppdragsgiver;Oppdragsgivers organisasjonsnummer;Leverandør;Leverandørens organisasjonsnummer\n"
    "2024-100001;Bilvedlikehold Oslo;Kunngjøring av tildeling;15.03.2024;Oslo kommune;974820994;AUTOBJØRN A/S;810 359 862\n"
    "2024-100002;Dekk;Kunngjøring av konkurranse;01.04.2024;Oslo kommune;974820994;;\n"
    ";Uten id;;2024-05-01;Oslo kommune;974820994;Noen AS;923609016\n"
    "2024-100003;Leiebil;Kunngjøring av tildeling;2024-06-01;Bergen kommune;964338531;Autobjørn (uten nummer);\n"
)


def test_doffin_open_data_parsing_and_lookup(tmp_path: Path) -> None:
    path = tmp_path / "doffin-2024.csv"
    path.write_text(DOFFIN_CSV, encoding="cp1252")
    db = Database(":memory:")
    report = import_file(db, path)
    assert report["columns"]["winner_org"] == "Leverandørens organisasjonsnummer" and report["period"] == "2024"
    assert report["rows"] == 4 and report["linkable_notices"] == 3 and report["skipped"] == {"no notice id": 1}
    res = procurement.doffin_open_data(db, ident(), enabled=True)
    obs = res.observations
    assert [(o.field, o.key_suffix) for o in obs] == [("procurement_award", "doffin_open-2024-100001")]
    o = obs[0]
    assert o.source_url == "https://doffin.no/notices/2024-100001" and o.as_of == "2024-03-15" and o.attributes["dataset_period"] == "2024"
    assert "period 2024" in o.claim_span and check(o) is None
    assert "Historical dataset" in res.modules[0].note
    # name-only rows ("Autobjørn (uten nummer)") never link a company
    assert not db.one("SELECT 1 FROM procurement_parties WHERE notice_key = 'doffin:2024-100003' AND role = 'winner'")
    # re-import replaces the file's rows (idempotent)
    import_file(db, path)
    assert db.one("SELECT COUNT(*) FROM procurement_notices")[0] == 3


def test_doffin_open_data_never_guesses_columns() -> None:
    cols, _, problems = map_columns(["Doffin referanse", "Tittel", "Organisasjonsnummer"])
    assert "buyer_org" not in cols and "winner_org" not in cols and any("has no role" in p for p in problems)
    parsed = parse_rows(["Tittel", "Leverandørens organisasjonsnummer"], [["x", "810359862"]])
    assert parsed.notices == [] and any("no notice-id column" in p for p in parsed.problems)
    explicit = parse_rows(["Doffin referanse", "Organisasjonsnummer"], [["2024-1", "810359862"]], {"winner_org": "Organisasjonsnummer"})
    assert [p[:2] for p in explicit.notices[0].parties] == [("810359862", "winner")]
    assert org_numbers_in(["NO 810 359 862 MVA; 923609016"]) == {"810359862", "923609016"}


# ----------------------------------------------------- Proff-free capability map --
def test_proff_free_capability_mapping() -> None:
    manifest = {s["id"]: s for s in yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["sources"]}
    rows = capabilities.PROFF_CAPABILITY_MAP
    assert rows and {r["status"] for r in rows} <= {"covered", "partial", "unavailable"}
    for r in rows:
        if r["status"] == "unavailable":
            assert r["sources"] == [] and r["note"]
        else:
            assert r["sources"] and all(src in manifest and manifest[src]["enabled_by_default"] for src in r["sources"]), r
            assert "proff" not in r["sources"]
    unavailable = " ".join(capabilities.unavailable_capabilities()).lower()
    assert "shareholders" in unavailable and "credit" in unavailable
    assert manifest["proff"]["access"] == "not_used" and manifest["proff"]["capabilities"] == []
    assert manifest["doffin"]["access"] == "not_used" and manifest["ted_search"]["auth_required"] is False
    from app.connectors import optional
    assert not hasattr(optional, "proff_company") and not hasattr(optional, "doffin_notices")


def test_no_paid_api_required_for_competition_mode(tmp_path: Path) -> None:
    from app.api.compare_export import system_status

    s = Settings(_env_file=None, app_env="test", run_mode="competition", llm_provider="none", data_dir=tmp_path / "d", brreg_account_copies_min_interval_seconds=0,
                 retry_base_delay_seconds=0, retry_max_delay_seconds=1, tavily_api_key=None, groq_api_key=None, proff_api_key=None, doffin_api_key=None,
                 nav_feed_token=None, ted_min_interval_seconds=0, nav_min_interval_seconds=0)
    override_settings(s)
    try:
        warnings = validate_configuration(s)
        assert not any("PROFF" in w or "DOFFIN" in w or "NAV" in w for w in warnings)
        assert s.enable_nav_jobs and s.enable_ted and s.nav_use_public_token  # free sources on by default, no key needed
        net, calls, bodies = network()
        db = Database(":memory:")
        rec = run(research_with_db(net, db, mode="competition"))
        assert rec["terminal_status"] == "completed"
        hosts = {httpx.URL(u).host for u in net.requests}
        assert not hosts & {"api.proff.no", "api.doffin.no", "dof-notices-prod-api.developer.azure-api.net"}
        assert rec["modules"]["nav_jobs"]["state"] == "available" and bodies  # NAV and TED worked without any key
        for mod in rec["modules"].values():
            assert "PROFF_API_KEY" not in (mod.get("note") or "") and "DOFFIN_API_KEY" not in (mod.get("note") or "")

        class _S:
            settings = s
            db = Database(":memory:")
        status = {x["name"]: x for x in system_status(_S())["sources"]}
        assert status["Proff.no"]["status"] == "alternative" and status["Doffin (public procurement)"]["status"] == "alternative"
        assert status["LinkedIn"]["status"] == "not_used"
        assert not [n for n, x in status.items() if x["status"] == "unavailable" and ("Proff" in n or "Doffin" in n or "LinkedIn" in n)]
        assert status["NAV Arbeidsplassen job ads"]["status"] == "degraded"  # empty index in a fresh database: reported, not hidden
        _S.db = db
        assert {x["name"]: x for x in system_status(_S())["sources"]}["NAV Arbeidsplassen job ads"]["status"] == "available"
    finally:
        override_settings(None)


def test_paid_keys_left_in_env_are_ignored_and_redacted(tmp_path: Path) -> None:
    from app.security.redaction import redact

    s = Settings(_env_file=None, app_env="test", data_dir=tmp_path, proff_api_key="proff-secret-123456", doffin_api_key="doffin-secret-123456")
    override_settings(s)
    try:
        assert any("not used" in w for w in validate_configuration(s))
        assert "proff-secret-123456" not in redact("key=proff-secret-123456 and doffin-secret-123456")
        assert "doffin-secret-123456" not in redact("doffin-secret-123456")
    finally:
        override_settings(None)
