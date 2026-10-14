"""Full Research Report (PDF), Evidence & Sources export, and the Research Data (CSV) export that must keep working unchanged.

The report is read back with pypdf: the tests check the text, the link annotations, the outline and the page footers of the real PDF — not an
intermediate model.
"""
from __future__ import annotations

import copy
import csv
import io
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.api import report_data, report_pdf
from app.core.util import now_iso
from app.storage import repository as repo
from app.testing.fixtures import verified_site

AUTO = "810359862"
SECTIONS = ["About this report", "Company identity", "Executive summary & key metrics", "Financial performance", "People & leadership",
            "Registered locations & establishments", "Digital presence", "Hiring & careers", "Recent activity", "Changes detected & research history",
            "Research coverage & verification", "Source references & evidence"]
EXISTING_CSV_COLUMNS = ["org_number", "company", "field", "label", "value", "raw_value", "currency", "status", "evidence_state", "reporting_period", "source",
                        "source_url", "retrieved_at", "evidence_excerpt"]
ALL_OPTIONS = {"sourceLinks": True, "evidence": True, "retrievalDates": True, "reportingPeriods": True, "changes": True}


@pytest.fixture
def env(net, settings):  # noqa: ANN001, ANN201
    from app.api.main import create_app
    from app.api.services import Services
    from app.providers.fake_provider import FakeProvider
    from app.storage.db import Database

    net.add_site("autobjorn.no", verified_site("AUTOBJØRN A/S", AUTO, jobs=["Bilselger", "Mekaniker"]))
    svc = Services(settings, db=Database(":memory:"), transport=net.transport(), provider=FakeProvider(), use_provider=True)
    with TestClient(create_app(svc)) as c:
        yield c, svc


def _research(client: TestClient) -> None:
    import json

    run = client.post("/api/research/runs", json={"query": AUTO, "mode": "quick"}).json()
    with client.stream("GET", f"/api/research/runs/{run['id']}/events?lastSeq=0") as stream:
        for line in stream.iter_lines():
            if line.startswith("data: ") and json.loads(line[6:])["type"] in ("run.completed", "run.failed"):
                break


@pytest.fixture
def researched(env):  # noqa: ANN001, ANN201
    client, svc = env
    _research(client)
    return client, svc


def _export(client: TestClient, kind: str | None, fmt: str, target: dict[str, str] | None = None, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"target": target or {"type": "company", "id": AUTO}, "format": fmt, "options": ALL_OPTIONS, **extra}
    if kind:
        body["kind"] = kind
    return client.post("/api/exports", json=body).json()


