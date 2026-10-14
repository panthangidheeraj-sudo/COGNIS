# COGNIS design system

**Direction:** a premium corporate intelligence platform (not a dark-mode SaaS dashboard) — a low-saturation luxury-navy workspace with **solid** surfaces, ivory/warm-white reading surfaces (DARK = INVESTIGATE, IVORY = UNDERSTAND), and glass used only as a restrained accent on small floating layers. Blue stays a quiet accent (links, live research activity, the faint depth glow). A slowly rotating monochrome globe — near-black navy, ivory geography, a restrained silver rim — is the atmospheric anchor of the workspace (the natural Earth is kept for the About story); data, identity, evidence and actions always dominate it. Minimal architecture, calm motion. All tokens live in `src/styles/tokens.css`. Light mode redefines the same names, so components never branch on theme.

## Color tokens

| Token | Dark | Light | Use |
| --- | --- | --- | --- |
| `--bg-canvas` → `--bg-canvas-2` | `#060A12` ink → `#08101C` midnight | `#F7F3EA` ivory | Level 0 canvas with faint neutral depth glows (top right, left, bottom) + faint grain |
| `--surface-1/2/3` | `#0F1725` / `#141D2D` / `#1A2436` low-saturation luxury navy | `#FFFDF8` warm white / `#FFFFFF` / `#F2EEE5` ivory | Level 1 **solid** cards and panels, raised controls/inputs/chips, wells and hover |
| `--frost-sheen` (`--frost-blur` = 0) | cool white 3% → 0 top light | white 60% → 0 | A faint top light on solid surfaces — not glass, no blur |
| `--solid-1/2/3`, `--solid-card(-head)` | same navy steps | same whites | Sticky table headers, frozen sheet columns, SVG nodes — identical to the surfaces they sit on |
| `--chrome-bg` | `#090F1A` | `#FBF9F4` | Solid rail, scrolled top bar, mobile nav, sticky anchor bars |
| `--glass-bg` / `--glass-bg-strong` + `--glass-sheen` | navy 74% / navy 94% | warm white 78% / 94% | **Floating layers only:** command palette, search dropdowns, menus, popovers, tooltips, toasts, drawers/modals, compare tray, globe controls and labels, the hero search field |
| `--primary-bg` / `--primary-fg` | `#F2F4F7` / `#0A1018` | `#0F1B2A` / `#FFFFFF` | Primary action. White on dark, navy on light/paper |
| `--accent-soft` / `--accent-ice` | `#C6D3E4` silver / `#EEF2F8` | `#34507A` / `#1F3656` | Highlights: icons, coverage meter, selected borders, eyebrows, tab underline |
| `--accent-wash` / `-wash-2` / `--pressed-bg` | white 6% / 11% / 13% | navy 5% / 9% / white | Hover, selected and pressed states |
| `--accent` / `--live` / `--link` | `#5B8DEF` / `#7AA7F2` / `#A7C3EF` | `#3F72D8` / `#2F66D0` / `#2A5BBF` | The remaining blue: running research, active steps, links, checkboxes, map HQ ring |
| `--surface-paper` | `#F7F3EA` | `#FFFDF8` | Artifact/report body (`.paper` re-scopes tokens and turns blur off) |
| `--surface-ivory` | `#FBF8F1` | `#FFFDF8` | Flat ivory reading panels inside the dark workspace (financial views, research synthesis, compare summary band, About chapter 05) |
| `--line` / `--line-strong` | neutral white 10% / 18% | navy 8.5% / 16% | Hairlines — neutral, not blue |
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
| **Investigation workspace** | Luxury-navy canvas, solid navy surfaces and data grids, glass only on floating layers | Navigation, search, Discover, live research steps and source activity, data sheets, compare detail sections, the globe |
| **Knowledge layer** | Ivory paper (`.paper`, `src/styles/knowledge.css`) | Research artifacts (dossier body), Executive Briefs and the executive summary, the evidence drawer, "Explain this change", the research synthesis panel, the financial reading views (trend, annual values, ratios, cash/debt, sources), Compare's company headers + At-a-glance band, About's dossier sheets, chapter 05 and closing notes |

Ivory is a premium institutional research note, not a light theme: a mono masthead with hairline rules (`.note-mast`), serif section titles with mono numbering (`.note-sec-title` + `.note-sec-num`), numbered source references (`.note-ref`) that open evidence, and footnotes (`.note-footnotes`). Nothing on paper is blurred. Use paper when the user is *reading* knowledge; use navy when they are *working*. Large cards and sections should not all be navy: each reading view gets one clear ivory surface so the page has real surface contrast.

