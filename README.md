# COGNIS — Frontend

**Company intelligence, built from evidence.** Research · Discover · Verify

The COGNIS frontend for the Builderr Signalpost Hackathon: a React + TypeScript + Vite workspace to **find, understand, compare and verify** Norwegian companies. It talks to the backend only through a typed API contract. Until the backend is ready, it runs on a built-in **mock backend** that uses the same contract.

> **Demo data notice:** In mock mode, every company, person and figure is **fictional**. Source names such as Brønnøysundregistrene are real public sources, but they only appear as labels here. Evidence excerpts are sample text.

---

## Quick start

```bash
npm install
npm run dev          # http://localhost:5173  (mock backend by default)
```

| Script | What it does |
| --- | --- |
| `npm run dev` | Starts the dev server (built-in mock backend) |
| `npm run dev:live` | Starts the dev server against the real backend (`backend/`, port 8000) |
| `npm run build` | Type-checks, then builds to `dist/` |
| `npm run preview` | Serves the production build |
| `npm test` | Runs the unit, component and integration tests (Vitest + Testing Library) |
| `npm run typecheck` | Runs TypeScript only |
| `npm run gen:geo` | Regenerates the offline globe dots and the Norway outline from Natural Earth |

Requires Node 20 or newer.

## Connecting the real backend

The backend lives in [`backend/`](./backend/README.md) (Python / FastAPI). Start it with
`uvicorn app.api.main:app --port 8000` inside `backend/`, then run `npm run dev:live` here — Vite's
`live` mode switches the app to the real API and the dev server proxies `/api` to port 8000.
You can also put `VITE_API_MODE=live` and `VITE_API_BASE_URL=/api` in `.env.local` and use `npm run dev`.

The backend implements the endpoints listed in [`API_CONTRACT.md`](./API_CONTRACT.md). No UI code needs to change. **Never put API keys in `VITE_*` variables**, because they ship to the browser. All calls that need secrets (Groq, source APIs, Builderr) go through the backend.

## What's inside

| Area | Route | Highlights |
| --- | --- | --- |
| Home | `/` | Lazy WebGL dot-matrix Earth with a static fallback, hero search that routes on the backend's intent, action cards, recent research and watchlist updates |
| Discover | `/discover` | Natural-language queries with an editable "Interpreted as" panel. Filters come only from the backend's declared capabilities. Card, table and landscape (scatter) views |
| Research | `/research` | Prompt composer, editable plan for deep runs, a live **semantic source stack** (Registry · Financials · Company Website · People · Hiring · Public Activity), a stage track, an event timeline, streaming synthesis with citations, a **completion summary** from the backend's real values, and states for ambiguity, blocked sources and failures |
| Company | `/company/:org` | Five-second **snapshot** (revenue, employees, CEO, hiring, coverage, freshness), **What changed?**, **Executive brief**, **Explain this change**, and tabs for Overview · Financials (Trend · Annual values · Ratios · Cash / debt · Sources, each chart with View table) · People · Locations · Website · Hiring · Activity (major / all events) · Changes · Sources. Every fact opens its evidence |
| Library | `/library` | Search, type filters with counts, tags, **Card / List / Dense** views, distinct artifact types, pinning, rename, tag, archive (with confirmation) and export |
| Artifact | `/library/:id` | Dossier: cover with the ambient globe, ivory "paper", section navigation, **Search this research** (values, people, events, dates, sources and evidence excerpts; keyboard navigation; "Back to where you were"), version history and comparison, Continue research, and Ask this research |
| Data Sheets | `/sheets`, `/sheets/:id` | Create sheets from natural language, add AI columns with a **preview step**, batch research with live per-cell states, compact cell evidence, sort, filter, group, resize, freeze, hide, and export. Rows are virtualized |
| Compare | `/compare?orgs=a,b,c` | 2–5 companies: an **At a glance** strip, section anchors, aligned facts (including Changes), the same chart scale for everyone, and no rankings |
| Watchlist | `/watchlist` | Change indicators and a signals feed |
| Settings / About | `/settings`, `/about` | Theme, motion, density, default research mode, backend and source status |

Global features: the **⌘K / Ctrl+K command center** — Search company, Open company, Start / Continue research, Search Library, Search this research, Create Data Sheet, Compare companies, Open Watchlist, Export, Executive brief, Toggle Compact Mode, Toggle Theme (also try `research Nordvik`, `compare Tindra + Lumen`, `find SaaS companies in Oslo`) — plus **Comfortable / Compact density** (top bar or Settings), an ivory evidence drawer (a bottom sheet on mobile), a compare tray, toasts, and a status center.

### Demo walkthrough (mock mode)

1. Home → search **Nordvik** → open *Nordvik Helseteknologi AS* (complete, changing company, 3 versions). Read the snapshot and **What changed?** → click *CEO changed* → **Explain this change**.
2. **Executive brief** → click a numbered source. Click **Revenue** → the evidence drawer opens. Then **Continue research** → watch the source stack light up as events arrive, and read the completion summary.
3. Library → open the Nordvik research → search "CEO" inside it → **Compare versions**.
4. Data Sheets → *Norwegian SaaS & software companies* → **Add AI column** "Find the company's current CEO".
5. Compare *Nordvik + Polarlys + Tindra* → **Export comparison**.

Scenario companies: **Havbris Sjømat** (conflicting revenue, failed source), **Brattøra Maritime** (blocked website and LinkedIn), **Fjellmark Logistikk** (partial), **Kvartsfjord Energi** (under liquidation), **Isbre Analyse** (not researched yet). Searching **"Solstad Data"** in Research returns an ambiguous identity.

## Architecture

```
src/
├── app/            router, providers (React Query, preference sync), layout shell
├── pages/          Home, Discover, Research, Company, Library, Artifact, DataSheets, Compare, Watchlist, Settings
├── components/     navigation, search, company (+sections), research, library, artifacts, sheets,
│                   evidence, charts (lazy), globe (lazy), network, maps, source, common
├── api/            contract.ts (the interface), http.ts (fetch + SSE), domain modules, runs.ts (stream reducer)
├── data/mock/      mock backend: fixtures, research event scripts, in-memory store
├── hooks/  stores/ utils/  types/  styles/  tests/
```

- **State:** server state lives in TanStack Query. Research streams use a pure reducer that removes duplicate events by `seq` and reconnects with `lastSeq`. Small UI state (preferences, the compare tray, overlays, globe focus) lives in separate Zustand stores.
- **Honesty rules in code:** progress and "verified" states change only when backend events arrive. Missing, blocked, ambiguous and conflicting data each have their own UI. There are no confidence percentages and no scores.
- **Performance:** routes, charts (Recharts) and the globe (three.js) are code-split. The globe loads after first paint, pauses when it is off-screen, and falls back to a 2D canvas when WebGL is missing. Data sheets are virtualized, and each row is memoized.
- **Accessibility:** a skip link, visible focus, ARIA tabs/menus/dialogs with focus traps, keyboard grid navigation, status shown as text (never color alone), reduced motion (from the system or the user setting), and screen-reader tables behind charts.

See [`DESIGN_SYSTEM.md`](./DESIGN_SYSTEM.md) for tokens and component rules.
