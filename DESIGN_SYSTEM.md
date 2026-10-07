# COGNIS design system

**Direction:** a luxury enterprise intelligence terminal — a midnight-navy workspace with **solid** surfaces, ivory/white research surfaces, and glass used only as a restrained accent on small floating layers. Blue stays a quiet accent (links, live research activity, the faint depth glow). A natural, slowly rotating Earth is the atmospheric anchor; data, identity, evidence and actions always dominate it. Minimal architecture, calm motion. All tokens live in `src/styles/tokens.css`. Light mode redefines the same names, so components never branch on theme.

## Color tokens

| Token | Dark | Light | Use |
| --- | --- | --- | --- |
| `--bg-canvas` → `--bg-canvas-2` | `#040B17` blue-black → `#06142B` midnight | `#F7F3EA` ivory | Level 0 canvas with subtle blue tonal glows (top right, left, bottom) + faint grain |
| `--surface-1/2/3` | `#0A1830` / `#0E1F3A` / `#132845` deep navy | `#FFFDF8` warm white / `#FFFFFF` / `#F2EEE5` ivory | Level 1 **solid** cards and panels, raised controls/inputs/chips, wells and hover |
| `--frost-sheen` (`--frost-blur` = 0) | blue-white 3.5% → 0 top light | white 60% → 0 | A faint top light on solid surfaces — not glass, no blur |
| `--solid-1/2/3`, `--solid-card(-head)` | same navy steps | same whites | Sticky table headers, frozen sheet columns, SVG nodes — identical to the surfaces they sit on |
| `--chrome-bg` | `#071326` | `#FBF9F4` | Solid rail, scrolled top bar, mobile nav, sticky anchor bars |
| `--glass-bg` / `--glass-bg-strong` + `--glass-sheen` | navy 68% / navy 92% | warm white 78% / 94% | **Floating layers only:** command palette, search dropdowns, menus, popovers, tooltips, toasts, drawers/modals, compare tray, globe controls and labels, the hero search field |
| `--primary-bg` / `--primary-fg` | `#F2F4F7` / `#0A1018` | `#0F1B2A` / `#FFFFFF` | Primary action. White on dark, navy on light/paper |
| `--accent-soft` / `--accent-ice` | `#C6D3E4` silver / `#EEF2F8` | `#34507A` / `#1F3656` | Highlights: icons, coverage meter, selected borders, eyebrows, tab underline |
| `--accent-wash` / `-wash-2` / `--pressed-bg` | white 6% / 11% / 13% | navy 5% / 9% / white | Hover, selected and pressed states |
| `--accent` / `--live` / `--link` | `#5B8DEF` / `#7AA7F2` / `#A7C3EF` | `#3F72D8` / `#2F66D0` / `#2A5BBF` | The remaining blue: running research, active steps, links, checkboxes, map HQ ring |
| `--surface-paper` | `#F7F3EA` | `#FFFDF8` | Artifact/report body (`.paper` re-scopes tokens and turns blur off) |
| `--ok` `--warn` `--err` | teal / muted amber / muted red | darker variants | Status. Always paired with an icon and text |
| `--text-1…4` | `#F6F8FB` → `#6C7785` | `#0F1B2A` → `#7A889A` | Text hierarchy |

## Type

- Sans: **Geist** (UI, data). Serif: **Instrument Serif** (hero accents, dossier section titles). Mono: **Geist Mono** (micro-labels, org numbers, timestamps).
- Scale: display `clamp(40–80px)`, H1 `clamp(28–42px)`, H2 `clamp(22–30px)`, H3 19px, body 15px, data 17px, small 13.5/12px, micro 11px mono uppercase.
- Financial values use tabular numerals (`.t-num`).

## Shape, depth and spacing

- Radii: 6 / 8 / 10 / 12px (cards), 18px only for hero and overlay surfaces. Pills only for status, filters, tags and capsules.
- Borders: 1px low-contrast `--line`. Shadows: broad and soft (`--shadow-1/2/3`). Glow appears only on selected or active elements (`--glow-edge`).
- Spacing: 4px base (`--sp-1 … --sp-12`).
- Density: **Comfortable** (default) or **Compact** (`<html data-density="compact">`, set from Settings, the top-bar toggle or the command center). Compact changes `--row-h` 44 → 34px, `--cell-px`, `--card-p`, and tightens page padding, metrics, tables, data sheets (virtualizer row height follows), compare, financials, research panels and the company snapshot. All compact rules live in `src/styles/density.css`; value sizes stay legible.

