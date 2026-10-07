# COGNIS API contract (frontend ↔ backend)

> Implemented by the Python backend in [`backend/`](./backend/README.md) (`app/api/main.py`). Run it on port 8000 and start the frontend with `npm run dev:live`.

The frontend's source of truth is **`src/types/`** (payload shapes) and **`src/api/contract.ts`** (operations). The mock backend in `src/data/mock/` implements the same interface. All paths are relative to `VITE_API_BASE_URL` (default `/api`). Requests and responses are JSON.

## Errors

Non-2xx responses should return `{ "code": ApiErrorCode, "message": string, "details"?: any }`.

| HTTP | `code` | UI behaviour |
| --- | --- | --- |
| 404 | `not_found` | "Not found" panel |
| 409 | `ambiguous` | `details` = `AmbiguousMatch` → candidate picker (never guesses) |
| 403 / 451 | `blocked` | "Source access blocked" |
| 429 | `rate_limited` | Retry offered |
| 400 / 422 | `invalid` | Message shown |
| 5xx | `unavailable` | "Something went wrong", retry |

Messages are shown to users, so they must never contain stack traces or secrets.

## Endpoints

| Method | Path | Body / query | Returns |
| --- | --- | --- | --- |
| GET | `/status` | — | `SystemStatus` (health, sources, **capabilities**: export formats, pause/cancel, discover filters…) |
| GET | `/search?q=` | — | `SearchResult` (grouped results + `intent` used for routing) |
| POST | `/companies/discover` | `DiscoverQuery` | `DiscoverResult` (+ `interpretation`, `appliedFilters`) |
| POST | `/companies/interpret` | `{ text }` | `QueryInterpretation` |
| GET | `/companies/:orgNumber` | — | `CompanyProfile` |
| GET | `/companies/recent` | — | `CompanySummary[]` |
| GET | `/companies/:orgNumber/brief` | — | `ExecutiveBrief` — one-screen factual summary compiled from saved evidence (sections `what`, `scale`, `financials`, `leadership`, `locations`, `hiring`, `changes`; each item has `evidence[]`; plus `gaps`, `sourceIds`, `sourceIndex`, `artifactId?`). No scores or advice |
| POST | `/companies/:orgNumber/explain` | `{ subject: ExplainSubject, fresh?: boolean }` | `ChangeExplanation` — `observed[]` (verified facts), `reported[]` (attributed statements with `sourceId`, `quote`), `synthesis` (text + `basis` + `caveat`, or `null`), `gaps[]`, `origin` (`saved_evidence` \| `fresh_research`). `ExplainSubject` = `{ kind: 'change', changeId }` or `{ kind: 'metric', metric, fromPeriod, toPeriod }` |
| POST | `/research/runs` | `StartResearchInput` | `ResearchRun` (`status: ambiguous` with `ambiguity` when identity is unclear) |
| POST | `/research/runs/:id/confirm` | `{ stepKeys }` | `ResearchRun` |
| GET | `/research/runs/:id` | — | `ResearchRun` |
| POST | `/research/runs/:id/pause` · `/cancel` · `/retry` | — | `ResearchRun` (only if `run.capabilities` allows) |
| GET (SSE) | `/research/runs/:id/events?lastSeq=N` | — | stream of `ResearchEvent` |
| POST | `/research/ask` | `{ orgNumber, artifactId?, question, fresh }` | `ResearchAnswer` (`origin`: `saved_evidence` \| `fresh_research`) |
| GET | `/library/:id/assessment` | — | `ContinueResearchAssessment` |
| GET | `/library?q=&type=&sort=&page=&pageSize=&tag=&includeArchived=` | — | `LibraryPage` = `Paged<ArtifactSummary>` + `facets?: { all, company, report, data_sheet, comparison, watchlist, saved_search }` (counts for the current `q`/`tag`, **before** the type filter) |
| GET | `/library/recent` | — | `ArtifactSummary[]` |
| GET | `/library/capabilities` | — | `ArtifactCapabilities` (only these actions are shown) |
| GET | `/library/:id` | — | `Artifact` (company dossier or report) |
| GET | `/library/:id/versions/:versionId` | — | `CompanyArtifact` |
| GET | `/library/:id/versions/compare?from=&to=` | — | `VersionComparison` |
| PATCH | `/library/:id` | `{ title?, tags?, pinned?, archived? }` | `ArtifactSummary` |
| POST | `/library/:id/duplicate` | — | `ArtifactSummary` |
| POST | `/library/from-run/:runId` | — | `ArtifactSummary` |
| GET | `/library/by-org/:orgNumber` | — | `ArtifactSummary \| null` |
| POST | `/reports` | `{ orgNumber, kind, sections }` | `ArtifactSummary` |
| GET | `/sheets` | — | `DataSheetSummary[]` |
| GET | `/sheets/:id` | — | `DataSheet` (+ `sourceIndex`) |
| POST | `/sheets/interpret` | `{ text }` | `QueryInterpretation` |
| POST | `/sheets` | `{ title, criteria, text? }` | `DataSheetSummary` |
| PATCH | `/sheets/:id` | `{ title }` | `DataSheetSummary` |
| POST | `/sheets/:id/columns/preview` | `AddColumnInput` | `ColumnPreview` — the backend's interpretation (title, value type, what each cell will contain, planned sources, notes, `supported`). Nothing is researched yet |
| POST | `/sheets/:id/columns` | `AddColumnInput` | `DataSheetColumn` (cells start `pending`) |
| PATCH / DELETE | `/sheets/:id/columns/:columnId` | `{ title?, width?, frozen? }` | `DataSheetColumn` / 204 |
| PUT | `/sheets/:id/columns/order` | `{ columnIds }` | 204 |
| POST | `/sheets/:id/research` | `{ columnIds? }` | `BatchStatus` |
| GET (SSE) | `/sheets/:id/events` | — | stream of `SheetEvent` |
| GET | `/compare?orgs=a,b,c` | — | `Comparison` (+ `sourceIndex`). `summary: ComparisonRow[]` is the executive strip (`revenue`, `employees`, `hiring`, `locations`, `filing`); `sections` are `overview`, `financials`, `people`, `locations`, `hiring`, `activity`, `changes` |
| GET | `/watchlist` | — | `Watchlist` |
| POST | `/watchlist/items` | `{ orgNumber }` | `Watchlist` |
| DELETE | `/watchlist/items/:orgNumber` | — | `Watchlist` |
| POST | `/watchlist/checked` | — | `Watchlist` |
| GET | `/signals` | — | `SignalFeedGroup[]` |
| POST | `/exports` | `ExportRequest` | `ExportResult` (`url` to download) |

