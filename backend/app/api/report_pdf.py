"""Full Research Report (PDF) — a multi-page, branded document rendered from the *saved* research record.

Nothing is regenerated or invented here: every number, name, date and excerpt comes from the saved record and the profile built from it
(``report_data.load_saved_research``). Where the record has no data the report says so and, when the record says why, quotes the reason.
Verified facts, AI synthesis, unverified claims and unavailable information are visibly different (colour *and* wording), amounts keep the
currency their own filing states (no conversion), and every fact points to numbered evidence (E…) and sources (S…) listed in full at the end.
"""
from __future__ import annotations

import hashlib
import io
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    KeepTogether,
    LongTable,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
)
from reportlab.platypus.tableofcontents import TableOfContents

from ..core.util import format_money
from .pdf_support import FONT_DIR
from .pdf_support import FONT_FILES as _FONT_FILES
from .pdf_support import pdf_available as pdf_available  # noqa: F401 - re-exported: callers that already imported this module keep working
from .report_data import EVIDENCE_STATE_LABEL, MODULE_LABELS, MODULE_STATES, SECTION_TITLES, SavedResearch, display_value, verification_of

REG, BOLD, ITAL, BOLDITAL, SERIF = "Cognis", "Cognis-Bold", "Cognis-Italic", "Cognis-BoldItalic", "CognisSerif-Bold"

# Palette: restrained navy, ivory and blue. One muted ochre and one muted red are used only to mark claims that need caution.
NAVY_HEX, BLUE_HEX, INK_HEX, MUTED_HEX = "#0B1F3A", "#2F5D9E", "#1C2434", "#5E6677"
OCHRE_HEX, RED_HEX, IVORY_HEX, TINT_HEX = "#8A5A12", "#8C2F2F", "#F8F4EA", "#E8EEF7"
NAVY, BLUE, INK, MUTED = HexColor(NAVY_HEX), HexColor(BLUE_HEX), HexColor(INK_HEX), HexColor(MUTED_HEX)
IVORY, IVORY_ROW, IVORY_DEEP, RULE, TINT = HexColor(IVORY_HEX), HexColor("#FBF8F1"), HexColor("#EFE9D9"), HexColor("#D8D0BC"), HexColor(TINT_HEX)
OCHRE, RED = HexColor(OCHRE_HEX), HexColor(RED_HEX)

PAGE_W, PAGE_H = A4
LM = RM = 17 * mm
TM, BM = 25 * mm, 21 * mm
CW = PAGE_W - LM - RM

_render_lock = threading.Lock()
_fonts_ready = False


class ReportUnavailable(RuntimeError):
    """The PDF cannot be produced on this installation (fonts missing)."""


def fonts_available() -> bool:
    return all((FONT_DIR / f).is_file() for f in _FONT_FILES.values())


def _register_fonts() -> None:
    global _fonts_ready
    if _fonts_ready:
        return
    if not fonts_available():
        raise ReportUnavailable(f"The PDF report fonts are missing from this installation ({FONT_DIR}). Re-install COGNIS or restore backend/app/assets/fonts.")
    for name, fname in _FONT_FILES.items():
        pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / fname)))
    registerFontFamily(REG, normal=REG, bold=BOLD, italic=ITAL, boldItalic=BOLDITAL)
    _fonts_ready = True


# --------------------------------------------------------------------------------------------- text helpers --
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_CELL_CHARS = 4000  # a single excerpt longer than this is cut visibly (the full text is in the Evidence & Sources export)


def esc(value: Any) -> str:
    """Escape for Paragraph markup. Line breaks are kept."""
    if value is None:
        return ""
    text = _CTRL.sub("", str(value))
    return _xml_escape(text).replace("\n", "<br/>")


def clip(text: str | None, limit: int = MAX_CELL_CHARS) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"… [shortened for layout: {len(text) - limit} more characters are in the Evidence & Sources export]"


def safe_url(url: Any) -> str | None:
    """Only plain http(s) links become clickable (never javascript:, file: or data: links)."""
    if not isinstance(url, str):
        return None
    u = url.strip()
    if not re.match(r"^https?://[^\s<>\"']+$", u, re.IGNORECASE):
        return None
    return u


def link(url: Any, label: str | None = None) -> str:
    u = safe_url(url)
    if not u:
        return esc(label or url or "")
    return f'<a href="{_xml_escape(u, {chr(34): "&quot;"})}" color="{BLUE_HEX}">{esc(label or u)}</a>'


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fmt_date(iso: Any) -> str:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(iso or ""))
    return f"{int(m.group(3)):02d} {_MONTHS[int(m.group(2)) - 1]} {m.group(1)}" if m else str(iso or "")


def fmt_dt(iso: Any) -> str:
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})", str(iso or ""))
    return f"{fmt_date(m.group(1))}, {m.group(2)}:{m.group(3)} UTC" if m else fmt_date(iso)


def fmt_org(org: str) -> str:
    return f"{org[0:3]} {org[3:6]} {org[6:9]}" if re.fullmatch(r"\d{9}", org or "") else org


def raw_number(v: Any) -> str:
    if isinstance(v, bool) or v is None:
        return "" if v is None else str(v)
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{int(v):,}" if v.is_integer() else f"{v:,.2f}"
    return str(v)


def money_no_code(v: float, currency: str) -> str:
    out = format_money(v, currency)
    return out.replace(currency, "").strip() if currency else out


# ------------------------------------------------------------------------------------------------- styles --
def _styles() -> dict[str, ParagraphStyle]:
    def st(name: str, **kw: Any) -> ParagraphStyle:
        base = dict(fontName=REG, fontSize=9.2, leading=13.2, textColor=INK, spaceAfter=0, splitLongWords=1)
        base.update(kw)
        return ParagraphStyle(name, **base)

    return {
        "body": st("body", spaceAfter=5), "bodytight": st("bodytight"), "small": st("small", fontSize=8, leading=11, textColor=MUTED, spaceAfter=4),
        "h1": st("H1", fontName=SERIF, fontSize=19, leading=23, textColor=NAVY),
        "h2": st("H2", fontName=BOLD, fontSize=11.5, leading=15, textColor=NAVY, spaceBefore=12, spaceAfter=5),
        "h3": st("H3", fontName=BOLD, fontSize=9.4, leading=12, textColor=BLUE, spaceBefore=8, spaceAfter=3, keepWithNext=1),
        "cell": st("cell", fontSize=8.1, leading=10.5), "cellb": st("cellb", fontName=BOLD, fontSize=8.1, leading=10.5),
        "cellsm": st("cellsm", fontSize=7.1, leading=9.2, textColor=MUTED), "cellit": st("cellit", fontName=ITAL, fontSize=7.4, leading=9.6, textColor=MUTED),
        "cellhead": st("cellhead", fontName=BOLD, fontSize=7.3, leading=9.2, textColor=IVORY), "label": st("label", fontName=BOLD, fontSize=8, leading=10.5, textColor=NAVY),
        "boxlabel": st("boxlabel", fontName=BOLD, fontSize=7.2, leading=9, spaceAfter=3), "box": st("box", fontSize=9, leading=13),
        "caption": st("caption", fontName=ITAL, fontSize=7.6, leading=10, textColor=MUTED, spaceBefore=3, spaceAfter=6),
        "contents": st("contents", fontName=SERIF, fontSize=19, leading=23, textColor=NAVY, spaceAfter=6),
        "toc0": st("toc0", fontName=BOLD, fontSize=9.8, leading=12.4, textColor=NAVY, spaceBefore=5, leftIndent=0, rightIndent=18),
        "toc1": st("toc1", fontSize=8.3, leading=10.4, textColor=INK, leftIndent=16, rightIndent=18),
    }


ST = None  # populated by _ensure_styles() once the fonts are registered


def _ensure_styles() -> dict[str, ParagraphStyle]:
    global ST
    _register_fonts()
    if ST is None:
        ST = _styles()
    return ST


SOURCE_TYPE_LABEL = {"investor_relations": "Investor relations", "company_newsroom": "Company newsroom", "public_procurement": "Public procurement notice",
                     "official_registry": "Official registry", "secondary_news": "Press coverage"}
VERIFICATION_STYLE = {  # key → (colour, label prefix)
    "verified": NAVY_HEX, "unverified": OCHRE_HEX, "conflict": RED_HEX, "unavailable": MUTED_HEX, "ai_synthesis": BLUE_HEX, "compiled_from_facts": NAVY_HEX,
}


def chip(key: str, label: str) -> str:
    colour = VERIFICATION_STYLE.get(key, MUTED_HEX)
    return f'<font name="{BOLD}" size="6.7" color="{colour}">&#9679; {esc(label).upper()}</font>'