**Typography over badges.** Pills are reserved for statuses, filters, verification and compact controls. Categorical labels (reporting period, event type, change category, source kind, location kind, tags, "AI synthesis") use `.tag` — mono micro text, separated by `·`. A status inside a header or card can be `.pill--bare` (dot + words in the tone colour, no capsule). Material changes on a company read as a ledger line divided by hairlines, not a row of capsules.

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
- **Compare** (`pages/Compare`): a true side-by-side board. Each company is a peer column — a header card (mark, name, municipality, org. number, coverage, status as dot + words) — and every metric sits on one shared row (At a glance → Overview → Financials → People → Locations → Hiring → Activity → Changes), so "Revenue → A vs B vs C" reads across. The label column is narrow and quiet and stays pinned left while the columns scroll horizontally on narrow screens; companies are never stacked vertically. The header cards and the At-a-glance rows form one **ivory summary band** (the company colour, deepened, as the top line); below it each detail section opens with a sans heading on the canvas (each column's name repeated quietly) and continues as its own solid navy block per column, so the board never reads as one continuous table. Sticky section anchors are quiet text links; charts below. No winner badges, rankings or better/worse colour.
- **Discover** (`pages/Discover`): search first, interpretation second, results third. Filters are a secondary control — a **Filters** button with an active-count badge (and *Clear filters*) beside the result count and Sort — that opens a slide-over drawer with the same backend-declared filters (results update as they change). Results use the full width; cards are set editorially — a quiet place/org kicker, the company name as a 19px headline, the industry as a standfirst, the website domain with a globe icon, three key figures (mono micro labels, hairline column rules, never truncated, or *Not available*), then coverage, research state and Compare. Registry-only companies sit one surface step quieter than researched ones.
- **About** (`pages/Settings/AboutPage.tsx`): a scroll story in seven chapters (COGNIS · Find · Understand · Verify · Evidence · Research · Precision). Each act is a tall section whose stage pins under the top bar while `useScrollStory` writes its progress to `--p` (no React render per frame); CSS turns `--p` into restrained transforms/opacity — the Earth turns towards Norway, the dossier layers assemble, the verification labels arrive, the source tiers light up in rank order, the research track fills. A small floating chapter index tracks the active chapter. Reduced motion renders the same content as a calm static page (`--p: 1`).
- **Library**: Card / List / Dense. Each artifact type has an icon, a label and one quiet tint (Company silver, Report ivory, Data Sheet teal, Comparison blue, Watchlist amber, Saved search lilac).

## Globe

One scene, two looks (`GlobeStage` → lazy `IntelGlobe` / `EarthGlobe` → shared `GlobeCanvas`; each look is a `GlobeSurface` in `src/components/globe/surfaces/`). `GlobeStage` takes `variant`: `intel` (default) or `earth`.

- **`intel` — the workspace globe** (Home, Discover; result locations, and the globe turns toward hovered companies). *Corporate intelligence visualization, not Google Earth.* A matte near-black navy sphere (soft fall-off from a lit upper-left face into shade, no specular); **fine ivory dots** for land (the Natural Earth lattice in `landDots.ts`, ~1.1° apart; globes under ~190 px radius draw every other row and column so the dots never turn to grain; each dot varies a little in size and brightness, deterministically); a **hairline ivory coastline**, a faint tone on land and one soft contour a little inland, all read from a 2048×1024 Natural Earth land mask (`assets/land-mask-2k.png`, rebuilt by `scripts/prepare-land-mask.py`); a **restrained silver rim** and a barely-there halo; **sparse, small location nodes** (backend points, ringed softly; the focus node a little larger) and a few faint connection arcs from Oslo to five hubs (decorative, no data meaning). No satellite imagery, no green/brown, no neon glow, no dense wireframe. On the light (ivory) theme the same drawing is inverted: a pale paper sphere with navy ink. Palette and shading live in `intelPalette.ts`, shared by the WebGL surface and the static fallback.
- **`earth` — the natural Earth, About story only** (`#act-earth`): NASA Blue Marble imagery (public domain; `assets/earth-*.jpg`, rebuilt by `scripts/prepare-earth-textures.py`) with a natural ocean grade, green/brown land, white ice, a soft terminator, a sun glint, procedural clouds and a thin atmosphere. Its textures are only requested when this look is mounted.
- **Motion** (tuned per look): slow continuous eastward rotation that never waits for input (intel ≈ 125 s per turn, earth ≈ 105 s). Pointer → a small orientation/parallax offset (intel ≈ 5° at the screen edge) that relaxes after 2.5 s at rest. Wheel / page scroll → a small, capped, smoothly decaying spin impulse (down = faster forward, up = eases into reverse; intel adds at most ~9°/s and settles in about a second) plus a slight tilt; it always settles back to the normal rotation. With a backend focus (search hit, Discover results) it turns to the location and sways gently around it.
- **Performance:** three.js loads only where a globe is shown, and the two looks are separate lazy chunks (the land mask is ~64 KB; the Earth imagery is 2k, 1k on low-power devices); ≤ 60 fps (30 on low power), pixel ratio ≤ 1.5, paused when off-screen or the tab is hidden, and no frames at all when the scene is still (paused or reduced motion).
- **Fallback & accessibility:** a static globe in the same palette (`GlobeFallback`, shaded per pixel with the shader's own formula and drawn with the same dots) shows while WebGL loads, without WebGL, or on failure, and cross-fades to the 3D globe (the coastline arrives with WebGL). The play/pause control stops all motion (WCAG 2.2.2). Reduced motion holds the globe still; pressing play then brings back only the slow rotation (no parallax, scroll response or pulses).

A static dotted hemisphere centred on the headquarters (`AmbientGlobe`) is the quiet line-art motif on the Company header, Research Artifact cover and Data Sheet header. It is drawn once and never animates.

## Logo

The official COGNIS logo is **Atlas carrying the celestial letter C**: icon only, never with the name drawn into the image. The supplied artwork is `public/brand/cognis-atlas-reference.png`; it is the source and is never edited.

| File (`public/brand/`) | What it is | Used for |
| --- | --- | --- |
| `cognis-atlas-reference.png` | The supplied artwork, navy ink on ivory | Source only |
| `cognis-atlas-navy.png` / `-navy-sm.png` | Transparent, original ink colour | Light theme |
| `cognis-atlas-ivory.png` / `-ivory-sm.png` | Same silhouette in the original paper colour | Dark theme |
| `favicon-16/32/48.png`, `favicon.ico`, `apple-touch-icon.png`, `icon-192/512.png` | The artwork as supplied, on a rounded ivory tile | Browser tab, home screen, `manifest.webmanifest` |

- **Component**: `<CognisLogo height={…} />` (`src/components/common/CognisLogo.tsx`). `variant="auto"` follows the resolved theme (ivory emblem on dark, navy on light); `navy` / `ivory` force one. The emblem is portrait (612 × 984), so give it a **height**; the width follows. `-sm` files are chosen automatically up to 64 px tall. `object-fit: contain`, never stretched or cropped.
- **Placements**: the rail (56 px) and the mobile top bar (34 px, with the COGNIS name as live text beside it) are links that already carry `aria-label="COGNIS home"`, so the image is marked `decorative`. Anywhere else the emblem keeps its alt text, "COGNIS".
- **How the transparent files are made**: `scripts/prepare-brand-assets.py`. The artwork is one ink on one paper colour, so each pixel's mix of the two is its opacity — no colour threshold, no flood fill, no feathering. Edges, the thin orbit line and the gap where the orbit passes in front of the C are exactly the supplied artwork; the ivory version is the same shape with the colours swapped. To change the logo, replace the reference PNG and re-run the script.
- **Minimum size**: the emblem reads down to ~24 px tall; the favicon tiles are the smallest placement and keep the silhouette at 16 px.

## Component rules

- **Facts** (`FactValue`, `MetricCard`): show the value, a source-count marker and the freshness line ("FY2025 · Verified 03 Oct 2026"). Clicking opens the evidence popover, then the drawer. Missing values say why.
- **Coverage**: the 5-segment meter plus "x/5 areas". Missing areas are always listed.
- **Status**: `StatusMark` / `Pill` always pair an icon with text.
- **Evidence drawer**: ivory paper; on the right on desktop, a bottom sheet on mobile, with a focus trap and Esc to close (only the topmost overlay handles Esc). Executive-first order: the fact and exact value, verification, reporting period, last verified, source count, supporting evidence, source links; raw metadata sits behind "More technical details". Conflicts list each competing value with its source and period, mark the value shown as the headline, and give the backend's reason (or say none was given).
- **Solid by default, glass by exception**: page backgrounds, hero sections, cards, company panels, financials, tables, research surfaces, the rail and the top bar are **solid** (`--surface-*`, `--chrome-bg`) with at most a faint top light. `backdrop-filter` is used only on small floating layers — command palette, search dropdowns (`.hero-suggest`, `.art-search-results`), menus/popovers, tooltips, toasts, drawers/modals, the compare tray, the hero search field, globe controls/labels and the small source-stack tiles. Analyst tables, data grids, sticky headers and frozen columns use the same solid tones (`--solid-*`, `--solid-card`). Nothing inside `.paper` is blurred.
- **White is the action colour**: primary buttons, completed research steps, finished source tiles, the active tab underline and the rail indicator are white (navy in light mode). Blue only marks things that are live or clickable text.
- **Motif**: concentric evidence rings + node + ray. A decorative illustration — empty states, the globe, the source stack, the network graph, the report cover. It is not the logo (see Logo).
