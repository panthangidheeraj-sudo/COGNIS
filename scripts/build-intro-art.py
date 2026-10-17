#!/usr/bin/env python3
"""Builds the five launch-tour slides (public/intro/*.svg, 1200 x 800).

Every text run gets an explicit textLength computed from Inter's metrics, so the artwork lays out identically whatever
fonts the viewer's system has (an SVG used as an <img> cannot load web fonts). All names, numbers and figures are fictional
sample data and every slide says so. Run:  python3 scripts/build-intro-art.py
"""
from pathlib import Path
from xml.sax.saxutils import escape
from PIL import ImageFont

OUT = Path(__file__).resolve().parent.parent / "public" / "intro"
FONT_DIR = "/usr/share/fonts/opentype/inter/Inter-"
WEIGHTS = {400: "Regular", 500: "Medium", 600: "SemiBold", 700: "Bold"}
_cache: dict = {}

IVORY, PAPER, WELL, LINE = "#fbf8f1", "#fffdf8", "#f3eee3", "#e3dccb"
NAVY, NAVY2, INK2, INK3 = "#0f1b2a", "#1b2d46", "#34445a", "#5b6b80"
GOLD, GOLD_D, GOLD_L = "#b08d4a", "#7d6128", "#efe4cb"
GREEN, GREEN_L, AMBER, AMBER_L, COOL = "#2b7a58", "#dcefe5", "#9a6a14", "#f6e8c9", "#c6d3e4"
SANS = "Inter, 'Segoe UI', system-ui, -apple-system, Roboto, Arial, sans-serif"
MONO = "Consolas, 'SF Mono', Menlo, 'DejaVu Sans Mono', monospace"


def width(s: str, size: float, weight: int = 400, mono: bool = False) -> float:
    if mono:
        return len(s) * size * 0.6
    key = (weight, round(size * 4))
    if key not in _cache:
        _cache[key] = ImageFont.truetype(f"{FONT_DIR}{WEIGHTS[weight]}.otf", int(size * 4))
    return _cache[key].getlength(s) / 4


class Svg:
    def __init__(self, label: str):
        self.label = label
        self.parts: list[str] = []

    def add(self, s: str):
        self.parts.append(s)

    def rect(self, x, y, w, h, fill=PAPER, r=0, stroke=None, sw=2, extra=""):
        st = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}"{st}{extra}/>')

    def text(self, x, y, s, size=26, weight=400, fill=NAVY, anchor="start", mono=False, max_w=None):
        w = width(s, size, weight, mono)
        if max_w and w > max_w:
            raise ValueError(f"text too wide ({w:.0f} > {max_w}): {s}")
        fam = MONO if mono else SANS
        x0 = x if anchor == "start" else (x - w if anchor == "end" else x - w / 2)
        self.add(f'<text x="{x0:.1f}" y="{y}" font-family="{fam}" font-size="{size}" font-weight="{weight}" fill="{fill}" textLength="{w:.1f}" lengthAdjust="spacingAndGlyphs">{escape(s)}</text>')
        return w

    def pill(self, x, y, s, fg, bg, size=22, weight=600, h=40, pad=18):
        w = width(s, size, weight) + pad * 2
        self.rect(x, y, w, h, bg, h / 2)
        self.text(x + pad, y + h / 2 + size * 0.35, s, size, weight, fg)
        return w

    def badge(self, cx, cy, n, r=15):
        self.add(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{GOLD_L}" stroke="{GOLD}" stroke-width="2"/>')
        self.text(cx, cy + 7, str(n), 20, 700, GOLD_D, "middle")

    def check(self, cx, cy, r=17, fill=GREEN):
        self.add(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}"/>')
        self.add(f'<path d="M{cx - r * .45:.1f} {cy + r * .02:.1f} l{r * .3:.1f} {r * .32:.1f} l{r * .6:.1f} {-r * .65:.1f}" fill="none" stroke="#fff" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/>')

    def card(self, x, y, w, h, fill=PAPER, r=20, stroke=LINE):
        self.add(f'<rect x="{x + 1}" y="{y + 6}" width="{w}" height="{h}" rx="{r}" fill="{NAVY}" opacity="0.06"/>')
        self.rect(x, y, w, h, fill, r, stroke, 2)

    def render(self) -> str:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 1200 800" role="img" aria-label="{escape(self.label)}">\n'
                + "\n".join(self.parts) + "\n</svg>\n")