# ------------------------------------------------------------------------------------------------ flowables --
class TrendChart(Flowable):
    """Small bar chart of one metric over its reporting periods, drawn only when every point is stated in the same currency."""

    def __init__(self, title: str, points: list[tuple[str, float]], currency: str, width: float, height: float = 118):
        super().__init__()
        self.title, self.points, self.currency, self.width, self.height = title, points, currency, width, height

    def wrap(self, aw: float, ah: float) -> tuple[float, float]:
        return self.width, self.height

    def draw(self) -> None:
        c, w, h = self.canv, self.width, self.height
        c.setFillColor(NAVY)
        c.setFont(BOLD, 8.2)
        c.drawString(0, h - 9, self.title)
        c.setFillColor(MUTED)
        c.setFont(REG, 6.6)
        c.drawString(0, h - 18, f"{self.currency}, as filed (no conversion)")
        x0, x1, y0, y1 = 2, w - 2, 22, h - 36
        vals = [v for _, v in self.points]
        vmax, vmin = max(max(vals), 0), min(min(vals), 0)
        span = (vmax - vmin) or 1
        zero = y0 + (0 - vmin) / span * (y1 - y0)
        slot = (x1 - x0) / len(self.points)
        bw = min(slot * 0.56, 34)
        for i, (period, v) in enumerate(self.points):
            x = x0 + i * slot + (slot - bw) / 2
            hgt = v / span * (y1 - y0)
            c.setFillColor(BLUE if i == len(self.points) - 1 else NAVY)
            c.rect(x, min(zero, zero + hgt), bw, max(abs(hgt), 0.6), stroke=0, fill=1)
            c.setFillColor(INK)
            c.setFont(REG, 6.4)
            label = money_no_code(v, self.currency)
            c.drawCentredString(x + bw / 2, (zero + hgt + 2.5) if v >= 0 else (zero + hgt - 8), label)
            c.setFillColor(MUTED)
            c.setFont(REG, 6.4)
            c.drawCentredString(x + bw / 2, y0 - 11, period)
        c.setStrokeColor(RULE)
        c.setLineWidth(0.6)
        c.line(x0, zero, x1, zero)


def _paint_furniture(c: rl_canvas.Canvas, page: int, total: int | None, meta: dict[str, str]) -> None:
    """Running header and footer ("Page X of Y"). The total comes from a first, counting pass (see ``render_report``): deferring pages inside
    one pass would leave every bookmark and link pointing at the first page."""
    c.saveState()
    c.setStrokeColor(RULE)
    c.setLineWidth(0.5)
    c.line(LM, PAGE_H - 17 * mm, PAGE_W - RM, PAGE_H - 17 * mm)
    c.setFillColor(NAVY)
    c.setFont(SERIF, 11)
    c.drawString(LM, PAGE_H - 13.5 * mm, "COGNIS")
    c.setFont(REG, 7.6)
    c.setFillColor(MUTED)
    head = f"Full Research Report  ·  {meta.get('company', '')}  ·  Org. no. {fmt_org(meta.get('org', ''))}"
    while pdfmetrics.stringWidth(head, REG, 7.6) > CW - 60 and len(head) > 20:
        head = head[:-2]
    c.drawRightString(PAGE_W - RM, PAGE_H - 13.3 * mm, head)
    c.line(LM, 16 * mm, PAGE_W - RM, 16 * mm)
    c.setFont(REG, 7.4)
    c.drawString(LM, 11.5 * mm, f"Generated {meta.get('generated', '')}  ·  from research saved {meta.get('saved', '')}  ·  {meta.get('ref', '')}")
    c.setFillColor(NAVY)
    c.setFont(BOLD, 7.8)
    c.drawRightString(PAGE_W - RM, 11.5 * mm, f"Page {page} of {total if total else '…'}")
    c.restoreState()


@dataclass
class ReportInfo:
    pages: int = 0
    sections: list[dict[str, Any]] = field(default_factory=list)
    evidence_count: int = 0
    source_count: int = 0
    reference: str = ""


class _Doc(BaseDocTemplate):
    def __init__(self, target: Any, meta: dict[str, str], cover_painter: Any, total_pages: int | None):
        super().__init__(target, pagesize=A4, leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM, title=f"Full Research Report — {meta['company']}",
                         author="COGNIS", subject=f"Company research report for organisation number {meta['org']}", creator="COGNIS", producer="COGNIS",
                         keywords=f"COGNIS, research report, {meta['org']}")
        cover_h = PAGE_H * 0.46 - 22 * mm
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[Frame(LM, 18 * mm, CW, cover_h, id="cover", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=cover_painter),
            PageTemplate(id="body", frames=[Frame(LM, BM, CW, PAGE_H - TM - BM, id="body", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)],
                         onPage=lambda c, d: _paint_furniture(c, d.page, total_pages, meta)),
        ])
        self.found: dict[str, dict[str, Any]] = {}

    def afterFlowable(self, flowable: Any) -> None:  # noqa: N802
        entry = getattr(flowable, "_toc", None)
        if entry:
            level, text, key = entry
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level, closed=0)
            self.notify("TOCEntry", (level, text, self.page, key))
            self.found[key] = {"level": level, "title": text, "page": self.page}