## Motion

`--motion-fast 140ms · base 220ms · slow 360ms · panel 450ms · cinematic 800ms`, with `--ease-out` for entrances. Reduced motion (from the system or the user setting) shortens these durations and stops globe rotation, parallax and floating layers. Only transform and opacity are animated.

## Breakpoints

Small mobile ≤ 400 · mobile ≤ 640 (bottom nav, sheets) · tablet ≤ 960 (narrow rail) · desktop ≤ 1440 · wide > 1440.

## Two layers: investigation and knowledge

| Layer | Surface | Where |
| --- | --- | --- |
| **Investigation workspace** | Midnight-navy canvas, solid navy surfaces and data grids, glass only on floating layers | Navigation, search, Discover, live research, data sheets, compare, graphs, the globe, source activity |
| **Knowledge layer** | Ivory paper (`.paper`, `src/styles/knowledge.css`) | Research artifacts (dossier body), Executive Briefs, reports, the evidence drawer, "Explain this change", synthesis |

Ivory is a premium institutional research note, not a light theme: a mono masthead with hairline rules (`.note-mast`), serif section titles with mono numbering (`.note-sec-title` + `.note-sec-num`), numbered source references (`.note-ref`) that open evidence, and footnotes (`.note-footnotes`). Nothing on paper is blurred. Use paper when the user is *reading* knowledge; use navy when they are *working*.

## Verification language

Never percentages or scores. Labels come from `verification()` in `src/utils/status.ts`, computed from the evidence's source tiers, and always pair an icon with text:

`Verified by 2 primary sources + 1 secondary source` · `Verified by 1 primary source` · `Secondary-source evidence` · `Potential conflict` · `Not verified` · `Source blocked` · `Researching` · `Not available`.

Use `VerificationBadge` (pill) in popovers and drawers, `VerificationLine` (icon + short line) on tiles and cards.

## Executive patterns

- **Snapshot** (`components/company/Snapshot.tsx`): six facts in one solid band above the fold — Revenue (period, change vs prior period), Employees, CEO (flagged when changed), Hiring, Coverage, Last researched (freshness + Update). Every tile opens its evidence. On mobile the order is coverage, revenue, employees, CEO, hiring, freshness.
- **What changed?** (`WhatChanged.tsx`): only backend-verified *material* changes, ordered leadership → legal status → financial filings → ownership → locations → hiring → major activity → website; repeated additions fold ("2 new locations"). With none it says so and adds that this covers the sources checked, not every possible change.
- **Executive brief** (`ExecutiveBriefModal.tsx`): one screen on paper, numbered sources, "Not established by the evidence", Print, View full research. No assessment, score or advice.
- **Explain this change** (`ExplainModal.tsx`): three visibly separate layers — *Observed facts* (verified data), *Reported by sources* (attributed statements with quotes), *AI synthesis* (hatched, labelled "Not established fact", with a caveat). The backend researches; the UI never infers causes.
- **Timeline**: Major events by default, "Show all events" for minor updates.
- **Financials**: one view at a time — Trend · Annual values · Ratios · Cash / debt · Sources — shown only when the data supports it; every chart has **View table** (exact values, period, change vs prior, source).
- **Compare** (`pages/Compare`): a true side-by-side board. Each company is a peer column — a header card (mark, name, municipality, org. number, coverage, status) with a solid column band running down through every section — and every metric sits on one shared row (At a glance → Overview → Financials → People → Locations → Hiring → Activity → Changes), so "Revenue → A vs B vs C" reads across. The label column is narrow and quiet and stays pinned left while the columns scroll horizontally on narrow screens; companies are never stacked vertically. Sections are a small mono label plus a thin rule, with each column's name repeated quietly. Sticky section anchors; charts below. No winner badges, rankings or better/worse colour.
- **Discover** (`pages/Discover`): search first, interpretation second, results third. Filters are a secondary control — a **Filters** button with an active-count badge (and *Clear filters*) beside the result count and Sort — that opens a slide-over drawer with the same backend-declared filters (results update as they change). Results use the full width; cards show name, location, org. number, industry and verified website, key metrics (or *Not available*), coverage and Compare.
- **About** (`pages/Settings/AboutPage.tsx`): a scroll story in seven chapters (COGNIS · Find · Understand · Verify · Evidence · Research · Precision). Each act is a tall section whose stage pins under the top bar while `useScrollStory` writes its progress to `--p` (no React render per frame); CSS turns `--p` into restrained transforms/opacity — the Earth turns towards Norway, the dossier layers assemble, the verification labels arrive, the source tiers light up in rank order, the research track fills. A small floating chapter index tracks the active chapter. Reduced motion renders the same content as a calm static page (`--p: 1`).
- **Library**: Card / List / Dense. Each artifact type has an icon, a label and one quiet tint (Company silver, Report ivory, Data Sheet teal, Comparison blue, Watchlist amber, Saved search lilac).