NAV = ["home", "discover", "research", "chat", "library"]


def icon(s: Svg, kind: str, cx: float, cy: float, on: bool):
    c = IVORY if on else "#8fa1b8"
    sty = f'fill="none" stroke="{c}" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"'
    if kind == "home":
        s.add(f'<path d="M{cx-15} {cy+1} L{cx} {cy-13} L{cx+15} {cy+1} M{cx-10} {cy-3} V{cy+14} H{cx+10} V{cy-3}" {sty}/>')
    elif kind == "discover":
        s.add(f'<circle cx="{cx}" cy="{cy}" r="14" {sty}/><path d="M{cx+5} {cy-5} L{cx-3} {cy+3} M{cx+5} {cy-5} L{cx+1} {cy+6} M{cx+5} {cy-5} L{cx-6} {cy-1}" {sty.replace('3.2', '2.4')}/>')
    elif kind == "research":
        s.add(f'<circle cx="{cx-3}" cy="{cy-3}" r="10" {sty}/><path d="M{cx+5} {cy+5} L{cx+14} {cy+14}" {sty}/>')
    elif kind == "chat":
        s.add(f'<path d="M{cx-14} {cy-12} H{cx+14} V{cy+6} H{cx-2} L{cx-10} {cy+14} V{cy+6} H{cx-14} Z" {sty}/>')
    else:
        s.add(f'<path d="M{cx-13} {cy-13} V{cy+13} M{cx-4} {cy-13} V{cy+13} M{cx+6} {cy-10} L{cx+14} {cy+12}" {sty}/>')


def frame(label: str, active: str, crumb: str) -> Svg:
    s = Svg(label)
    s.rect(0, 0, 1200, 800, IVORY)
    s.rect(0, 0, 96, 800, NAVY)
    # monogram mark (the product's own logo is not reproduced here)
    s.add(f'<circle cx="48" cy="52" r="21" fill="none" stroke="{GOLD}" stroke-width="3.5"/><path d="M57 44 A13 13 0 1 0 57 60" fill="none" stroke="{IVORY}" stroke-width="3.5" stroke-linecap="round"/>')
    for i, k in enumerate(NAV):
        cy = 150 + i * 84
        on = k == active
        if on:
            s.rect(12, cy - 34, 72, 68, NAVY2, 16)
            s.rect(0, cy - 20, 5, 40, GOLD, 2)
        icon(s, k, 48, cy, on)
    s.rect(96, 0, 1104, 80, PAPER)
    s.rect(96, 78, 1104, 2, LINE)
    s.text(128, 50, crumb, 24, 600, INK2)
    s.pill(1000, 20, "Sample data", GOLD_D, GOLD_L, 21, 600, 40, 16)
    return s


# ------------------------------------------------------------------------------------------------------------------ slides
def discover() -> Svg:
    s = frame("Discover: search for a company, tell similar names apart and confirm the legal identity before researching (sample data)", "discover", "Discover")
    s.text(128, 160, "Find a company", 46, 700)
    s.text(128, 198, "Search by name or organisation number", 25, 400, INK3)
    s.rect(128, 226, 600, 76, PAPER, 18, GOLD, 3)
    s.add(f'<circle cx="168" cy="262" r="11" fill="none" stroke="{INK3}" stroke-width="3.4"/><path d="M176 270 L186 280" stroke="{INK3}" stroke-width="3.4" stroke-linecap="round"/>')
    w = s.text(204, 275, "Nordlys", 31, 500)
    s.rect(204 + w + 4, 247, 3, 34, GOLD)
    x = 128
    for label, on in (("Active", True), ("Oslo", False), ("IT services", False)):
        x += s.pill(x, 324, label, IVORY if on else INK2, NAVY if on else WELL, 23, 600, 48, 22) + 12
    rows = [("NA", "Nordlys Analytics AS", "999 100 201 · Oslo", True), ("NM", "Nordlys Maritime Tech AS", "999 100 318 · Bergen", False), ("NE", "Nordlys Energi Holding ASA", "999 100 427 · Stavanger", False)]
    for i, (m, name, sub, sel) in enumerate(rows):
        y = 396 + i * 126
        s.card(128, y, 600, 108, WELL if sel else PAPER, 18, GOLD if sel else LINE)
        if sel:
            s.rect(128, y + 14, 7, 80, GOLD, 3)
        s.rect(156, y + 22, 64, 64, NAVY, 14)
        s.text(188, y + 63, m, 25, 700, GOLD_L, "middle")
        s.text(240, y + 48, name, 28, 700, max_w=470)
        s.text(240, y + 84, sub, 23, 400, INK3, mono=False, max_w=470)
    s.card(764, 226, 406, 520, PAPER, 22)
    s.text(796, 276, "SELECTED COMPANY", 20, 600, INK3)
    s.text(796, 330, "Nordlys Analytics AS", 33, 700, max_w=350)
    for i, (k, v) in enumerate((("Org. number", "999 100 201"), ("Legal form", "Private limited (AS)"), ("Municipality", "Oslo"), ("Status", "Active"))):
        y = 392 + i * 52
        s.text(796, y, k, 22, 400, INK3)
        s.text(1138, y, v, 23, 600, GREEN if k == "Status" else NAVY, "end")
        s.rect(796, y + 16, 342, 2, LINE)
    s.rect(796, 614, 342, 54, GREEN_L, 14)
    s.check(826, 641, 14)
    s.text(852, 650, "Identity confirmed", 24, 700, GREEN)
    s.rect(796, 684, 342, 46, NAVY, 14)
    s.text(967, 715, "Start research", 25, 600, IVORY, "middle")
    return s