def _download(client: TestClient, res: dict[str, Any]) -> bytes:
    assert res["status"] == "ready", res
    r = client.get(res["url"])
    assert r.status_code == 200
    return r.content


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _flat(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


class Pdf:
    def __init__(self, data: bytes):
        self.reader = PdfReader(io.BytesIO(data))
        self.pages = [p.extract_text() or "" for p in self.reader.pages]
        self.text = "\n".join(self.pages)
        self.norm = _norm(self.text)
        self.flat = _flat(self.text)

    def has(self, *needles: str) -> bool:
        return all(_norm(n) in self.norm for n in needles)

    def missing(self, *needles: str) -> list[str]:
        return [n for n in needles if _norm(n) not in self.norm]

    @property
    def uris(self) -> list[str]:
        out = []
        for page in self.reader.pages:
            for annot in page.get("/Annots") or []:
                a = annot.get_object().get("/A")
                if a and a.get_object().get("/URI"):
                    out.append(str(a.get_object()["/URI"]))
        return out


def internal_links(pdf: Pdf) -> list[dict[str, Any]]:
    """Every clickable internal reference: the page it is on, the text inside its rectangle, and the page it jumps to (0-based)."""
    page_index = {p.indirect_reference.idnum: i for i, p in enumerate(pdf.reader.pages)}
    out: list[dict[str, Any]] = []
    for i, page in enumerate(pdf.reader.pages):
        pieces: list[tuple[float, float, str]] = []

        def visit(text: str, cm: list[float], tm: list[float], _fd: Any, _fs: Any, pieces: list = pieces) -> None:
            if text.strip():
                pieces.append((cm[4] + tm[4] * cm[0], cm[5] + tm[5] * cm[3], text))

        page.extract_text(visitor_text=visit)
        for annot in page.get("/Annots") or []:
            a = annot.get_object()
            if "/Dest" not in a:
                continue
            x0, y0, x1, y1 = (float(v) for v in a["/Rect"])
            inside = sorted((p for p in pieces if x0 - 1 <= p[0] <= x1 + 1 and y0 - 3 <= p[1] <= y1 + 3), key=lambda p: p[0])
            line = sorted((p for p in pieces if y0 - 3 <= p[1] <= y1 + 3), key=lambda p: p[0])  # the whole text line the link sits on (text runs share their start position)
            out.append({"page": i, "text": _norm("".join(t for _, _, t in inside)), "line": _norm("".join(t for _, _, t in line)), "dest": page_index[a["/Dest"][0].idnum]})
    return out


def _render(sr: report_data.SavedResearch) -> tuple[Pdf, report_pdf.ReportInfo]:
    buf = io.BytesIO()
    info = report_pdf.render_report(sr, buf)
    return Pdf(buf.getvalue()), info


def _saved(svc: Any) -> report_data.SavedResearch:
    return report_data.load_saved_research(svc, AUTO, generated_at=now_iso())


def _rebuild(sr: report_data.SavedResearch) -> report_data.SavedResearch:
    return report_data.build_view(sr)


def _fact(fid: str, label: str, value: Any, evidence: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    return {"id": fid, "field": fid, "label": label, "status": "verified", "value": value, "evidenceState": "primary", "evidence": evidence,
            "verifiedAt": "2026-10-01T10:00:00Z", "freshness": "current", **kw}


def _ev(i: int, source: str = "brreg", **kw: Any) -> dict[str, Any]:
    return {"id": f"ev-synth-{i}", "sourceId": source, "url": f"https://example.test/evidence/{i}", "retrievedAt": "2026-10-01T10:00:00Z",
            "excerpt": f"Excerpt number {i}: the register states this exactly.", "documentTitle": f"Document {i}", **kw}


# ------------------------------------------------------------------------------------------- the report --
def test_report_contains_every_applicable_section_of_the_saved_research(researched) -> None:  # noqa: ANN001
    client, svc = researched
    res = _export(client, "report", "pdf")
    assert res["status"] == "ready" and res["filename"].startswith("COGNIS-Research-Report-") and res["filename"].endswith(".pdf")
    r = client.get(res["url"])
    assert r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    pdf = Pdf(r.content)
    n = len(pdf.reader.pages)
    assert n >= 10

    # table of contents + a heading for every section, bookmarks, "Page X of Y", generation date, branding
    for title in SECTIONS:
        assert pdf.norm.count(_norm(title)) >= 2, f"{title!r} should appear in the contents and as a heading"
    outline = [o.title for o in pdf.reader.outline if not isinstance(o, list)]
    assert [re.sub(r"^\d+\.\s*", "", t) for t in outline] == SECTIONS
    assert "contents" in pdf.norm
    assert pdf.has(f"Page 2 of {n}", f"Page {n} of {n}")
    assert pdf.has("Generated " + report_pdf.fmt_date(now_iso()), "COGNIS", "Full Research Report")
    assert pdf.reader.metadata.title.startswith("Full Research Report") and pdf.reader.metadata.author == "COGNIS"

    # identity
    assert not pdf.missing("AUTOBJØRN A/S", "810 359 862", "Active", "Private limited company (AS)", "Cecilie Thoresens vei 5-7", "Reparasjon og vedlikehold av motorvogner",
                           "1968-06-10", "autobjorn.no")
    # executive summary and key metrics
    assert not pdf.missing("Compiled from verified facts", "The register reports 12 employees", "12 people", "Registered establishments", "Open positions")
    # financials: every period, currency, raw filed value, ratios, trend charts
    assert not pdf.missing("FY2023", "FY2024", "FY2025", "NOK 21.8M", "21,789,260", "Operating result", "Annual result", "Total assets", "Equity", "Total debt",
                           "Operating margin", "Equity ratio", "as filed (no conversion)", "Historical trend")
    # people, locations, digital presence, hiring, activity
    assert not pdf.missing("Kristin Johannessen", "Bjørn Inge Johannessen", "Chair of the board", "INTRA REVISJON DA", "AUTOBJØRN AS AVD SALG", "AUTOBJØRN AS AVD VERKSTED",
                           "https://www.autobjorn.no/om-oss", "Investor relations", "Not found", "Linkedin", "Careers page", "Bilselger", "Mekaniker", "Current",
                           "Vi åpner nytt kontor i Bergen og ansetter flere rådgivere", "14 Aug 2026")
    # explicit limitations and what could not be checked
    assert not pdf.missing("Only the registered business address is known", "first research of this company", "NAV job-ad index has not been synced",
                           "Automated LinkedIn collection is not permitted", "Limitations of this report", "No month-by-month hiring series")
    # coverage, verification, source registers
    assert not pdf.missing("5 of 5 research areas are complete", "Verification status", "Source register", "Evidence register", "S1", "E1")
    # the four kinds of statement are told apart in the legend
    assert not pdf.missing("Verified", "AI synthesis", "Unverified", "Unavailable", "Conflict")


def test_toc_and_bookmarks_point_to_the_pages_the_sections_are_on(researched) -> None:  # noqa: ANN001
    _, svc = researched
    pdf, info = _render(_saved(svc))
    top = [s for s in info.sections if s["level"] == 0]
    assert len(top) == len(SECTIONS) and info.pages == len(pdf.pages)
    for s in info.sections:
        title = re.sub(r"^\d+(\.\d+)?\.?\s*", "", s["title"])
        assert _norm(title) in _norm(pdf.pages[s["page"] - 1]), f"{title!r} is not on page {s['page']}"
    # the contents page is clickable: each entry jumps to the page its heading is really on
    links = [lk for lk in internal_links(pdf) if lk["page"] in (1, 2)]
    for s in info.sections:
        entry = next((lk for lk in links if lk["text"].startswith(_norm(s["title"]))), None)
        assert entry is not None, f"no contents link for {s['title']!r}"
        assert entry["dest"] == s["page"] - 1, f"contents entry {s['title']!r} jumps to page {entry['dest'] + 1}, heading is on page {s['page']}"
    # and the printed page numbers in the contents agree (the number is drawn just before the title in the text layer)
    toc_text = _norm(" ".join(pdf.pages[1:3]))
    for s in top:
        m = re.search(r"(\d+)\s+" + re.escape(_norm(s["title"])), toc_text)
        assert m and int(m.group(1)) == s["page"], f"printed page number for {s['title']!r}"


def test_every_source_url_and_excerpt_is_preserved_and_linked(researched) -> None:  # noqa: ANN001
    _, svc = researched
    sr = _saved(svc)
    pdf, info = _render(sr)
    entries = sr.registry.entries()
    assert len(entries) >= 40 and info.evidence_count == len(entries) and info.source_count == len(sr.registry.sources)
    uris = set(pdf.uris)
    links = internal_links(pdf)
    card_page: dict[int, int] = {}
    for entry in entries:  # the page each evidence card is on: its heading is "E<n>  <source name>"
        n = entry["n"]
        src = entry["evidence"]["sourceId"]
        name = _norm(sr.registry.sources[src]["name"])[:18]
        card_page[n] = next(i for i, pg in enumerate(pdf.pages) if i >= info.sections[-1]["page"] - 2 and re.search(rf"\be{n}\s+{re.escape(name)}", _norm(pg)))
    cited: dict[int, list[dict[str, Any]]] = {}
    for lk in links:  # a reference reads "E<n>"; neighbours in "E5 E6" share one text run, so each rectangle is identified by the number it starts with
        m = re.match(r"e(\d+)\b", lk["text"])
        if m and int(m.group(1)) in card_page:
            cited.setdefault(int(m.group(1)), []).append(lk)
    assert len(cited) >= 0.75 * len(entries), "most evidence numbers should be clickable where they are cited"
    for n, lks in cited.items():
        assert all(lk["dest"] == card_page[n] for lk in lks), f"a reference to E{n} jumps to the wrong page"
    for entry in entries:
        ev, n = entry["evidence"], entry["n"]
        assert f"E{n}" in pdf.text
        if ev.get("url"):
            assert ev["url"] in uris, f"E{n}: link to {ev['url']} is missing"
            assert _flat(ev["url"].split("://", 1)[1]) in pdf.flat
        if ev.get("excerpt"):
            assert _flat(ev["excerpt"][:70]) in pdf.flat, f"E{n}: excerpt missing"
        assert report_pdf.fmt_dt(ev["retrievedAt"]) in pdf.text.replace("\n", " ") or report_pdf.fmt_date(ev["retrievedAt"]) in pdf.text
    first_page = info.sections[-1]["page"] - 1  # the sources section: where each "S<n>" row of the source register is
    for sid, n in sr.registry.source_numbers.items():
        name = sr.registry.sources[sid]["name"]
        assert name.split(" — ")[0][:20] in pdf.text
        reg_page = next(i for i, pg in enumerate(pdf.pages) if i >= first_page and re.search(rf"\bs{n}\s+{re.escape(_norm(name)[:14])}", _norm(pg)))
        cites = [lk for lk in links if re.match(rf"\[?s{n}\b", lk["text"]) or f"[s{n}]" in lk["line"]]
        assert cites, f"S{n} is cited nowhere as a clickable reference"
        assert any(lk["dest"] == reg_page for lk in cites), f"no reference to S{n} jumps to its row in the source register (page {reg_page + 1})"
    # every fact that carries evidence cites it by number
    for item in sr.items:
        for ev in item["evidence"]:
            assert sr.registry.number(ev["id"]) is not None


def test_report_is_built_from_the_saved_record_and_changes_nothing(researched) -> None:  # noqa: ANN001
    client, svc = researched
    before = {t: svc.db.one(f"SELECT COUNT(*) FROM {t}")[0] for t in ("profile_versions", "tool_calls", "facts", "evidence", "changes")}
    record_before = repo.latest_record(svc.db, AUTO)
    _download(client, _export(client, "report", "pdf"))
    _download(client, _export(client, "evidence", "csv"))
    after = {t: svc.db.one(f"SELECT COUNT(*) FROM {t}")[0] for t in before}
    assert after == before  # no new research, no requests, no new versions
    assert repo.latest_record(svc.db, AUTO) == record_before


def test_executive_summary_is_labelled_ai_synthesis_only_when_a_model_wrote_it(researched) -> None:  # noqa: ANN001
    _, svc = researched
    sr = _saved(svc)
    pdf, _ = _render(sr)
    assert pdf.has("Compiled from verified facts (template, no AI)") and not pdf.has("not a verified fact")
    sr.record["summary"]["method"] = "llm_grounded"
    pdf, _ = _render(_rebuild(sr))
    assert pdf.has("AI synthesis — not a verified fact") and not pdf.has("Compiled from verified facts (template, no AI)")


def test_verified_unverified_conflicting_and_unavailable_facts_are_told_apart(researched) -> None:  # noqa: ANN001
    _, svc = researched
    sr = _saved(svc)
    P = sr.profile
    rev = next(s for s in P["financials"]["series"] if s["key"] == "revenue")
    fy25 = next(pt["fact"] for pt in rev["points"] if pt["period"] == "FY2025")
    fy25["evidenceState"] = "conflict"
    fy25["conflict"] = {"reason": "Parent and group accounts differ", "candidates": [
        {"sourceId": "accounts", "value": 21789260, "currency": "NOK", "reportingPeriod": "FY2025", "evidenceId": "a"},
        {"sourceId": "web-810359862", "value": 2300000, "currency": "USD", "displayValue": "USD 2.3M", "reportingPeriod": "FY2025", "evidenceId": "b"}]}
    P["people"]["people"][-1]["fact"]["evidenceState"] = "secondary"
    P["identity"]["founded"] = {"id": f"{AUTO}:identity.founded", "field": "identity.founded", "label": "Founded", "status": "not_available", "value": None,
                                "evidenceState": "unverified", "evidence": [], "note": "No founding date is stored in the register data."}
    pdf, _ = _render(_rebuild(sr))
    assert not pdf.missing("Sources disagree", "Parent and group accounts differ", "USD 2.3M", "NOK 21.8M", "Conflicting facts", "No founding date is stored in the register data",
                           "Secondary only", "Unavailable")
    # the conflict is reported with each source's own currency and is counted in the verification summary
    assert re.search(r"conflict\s+1\b", pdf.norm)


def test_amounts_keep_the_currency_their_filing_states_and_are_never_converted(researched) -> None:  # noqa: ANN001
    _, svc = researched
    sr = _saved(svc)
    rev = next(s for s in sr.profile["financials"]["series"] if s["key"] == "revenue")
    fy24 = next(pt["fact"] for pt in rev["points"] if pt["period"] == "FY2024")
    fy24.update({"currency": "EUR", "value": 2400000, "displayValue": "EUR 2.4M"})
    pdf, _ = _render(_rebuild(sr))
    assert not pdf.missing("EUR 2.4M", "NOK 29.8M", "NOK 21.8M", "2,400,000")
    assert pdf.norm.count("as filed (no conversion)") == 2  # revenue (mixed currencies) is not drawn as one chart; the other two series are


def test_missing_data_is_explained_never_invented(env) -> None:  # noqa: ANN001
    client, svc = env
    client.get(f"/api/companies/{AUTO}")  # a registry lookup is saved the first time the company is opened — no full research
    assert repo.latest_record(svc.db, AUTO)["mode"] == "registry"
    pdf = Pdf(_download(client, _export(client, "report", "pdf")))
    assert not pdf.missing("Registry lookup only", "Not researched yet", "Unavailable", "AUTOBJØRN A/S", "810 359 862", "Cecilie Thoresens vei 5-7", "Kristin Johannessen")
    assert not pdf.has("Bilselger") and not pdf.has("Mekaniker") and not pdf.has("Vi åpner nytt kontor")  # nothing from research that never ran
    assert not pdf.missing("Hiring & careers", "Recent activity", "Digital presence")
    assert not pdf.missing("No description of the business could be established", "No job postings are saved for this company", "No verified website, so no company-owned careers sources")
    assert repo.latest_record(svc.db, AUTO)["mode"] == "registry"  # exporting did not run research


def test_company_without_saved_research_gets_a_clear_message_and_no_file(env) -> None:  # noqa: ANN001
    client, svc = env
    for kind, fmt in (("report", "pdf"), ("evidence", "csv"), ("evidence", "json")):
        res = _export(client, kind, fmt, target={"type": "company", "id": "923609016"})
        assert res["status"] == "failed" and "No saved research exists" in res["message"] and "url" not in res
    assert svc.db.one("SELECT COUNT(*) FROM profile_versions")[0] == 0 and svc.db.one("SELECT COUNT(*) FROM exports")[0] == 0


def test_long_lists_run_over_many_pages_without_losing_an_entry(researched) -> None:  # noqa: ANN001
    _, svc = researched
    sr = _saved(svc)
    P = sr.profile
    base_people = len(P["people"]["people"])
    n_people, n_loc, n_events, n_jobs, n_changes, n_old = 140, 120, 200, 90, 110, 70
    for i in range(n_people):
        P["people"]["people"].append({"id": f"p{i}", "name": f"Person-{i:04d} Testesen", "role": "Board member", "roleGroup": "board", "current": i % 3 != 0,
                                      "since": "2020-01-01", "fact": _fact(f"{AUTO}:people.synth{i}", "Board member", f"Person-{i:04d} Testesen", [_ev(i)])})
    for i in range(n_loc):
        P["locations"]["locations"].append({"id": f"l{i}", "kind": "operating", "label": f"Location-{i:04d}", "address": f"Gate {i}", "postalCode": "0150", "municipality": "Oslo",
                                            "verified": True, "fact": _fact(f"{AUTO}:locations.synth{i}", f"Location-{i:04d}", f"Gate {i}, 0150 Oslo", [_ev(1000 + i, "subunits")])})
    for i in range(n_events):
        P["activity"]["events"].append({"id": f"e{i}", "date": f"2025-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}", "type": "announcement", "title": f"Event-{i:04d} announced",
                                        "description": f"Description of event {i}.", "significance": ("major", "relevant", "routine", "routine")[i % 4], "sourceIds": ["web-810359862"],
                                        "evidence": [_ev(2000 + i, "web-810359862")]})
    for i in range(n_jobs):
        P["hiring"]["jobs"].append({"id": f"j{i}", "title": f"Job-{i:04d} Engineer", "sourceId": "web-810359862", "url": f"https://example.test/jobs/{i}", "state": "current",
                                    "postedAt": "2026-09-01", "evidence": [_ev(3000 + i, "web-810359862")]})
    for i in range(n_changes):
        P["changes"]["changes"].append({"id": f"c{i}", "detectedAt": "2026-10-01T10:00:00Z", "kind": "modified", "category": "event", "label": f"Change-{i:04d}", "headline": f"Change-{i:04d} headline",
                                        "previous": "a", "current": "b", "material": True, "evidence": [_ev(4000 + i)]})
    P["changes"]["status"] = "available"
    sr.change_log = [{"id": f"old{i}", "detected_at": "2026-05-01T10:00:00Z", "category": "hiring", "label": f"Older-{i:04d}", "old_display": "1", "new_display": "2", "material": True,
                      "source_url": f"https://example.test/old/{i}"} for i in range(n_old)]
    pdf, info = _render(_rebuild(sr))
    assert info.pages >= 40 and len(pdf.pages) == info.pages
    wanted = ([f"Person-{i:04d} Testesen" for i in range(n_people)] + [f"Location-{i:04d}" for i in range(n_loc)] + [f"Event-{i:04d} announced" for i in range(n_events)]
              + [f"Job-{i:04d} Engineer" for i in range(n_jobs)] + [f"Change-{i:04d} headline" for i in range(n_changes)] + [f"Older-{i:04d}" for i in range(n_old)])
    assert pdf.missing(*wanted) == []
    # their evidence is in the register too, and the originals are still there
    assert pdf.has("E1", f"Excerpt number {n_people - 1}:") and pdf.has("Kristin Johannessen")
    assert len(P["people"]["people"]) == base_people + n_people
    assert "shortened for layout" not in pdf.norm  # nothing was cut
    # running header/footer on every page after the cover, numbered "of N"
    assert all(f"Page {i} of {info.pages}" in pdf.pages[i - 1] for i in range(2, info.pages + 1))


def test_an_oversized_excerpt_is_cut_visibly_and_special_characters_are_safe(researched) -> None:  # noqa: ANN001
    _, svc = researched
    sr = _saved(svc)
    nasty = _ev(9, excerpt="<b>bold</b> & <script>alert(1)</script> A&B " + "word " * 1200, url="javascript:alert(1)", documentTitle="Title with <tags> & ampersand")
    sr.profile["people"]["people"][0]["fact"]["evidence"].append(nasty)
    pdf, _ = _render(_rebuild(sr))
    assert pdf.has("<script>alert(1)</script>", "Title with <tags> & ampersand", "shortened for layout")
    assert not any(u.lower().startswith("javascript:") for u in pdf.uris)  # only http(s) addresses become links
    assert report_pdf.safe_url("javascript:alert(1)") is None and report_pdf.safe_url("file:///etc/passwd") is None
    assert report_pdf.safe_url("https://data.brreg.no/enhetsregisteret/api/enheter/810359862") is not None


# ----------------------------------------------------------------------------- Evidence & Sources export --
def test_evidence_export_csv_has_one_row_per_fact_and_evidence_with_status_timestamps_and_periods(researched) -> None:  # noqa: ANN001
    client, svc = researched
    res = _export(client, "evidence", "csv")
    assert res["status"] == "ready" and res["filename"].startswith("COGNIS-Evidence-") and res["filename"].endswith(".csv")
    content = _download(client, res).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    assert reader.fieldnames == report_data.EVIDENCE_COLUMNS and len(rows) > 40
    rev = next(r for r in rows if r["label"] == "Revenue" and r["reporting_period"] == "FY2025")
    assert rev["verification_status"] == "verified" and rev["currency"] == "NOK" and rev["value"] == "NOK 21.8M" and rev["raw_value"] == "21789260"
    assert rev["source_url"].startswith("https://data.brreg.no/") and "NOK" in rev["evidence_excerpt"] and rev["retrieved_at"].endswith("Z")
    assert rev["source_name"] and rev["source_ref"].startswith("S") and rev["evidence_ref"].startswith("E") and rev["research_completed_at"] and rev["exported_at"]
    assert all(r["verification_status"] in {"verified", "unverified", "conflict", "unavailable", "compiled_from_facts", "ai_synthesis"} for r in rows)
    # what is missing is as visible as what is known: unavailable sources get rows with their reason, and no evidence columns
    nav = next(r for r in rows if r["item_type"] == "source_check" and "NAV" in r["label"])
    assert nav["verification_status"] == "unavailable" and "has not been synced" in nav["note"] and nav["evidence_ref"] == "" and nav["source_url"] == ""
    assert any(r["item_type"] == "summary" and r["verification_status"] == "compiled_from_facts" for r in rows)
    assert {r["item_type"] for r in rows} >= {"fact", "job", "event", "summary", "source_check"}
    # the job postings and events keep their URLs and dates
    job = next(r for r in rows if r["item_type"] == "job" and "Bilselger" in r["label"])
    assert job["source_url"].startswith("https://www.autobjorn.no") and job["reporting_period"] == "2026-09-20"


def test_evidence_export_json_and_pdf_share_one_numbering(researched) -> None:  # noqa: ANN001
    client, svc = researched
    data = __import__("json").loads(_download(client, _export(client, "evidence", "json")))
    assert data["company"]["orgNumber"] == AUTO and data["research"]["mode"] == "quick" and data["exportedAt"]
    refs = {e["ref"] for e in data["evidence"]}
    assert len(refs) == data["counts"]["evidence"] == len(data["evidence"]) and data["counts"]["sources"] == len(data["sources"])
    assert all(e["supports"] and e["sourceRef"].startswith("S") for e in data["evidence"])
    assert all(set(f["evidenceRefs"]) <= refs for f in data["facts"])
    assert any(f["verification"] == "unavailable" and f["note"] for f in data["facts"])
    pdf, info = _render(_saved(svc))
    assert info.evidence_count == data["counts"]["evidence"] and info.source_count == data["counts"]["sources"]
    for e in data["evidence"][:10]:  # the same E-number leads to the same evidence in both
        assert e["ref"] in pdf.text


# --------------------------------------------------------------------------- Research Data (CSV) unchanged --
def test_research_data_csv_is_unchanged_and_is_still_the_default(researched) -> None:  # noqa: ANN001
    client, _ = researched
    plain = _export(client, None, "csv")  # exactly what the frontend sent before the report existed
    explicit = _export(client, "data", "csv")
    assert plain["status"] == explicit["status"] == "ready" and plain["filename"].endswith(".csv") and "Research-Report" not in plain["filename"]
    a, b = _download(client, plain), _download(client, explicit)
    assert a == b and a.startswith("﻿".encode())
    rows = list(csv.DictReader(io.StringIO(a.decode("utf-8-sig"))))
    assert list(rows[0].keys()) == EXISTING_CSV_COLUMNS
    rev = next(r for r in rows if r["label"] == "Revenue" and r["reporting_period"] == "FY2025")
    assert rev["value"] == "NOK 21.8M" and rev["raw_value"] == "21789260.0" and rev["currency"] == "NOK" and rev["source_url"].startswith("https://data.brreg.no/")
    for fmt in ("json", "xlsx"):
        assert _download(client, _export(client, None, fmt))
    narrow = _export(client, "data", "csv", options={"sourceLinks": False, "evidence": False, "retrievalDates": False, "reportingPeriods": False, "changes": False})
    narrow_rows = list(csv.DictReader(io.StringIO(_download(client, narrow).decode("utf-8-sig"))))
    assert list(narrow_rows[0].keys()) == ["org_number", "company", "field", "label", "value", "raw_value", "currency", "status", "evidence_state"]


def test_export_kinds_and_formats_are_validated(researched) -> None:  # noqa: ANN001
    client, _ = researched
    assert _export(client, None, "pdf")["filename"].endswith(".pdf")  # a bare "pdf" request means the report
    pdf_as_data = _export(client, "data", "pdf")
    assert pdf_as_data["status"] == "failed" and "Full Research Report" in pdf_as_data["message"]
    assert _export(client, "report", "csv")["status"] == "failed"
    assert _export(client, "evidence", "xlsx")["status"] == "failed"
    assert _export(client, "bogus", "csv")["status"] == "failed"
    sheet = _export(client, "report", "pdf", target={"type": "sheet", "id": "x"})
    assert sheet["status"] == "failed" and "single company" in sheet["message"]
    assert _export(client, "evidence", "csv", target={"type": "comparison", "id": f"{AUTO},810363142"})["status"] == "failed"
    # the saved-research artifact target works like the company
    assert _export(client, "report", "pdf", target={"type": "artifact", "id": f"art-{AUTO}"})["status"] == "ready"


def test_status_advertises_what_can_be_exported(researched) -> None:  # noqa: ANN001
    client, _ = researched
    caps = client.get("/api/status").json()["capabilities"]
    assert caps["pdfReports"] is True and "pdf" in caps["exports"] and {"csv", "xlsx", "json"} <= set(caps["exports"])
    assert caps["exportKinds"] == ["data", "report", "evidence"]


def test_report_models_do_not_mutate_the_profile_they_read(researched) -> None:  # noqa: ANN001
    _, svc = researched
    sr = _saved(svc)
    snapshot = copy.deepcopy(sr.profile)
    _render(sr)
    assert sr.profile == snapshot
