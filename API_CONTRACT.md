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

### Enhetsregisteret search failures (`POST /companies/discover`, `POST /sheets`, `GET /search`)

When the register search fails the answer is **never** an empty list and never a generic message: it is `503` / `code: "unavailable"` with the cause in the message and in `details`:

```json
{ "code": "unavailable",
  "message": "Company search in Enhetsregisteret failed. Enhetsregisteret reported a server-side error (HTTP 503) on 4 attempts. …",
  "details": { "source": "enhetsregisteret", "reason": "server_error", "cause": "…", "httpStatus": 503, "attempts": 4,
               "retryable": true, "detail": "…", "elapsedMs": 2100,
               "fallback": { "available": true, "count": 3, "kind": "verified_companies", "note": "3 companies COGNIS has already verified match the selected filters." } } }
```

* `reason`: `timeout` · `network` (DNS, TLS certificate, refused connection — `detail` has the underlying error) · `server_error` (5xx) · `rate_limited` (429) · `client_error` (the register rejected the request, e.g. HTTP 400; `detail` quotes its message) · `blocked` (401/403/451 — access controls are never bypassed) · `unsafe_url` · `invalid_content` (not JSON — proxy / captive portal) · `unexpected_response` (JSON that is not a search answer) · `budget_exhausted` · `too_large`.
* `attempts` counts every try. Timeouts, network errors, 429 and 5xx are retried with exponential backoff and jitter (`REGISTRY_SEARCH_RETRIES`, default 3 retries; `Retry-After` honoured); `client_error` / `blocked` are not retried. Failures are never cached.
* `retryable: false` means the same request cannot succeed (the UI hides Retry and asks for different filters).
* `fallback` says whether COGNIS holds already-verified companies (a stored record with a resolved identity) that match the **selected** filters. It is an offer only: nothing is substituted unless the client asks.
* The failure is also logged by the backend (`enhetsregisteret search failed`, with `reason`, `http_status`, `attempts`, `detail` and the search parameters; secrets are redacted).