def research() -> Svg:
    s = frame("Research: a structured run that retrieves registry and filing sources, confirms identity and shows progress (sample data)", "research", "Research")
    s.rect(128, 112, 1042, 100, PAPER, 20, LINE, 2)
    s.rect(152, 132, 60, 60, NAVY, 14)
    s.text(182, 171, "NA", 24, 700, GOLD_L, "middle")
    s.text(232, 156, "Nordlys Analytics AS", 33, 700, max_w=470)
    s.text(232, 192, "Org. number 999 100 201", 22, 400, INK3)
    s.pill(1146 - (width("Quick · 4 of 6 sources", 21, 600) + 32), 142, "Quick · 4 of 6 sources", AMBER, AMBER_L, 21, 600, 42, 16)
    steps = [("Identity confirmed", "Matched to the register", "done"), ("Registry facts", "Roles, address, status", "done"), ("Annual accounts", "3 filings retrieved", "done"), ("Cross-checking sources", "Comparing against the website", "live"), ("Executive brief", "Waiting for checks", "wait")]
    for i, (t, sub, st) in enumerate(steps):
        y = 252 + i * 100
        if i < len(steps) - 1:
            s.rect(158, y + 38, 3, 62, GOLD if st == "done" else LINE)
        if st == "done":
            s.check(160, y + 22, 21)
        elif st == "live":
            s.add(f'<circle cx="160" cy="{y + 22}" r="21" fill="{PAPER}" stroke="{GOLD}" stroke-width="5"/><circle cx="160" cy="{y + 22}" r="7" fill="{GOLD}"/>')
        else:
            s.add(f'<circle cx="160" cy="{y + 22}" r="21" fill="{PAPER}" stroke="{LINE}" stroke-width="4"/>')
        s.text(202, y + 18, t, 28, 700 if st != "wait" else 500, NAVY if st != "wait" else INK3, max_w=420)
        s.text(202, y + 52, sub, 22, 400, INK3, max_w=420)
    s.add(f'<rect x="202" y="{252 + 3 * 100 + 62}" width="300" height="8" rx="4" fill="{LINE}"/><rect x="202" y="{252 + 3 * 100 + 62}" width="204" height="8" rx="4" fill="{GOLD}"/>')
    s.card(664, 240, 506, 270, PAPER, 22)
    s.text(692, 288, "SOURCES", 20, 600, INK3)
    src = [("Brønnøysundregistrene", "Verified", GREEN, GREEN_L), ("Regnskapsregisteret", "Verified", GREEN, GREEN_L), ("Company website", "Checking", AMBER, AMBER_L), ("Job listings", "Not yet", INK3, WELL)]
    for i, (n, st, fg, bg) in enumerate(src):
        y = 308 + i * 48
        s.text(692, y + 32, n, 25, 600, max_w=290)
        w = width(st, 21, 600) + 32
        s.pill(1142 - w, y + 4, st, fg, bg, 21, 600, 40, 16)
        if i < 3:
            s.rect(692, y + 46, 450, 2, LINE)
    s.card(664, 534, 506, 216, PAPER, 22)
    s.text(692, 580, "FILED FINANCIALS · FY2025", 20, 600, INK3)
    for i, (k, v) in enumerate((("Revenue", "NOK 412.6M"), ("Operating result", "NOK 38.1M"), ("Equity", "NOK 126.4M"))):
        y = 622 + i * 40
        s.text(692, y + 12, k, 24, 400, INK2)
        s.text(1142, y + 12, v, 25, 700, NAVY, "end")
    return s