## Globe

Prominent (WebGL, `GlobeStage` → lazy `GlobeCanvas`) on **Home** and **Discover** (result locations; the globe turns toward hovered companies).

- **Look:** a natural Earth — NASA Blue Marble imagery (public domain; `src/components/globe/assets/`, rebuilt by `scripts/prepare-earth-textures.py`) with a natural ocean grade, green/brown land, white ice, a soft day/night terminator on the right limb, a sun glint on water, a restrained procedural cloud layer and a thin atmosphere. Exposure sits below the UI so text and actions stay dominant.
- **Motion:** slow continuous eastward rotation (~105 s per turn) that never waits for input. Pointer → small orientation/parallax offset that relaxes after 2.5 s at rest. Wheel / page scroll → a capped, smoothly decaying spin impulse (down = faster forward, up = eases into reverse) plus a slight tilt; it always settles back to the normal rotation. With a backend focus (search hit, Discover results) it turns to the location and sways gently around it.
- **Performance:** three.js and the imagery load only where the globe is shown (2k texture, 1k on low-power devices); ≤ 60 fps (30 on low power), pixel ratio ≤ 1.5, paused when off-screen or the tab is hidden, and no frames at all when the scene is still (paused or reduced motion).
- **Fallback & accessibility:** a static natural-palette globe (`GlobeFallback`) shows while WebGL loads, without WebGL, or on failure, and cross-fades to the 3D Earth. The play/pause control stops all motion (WCAG 2.2.2). Reduced motion holds the Earth still; pressing play then brings back only the slow rotation (no parallax, scroll response or cloud drift).

A static dotted hemisphere centred on the headquarters (`AmbientGlobe`) is the quiet line-art motif on the Company header, Research Artifact cover and Data Sheet header. It is drawn once and never animates.

## Component rules

- **Facts** (`FactValue`, `MetricCard`): show the value, a source-count marker and the freshness line ("FY2025 · Verified 03 Oct 2026"). Clicking opens the evidence popover, then the drawer. Missing values say why.
- **Coverage**: the 5-segment meter plus "x/5 areas". Missing areas are always listed.
- **Status**: `StatusMark` / `Pill` always pair an icon with text.
- **Evidence drawer**: ivory paper; on the right on desktop, a bottom sheet on mobile, with a focus trap and Esc to close (only the topmost overlay handles Esc). Executive-first order: the fact and exact value, verification, reporting period, last verified, source count, supporting evidence, source links; raw metadata sits behind "More technical details". Conflicts list each competing value with its source and period, mark the value shown as the headline, and give the backend's reason (or say none was given).
- **Solid by default, glass by exception**: page backgrounds, hero sections, cards, company panels, financials, tables, research surfaces, the rail and the top bar are **solid** (`--surface-*`, `--chrome-bg`) with at most a faint top light. `backdrop-filter` is used only on small floating layers — command palette, search dropdowns (`.hero-suggest`, `.art-search-results`), menus/popovers, tooltips, toasts, drawers/modals, the compare tray, the hero search field, globe controls/labels and the small source-stack tiles. Analyst tables, data grids, sticky headers and frozen columns use the same solid tones (`--solid-*`, `--solid-card`). Nothing inside `.paper` is blurred.
- **White is the action colour**: primary buttons, completed research steps, finished source tiles, the active tab underline and the rail indicator are white (navy in light mode). Blue only marks things that are live or clickable text.
- **Motif**: concentric evidence rings + node + ray. It appears in the logo, empty states, the globe, the source stack, the network graph and the report cover.