**Verified-companies fallback.** `POST /companies/discover` and `POST /sheets` accept `fallback: "verified"` (the user's explicit choice). The backend then uses the register if it answers; only if the search is unavailable — a failure the **server itself** observed (a recent one, or one quick attempt) — does it return exactly the stored companies that match the selected registry filters (location, industry, employees, founded, status, name). It never invents a company, widens a filter, or fills a field it does not hold. Rows keep the time their record was really retrieved (`verifiedAt`; the evidence says "stored copy"). The result carries `source` (discover) / `discovery` (sheet summary): `{ kind: "verified_companies", registryAvailable: false, reason, cause, at, count, note }`. A sheet built from a live search has no `discovery`. If nothing stored matches, the original 503 is returned (with `fallback.available: false` and the reason).

## Endpoints

| Method | Path | Body / query | Returns |
| --- | --- | --- | --- |
| GET | `/status` | — | `SystemStatus` (health, sources, **capabilities**: export formats, pause/cancel, discover filters…). Source `status`: `available` · `degraded` · `unavailable` · `alternative` (deliberately replaced by a free source, e.g. Proff, Doffin's API) · `not_used` (deliberately not collected or paid and not integrated, e.g. LinkedIn, Fakt.no) |
| GET | `/search?q=` | — | `SearchResult` (grouped results + `intent` used for routing) |
| POST | `/companies/discover` | `DiscoverQuery` (+ optional `fallback: "verified"`) | `DiscoverResult` (+ `interpretation`, `appliedFilters`, `source` when it fell back to verified companies). With `interpret: true`, `interpretation.filters` are **suggestions**: they are returned for the user to choose and never restrict the result. Only `filters` (selected by the user) do, and `appliedFilters` is exactly those; `interpretation.keywords` (what was left after the suggestions) remains the name search |
| POST | `/companies/interpret` | `{ text }` | `QueryInterpretation` |
| GET | `/companies/:orgNumber` | — | `CompanyProfile` |
| GET | `/companies/recent` | — | `CompanySummary[]` |
| GET | `/companies/:orgNumber/brief` | — | `ExecutiveBrief` — one-screen factual summary compiled from saved evidence (sections `what`, `scale`, `financials`, `leadership`, `locations`, `hiring`, `changes`; each item has `evidence[]`; plus `gaps`, `sourceIds`, `sourceIndex`, `artifactId?`). No scores or advice |
| POST | `/companies/:orgNumber/explain` | `{ subject: ExplainSubject, fresh?: boolean }` | `ChangeExplanation` — `observed[]` (verified facts), `reported[]` (attributed statements with `sourceId`, `quote`), `synthesis` (text + `basis` + `caveat`, or `null`), `gaps[]`, `origin` (`saved_evidence` \| `fresh_research`). `ExplainSubject` = `{ kind: 'change', changeId }` or `{ kind: 'metric', metric, fromPeriod, toPeriod }` |
| POST | `/research/runs` | `StartResearchInput` | `ResearchRun` (`status: ambiguous` with `ambiguity` for any typed *name*, even a single match: the user must pick or confirm a candidate; a research run starts only from an `orgNumber` — 9 digits, valid check digit, found in Enhetsregisteret. Optional `expectedName` is the legal name the user confirmed: a different registered name → `409 ambiguous`) |
| POST | `/research/ask` | `{ orgNumber, question, fresh? }` | `ResearchAnswer` — routed to the evidence the question is about (filed accounts with period, currency and scope; dated announcements inside the requested window; people, locations, hiring, changes). Questions public sources cannot answer (confidential, future, forecast) or that no evidence addresses return `blocks: []` and a `limitation` sentence; `gaps` lists what could not be verified. Saved facts are never returned just because they exist |
| POST | `/research/runs/:id/confirm` | `{ stepKeys }` | `ResearchRun` |
| GET | `/research/runs/:id` | — | `ResearchRun` |
| POST | `/research/runs/:id/pause` · `/cancel` · `/retry` | — | `ResearchRun` (only if `run.capabilities` allows) |
| GET (SSE) | `/research/runs/:id/events?lastSeq=N` | — | stream of `ResearchEvent` |
| POST | `/research/ask` | `{ orgNumber, artifactId?, question, fresh }` | `ResearchAnswer` (`origin`: `saved_evidence` \| `fresh_research`) |
| GET | `/library/:id/assessment` | — | `ContinueResearchAssessment` |
| GET | `/library?q=&type=&sort=&page=&pageSize=&tag=&includeArchived=` | — | `LibraryPage` = `Paged<ArtifactSummary>` + `facets?: { all, company, report, data_sheet, comparison, watchlist, saved_search }` (counts for the current `q`/`tag`, **before** the type filter) |
| GET | `/library/recent` | — | `ArtifactSummary[]` |
| GET | `/library/capabilities` | — | `ArtifactCapabilities` (only these actions are shown) |
| GET | `/library/:id` | — | `Artifact` (company dossier or report). Company dossiers also carry `runs: ResearchRunSnapshot[]` (newest first) — see “Research runs and modes” |
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
| POST | `/sheets` | `{ title, criteria, text?, fallback?: "verified" }` | `DataSheetSummary` (+ `discovery` when it was built from already-verified companies because the register search was unavailable; see *Enhetsregisteret search failures*). Only `criteria` the user selected restrict the sheet; `/sheets/interpret` results are suggestions. With no criteria the sheet starts from the register unrestricted (only words left over after the suggestions, e.g. a company name, are a name search). Every sheet has a `hiring` data column (verified openings, filled by research), never a hiring filter |
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
| POST | `/exports` | `ExportRequest` (`target`, optional `kind`, `format`, `options`) | `ExportResult` (`url` to download; `status: "failed"` carries a plain-language `message`) — see **Exports** below |

## Exports

`POST /exports` takes `{ target, kind?, format, options? }`. `kind` selects what is exported; a request without `kind` behaves as it always did (`format: "pdf"` means the report, anything else is the data export).

| `kind` | What it is | `format` | Targets |
| --- | --- | --- | --- |
| `report` | **Full Research Report** — a multi-page PDF (cover, table of contents, page numbers, generation date; identity, executive summary, key metrics, financials, people, locations, digital presence, hiring, activity, changes and research history, coverage and verification, limitations, source register and the full evidence register with excerpts and URLs). | `pdf` | `company`, `artifact` (saved research) |
| `data` | **Research Data** — the original structured export, one row per fact (`value`, `raw_value`, `currency`, status, period, sources…). Unchanged. | `csv` (default), `xlsx`, `json` | `company`, `artifact`, `sheet`, `comparison` |
| `evidence` | **Evidence & Sources** — one row/object per piece of evidence behind each fact: source name/URL, document title, page, excerpt (and translation), verification status, retrieval and verification timestamps, reporting period, plus the explicitly unavailable fields and unverified claims. CSV has 37 fixed columns (`EVIDENCE_COLUMNS`); JSON carries the same rows plus company/research metadata. | `csv`, `json` | `company`, `artifact` |

* The report and the evidence export are built from the **saved research record only** (`latest_record`). They never start research, call a source, call a model or write a profile version. If a company has no saved research the result is `failed` with “No saved research exists for this company yet…”.
* Nothing is invented: a section the record cannot support says that it is unavailable and why. Facts are labelled **Verified** (with the number of agreeing sources), **Unverified**, **Conflict**, **Unavailable**, **AI synthesis** (executive summary written by a model) or **Compiled from facts** (deterministic template). Amounts keep their own filing currency and reporting period; nothing is converted.
* Evidence is numbered `E1…En` and sources `S1…Sn` in first-cited order; the same numbers appear in the PDF and in the evidence export (`evidence_ref`, `source_ref`), and every `E`/`S` reference inside the PDF is a clickable link to its entry in the evidence register.
* Files are named `COGNIS-Research-Report-<company>-<orgNumber>.pdf`, `COGNIS-Evidence-<company>-<orgNumber>.csv|json`.
* `SystemStatus.capabilities` advertises `exports` (formats; contains `pdf` when reports can be produced), `exportKinds` (`data`, `report`, `evidence`) and `pdfReports`. The UI offers only what is advertised; an older backend without `exportKinds` is treated as data-only (plus the report when `pdfReports` is true).
* Failure messages (all `status: "failed"`): no saved research; wrong target type (sheets and comparisons export Research Data only); unsupported format for the kind; report fonts missing on this installation.

## Streaming (SSE)

- Each `data:` line is one JSON event with a monotonically increasing integer `seq`.
- On reconnect the client sends `?lastSeq=N`. The server replays events after `N`. The client drops anything with `seq <= N`.
- Research streams end with `run.completed` or `run.failed`. Sheet streams end with `batch.completed`.
- **The UI shows only what the events say.** Step names such as "LinkedIn" appear only if a `step.started` event names that source. A fact is shown as confirmed only after `fact.confirmed`.

Research event order (typical): `run.started` → `stage.changed(identify)` → `step.started/completed` per source (+ `fact.confirmed`) → `stage.changed(verify|reconcile|synthesize)` → `synthesis.delta`* → `synthesis.completed` → `run.completed { artifactId, autoSaved, coverage, summary? }`.

- Source Activity is driven by these step events and nothing else (no timers invent states): `step.started` → `running`; `step.progress { message }` → the line under a running source (only real sub-stages, e.g. “Reading page 2 of 3”); `step.completed` (`outcome`, `durationMs`, `message`) → succeeded / not available; `step.failed` / `step.blocked` → failed / blocked with the reason in `message`; `step.skipped { message }` → the source was never started (the message says why: mode, missing key, cancelled, no identity); `step.cancelled { message }` → it was running when the run was cancelled. A source with no event is **pending**, never “active”. The server flushes each event to the SSE stream as soon as it is emitted; the 15 s keep-alive is only a heartbeat.
- The hiring step (`jobs`) reports three different results: **confirmed openings** → `step.completed` with `outcome: verified`; **no verified openings** (every source was checked) → `step.completed` with `outcome: not_available` and a message that this does not mean the company is not hiring; **a source could not be reached or read** (NAV or a careers page timed out, was refused or too slow) → `step.failed` with the reason in `message`, and the profile's `hiring.outcome` is `source_unavailable`. Missing evidence is never read as “not hiring”, and no `0 open positions` is published while a source was unavailable.
- A cancelled run emits `step.cancelled` / `step.skipped` for every open step and then `run.failed { cancelled: true }`; nothing is saved from it except its run snapshot (status `cancelled`).
- `step.completed.outcome`: `verified` (the source yielded verified facts) or `not_available` (searched, nothing to verify). The source stack shows the latter as "Not available", never as verified.
- `run.completed.outcome` is `completed` (every coverage area verified, no failed or blocked sources, no timeout) or `partial`; `issues[]` says what kept it from `completed`. A `partial` run is saved and shown as **partial** — never labelled completed.
- `run.completed.summary` (`ResearchRunSummary`): `coverage`, and optionally `sourcesVerified`, `primarySources`, `secondarySources`, `factsVerified`, `conflicts`, `identityConflicts`, `changesDetected`, `blockedSources`, `failedSources`, `elapsedMs`. The completion panel shows only fields that are present.

## Research runs and modes

- **One card, many runs.** A company has one Library card and a chain of report versions. Every run — completed, partial, failed or cancelled — is also kept as a `ResearchRunSnapshot` in `company_research_runs`, returned as `runs[]` on `GET /library/:id` (company dossiers only; newest first, up to 50). Fields: `id`, `mode`, `prompt` (focus / custom question), `status` (`completed` \| `partial` \| `failed` \| `cancelled`), `startedAt`, `finishedAt`, `versionId` / `versionNumber` (the report version the run produced; absent when it saved nothing), `hasReport`, `isLatestReport`, `evidenceChanged` (false = exactly the same facts as the run before), `summary`, `effort`, `steps[]` (per-source status, time, message), `answer` (a custom question's answer), `issues[]`. Runs made before this feature existed are not listed.
- **Quick vs Deep.** Quick reads the core sources only (registry, annual accounts, the company's own site up to 3 pages, one follow-up round) and uses at most one model call. Deep adds the filing history, up to the configured number of site pages, a search-based site fallback, multi-round follow-up page reading guided by the research focus, quote-verified AI page reading, a press/news search and a deterministic cross-source check. Deep does not promise more facts; it reports its extra work in `effort` and the extra findings it made (`crosscheck`).
- `effort` (`ResearchEffort`): `mode`, `requests`, `llmCalls`, `pagesRead`, `timedOut?`, `workflows[]` (`{key, label, status: ran \| skipped \| failed, detail}` — each optional workflow with the reason it did or did not run, e.g. “needs a search key” or “Quick mode skips filing history”), `crosscheck?` (`{checked, corroborated, singleSource, conflicts, corroboratedFacts[], conflictFacts[]}`), `focusKinds?`.
- Optional steps in the plan (`followup`, `crosscheck`) are only started when the mode and configuration allow it; otherwise they emit `step.skipped` with the reason.

## Profile fields used by executive views

- **Recent activity** (`activity: ActivitySection`). `TimelineEvent.significance` is `major` | `relevant` | `routine` (older saved data may say `minor`; read it as `routine`):
  - `major` — acquisitions and divestments, material contracts, results, discoveries, top-level leadership changes and similar developments. A contract counts as major only with material weight (a large stated amount, a large share of revenue in the *same* currency, strategic wording, or an investor-relations source).
  - `relevant` — worth knowing, not by itself a change to the picture of the company (cooperation agreements, a new office, a product launch, other leadership changes).
  - `routine` — invitations, webinars, greetings and **all register entries** (registrations, establishments, group and name changes, procurement as buyer). Register entries stay in the timeline but are capped below `major` by rule; they never count as business developments.
  - Per event: `score` (0–100) and `rank` (1 = most significant; tier first, then score, then recency), `reasons[]` (plain-language reasons for the tier), `type` (adds `results`, `partnership`, `discovery`, `project`, `production`, `regulatory`, `restructuring`), `sourceType` (`investor_relations` | `company_newsroom` | `public_procurement` | `official_registry` | `secondary_news`), `url` (the announcement), `sources[]` (every place the same announcement was found; the event is shown once), `duplicates?`, `description?`, `evidence[]` (date, URL and excerpt for each place it was read).
  - Section: `counts {major, relevant, routine}`, `consolidated` (duplicate reports merged), `sourcesChecked[]` (`{id, kind: newsroom | investor_relations | feed | news_search | registry | procurement, name, status: read | blocked | not_found | failed | not_run | no_dated_items | not_checked, note, url?, items?}`), `excluded {count, items[]}` (candidates dropped for lacking a valid date, source URL or matching evidence), `omitted?` (routine events beyond the display limit).
  - `status` / `message` never read a missing result as "nothing happened": when announcement sources could not be read, `status` is `partial` (or `blocked`) and `message` says the gap is "not evidence that none were made".
  - Events need a valid date (not in the future), a source URL and an evidence excerpt; news-like events also need their headline inside the stored excerpt. Everything else is excluded and counted.
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

### Hiring section (`CompanyProfile.hiring`)

`status` (`available` · `partial` · `not_available` · `blocked` · `ambiguous` · `pending`), `message?`, `totalCurrent: number | null`, `jobs[]`,
`locations[]`, `categories[]`, `searchedSourceIds[]`, plus:

* `outcome?`: `verified` (≥ 1 verified current opening) · `none_found` (sources checked, none found — not "not hiring") · `source_unavailable` (a source
  could not be reached or read, e.g. a NAV timeout) · `incomplete` (research did not check every source) · `pending`.
* `checks?`: `{ id, name, state: checked | unavailable | incomplete, note, required }[]` — what each hiring source returned.
* `totalCurrent` is `null` whenever nothing is verified; a `0` appears only when the company's own careers page says it has no open positions and no source was unavailable.
* `Job`: `title`, `url`, `state` (`current` | `stale` | `closed`), `postedAt?`, `updatedAt?`, `validThrough?`, `checkedAt?`, `alsoListed?` (`{ source, url, state, posted_at?, updated_at? }[]` — the same opening on other sources, counted once), `evidence[]`.