def evidence() -> Svg:
    s = frame("Evidence: cited claims beside the original filing record, with reporting period, retrieval date and verification state (sample data)", "library", "Evidence")
    claims = [("Revenue was NOK 412.6M in FY2025", "1", "Regnskapsregisteret", "Verified", GREEN, GREEN_L), ("Registered office is in Oslo", "2", "Brønnøysundregistrene", "Single source", AMBER, AMBER_L)]
    for i, (t, n, src, st, fg, bg) in enumerate(claims):
        y = 108 + i * 150
        s.card(128, y, 520, 134, PAPER, 18)
        s.text(156, y + 46, t, 25, 700, max_w=470)
        s.badge(170, y + 90, n)
        s.text(196, y + 97, src, 21, 500, INK2, max_w=250)
        w = width(st, 20, 600) + 28
        s.pill(620 - w, y + 74, st, fg, bg, 20, 600, 38, 14)
    s.card(128, 418, 520, 332, PAPER, 18)
    s.text(156, 464, "Revenue, NOK million", 24, 700)
    vals = [("FY21", 301), ("FY22", 322), ("FY23", 348), ("FY24", 381), ("FY25", 413)]
    base = 706
    for i, (lab, v) in enumerate(vals):
        h = (v - 240) * 1.3
        x = 168 + i * 88
        last = i == len(vals) - 1
        s.rect(x, base - h, 58, h, GOLD if last else COOL, 8)
        s.text(x + 29, base - h - 12, str(v), 21, 700 if last else 500, GOLD_D if last else INK2, "middle")
        s.text(x + 29, base + 28, lab, 20, 500, INK3, "middle")
    s.rect(160, base, 450, 2, LINE)
    s.card(684, 108, 486, 642, PAPER, 22)
    s.text(716, 156, "ORIGINAL RECORD", 20, 600, INK3)
    s.text(716, 204, "Årsregnskap 2025", 33, 700, max_w=420)
    s.text(716, 240, "Regnskapsregisteret", 24, 500, INK2)
    for i, (k, v) in enumerate((("Reporting period", "1 Jan – 31 Dec 2025"), ("Published", "30 Jun 2026"), ("Retrieved", "3 Oct 2026"), ("Account type", "Company only"))):
        y = 304 + i * 58
        s.text(716, y, k, 22, 400, INK3)
        s.text(1138, y, v, 23, 600, NAVY, "end")
        s.rect(716, y + 18, 422, 2, LINE)
    s.rect(716, 548, 422, 92, WELL, 14, LINE)
    s.text(738, 588, "Sum driftsinntekter", 23, 500, INK2, mono=False, max_w=250)
    s.text(1116, 620, "412 600 000", 30, 700, NAVY, "end", mono=True)
    s.rect(716, 664, 422, 52, GREEN_L, 14)
    s.check(744, 690, 13)
    s.text(768, 698, "Matches the cited claim", 23, 700, GREEN)
    return s