## Streaming (SSE)

- Each `data:` line is one JSON event with a monotonically increasing integer `seq`.
- On reconnect the client sends `?lastSeq=N`. The server replays events after `N`. The client drops anything with `seq <= N`.
- Research streams end with `run.completed` or `run.failed`. Sheet streams end with `batch.completed`.
- **The UI shows only what the events say.** Step names such as "LinkedIn" appear only if a `step.started` event names that source. A fact is shown as confirmed only after `fact.confirmed`.

Research event order (typical): `run.started` → `stage.changed(identify)` → `step.started/completed` per source (+ `fact.confirmed`) → `stage.changed(verify|reconcile|synthesize)` → `synthesis.delta`* → `synthesis.completed` → `run.completed { artifactId, autoSaved, coverage, summary? }`.

- `step.completed.outcome`: `verified` (the source yielded verified facts) or `not_available` (searched, nothing to verify). The source stack shows the latter as "Not available", never as verified.
- `run.completed.summary` (`ResearchRunSummary`): `coverage`, and optionally `sourcesVerified`, `primarySources`, `secondarySources`, `factsVerified`, `conflicts`, `identityConflicts`, `changesDetected`, `blockedSources`, `failedSources`, `elapsedMs`. The completion panel shows only fields that are present.

## Profile fields used by executive views

- `TimelineEvent.significance`: `major` | `minor` (backend classification; the executive timeline shows `major`).
- `Change`: `category` (`leadership` | `status` | `financial` | `filing` | `ownership` | `location` | `address` | `hiring` | `employees` | `event` | `website`), `material: boolean`, `headline?` (e.g. "CEO changed"), `direction?` (`up` | `down`), `explainable?`. `ChangesSection.since` + `baselineLabel` describe the comparison point.
- `FinancialsSection.ratioHistory?`: ratios per period (`{ key, label, formula, points: { period, value }[] }`), computed deterministically by the backend.

## Evidence model (summary)

`Fact { value, status, evidenceState, evidence[], reportingPeriod, verifiedAt, conflict?, note? }`

- `status` is one of `verified | researching | pending | not_available | ambiguous | blocked | failed | stale`.
- `evidenceState` is one of `verified | primary | secondary | conflict | unverified`. These are deliberately not confidence scores.
- `Evidence { sourceId, url, documentTitle, page, excerpt, excerptTranslation, retrievedAt, reportingPeriod, statedValue }`
- `conflict.candidates[]` lists each source's value. `conflict.reason` comes from the backend and is never invented by the frontend.

### Currency (financial amounts)

- A monetary `Fact` carries `value` (the unrounded number exactly as filed), `currency` and `unit` (the ISO code the filing states, e.g. `NOK`, `USD`) and a `displayValue` built from that same code. The evidence `excerpt` states the same amount and code. The frontend never assumes a currency: with none stated it shows the bare number.
- `FinancialSeries.unit` is a currency code, `"mixed currencies"` (filings in different currencies; `currencies[]` lists them), `"currency not stated"`, `"people"` or `"%"`. `FinancialsSection.currency` follows the same rule. `CompanySummary.revenue.currency` is the latest filing's currency (`""` when none is stated).
- Amounts are never converted between currencies: growth, ratios and comparisons are only computed within one currency; `ComparisonRow.unit` / `ComparisonSeries.unit` may be `"mixed currencies"` (`mixedCurrency: true`, per-company `currencies`) and are then shown per company rather than on one axis. `DataSheetCell.currency` and the export column `currency` carry the same code. The Discover revenue filter is a NOK threshold and only matches companies whose revenue is stated in NOK.