# ----------------------------------------------------------------------------------------------- builder --
class ReportBuilder:
    def __init__(self, sr: SavedResearch):
        self.sr = sr
        self.P = sr.profile
        self.rec = sr.record
        self.reg = sr.registry
        self.st = _ensure_styles()
        self.sec = 0
        self.sub = 0
        self.company = sr.company["legalName"]
        self.org = sr.company["orgNumber"]
        self.completed_at = sr.record.get("completed_at") or ""
        latest = (sr.versions[0]["id"] if sr.versions else "") or self.completed_at
        self.reference = f"COGNIS-RR-{self.org}-{(sr.generated_at or '')[:10].replace('-', '')}-{hashlib.sha1(f'{self.org}|{latest}'.encode()).hexdigest()[:6].upper()}"
        self.meta = {"company": self.company, "org": self.org, "generated": fmt_date(sr.generated_at), "saved": fmt_date(self.completed_at) or "n/a", "ref": self.reference}

    # ----------------------------------------------------------------------------------- primitives --
    def p(self, text: str, style: str = "body") -> Paragraph:
        return Paragraph(text, self.st[style])

    def cell(self, c: Any, style: str = "cell") -> Any:
        if isinstance(c, (Flowable, list)):
            return c
        return Paragraph("" if c is None else str(c), self.st[style])

    def refs(self, evidence: list[dict[str, Any]] | None) -> str:
        parts: list[str] = []
        for ev in evidence or []:
            n = self.reg.number(ev["id"]) or self.reg.add(ev)
            tag = f'<a href="#ev-{n}" color="{BLUE_HEX}">E{n}</a>'
            if tag not in parts:
                parts.append(tag)
        return " ".join(parts) if parts else f'<font color="{MUTED_HEX}">none stored</font>'

    def src_ref(self, source_id: str) -> str:
        n = self.reg.source_number(source_id)
        name = (self.reg.sources.get(source_id) or {}).get("name") or source_id
        return f'<a href="#src-{n}" color="{BLUE_HEX}">S{n}</a> {esc(name)}' if n else esc(name)

    def h1(self, title: str) -> list[Any]:
        self.sec += 1
        self.sub = 0
        key = f"sec{self.sec}"
        head = Table([[Paragraph(f'<font color="{BLUE_HEX}">{self.sec:02d}</font>&nbsp;&nbsp;{esc(title)}', self.st["h1"])]], colWidths=[CW], spaceBefore=16)
        head.setStyle([("LINEBELOW", (0, 0), (-1, -1), 1.2, BLUE), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                       ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)])
        head.keepWithNext = 1
        head._toc = (0, f"{self.sec}. {title}", key)  # type: ignore[attr-defined]
        return [CondPageBreak(72 * mm), head, Spacer(1, 7)]

    def h2(self, title: str) -> list[Any]:
        self.sub += 1
        key = f"sec{self.sec}-{self.sub}"
        para = Paragraph(f'<font color="{BLUE_HEX}">{self.sec}.{self.sub}</font>&nbsp;&nbsp;{esc(title)}', self.st["h2"])
        para._toc = (1, f"{self.sec}.{self.sub} {title}", key)  # type: ignore[attr-defined]
        return [CondPageBreak(42 * mm), para]

    def table(self, head: list[str], rows: list[list[Any]], widths: list[float], *, zebra: bool = True) -> Table:
        data = [[Paragraph(esc(h), self.st["cellhead"]) for h in head]] + [[self.cell(c) for c in r] for r in rows]
        t = LongTable(data, colWidths=[w * CW for w in widths], repeatRows=1, splitByRow=1, splitInRow=1)
        style = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                 ("TOPPADDING", (0, 0), (-1, -1), 3.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.6), ("LINEBELOW", (0, 1), (-1, -1), 0.35, RULE),
                 ("TOPPADDING", (0, 0), (-1, 0), 4.5), ("BOTTOMPADDING", (0, 0), (-1, 0), 4.5)]
        if zebra:
            style.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, IVORY_ROW]))
        t.setStyle(style)
        return t

    def kv(self, rows: list[tuple[str, Any]], widths: tuple[float, float] = (0.28, 0.72)) -> Table:
        data = [[Paragraph(esc(k), self.st["label"]), self.cell(v)] for k, v in rows]
        t = LongTable(data, colWidths=[w * CW for w in widths], splitByRow=1, splitInRow=1)
        t.setStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LINEBELOW", (0, 0), (-1, -1), 0.35, RULE), ("BACKGROUND", (0, 0), (0, -1), IVORY), ("LINEABOVE", (0, 0), (-1, 0), 0.8, NAVY)])
        return t

    def box(self, kind: str, label: str, body: Any, *, basis: str | None = None) -> Table:
        """A labelled call-out. kind: ai (blue), fact (navy), unavailable (dashed grey), warn (ochre), note (ivory)."""
        accent, tint, key = {"ai": (BLUE, TINT, "ai_synthesis"), "fact": (NAVY, IVORY, "compiled_from_facts"), "unavailable": (MUTED, IVORY_ROW, "unavailable"),
                             "warn": (OCHRE, IVORY, "unverified"), "note": (BLUE, IVORY, "ai_synthesis"), "conflict": (RED, IVORY, "conflict")}[kind]
        inner: list[Any] = [Paragraph(chip(key, label) if kind != "note" else f'<font name="{BOLD}" size="7" color="{NAVY_HEX}">{esc(label).upper()}</font>', self.st["boxlabel"])]
        inner += body if isinstance(body, list) else [Paragraph(body, self.st["box"])]
        if basis:
            inner.append(Paragraph(f'<font color="{MUTED_HEX}" size="7.6">Basis: {basis}</font>', self.st["cellsm"]))
        t = Table([[inner]], colWidths=[CW])
        style = [("BACKGROUND", (0, 0), (-1, -1), tint), ("LEFTPADDING", (0, 0), (-1, -1), 11), ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 8),
                 ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]
        if kind == "unavailable":
            style.append(("BOX", (0, 0), (-1, -1), 0.8, MUTED, 1, (3, 2)))
        else:
            style.append(("LINEBEFORE", (0, 0), (0, -1), 3, accent))
        t.setStyle(style)
        return t

    def unavailable(self, what: str, reason: str | None, default: str = "Not established in the sources searched.") -> Table:
        return self.box("unavailable", f"Unavailable — {what}", esc(reason or default))

    def verification_cell(self, fact: dict[str, Any]) -> str:
        key, label = verification_of(fact)
        return chip(key, label)

    def value_cell(self, f: dict[str, Any]) -> str:
        """Value + the backend's note + every conflicting candidate with its own currency."""
        if f.get("status") != "verified":
            return f'<font color="{MUTED_HEX}"><i>{esc(f.get("note") or "Not established in the sources searched.")}</i></font>'
        text = esc(display_value(f))
        unit = f.get("unit")
        if unit and not f.get("currency") and isinstance(f.get("value"), (int, float)) and not isinstance(f.get("value"), bool) and unit not in (display_value(f) or ""):
            text += f" {esc(unit)}"
        out = [text or "—"]
        if f.get("note"):
            out.append(f'<font size="7.2" color="{MUTED_HEX}"><i>{esc(f["note"])}</i></font>')
        conflict = f.get("conflict")
        if conflict:
            lines = []
            for cand in conflict.get("candidates") or []:
                val = cand.get("displayValue") or (format_money(cand["value"], cand["currency"]) if cand.get("currency") and isinstance(cand["value"], (int, float)) else cand["value"])
                period = f" ({esc(cand['reportingPeriod'])})" if cand.get("reportingPeriod") else ""
                lines.append(f"{self.src_ref(cand['sourceId'])}: <b>{esc(val)}</b>{period}")
            reason = f' — {esc(conflict["reason"])}' if conflict.get("reason") else ""
            out.append(f'<font size="7.2" color="{RED_HEX}">Sources disagree{reason}:</font><br/><font size="7.2">' + "<br/>".join(lines) + "</font>")
        return "<br/>".join(out)

    def fact_rows(self, facts: list[dict[str, Any]], *, with_period: bool = True) -> list[list[Any]]:
        rows = []
        for f in facts:
            row = [f'<b>{esc(f["label"])}</b>', self.value_cell(f)]
            if with_period:
                row.append(esc(f.get("reportingPeriod") or "—"))
            row += [self.verification_cell(f), self.refs(f.get("evidence"))]
            rows.append(row)
        return rows

    def facts_table(self, facts: list[dict[str, Any]], *, with_period: bool = True) -> Table:
        if with_period:
            return self.table(["Item", "Value", "Period", "Verification", "Evidence"], self.fact_rows(facts), [0.20, 0.34, 0.10, 0.20, 0.16])
        return self.table(["Item", "Value", "Verification", "Evidence"], self.fact_rows(facts, with_period=False), [0.22, 0.42, 0.20, 0.16])

    def section_status(self, section: dict[str, Any], what: str) -> list[Any]:
        """Explains a section that is not fully available, quoting the record's own message."""
        status, msg = section.get("status"), section.get("message")
        if status in (None, "available"):
            return [self.box("warn", "Note", esc(msg))] if msg else []
        label = {"partial": "Partially available", "not_available": "Unavailable", "blocked": "Blocked", "ambiguous": "Ambiguous", "pending": "Not researched yet"}.get(status, status)
        kind = "warn" if status in ("partial", "ambiguous") else "unavailable"
        return [self.box(kind, f"{label} — {what}", esc(msg or "The record gives no further explanation."))]

    # ---------------------------------------------------------------------------------------- cover --
    def paint_cover(self, c: rl_canvas.Canvas, doc: Any) -> None:
        c.saveState()
        c.setFillColor(IVORY)
        c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
        top = PAGE_H * 0.46
        c.setFillColor(NAVY)
        c.rect(0, top, PAGE_W, PAGE_H - top, stroke=0, fill=1)
        c.setFillColor(BLUE)
        c.rect(0, top - 2.2 * mm, PAGE_W, 2.2 * mm, stroke=0, fill=1)
        c.setFillColor(IVORY)
        c.setFont(SERIF, 24)
        c.drawString(LM, PAGE_H - 30 * mm, "COGNIS")
        c.setFont(REG, 8.5)
        c.setFillColor(HexColor("#A9BEDD"))
        c.drawString(LM, PAGE_H - 36 * mm, "COMPANY INTELLIGENCE")
        c.setFont(BOLD, 9)
        c.setFillColor(HexColor("#A9BEDD"))
        c.drawString(LM, top + 74 * mm, "F U L L   R E S E A R C H   R E P O R T")
        size = 32
        lines = simpleSplit(self.company, SERIF, size, CW)
        while len(lines) > 3 and size > 20:
            size -= 2
            lines = simpleSplit(self.company, SERIF, size, CW)
        c.setFillColor(IVORY)
        c.setFont(SERIF, size)
        y = top + 62 * mm
        for ln in lines[:4]:
            c.drawString(LM, y, ln)
            y -= size * 1.16
        c.setFont(REG, 11)
        c.setFillColor(HexColor("#D9E3F3"))
        c.drawString(LM, top + 14 * mm, f"Organisation number {fmt_org(self.org)}   ·   {self.sr.company.get('statusLabel') or ''}")
        c.restoreState()

    def cover_story(self) -> list[Any]:
        mode = self.rec.get("mode")
        depth = {"registry": "Registry lookup only (no web research)", "quick": "Quick research", "deep": "Deep research"}.get(mode or "", mode or "Not recorded")
        ind = self.sr.company.get("industry") or {}
        rows = [("Saved research completed", fmt_dt(self.completed_at) or "Not recorded"), ("Research depth", depth),
                ("Research coverage", f"{self.sr.company['coverage']['complete']} of {self.sr.company['coverage']['total']} areas complete"),
                ("Industry", f"{ind.get('description')} ({ind.get('code')})" if ind.get("description") else "Not established"),
                ("Report generated", fmt_dt(self.sr.generated_at)), ("Report reference", self.reference)]
        t = Table([[Paragraph(esc(k).upper(), ParagraphStyle("ck", fontName=BOLD, fontSize=7, leading=9, textColor=MUTED)),
                    Paragraph(esc(v), ParagraphStyle("cv", fontName=REG, fontSize=10, leading=13, textColor=INK))] for k, v in rows], colWidths=[0.30 * CW, 0.70 * CW])
        t.setStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE), ("LINEABOVE", (0, 0), (-1, 0), 0.8, NAVY)])
        out: list[Any] = [Spacer(1, 10), t, Spacer(1, 12),
                          Paragraph("Compiled from the research COGNIS saved for this company. Nothing in this report was regenerated, estimated or added at export time. "
                                    "Where information was unavailable, the report says so.", ParagraphStyle("cn", fontName=ITAL, fontSize=8.6, leading=12, textColor=MUTED))]
        if not self.sr.is_full_research:
            out += [Spacer(1, 8), self.box("warn", "Registry lookup only", "Only the company register was queried for this company; full research (website, hiring, activity) "
                                           "has not been run. Sections that need it are marked as not researched.")]
        return out

    # -------------------------------------------------------------------------------- 1 About this report --
    def s_about(self) -> list[Any]:
        rec = self.rec
        ops = rec.get("operations") or {}
        llm = ops.get("llm") or {}
        method = self.sr.summary_method
        summary_how = {"llm_grounded": "AI synthesis grounded in the evidence (language model)", "deterministic_template": "Compiled from verified facts by a fixed template (no AI)"}.get(method or "", "No executive summary saved")
        out = self.h1("About this report")
        out.append(self.p("This report presents the research COGNIS saved for the company named on the cover. It is produced from that saved record — the same facts, sources and "
                          "evidence shown in the COGNIS company view — and does not search, estimate or fill gaps when it is generated."))
        out.extend(self.h2("Report basis"))
        versions = self.sr.versions
        out.append(self.kv([
            ("Company", f"{esc(self.company)} (org. no. {esc(fmt_org(self.org))})"),
            ("Saved research completed", esc(fmt_dt(self.completed_at) or "Not recorded")),
            ("Research depth", esc({"registry": "Registry lookup only", "quick": "Quick research", "deep": "Deep research"}.get(rec.get("mode") or "", rec.get("mode") or "Not recorded"))),
            ("Run status", esc(f"{rec.get('terminal_status') or 'not recorded'} · company state: {rec.get('entity_state') or 'not recorded'}")),
            ("Saved versions of this research", esc(f"{len(versions)} (this report uses the latest)")),
            ("Executive summary method", esc(summary_how)),
            ("Language model used in research", esc(f"{llm.get('model')} ({llm.get('provider')}), {llm.get('calls', 0)} call(s)") if llm.get("model") else "None recorded"),
            ("Report generated", esc(fmt_dt(self.sr.generated_at))), ("Report reference", esc(self.reference))]))
        out.extend(self.h2("How to read the evidence labels"))
        legend = [
            [chip("verified", "Verified"), "A fact backed by stored evidence from a primary source — a government register, or the company's own website once COGNIS has verified it "
             "belongs to the company. “2+ sources” means independent sources agree."],
            [chip("ai_synthesis", "AI synthesis"), "Text written by a language model from the evidence. It is a reading of the facts, never a fact itself, and is always labelled."],
            [chip("unverified", "Unverified"), "Found, but supported only by secondary sources, ambiguous, or without stored evidence. Treat as a lead, not as established."],
            [chip("conflict", "Conflict"), "Sources disagree. Each source's own value is shown with its own currency and period; COGNIS does not pick a winner."],
            [chip("unavailable", "Unavailable"), "Not established, not researched, or the source could not be read. Absence of data is never reported as absence of the thing itself."],
        ]
        out.append(self.table(["Label", "Meaning"], legend, [0.22, 0.78]))
        out.append(Spacer(1, 6))
        out.extend(self.h2("Conventions"))
        for line in [
            "<b>Evidence and sources.</b> Every fact lists evidence references (E1, E2 …) that link to the Evidence register in section 12, which holds the source, URL, retrieval time and "
            "the excerpt. Sources are numbered S1, S2 …; both registers are also available as an Evidence &amp; Sources export (CSV or JSON).",
            "<b>Currencies and periods.</b> Each amount is shown in the currency its own filing states, with its fiscal period, exactly as filed. COGNIS never converts currencies or assumes NOK; "
            "amounts in different currencies are not compared.",
            "<b>Company statements.</b> Text taken from the company's own website (descriptions, news, job ads) is shown as the company states it. COGNIS verifies that the website belongs "
            "to the company, not that every statement on it is true.",
            "<b>Language.</b> Excerpts are kept in the language of the source; an English translation is shown where one was saved.",
            "<b>Completeness.</b> Lists (people, locations, events, jobs, evidence) are printed in full over as many pages as needed.",
        ]:
            out.append(self.p(line))
        return out

    # ----------------------------------------------------------------------------- 2 Company identity --
    def s_identity(self) -> list[Any]:
        ident = self.P["identity"]
        out = self.h1("Company identity")
        reg_ev = (ident.get("legalName") or {}).get("evidence") or []
        rows: list[list[Any]] = []

        def add_fact(key: str, label: str, missing: str) -> None:
            f = ident.get(key)
            if f:
                rows.append([f'<b>{esc(f["label"])}</b>', self.value_cell(f), self.verification_cell(f), self.refs(f.get("evidence"))])
            else:
                rows.append([f"<b>{esc(label)}</b>", f'<font color="{MUTED_HEX}"><i>{esc(missing)}</i></font>', chip("unavailable", "Unavailable"), self.refs([])])

        add_fact("legalName", "Legal name", "Not established.")
        rows.append(["<b>Organisation number</b>", esc(fmt_org(self.org)), chip("verified", "Verified · primary") if reg_ev else chip("unverified", "Unverified"), self.refs(reg_ev)])
        add_fact("status", "Registration status", "Not established.")
        add_fact("legalForm", "Legal form", "Not established in the register data saved for this company.")
        add_fact("founded", "Founded / registered", "No founding or registration date was saved.")
        add_fact("industry", "Industry", "No industry classification was saved.")
        add_fact("registeredAddress", "Registered address", "No registered business address was saved.")
        hq_note = next((k["text"] for k in self.P["knowns"] if k["id"] == "k-hq"), "An operating headquarters is not verified.")
        if ident.get("headquarters"):
            add_fact("headquarters", "Headquarters", "")
        else:
            rows.append(["<b>Headquarters</b>", f'<font color="{MUTED_HEX}"><i>{esc(hq_note)}</i></font>', chip("unavailable", "Unavailable"), self.refs([])])
        add_fact("website", "Official website", "No official website has been verified for this company.")
        out.append(self.table(["Item", "Value", "Verification", "Evidence"], rows, [0.21, 0.43, 0.20, 0.16]))
        out.extend(self.h2("Company description"))
        desc = self.P.get("description")
        if desc and desc.get("status") == "verified":
            out.append(self.box("note", "Company-stated description" if self._is_company_stated(desc) else "Description from the register", esc(clip(display_value(desc))),
                                basis=f"{self.verification_cell(desc)} &nbsp; {self.refs(desc.get('evidence'))}"))
        else:
            out.append(self.unavailable("company description", (desc or {}).get("note"), "No description of the business could be established from the sources searched."))
        return out

    def _is_company_stated(self, fact: dict[str, Any]) -> bool:
        return any(str(e.get("sourceId", "")).startswith("web-") or "jobs-" in str(e.get("sourceId", "")) for e in fact.get("evidence") or [])

    # ------------------------------------------------------------------ 3 Executive summary & key metrics --
    def s_summary(self) -> list[Any]:
        out = self.h1("Executive summary & key metrics")
        item = next((i for i in self.sr.items if i["type"] == "summary"), None)
        out.extend(self.h2("Executive summary"))
        if not item:
            out.append(self.unavailable("executive summary", None, "No executive summary was saved with this research record."))
        else:
            ai = item["verification"] == "ai_synthesis"
            sentences = item.get("sentences") or []
            by_id = {e["id"]: e for e in item["evidence"]}
            if sentences:
                paras: list[Any] = []
                for s in sentences:
                    evs = [by_id[i] for i in s.get("evidence_ids") or [] if i in by_id]
                    paras.append(Paragraph(f'{esc(s["text"])} <font size="7.4">{self.refs(evs) if evs else ""}</font>', self.st["box"]))
                body: Any = paras
                basis = None
            else:
                body = esc(clip(item["display"]))
                basis = self.refs(item["evidence"])
            label = "AI synthesis — not a verified fact" if ai else "Compiled from verified facts (template, no AI)"
            out.append(self.box("ai" if ai else "fact", label, body, basis=basis))
            out.append(self.p(f'Summary saved {esc(fmt_dt((self.rec.get("summary") or {}).get("generated_at")))}. '
                              + ("Numbers in an AI summary are checked against the stored facts before it is saved; the references show the evidence it was written from."
                                 if ai else "Each sentence restates stored facts; the references show where they come from."), "caption"))
        out.extend(self.h2("Key metrics"))
        metrics = self.P["keyMetrics"]
        if metrics:
            out.append(self.facts_table(metrics))
        else:
            out.append(self.unavailable("key metrics", None, "No key metrics could be derived from this research record."))
        out.extend(self.h2("What is known and what is not"))
        label = {"verified": ("verified", "Verified"), "unknown": ("unavailable", "Not established"), "blocked": ("unavailable", "Blocked"), "conflict": ("conflict", "Conflict")}
        rows = [[f'<b>{esc(k["label"])}</b>', chip(*label.get(k["status"], ("unavailable", k["status"]))), esc(k["text"])] for k in self.P["knowns"]]
        out.append(self.table(["Topic", "Status", "Statement"], rows, [0.18, 0.18, 0.64]) if rows else self.unavailable("known / unknown summary", None))
        return out

    # ---------------------------------------------------------------------------- 4 Financial performance --
    def s_financials(self) -> list[Any]:
        fin = self.P["financials"]
        out = self.h1("Financial performance")
        out += self.section_status(fin, "financials")
        series = fin["series"]
        if not series:
            if fin.get("status") == "available":
                out.append(self.unavailable("financials", None, "No filed annual accounts were found for this company."))
            return out
        curs = [c for c in (fin.get("currencies") or [fin.get("currency")]) if c]
        if curs:  # every amount keeps the currency its filing states; nothing is converted or compared across currencies
            text = (f"Filings are stated in: {', '.join(curs)}. Amounts are shown as filed and are not converted or compared across currencies." if len(curs) > 1
                    else f"All filings state {curs[0]}. Amounts are shown as filed and are not converted.")
            out.append(self.box("note", "Currency", esc(text)))
            out.append(Spacer(1, 4))
        periods = sorted({pt["period"] for s in series for pt in s["points"]}, key=lambda p: (re.search(r"\d{4}", p) and int(re.search(r"\d{4}", p).group()) or 0, p))  # type: ignore[union-attr]
        out.extend(self.h2("Reported figures by period"))
        per_chunk = 6
        for i in range(0, len(periods), per_chunk):
            chunk = periods[i:i + per_chunk]
            rows = []
            for s in series:
                by_p = {pt["period"]: pt["fact"] for pt in s["points"]}
                row: list[Any] = [f'<b>{esc(s["label"])}</b><br/><font size="7" color="{MUTED_HEX}">{esc(s.get("unit") or "")}</font>']
                for p in chunk:
                    f = by_p.get(p)
                    if not f:
                        row.append(f'<font color="{MUTED_HEX}">—</font>')
                    else:
                        key, _ = verification_of(f)
                        flag = f'<br/><font size="6.6" color="{RED_HEX if key == "conflict" else OCHRE_HEX}">{"conflict" if key == "conflict" else "unverified"}</font>' if key != "verified" else ""
                        row.append(f"{esc(display_value(f))}{flag}")
                rows.append(row)
            w_first = 0.22
            out.append(self.table(["Metric"] + chunk, rows, [w_first] + [(1 - w_first) / len(chunk)] * len(chunk)))
            out.append(Spacer(1, 6))
        wanted = [("revenue", "Revenue"), ("operating_result", "Operating result"), ("annual_result", "Annual result"), ("total_assets", "Total assets"), ("equity", "Equity"),
                  ("debt", "Total debt"), ("cash", "Cash")]
        have = {s["key"] for s in series if s["points"]}
        missing = [label for key, label in wanted if key not in have]
        if missing:
            out.append(self.box("unavailable", "Not reported in the saved filings", esc(f"No filed value was saved for: {', '.join(missing)}. These are not estimated.")))
            out.append(Spacer(1, 6))
        charts = []
        for s in series:
            cs = {pt["fact"].get("currency") for pt in s["points"]}
            if s["key"] in ("revenue", "operating_result", "annual_result") and len(s["points"]) >= 2 and len(cs) == 1 and None not in cs and "" not in cs:
                pts = [(pt["period"], float(pt["fact"]["value"])) for pt in s["points"] if isinstance(pt["fact"].get("value"), (int, float))]
                if len(pts) >= 2:
                    charts.append((s["label"], pts[-8:], next(iter(cs)), len(pts) > 8))
        if charts:
            out.extend(self.h2("Historical trend"))
            width = CW / 3 - 8
            cells = [[TrendChart(label, pts, c, width) for label, pts, c, _ in charts[:3]]]
            tbl = Table(cells, colWidths=[CW / 3] * len(cells[0]))
            tbl.setStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 8)])
            out.append(tbl)
            note = "Bars show filed values per fiscal period, oldest to newest (latest in blue)."
            if any(cut for *_, cut in charts):
                note += " Only the latest eight periods are drawn; every period is in the tables."
            out.append(self.p(note, "caption"))
        out.extend(self.h2("Every filed figure, with its source"))
        rows = []
        for s in series:
            for pt in s["points"]:
                f = pt["fact"]
                cur_txt = f.get("currency") or ("people" if s.get("unit") == "people" else "not stated")
                rows.append([f'<b>{esc(s["label"])}</b>', esc(pt["period"]), esc(raw_number(f.get("value"))), esc(cur_txt), self.value_cell(f), self.verification_cell(f), self.refs(f.get("evidence"))])
        out.append(self.table(["Metric", "Period", "Value as filed", "Currency", "Shown as", "Verification", "Evidence"], rows, [0.15, 0.08, 0.14, 0.09, 0.2, 0.19, 0.15]))
        out.append(self.p("“Value as filed” is the unrounded number in the filing; “Shown as” is the readable form. Both use the filing's own currency.", "caption"))
        if fin.get("ratios"):
            out.extend(self.h2("Ratios computed from the filed figures"))
            hist = {r["key"]: r for r in fin.get("ratioHistory") or []}
            rows = [[f'<b>{esc(r["label"])}</b>', esc(r["period"]), f'{r["value"]:.1f}%', esc(r["formula"]),
                     esc("; ".join(f'{pt["period"]}: {pt["value"]:.1f}%' for pt in hist[r["key"]]["points"])) if r["key"] in hist else "—"] for r in fin["ratios"]]
            out.append(self.table(["Ratio", "Latest period", "Value", "Formula", "History"], rows, [0.17, 0.11, 0.09, 0.27, 0.36]))
            out.append(self.p("Ratios are calculated by COGNIS from the figures above, only between amounts filed in the same currency and period.", "caption"))
        return out

    # ------------------------------------------------------------------------------ 5 People & leadership --
    def s_people(self) -> list[Any]:
        sec = self.P["people"]
        out = self.h1("People & leadership")
        out += self.section_status(sec, "people")
        people = sec["people"]
        if people:
            group_label = {"executive": "Executive", "board": "Board", "founder": "Founder", "other": "Other"}
            rows = []
            for x in people:
                tenure = ("Current" if x.get("current") else "Former") + (f" · since {fmt_date(x['since'])}" if x.get("since") else "") + (f" · until {fmt_date(x['until'])}" if x.get("until") else "")
                name = f'<b>{esc(x["name"])}</b>'
                for o in x.get("otherRoles") or []:
                    org = f" (org. {esc(o['orgNumber'])})" if o.get("orgNumber") else ""
                    name += (f'<br/><font size="7.1" color="{MUTED_HEX}">Also {esc(o["role"])} at {esc(o["companyName"])}{org} — {"current" if o.get("current") else "former"} {self.refs(o.get("evidence"))}</font>')
                rows.append([name, esc(x["role"]), esc(group_label.get(x["roleGroup"], x["roleGroup"])), esc(tenure), self.verification_cell(x["fact"]), self.refs(x["fact"].get("evidence"))])
            out.append(self.p(f"{len(people)} {'person is' if len(people) == 1 else 'people are'} registered in the saved roles data."))
            out.append(self.table(["Name", "Role", "Group", "Tenure", "Verification", "Evidence"], rows, [0.21, 0.16, 0.11, 0.19, 0.19, 0.14]))
        elif sec.get("status") == "available":
            out.append(self.unavailable("people", None, "No people are registered in the roles data saved for this company."))
        out.extend(self.h2("Relationships"))
        rels = self.P["relationships"]
        if rels:
            kind_label = {"ceo": "CEO", "board": "Board", "subsidiary": "Subsidiary", "parent": "Parent company", "related": "Related party", "investor": "Investor", "partner": "Partner", "founder": "Founder"}
            rows = [[esc(kind_label.get(r["kind"], r["kind"])), f'<b>{esc(r["entity"]["name"])}</b>' + (f'<br/><font size="7.1" color="{MUTED_HEX}">org. {esc(r["entity"]["orgNumber"])}</font>' if r["entity"].get("orgNumber") else ""),
                     esc(r["label"]), esc(r["entity"]["type"].title()), self.refs(r["evidence"])] for r in rels]
            out.append(self.table(["Relationship", "Entity", "Role / label", "Type", "Evidence"], rows, [0.17, 0.30, 0.25, 0.12, 0.16]))
        group_note = next((a["note"] for a in self.rec.get("absences") or [] if a["field"] == "parent_company" and a.get("note")), None)
        if not any(r["kind"] in ("parent", "subsidiary", "investor", "partner", "related") for r in rels):
            out.append(Spacer(1, 4))
            out.append(self.unavailable("corporate relationships", group_note, "No parent company, subsidiaries, investors or partners were established. Shareholder data has no free public source and is not collected."))
        return out

    # ----------------------------------------------------------------------- 6 Locations & establishments --
    def s_locations(self) -> list[Any]:
        sec = self.P["locations"]
        out = self.h1("Registered locations & establishments")
        out += self.section_status(sec, "locations")
        locs = sec["locations"]
        if locs:
            kind_label = {"registered_address": "Registered address", "headquarters": "Headquarters", "operating": "Establishment", "postal": "Postal address"}
            rows = []
            for loc in locs:
                addr = ", ".join(x for x in [loc.get("address"), " ".join(x for x in [loc.get("postalCode"), loc.get("municipality")] if x)] if x)
                geo = loc.get("geo")
                geo_txt = f'<br/><font size="7.1" color="{MUTED_HEX}">{geo["lat"]:.5f}, {geo["lon"]:.5f}</font>' if geo else ""
                rows.append([esc(kind_label.get(loc["kind"], loc["kind"])), f'<b>{esc(loc["label"])}</b>', esc(addr) + geo_txt, self.verification_cell(loc["fact"]), self.refs(loc["fact"].get("evidence"))])
            out.append(self.p(f"{len(locs)} registered {'location' if len(locs) == 1 else 'locations'} in the saved data."))
            out.append(self.table(["Type", "Name", "Address", "Verification", "Evidence"], rows, [0.14, 0.2, 0.31, 0.19, 0.16]))
        elif sec.get("status") == "available":
            out.append(self.unavailable("locations", None, "No registered locations were saved for this company."))
        return out

    # --------------------------------------------------------------------------------- 7 Digital presence --
    def s_digital(self) -> list[Any]:
        web = self.P["website"]
        out = self.h1("Digital presence")
        out += self.section_status(web, "website")
        rows: list[list[Any]] = []
        if web.get("url"):
            rows.append(["<b>Official website</b>", link(web["url"]) + (f'<br/><font size="7.1" color="{MUTED_HEX}">domain {esc(web.get("domain"))}</font>' if web.get("domain") else ""),
                         (self.verification_cell(web["verification"]) if web.get("verification") else chip("unverified", "Unverified")),
                         self.refs((web.get("verification") or {}).get("evidence"))])
        if web.get("verification"):
            v = web["verification"]
            rows.append(["<b>Ownership check</b>", self.value_cell(v), self.verification_cell(v), self.refs(v.get("evidence"))])
        if rows:
            out.append(self.table(["Item", "Value", "Verification", "Evidence"], rows, [0.21, 0.43, 0.20, 0.16]))
        out.extend(self.h2("Website description"))
        d = web.get("description")
        if d and d.get("status") == "verified":
            same = self.P.get("description") and self.P["description"].get("id") == d.get("id")
            out.append(self.box("note", "Company-stated description", esc("Same text as the company description in section 2.") if same else esc(clip(display_value(d))),
                                basis=f"{self.verification_cell(d)} &nbsp; {self.refs(d.get('evidence'))}"))
        else:
            out.append(self.unavailable("website description", (d or {}).get("note"), "No description could be read from a verified company website."))
        out.extend(self.h2("Key pages"))
        pages = web.get("pages") or []
        if pages:
            rows = [[f'<b>{esc(pg["title"])}</b>', chip("verified", "Found") if pg["found"] else chip("unavailable", "Not found"),
                     link(pg.get("url")) if pg.get("url") else f'<font color="{MUTED_HEX}"><i>not found on the verified website</i></font>'] for pg in pages]
            out.append(self.table(["Page", "Result", "Address"], rows, [0.24, 0.16, 0.60]))
        else:
            out.append(self.unavailable("key pages", None, "No pages were catalogued, because no verified website was read."))
        out.extend(self.h2("Social presence"))
        social = web.get("social") or []
        if social:
            rows = [[f'<b>{esc(s["network"].title())}</b>', esc(s.get("handle") or "—"), link(s["url"]), self.verification_cell(s["fact"]), self.refs(s["fact"].get("evidence"))] for s in social]
            out.append(self.table(["Network", "Handle", "Link", "Verification", "Evidence"], rows, [0.13, 0.17, 0.33, 0.21, 0.16]))
        else:
            li = (self.rec.get("modules") or {}).get("linkedin") or {}
            out.append(self.unavailable("social profiles", None, "No social profiles are linked from the verified website. " + (li.get("note") or "")))
        out.extend(self.h2("Digital signals"))
        sigs = web.get("signals") or []
        if sigs:
            rows = [[f'<b>{esc(s["label"])}</b>', esc(s["value"]), self.refs((s.get("fact") or {}).get("evidence")) if s.get("fact") else f'<font color="{MUTED_HEX}">observed on the website</font>'] for s in sigs]
            out.append(self.table(["Signal", "Observation", "Evidence"], rows, [0.3, 0.45, 0.25]))
        else:
            out.append(self.unavailable("digital signals", None, "No website was read, so no signals were observed."))
        attempts = self.rec.get("site_attempts") or []
        if attempts:
            out.extend(self.h2("How the website was verified"))
            rows = [[link(a.get("url")), esc(a.get("origin") or "—"), chip("verified", "Verified") if a.get("decision") == "verified" else chip("unverified", str(a.get("decision") or "Not verified")),
                     esc(", ".join(a.get("signals") or []) or "—") + (f'<br/><font color="{RED_HEX}" size="7.2">conflicts: {esc(", ".join(a["conflicts"]))}</font>' if a.get("conflicts") else "")
                     + (f'<br/><font size="7.2" color="{MUTED_HEX}">{esc(a["note"])}</font>' if a.get("note") else "")] for a in attempts]
            out.append(self.table(["Candidate website", "Found via", "Decision", "Identity signals"], rows, [0.30, 0.14, 0.14, 0.42]))
        return out

    # ------------------------------------------------------------------------------------ 8 Hiring --
    def s_hiring(self) -> list[Any]:
        h = self.P["hiring"]
        out = self.h1("Hiring & careers")
        outcome = h.get("outcome")
        headline = {"verified": ("verified", f"{h.get('totalCurrent')} verified current opening(s)"), "none_found": ("unavailable", "No openings found in the sources checked"),
                    "source_unavailable": ("unavailable", "Hiring source unavailable"), "incomplete": ("unverified", "Hiring research incomplete"),
                    "pending": ("unavailable", "Not researched yet")}.get(outcome or "", ("unavailable", "Hiring not established"))
        out.append(self.kv([("Hiring result", chip(*headline)), ("Current openings", esc(str(h["totalCurrent"])) if h["totalCurrent"] is not None else "Not established"),
                            ("Checked at", esc(fmt_dt(h.get("verifiedAt"))) if h.get("verifiedAt") else "Not recorded")] + ([("Statement", esc(h["message"]))] if h.get("message") else [])))
        out.append(self.p("Not finding openings is never reported as “not hiring”: it only means nothing was found in the sources that could be read.", "caption"))
        out.extend(self.h2("Sources checked"))
        checks = h.get("checks") or []
        if checks:
            state = {"checked": chip("verified", "Checked"), "unavailable": chip("unavailable", "Unavailable"), "incomplete": chip("unverified", "Incomplete")}
            rows = [[f'<b>{esc(c["name"])}</b>', state.get(c["state"], esc(c["state"])), "Yes" if c.get("required") else "No", esc(c.get("note") or "")] for c in checks]
            out.append(self.table(["Source", "Result", "Required", "Note"], rows, [0.27, 0.15, 0.10, 0.48]))
        else:
            nav = (self.rec.get("modules") or {}).get("nav_jobs") or {}
            jobs_mod = (self.rec.get("modules") or {}).get("jobs") or {}
            lines = [esc(x) for x in (jobs_mod.get("note"), nav.get("note")) if x]
            out.append(self.unavailable("per-source hiring checks", " ".join(lines) or None, "This research record does not list which hiring sources were checked."))
        out.extend(self.h2("Job postings"))
        jobs = h["jobs"]
        if jobs:
            state_chip = {"current": chip("verified", "Current"), "stale": chip("unverified", "Stale"), "closed": chip("unavailable", "Closed")}
            rows = []
            for j in jobs:
                dates = "<br/>".join(x for x in [f"posted {fmt_date(j['postedAt'])}" if j.get("postedAt") else "", f"updated {fmt_date(j['updatedAt'])}" if j.get("updatedAt") else "",
                                                  f"valid to {fmt_date(j['validThrough'])}" if j.get("validThrough") else "", f"read {fmt_dt(j['checkedAt'])}" if j.get("checkedAt") else ""] if x)
                also = "".join(f'<br/><font size="7" color="{MUTED_HEX}">also listed: {link(a.get("url"))}</font>' for a in j.get("alsoListed") or [])
                title = f'<b>{esc(j["title"])}</b>' + (f'<br/><font size="7.2" color="{MUTED_HEX}">{esc(j["department"])}</font>' if j.get("department") else "")
                rows.append([title, esc(j.get("location") or "—"), f'<font size="7.4">{dates or "—"}</font>', state_chip.get(j["state"], esc(j["state"])),
                             f'{self.src_ref(j["sourceId"])}<br/>{link(j.get("url"))}{also}<br/>{self.refs(j["evidence"])}'])
            out.append(self.p(f"{len(jobs)} posting(s) in the saved record; only those marked Current count as openings."))
            out.append(self.table(["Position", "Location", "Dates", "State", "Source and evidence"], rows, [0.21, 0.12, 0.17, 0.10, 0.40]))
        else:
            out.append(self.unavailable("job postings", None if outcome != "none_found" else h.get("message"), "No job postings are saved for this company."))
        if h["locations"] or h["categories"]:
            out.extend(self.h2("Where and what"))
            out.append(self.table(["Location", "Openings"], [[esc(x["name"]), str(x["count"])] for x in h["locations"]], [0.7, 0.3]))
            out.append(Spacer(1, 5))
            out.append(self.table(["Department / category", "Openings"], [[esc(x["name"]), str(x["count"])] for x in h["categories"]], [0.7, 0.3]))
        out.extend(self.h2("Hiring history"))
        if h.get("history"):
            out.append(self.table(["Month", "Openings"], [[esc(x["month"]), str(x["count"])] for x in h["history"]], [0.5, 0.5]))
        else:
            out.append(self.unavailable("hiring history", None, "No month-by-month hiring series is stored; COGNIS keeps the point-in-time result of each research run (see section 10)."))
        return out

    # ---------------------------------------------------------------------------------- 9 Recent activity --
    def activity_rows(self, events: list[dict[str, Any]], *, compact: bool) -> list[list[Any]]:
        rows = []
        for e in events:
            ev_lines = []
            for ev in e["evidence"]:
                line = f'{self.src_ref(ev["sourceId"])} \u00b7 {self.refs([ev])}'
                if ev.get("url"):
                    line += f"<br/>{link(ev['url'])}"
                if ev.get("excerpt"):
                    line += f'<br/><font name="{ITAL}" size="7.1" color="{MUTED_HEX}">\u201c{esc(clip(ev["excerpt"], 220 if compact else 600))}\u201d</font>'
                if ev.get("excerptTranslation") and not compact:
                    line += f'<br/><font size="7.1" color="{MUTED_HEX}">English: {esc(clip(ev["excerptTranslation"], 600))}</font>'
                ev_lines.append(line)
            title = f'<b>{esc(e["title"])}</b>' + (f'<br/>{esc(clip(e["description"], 300 if compact else 900))}' if e.get("description") else "")
            if e.get("url"):
                title += f"<br/>{link(e['url'])}"
            if not compact and e.get("reasons"):
                title += f'<br/><font size="7.1" color="{MUTED_HEX}">Why {esc(e["significance"])}: {esc("; ".join(e["reasons"]))}.</font>'
            others = [x for x in (e.get("sources") or [])[1:] if x.get("url")]
            if others:
                title += f'<br/><font size="7.1" color="{MUTED_HEX}">Also stated at: {"; ".join(esc(clip(x["url"], 90)) for x in others)}</font>'
            kind = esc(e["type"].replace("_", " ").title())
            rows.append([esc(fmt_date(e["date"])), title, f'{kind}<br/><font size="7.1" color="{MUTED_HEX}">{esc(SOURCE_TYPE_LABEL.get(e.get("sourceType") or "", "Source"))}</font>',
                         "<br/><br/>".join(ev_lines) if ev_lines else f'<font color="{MUTED_HEX}"><i>no evidence stored</i></font>'])
        return rows

    def s_activity(self) -> list[Any]:
        sec = self.P["activity"]
        out = self.h1("Recent activity")
        out += self.section_status(sec, "activity")
        events = sorted(sec["events"], key=lambda e: e["date"], reverse=True)
        counts = sec.get("counts") or {t: sum(1 for e in events if e["significance"] == t) for t in ("major", "relevant", "routine")}
        if events:
            out.append(self.p(f"{len(events)} event(s) recorded: {counts.get('major', 0)} major, {counts.get('relevant', 0)} relevant and {counts.get('routine', 0)} routine. "
                              "Events are ranked by business impact, financial importance, operational consequence, strategic relevance and recency; "
                              "register entries (registrations, establishments, group changes) stay listed but are never counted as major developments on their own."))
            out.append(self.p("Titles and descriptions are the source's wording, not COGNIS's. Each event states the reasons for its ranking.", "caption"))
            for tier, heading in (("major", "Major developments"), ("relevant", "Relevant developments"), ("routine", "Routine and register events")):
                group = [e for e in events if e["significance"] == tier]
                if not group:
                    continue
                out.extend(self.h2(f"{heading} ({len(group)})"))
                out.append(self.table(["Date", "Event", "Type and source", "Source and evidence"], self.activity_rows(group, compact=tier == "routine"), [0.11, 0.33, 0.12, 0.44]))
            if sec.get("consolidated"):
                out.append(self.p(f"{sec['consolidated']} duplicate report(s) of the same announcement were merged; each event lists every place it was found.", "caption"))
        elif sec.get("status") == "available":
            out.append(self.unavailable("recent activity", None, "No dated events were found in the sources searched."))
        omitted = sec.get("omitted")
        if omitted:
            out.append(self.box("warn", "Not all routine events are listed", esc(f"{omitted} lowest-ranked routine event(s) are not listed here; the saved record keeps them.")))
        checks = sec.get("sourcesChecked") or []
        if checks:
            out.extend(self.h2("What was checked for this section"))
            status_label = {"read": "Read", "blocked": "Blocked", "not_found": "Nothing found", "failed": "Could not be read", "not_run": "Not checked", "no_dated_items": "No dated items", "not_checked": "Not checked"}
            rows = [[esc(c["name"]), esc(status_label.get(c["status"], c["status"])) + (f' ({c["items"]})' if c.get("items") else ""),
                     (link(c["url"]) + "<br/>" if c.get("url") else "") + esc(clip(c.get("note") or "", 260))] for c in checks]
            out.append(self.table(["Source", "Result", "Detail"], rows, [0.26, 0.17, 0.57]))
            out.append(self.p("A source that could not be read, or a search that found nothing, is a limitation of this research. It is not evidence that nothing happened.", "caption"))
        excluded = sec.get("excluded") or {}
        if excluded.get("count"):
            out.extend(self.h2("Candidates not shown"))
            out.append(self.p(f"{excluded['count']} candidate event(s) were excluded because they could not be supported (no valid date, source URL or matching evidence)."))
            out.append(self.table(["Candidate", "Reason"], [[esc(clip(x["title"], 120)) + (f" ({esc(x['date'])})" if x.get("date") else ""), esc(x["reason"])] for x in excluded["items"]], [0.55, 0.45]))
        return out

    # ------------------------------------------------------------------- 10 Changes & research history --
    def s_changes(self) -> list[Any]:
        sec = self.P["changes"]
        out = self.h1("Changes detected & research history")
        out.extend(self.h2("Changes since the previous research"))
        out += self.section_status(sec, "changes")
        if sec.get("since"):
            out.append(self.p(f"Compared with the {esc(sec.get('baselineLabel') or 'previous research')} completed {esc(fmt_dt(sec['since']))}."))
        changes = sec["changes"]
        if changes:
            rows = [[esc(fmt_dt(c["detectedAt"])), f'<b>{esc(c["headline"] or c["label"])}</b><br/><font size="7.3" color="{MUTED_HEX}">{esc(c["category"].title())} · {esc(c["label"])}</font>',
                     f'{esc(c.get("previous") or "—")} <b>→</b> {esc(c.get("current") or "—")}', chip("verified", "Material") if c.get("material") else chip("unavailable", "Minor"), self.refs(c["evidence"])]
                    for c in changes]
            out.append(self.table(["Detected", "Change", "Previous → current", "Weight", "Evidence"], rows, [0.15, 0.30, 0.30, 0.10, 0.15]))
        shown = {c["id"] for c in changes}
        earlier = [c for c in self.sr.change_log if c.get("id") not in shown]
        out.extend(self.h2("Earlier changes (from previous runs)"))
        if earlier:
            rows = [[esc(fmt_dt(c.get("detected_at"))), f'<b>{esc(c.get("headline") or c.get("label") or c.get("field"))}</b><br/><font size="7.3" color="{MUTED_HEX}">{esc((c.get("category") or "event").title())}</font>',
                     f'{esc(c.get("old_display") or "—")} <b>→</b> {esc(c.get("new_display") or "—")}', chip("verified", "Material") if c.get("material", True) else chip("unavailable", "Minor"),
                     link(c.get("source_url")) if c.get("source_url") else f'<font color="{MUTED_HEX}">no URL stored</font>'] for c in earlier]
            out.append(self.table(["Detected", "Change", "Previous → current", "Weight", "Source"], rows, [0.15, 0.27, 0.27, 0.09, 0.22]))
        else:
            out.append(self.unavailable("earlier changes", None, "No changes from earlier research runs are saved for this company."))
        out.extend(self.h2("Research history"))
        versions = self.sr.versions
        if versions:
            rows = [[str(len(versions) - i), esc(fmt_dt(v["created_at"])), esc(v.get("label") or "—"), esc(v.get("run_id") or "—"),
                     chip("verified", "This report") if i == 0 else ""] for i, v in enumerate(versions)]
            out.append(self.table(["#", "Saved", "Label", "Run", ""], rows, [0.07, 0.28, 0.25, 0.25, 0.15]))
        else:
            out.append(self.unavailable("research history", None, "No saved versions are listed."))
        ops = self.rec.get("operations") or {}
        out.extend(self.h2("Latest run"))
        out.append(self.kv([("Started", esc(fmt_dt(self.rec.get("started_at")))), ("Completed", esc(fmt_dt(self.completed_at))),
                            ("Requests made", esc(str(ops.get("requests", "not recorded")))), ("Run time", esc(f"{ops['runtime_ms']} ms") if ops.get("runtime_ms") is not None else "not recorded"),
                            ("Searches", esc(str(ops.get("searches", "not recorded"))))]))
        return out

    # ---------------------------------------------------------------- 11 Research coverage & verification --
    def s_coverage(self) -> list[Any]:
        q = self.P["quality"]
        cov = q["coverage"]
        out = self.h1("Research coverage & verification")
        out.extend(self.h2("Coverage by area"))
        area_label = {"company_record": "Company record", "financials": "Financials", "people_locations": "People & locations", "website": "Website", "hiring_activity": "Hiring & activity"}
        status_chip = {"complete": chip("verified", "Complete"), "partial": chip("unverified", "Partial"), "unavailable": chip("unavailable", "Unavailable"),
                       "blocked": chip("unavailable", "Blocked"), "pending": chip("unavailable", "Not researched")}
        rows = [[f'<b>{esc(area_label.get(a["area"], a["area"]))}</b>', status_chip.get(a["status"], esc(a["status"])), str(a["factCount"]), esc(a.get("note") or "")] for a in cov["areas"]]
        out.append(self.p(f"{cov['complete']} of {cov['total']} research areas are complete."))
        out.append(self.table(["Area", "Status", "Verified facts", "Note"], rows, [0.22, 0.18, 0.14, 0.46]))
        out.extend(self.h2("Verification status"))
        facts = [i for i in self.sr.items if i["type"] == "fact"]
        counts: dict[str, int] = {}
        for i in facts:
            k = i["verificationLabel"] if i["verification"] != "unavailable" else "Unavailable"
            counts[k] = counts.get(k, 0) + 1
        rows = []
        for label in [*EVIDENCE_STATE_LABEL.values(), "Unavailable"]:
            vkey = "verified" if label.startswith("Verified") else "conflict" if label.startswith("Conflict") else "unavailable" if label == "Unavailable" else "unverified"
            rows.append([chip(vkey, label), str(counts.pop(label, 0))])
        rows += [[chip("unavailable", k), str(n)] for k, n in sorted(counts.items())]  # other statuses, e.g. "Blocked" or "Not researched"
        summary_item = next((i for i in self.sr.items if i["type"] == "summary"), None)
        if summary_item:
            rows.append([chip(summary_item["verification"], summary_item["verificationLabel"]), "executive summary (text)"])
        out.append(self.p(f"Counted over the {len(facts)} facts in this report; unavailable items are those the record explicitly lists as not established."))
        out.append(self.table(["Verification", "Facts"], rows, [0.7, 0.3]))
        out.extend(self.h2("Sources and conflicts"))
        reg = self.reg
        out.append(self.kv([("Sources cited", esc(f"{len(reg.sources)} (primary: {q['primarySources']}, secondary or discovery: {q['secondarySources']})")),
                            ("Evidence items stored", esc(str(len(reg.evidence)))), ("Conflicting facts", esc(str(q["conflicts"]))),
                            ("Last refreshed", esc(fmt_dt(q.get("lastRefreshedAt"))) if q.get("lastRefreshedAt") else "Not recorded")]))
        conflicts = [i for i in self.sr.items if i.get("conflict")]
        if conflicts:
            rows = []
            for i in conflicts:
                lines = []
                for cand in i["conflict"].get("candidates") or []:
                    val = cand.get("displayValue") or (format_money(cand["value"], cand["currency"]) if cand.get("currency") and isinstance(cand["value"], (int, float)) else cand["value"])
                    lines.append(f"{self.src_ref(cand['sourceId'])}: <b>{esc(val)}</b>" + (f" ({esc(cand['reportingPeriod'])})" if cand.get("reportingPeriod") else ""))
                rows.append([f'<b>{esc(i["label"])}</b>', esc(i.get("reportingPeriod") or "—"), "<br/>".join(lines), esc(i["conflict"].get("reason") or "No reason recorded.")])
            out.append(Spacer(1, 4))
            out.append(self.table(["Fact", "Period", "Values by source", "Possible reason"], rows, [0.2, 0.1, 0.45, 0.25]))
        else:
            out.append(Spacer(1, 4))
            out.append(self.p("No conflicting values were found between sources."))
        out.extend(self.h2("Source access and unavailable sources"))
        mods = self.rec.get("modules") or {}
        if mods:
            rows = []
            for name, m in sorted(mods.items(), key=lambda kv: (kv[1].get("state") == "available", kv[0])):
                state = m.get("state") or "not_available"
                rows.append([f'<b>{esc(MODULE_LABELS.get(name, name))}</b>', chip("verified", MODULE_STATES[state]) if state == "available" else chip("unavailable", MODULE_STATES.get(state, state)),
                             esc(fmt_dt(m.get("retrieved_at"))) if m.get("retrieved_at") else "—", esc(m.get("note") or "") + (f'<br/>{link(m.get("url"))}' if m.get("url") else "")])
            out.append(self.table(["Source", "Result", "Checked", "Note / address"], rows, [0.27, 0.2, 0.15, 0.38]))
        else:
            out.append(self.unavailable("source access log", None, "This record does not list per-source results."))
        out.extend(self.h2("Information not established"))
        absences = self.rec.get("absences") or []
        if absences:
            rows = [[f'<b>{esc(a["field"].replace("_", " ").capitalize())}</b>', chip("unavailable", str(a.get("availability", "unavailable")).replace("_", " ")),
                     esc(a.get("note") or "No explanation recorded.")] for a in absences]
            out.append(self.table(["Field", "Status", "Explanation"], rows, [0.25, 0.17, 0.58]))
        else:
            out.append(self.p("The record lists no explicitly absent fields."))
        rejections = self.rec.get("rejections") or []
        out.extend(self.h2("Observations the evidence gate rejected"))
        if rejections:
            out.append(self.p(f"{len(rejections)} observation(s) were found but not published, because they could not be tied to this company or failed an evidence check. They are not part of any figure in this report."))
            rows = [[esc(r.get("field")), esc(str(r.get("value"))[:200] + ("…" if len(str(r.get("value"))) > 200 else "")), esc(r.get("reason")), esc(r.get("module") or "—"),
                     link(r.get("source_url")) if r.get("source_url") else "—"] for r in rejections]
            out.append(self.table(["Field", "Observed value", "Reason", "Module", "Source"], rows, [0.15, 0.22, 0.28, 0.12, 0.23]))
        else:
            out.append(self.p("No observations were rejected in the saved run."))
        errors = self.rec.get("errors") or []
        if errors:
            out.extend(self.h2("Errors recorded during research"))
            out.append(self.table(["Stage", "Error"], [[esc(e.get("stage")), esc(e.get("error"))] for e in errors], [0.25, 0.75]))
        out.extend(self.h2("Limitations of this report"))
        limits: list[list[Any]] = []
        for _key, title, sec in (("financials", "Financials", self.P["financials"]), ("people", "People", self.P["people"]), ("locations", "Locations", self.P["locations"]),
                                ("website", "Website", self.P["website"]), ("hiring", "Hiring", self.P["hiring"]), ("activity", "Activity", self.P["activity"]), ("changes", "Changes", self.P["changes"])):
            if sec.get("status") != "available":
                limits.append([f"<b>{esc(title)}</b>", chip("unavailable", str(sec.get("status")).replace("_", " ")), esc(sec.get("message") or "Not fully available in the saved record.")])
        limits.append(["<b>Scope</b>", chip("unavailable", "General"),
                       "Only public sources COGNIS is permitted to use are searched. LinkedIn is not collected automatically; shareholder registers and credit ratings have no free source and are left empty. "
                       "Nothing here is investment, credit or legal advice."])
        out.append(self.table(["Area", "Status", "Statement"], limits, [0.17, 0.18, 0.65]))
        return out

    # --------------------------------------------------------------------- 12 Source references & evidence --
    def s_sources(self) -> list[Any]:
        reg = self.reg
        out = self.h1("Source references & evidence")
        out.extend(self.h2("Source register"))
        usage = {u["source"]["id"]: u for u in self.P.get("sources") or []}
        rows = []
        for sid, src in reg.sources.items():
            n = reg.source_number(sid)
            u = usage.get(sid)
            name = f'<a name="src-{n}"/><b>S{n}</b>&nbsp; {esc(src.get("name"))}' + (f'<br/><font size="7.1" color="{MUTED_HEX}">{esc(src["originalTitle"])}</font>' if src.get("originalTitle") else "")
            rows.append([name, esc(str(src.get("kind", "")).title()), esc(str(src.get("tier", "")).title()) + (" · official" if src.get("official") else ""),
                         esc(", ".join(SECTION_TITLES.get(x, x.title()) for x in u["sections"])) if u else "—", str(u["factCount"]) if u else "—",
                         esc(fmt_dt(u["lastRetrievedAt"])) if u and u.get("lastRetrievedAt") else "—", link(src.get("url")) if src.get("url") else "—"])
        out.append(self.p(f"{len(rows)} source(s) are cited in this record."))
        out.append(self.table(["Source", "Kind", "Tier", "Used in", "Facts", "Last read", "Address"], rows, [0.22, 0.09, 0.12, 0.17, 0.06, 0.14, 0.20]))
        out.extend(self.h2("Evidence register"))
        entries = reg.entries()
        if not entries:
            out.append(self.unavailable("evidence", None, "This record stores no evidence items."))
            return out
        out.append(self.p(f"{len(entries)} piece(s) of evidence, numbered in the order they are first cited. Excerpts are exactly as stored."))
        for entry in entries:
            ev, n = entry["evidence"], entry["n"]
            src = reg.sources.get(ev["sourceId"]) or {}
            sn = reg.source_number(ev["sourceId"])
            meta = [f"retrieved {fmt_dt(ev.get('retrievedAt'))}" if ev.get("retrievedAt") else "retrieval time not stored"]
            if ev.get("reportingPeriod"):
                meta.append(f"period {ev['reportingPeriod']}")
            if ev.get("page"):
                meta.append(f"page {ev['page']}")
            supports = []
            for s in entry["supports"]:
                t = f"{s['label']} ({s['reportingPeriod']})" if s.get("reportingPeriod") and s["reportingPeriod"] not in s["label"] else s["label"]
                supports.append(f"{SECTION_TITLES.get(s['section'], s['section'])}: {t}")
            parts: list[Any] = [Paragraph(f'<a name="ev-{n}"/><font name="{BOLD}" color="{NAVY_HEX}" size="9">E{n}</font>&nbsp;&nbsp;<b>{esc(src.get("name") or ev["sourceId"])}</b>'
                                          + (f' <a href="#src-{sn}" color="{BLUE_HEX}">[S{sn}]</a>' if sn else "") + f'<font color="{MUTED_HEX}" size="7.6"> &nbsp;·&nbsp; {esc(" · ".join(meta))}</font>', self.st["bodytight"])]
            if ev.get("documentTitle"):
                parts.append(Paragraph(f'<i>{esc(ev["documentTitle"])}</i>', self.st["cellsm"]))
            if supports:
                shown = supports
                parts.append(Paragraph(f'<font color="{MUTED_HEX}">Supports:</font> {esc("; ".join(shown))}', self.st["cell"]))
            if ev.get("url"):
                parts.append(Paragraph(link(ev["url"]), self.st["cell"]))
            if ev.get("statedValue"):
                parts.append(Paragraph(f'<font color="{MUTED_HEX}">Value as stated by this source:</font> {esc(ev["statedValue"])}', self.st["cell"]))
            if ev.get("excerpt"):
                parts.append(Paragraph(f'<font name="{ITAL}">“{esc(clip(ev["excerpt"]))}”</font>' + (f' <font color="{MUTED_HEX}" size="7">({"Norwegian" if ev.get("excerptLanguage") == "no" else "English"})</font>' if ev.get("excerptLanguage") else ""), self.st["cell"]))
            else:
                parts.append(Paragraph(f'<font color="{MUTED_HEX}"><i>No excerpt stored for this evidence.</i></font>', self.st["cellsm"]))
            if ev.get("excerptTranslation"):
                parts.append(Paragraph(f'<font color="{MUTED_HEX}">English:</font> {esc(clip(ev["excerptTranslation"]))}', self.st["cell"]))
            card = Table([[parts]], colWidths=[CW])
            card.setStyle([("LINEBEFORE", (0, 0), (0, -1), 2, BLUE), ("LEFTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.3, RULE)])
            out.append(KeepTogether([card, Spacer(1, 3)]))
        return out

    # ------------------------------------------------------------------------------------------ story --
    def story(self) -> list[Any]:
        toc = TableOfContents()
        toc.levelStyles = [self.st["toc0"], self.st["toc1"]]
        toc.dotsMinLevel = 0
        story: list[Any] = [*self.cover_story(), NextPageTemplate("body"), PageBreak(), Paragraph("Contents", self.st["contents"]), toc]
        for build in (self.s_about, self.s_identity, self.s_summary, self.s_financials, self.s_people, self.s_locations, self.s_digital, self.s_hiring, self.s_activity,
                      self.s_changes, self.s_coverage, self.s_sources):
            story += build()
        return story


def _build(sr: SavedResearch, target: Any, total_pages: int | None) -> tuple[ReportBuilder, _Doc]:
    builder = ReportBuilder(sr)
    doc = _Doc(target, builder.meta, builder.paint_cover, total_pages)
    doc.multiBuild(builder.story())  # multi-pass: the contents page needs the page numbers of the sections it lists
    return builder, doc


def render_report(sr: SavedResearch, target: Any) -> ReportInfo:
    """Render the report for ``sr`` to ``target`` (a path or a binary file object).

    Two passes: the first counts the pages (so every footer can say "Page X of Y"), the second writes the file.
    """
    _ensure_styles()
    if isinstance(target, Path):
        target = str(target)
    with _render_lock:
        _, counting = _build(sr, io.BytesIO(), None)
        builder, doc = _build(sr, target, counting.page)
        sections = [{"level": v["level"], "title": v["title"], "page": v["page"]} for v in doc.found.values()]
        return ReportInfo(pages=doc.page, sections=sections, evidence_count=len(sr.registry.evidence), source_count=len(sr.registry.sources), reference=builder.reference)