def ask() -> Svg:
    s = frame("Ask AI: a grounded answer to a research question, with numbered source citations and source attribution (sample data)", "chat", "Ask AI · Nordlys Analytics AS")
    s.rect(560, 108, 610, 100, NAVY, 22)
    s.text(590, 154, "How has revenue changed compared", 27, 500, IVORY, max_w=560)
    s.text(590, 188, "with the previous year?", 27, 500, IVORY, max_w=560)
    s.card(128, 232, 1042, 396, PAPER, 22)
    lines = [
        ("Revenue was NOK 412.6 million in FY2025, up 8.2%", None),
        ("from NOK 381.4 million in FY2024.", (1, 2)),
        ("The operating result was NOK 38.1 million.", (1,)),
    ]
    for i, (t, cites) in enumerate(lines):
        y = 290 + i * 46
        w = s.text(160, y, t, 29, 500, max_w=960)
        for j, c in enumerate(cites or ()):
            s.badge(160 + w + 26 + j * 38, y - 9, c)
    s.rect(160, 430, 978, 2, LINE)
    s.text(160, 470, "SOURCES", 20, 600, INK3)
    for i, (n, t, sub) in enumerate(((1, "Årsregnskap 2025 · Regnskapsregisteret", "Period FY2025 · retrieved 3 Oct 2026"), (2, "Årsregnskap 2024 · Regnskapsregisteret", "Period FY2024 · retrieved 3 Oct 2026"))):
        y = 496 + i * 58
        s.badge(176, y + 16, n)
        s.text(206, y + 14, t, 24, 600, max_w=640)
        s.text(206, y + 42, sub, 20, 400, INK3, max_w=640)
    s.pill(128, 654, "Show the original filing", NAVY, PAPER, 22, 600, 46, 22)
    s.rect(128, 654, 280, 46, "none", 23, LINE, 2)
    s.pill(428, 654, "What changed since last research?", NAVY, PAPER, 22, 600, 46, 22)
    s.rect(428, 654, 400, 46, "none", 23, LINE, 2)
    s.rect(128, 718, 1042, 56, PAPER, 18, GOLD, 3)
    s.text(156, 754, "Ask about Nordlys Analytics AS", 24, 400, INK3)
    s.add(f'<circle cx="1140" cy="746" r="22" fill="{NAVY}"/><path d="M1140 756 V736 M1131 745 L1140 736 L1149 745" fill="none" stroke="{IVORY}" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/>')
    return s


def workspace() -> Svg:
    s = frame("Your workspace: saved reports, a company watchlist, comparisons and recent activity (sample data)", "home", "Your workspace")
    for i, (big, lab, sub) in enumerate((("12", "Saved reports", "Library"), ("5", "Watchlist", "2 changed"), ("3", "Comparisons", "Side by side"))):
        x = 128 + i * 358
        s.card(x, 108, 326, 128, PAPER, 20)
        s.text(x + 28, 186, big, 56, 700, max_w=100)
        s.text(x + 118, 160, lab, 25, 700, max_w=190)
        s.text(x + 118, 196, sub, 22, 400, GOLD_D if i == 1 else INK3, max_w=190)
    s.card(128, 262, 560, 488, PAPER, 22)
    s.text(156, 312, "SAVED REPORTS", 20, 600, INK3)
    reps = [("Nordlys Analytics AS", "Executive brief · 3 Oct", "Verified", GREEN, GREEN_L), ("Aurora Kraft AS", "Research · 28 Sep", "Changed", GOLD_D, GOLD_L), ("Havnebyen Eiendom AS", "Comparison · 21 Sep", "Saved", INK2, WELL), ("Fjellvik Logistikk AS", "Research · 9 Sep", "Saved", INK2, WELL)]
    for i, (n, sub, st, fg, bg) in enumerate(reps):
        y = 332 + i * 100
        s.rect(156, y, 504, 84, WELL if i == 0 else PAPER, 14, LINE if i == 0 else None, 2)
        s.text(180, y + 38, n, 26, 700, max_w=340)
        s.text(180, y + 68, sub, 21, 400, INK3, max_w=300)
        w = width(st, 20, 600) + 28
        s.pill(636 - w, y + 22, st, fg, bg, 20, 600, 40, 14)
    s.card(722, 262, 448, 488, PAPER, 22)
    s.text(750, 312, "RECENT ACTIVITY", 20, 600, INK3)
    acts = [("New filing", "Nordlys Analytics AS", "FY2025 accounts", GREEN), ("CEO changed", "Aurora Kraft AS", "Since 1 Sep 2026", GOLD), ("Research complete", "Havnebyen Eiendom AS", "6 of 6 sources", GREEN), ("Added to watchlist", "Fjellvik Logistikk AS", "2 Oct 2026", COOL)]
    s.rect(764, 346, 3, 340, LINE)
    for i, (t, n, sub, c) in enumerate(acts):
        y = 346 + i * 100
        s.add(f'<circle cx="765" cy="{y + 16}" r="11" fill="{c}" stroke="{PAPER}" stroke-width="4"/>')
        s.text(796, y + 22, t, 25, 700, max_w=340)
        s.text(796, y + 52, n, 22, 500, INK2, max_w=340)
        s.text(796, y + 80, sub, 20, 400, INK3, max_w=340)
    return s


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in (("discover", discover), ("research", research), ("evidence", evidence), ("ask-ai", ask), ("workspace", workspace)):
        (OUT / f"{name}.svg").write_text(fn().render(), encoding="utf-8")
        print("wrote", name)
