import type { CompanyProfile, CompanyStatus, CompanySummary, Coverage } from './company';
import type { ResearchRunSnapshot } from './research';
import type { Evidence, EvidenceState, Fact, FactPrimitive, ISODateTime, Source, ValueStatus } from './evidence';

/* ============================== Common ============================== */

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

/** Library listing with per-type counts for the type filter. */
export interface LibraryPage extends Paged<ArtifactSummary> {
  facets?: Partial<Record<ArtifactType | 'all', number>>;
}

/* ============================== Discover ============================== */

export interface DiscoverFilters {
  location?: string;
  municipality?: string;
  industry?: string;
  status?: CompanyStatus;
  employeesMin?: number;
  employeesMax?: number;
  revenueMin?: number;
  revenueMax?: number;
  hiring?: boolean;
  coverageMin?: number;
  recentActivity?: boolean;
  foundedAfter?: number;
}

export type DiscoverFilterKey = keyof DiscoverFilters;

/** A filter the backend says it can actually apply. */
export interface FilterCapability {
  key: DiscoverFilterKey;
  label: string;
  type: 'text' | 'select' | 'range' | 'boolean' | 'number';
  options?: { value: string; label: string }[];
  unit?: string;
}

export interface InterpretedFilter {
  key: DiscoverFilterKey;
  label: string;
  value: string | number | boolean;
  display: string;
}

export interface QueryInterpretation {
  original: string;
  /** Filters the backend inferred from the text. Suggestions only: shown for the user to select, never applied automatically. */
  filters: InterpretedFilter[];
  /** Remaining free-text the backend kept as a keyword search. */
  keywords?: string;
  notes?: string[];
}

export type DiscoverSort = 'relevance' | 'revenue' | 'employees' | 'name' | 'researched' | 'hiring';

export interface DiscoverQuery {
  text?: string;
  filters: DiscoverFilters;
  sort: DiscoverSort;
  page: number;
  pageSize: number;
  /**
   * When true the backend interprets `text` as natural language and returns the interpretation as SUGGESTED filters.
   * Suggestions are never applied: only `filters` (explicitly selected by the user) restrict the results; the words
   * the interpreter did not turn into suggestions (`interpretation.keywords`) remain the text search.
   */
  interpret?: boolean;
}

export interface DiscoverResult extends Paged<CompanySummary> {
  interpretation?: QueryInterpretation;
  /** The filters that restricted this result: exactly the ones the user selected. */
  appliedFilters: DiscoverFilters;
}

/* ============================== Global search ============================== */

export interface SearchResult {
  query: string;
  /** Backend routing hint: what the query most likely is. */
  intent: { kind: 'company'; orgNumber: string } | { kind: 'discover'; text: string } | { kind: 'mixed' };
  companies: CompanySummary[];
  artifacts: ArtifactSummary[];
  sheets: DataSheetSummary[];
  reports: ArtifactSummary[];
  savedSearches: { id: string; title: string; query: string }[];
}

/* ============================== Library / artifacts ============================== */

export type ArtifactType = 'company' | 'report' | 'data_sheet' | 'comparison' | 'watchlist' | 'saved_search';

export interface ArtifactSummary {
  id: string;
  type: ArtifactType;
  title: string;
  subtitle?: string;
  orgNumber?: string;
  municipality?: string;
  updatedAt: ISODateTime;
  researchedAt?: ISODateTime;
  viewedAt?: ISODateTime;
  coverage?: Coverage;
  tags: string[];
  pinned: boolean;
  archived: boolean;
  changeCount?: number;
  openPositions?: number | null;
  /** Tiny trend for thumbnails (e.g. revenue). Only real backend values. */
  sparkline?: number[];
  /** Linked object id (sheet id, comparison org numbers, …). */
  targetId?: string;
  itemCount?: number;
}

export type LibrarySort = 'updated' | 'researched' | 'name' | 'coverage' | 'changed';

export interface LibraryQuery {
  q?: string;
  type: ArtifactType | 'all';
  sort: LibrarySort;
  page: number;
  pageSize: number;
  tag?: string;
  includeArchived?: boolean;
}

export interface ArtifactVersion {
  id: string;
  createdAt: ISODateTime;
  label: string;
  isCurrent: boolean;
  note?: string;
}

export interface ArtifactFreshness {
  state: 'saved' | 'fresh_available' | 'updating';
  lastUpdatedAt: ISODateTime;
  staleAreas: number;
  changedSources: number;
  newFilings: number;
}

export interface CompanyArtifact {
  id: string;
  type: 'company';
  title: string;
  orgNumber: string;
  createdAt: ISODateTime;
  updatedAt: ISODateTime;
  versionId: string;
  versions: ArtifactVersion[];
  freshness: ArtifactFreshness;
  /** Every research run of this company, newest first. The dossier itself shows the latest report; earlier runs keep their own versions. */
  runs?: ResearchRunSnapshot[];
  tags: string[];
  pinned: boolean;
  profile: CompanyProfile;
}

export type ReportKind = 'company_brief' | 'deep_report' | 'comparison_report' | 'market_overview';
export type ReportSection = 'summary' | 'financials' | 'people' | 'locations' | 'hiring' | 'activity' | 'sources';

export interface ReportArtifact {
  id: string;
  type: 'report';
  title: string;
  kind: ReportKind;
  orgNumber?: string;
  createdAt: ISODateTime;
  updatedAt: ISODateTime;
  sections: ReportSection[];
  profile: CompanyProfile;
  tags: string[];
  pinned: boolean;
}

export type Artifact = CompanyArtifact | ReportArtifact;

export interface VersionComparisonRow {
  key: string;
  label: string;
  from: string | null;
  to: string | null;
  changed: boolean;
}

export interface VersionComparison {
  artifactId: string;
  from: ArtifactVersion;
  to: ArtifactVersion;
  rows: VersionComparisonRow[];
}

export interface ArtifactCapabilities {
  rename: boolean;
  duplicate: boolean;
  tag: boolean;
  archive: boolean;
  delete: boolean;
  refresh: boolean;
  export: boolean;
  pin: boolean;
}

/* ============================== Data sheets ============================== */

export type ColumnValueType = 'text' | 'number' | 'currency' | 'date' | 'boolean' | 'url' | 'person';

export interface DataSheetColumn {
  id: string;
  title: string;
  kind: 'identity' | 'standard' | 'ai';
  valueType: ColumnValueType;
  /** Natural-language research instruction for AI columns. */
  instruction?: string;
  width: number;
  frozen?: boolean;
  unit?: string;
}

export interface DataSheetCell {
  status: ValueStatus;
  value: FactPrimitive | null;
  display?: string;
  /** Currency of a money cell, as stated by its own filing. */
  currency?: string;
  evidenceState?: EvidenceState;
  evidence: Evidence[];
  sourceName?: string;
  updatedAt?: ISODateTime;
  note?: string;
}

export interface DataSheetRow {
  id: string;
  company: Pick<CompanySummary, 'orgNumber' | 'legalName' | 'municipality' | 'industry' | 'website'>;
  cells: Record<string, DataSheetCell>;
}

export interface BatchStatus {
  runId: string;
  state: 'idle' | 'running' | 'completed' | 'failed';
  total: number;
  done: number;
  running: number;
  pending: number;
  failed: number;
  etaSeconds?: number;
  sourceUsage?: { sourceName: string; calls: number }[];
  errors: { rowId: string; columnId: string; message: string }[];
}

/**
 * Present only on a sheet that was built from companies COGNIS had already verified because the Enhetsregisteret search was unavailable when the
 * sheet was created. A sheet built from a live register search has no `discovery`.
 */
export interface SheetDiscovery {
  kind: 'verified_companies';
  registryAvailable: false;
  /** Machine-readable class of the register failure (timeout, server_error, …). */
  reason?: string;
  /** The register failure in plain words. */
  cause?: string;
  /** When the failure was observed. */
  at: ISODateTime;
  count: number;
  note: string;
}

export interface DataSheetSummary {
  id: string;
  title: string;
  description?: string;
  rowCount: number;
  columnCount: number;
  updatedAt: ISODateTime;
  criteria?: InterpretedFilter[];
  discovery?: SheetDiscovery;
}

export interface DataSheet extends DataSheetSummary {
  columns: DataSheetColumn[];
  rows: DataSheetRow[];
  batch?: BatchStatus;
  /** Sources referenced by any cell evidence, by id. */
  sourceIndex?: Record<string, Source>;
}

export interface AddColumnInput {
  instruction: string;
  title?: string;
  valueType?: ColumnValueType;
}

/** Backend interpretation of an AI-column instruction, shown before the column is added. */
export interface ColumnPreview {
  instruction: string;
  title: string;
  valueType: ColumnValueType;
  /** Plain-language description of what each cell will contain. */
  cellDescription: string;
  /** Source families the backend plans to check. */
  plannedSources: string[];
  rowCount: number;
  notes: string[];
  /** False when the backend cannot research this instruction. */
  supported: boolean;
}

export type SheetEvent =
  | { type: 'cell.updated'; seq: number; rowId: string; columnId: string; cell: DataSheetCell }
  | { type: 'batch.progress'; seq: number; batch: BatchStatus }
  | { type: 'batch.completed'; seq: number; batch: BatchStatus };

/* ============================== Compare ============================== */

export interface ComparisonRow {
  key: string;
  label: string;
  /** For money rows: the shared currency code, or "mixed currencies". */
  unit?: string;
  /** Per-company currency of a money row (aligned with `values`). */
  currencies?: (string | null)[];
  values: (Fact | null)[];
}

export interface ComparisonSection {
  id: string;
  label: string;
  rows: ComparisonRow[];
}

export interface ComparisonSeries {
  key: string;
  label: string;
  /** A shared currency code, or "mixed currencies" when the plotted filings are not all in one currency. */
  unit: string;
  /** Currencies stated per company (aligned with the compared companies). */
  currencies?: string[][];
  /** True when plotting these values on one axis would mix currencies. */
  mixedCurrency?: boolean;
  points: { period: string; values: (number | null)[] }[];
}

export interface Comparison {
  companies: CompanySummary[];
  /**
   * Executive strip: Revenue, Employees, Hiring, Locations, Latest filing —
   * one fact (or null) per company, in company order.
   */
  summary: ComparisonRow[];
  sections: ComparisonSection[];
  series: ComparisonSeries[];
  generatedAt: ISODateTime;
  /** Sources referenced by any fact in the comparison, by id. */
  sourceIndex: Record<string, Source>;
}

/* ============================== Watchlist / signals ============================== */

export type SignalKind = 'financial' | 'leadership' | 'hiring' | 'location' | 'announcement' | 'filing';

export interface Signal {
  id: string;
  kind: SignalKind;
  orgNumber: string;
  companyName: string;
  title: string;
  detectedAt: ISODateTime;
  evidence: Evidence[];
}

export interface WatchlistItem {
  company: CompanySummary;
  addedAt: ISODateTime;
  lastCheckedAt: ISODateTime;
  signals: Signal[];
}

export interface Watchlist {
  id: string;
  title: string;
  items: WatchlistItem[];
  changedCount: number;
  lastCheckedAt: ISODateTime;
}

export interface SignalFeedGroup {
  date: string;
  label: string;
  summary: { kind: SignalKind; count: number; label: string }[];
  signals: Signal[];
  sourceIndex?: Record<string, Source>;
}

/* ============================== Exports ============================== */

export type ExportFormat = 'csv' | 'xlsx' | 'json' | 'pdf';

/**
 * What an export contains:
 *  report   – Full Research Report, a multi-page PDF built from the saved research
 *  data     – Research Data, the structured facts (csv / xlsx / json) — the original export
 *  evidence – Evidence & Sources, every fact with its source URL, excerpt, verification status, timestamps and period (csv / json)
 */
export type ExportKind = 'report' | 'data' | 'evidence';

export interface ExportOptions {
  sourceLinks: boolean;
  evidence: boolean;
  retrievalDates: boolean;
  reportingPeriods: boolean;
  changes: boolean;
}

export interface ExportRequest {
  target: { type: 'company' | 'sheet' | 'comparison' | 'artifact'; id: string };
  /** Omitted = 'data', so requests from before the report existed behave as they always did. */
  kind?: ExportKind;
  format: ExportFormat;
  options: ExportOptions;
}

export interface ExportResult {
  status: 'ready' | 'queued' | 'failed';
  filename: string;
  /** Download URL (live) or object URL (mock). */
  url?: string;
  message?: string;
}

/* ============================== System ============================== */

export interface SystemCapabilities {
  exports: ExportFormat[];
  /** Export types the backend can produce. Older backends omit it: then only 'data' is offered (plus 'report' when `pdfReports` is true). */
  exportKinds?: ExportKind[];
  pdfReports: boolean;
  /** Why PDF reports are off on this installation (e.g. a missing Python package), when they are. */
  pdfReportsNote?: string;
  pauseResearch: boolean;
  cancelResearch: boolean;
  watchlist: boolean;
  versions: boolean;
  archive: boolean;
  tags: boolean;
  share: boolean;
  discoverFilters: FilterCapability[];
}

/** `alternative`: a free official source is used instead (e.g. Proff, Doffin's API) · `not_used`: deliberately not collected (e.g. LinkedIn). */
export type SourceAvailability = 'available' | 'degraded' | 'unavailable' | 'alternative' | 'not_used';

/** GET /health: the backend process answers. Says nothing about sources (see SystemStatus). */
export interface BackendHealth {
  status: 'ok';
  version: string;
  run_mode?: string;
  schema_version?: number;
  llm?: boolean;
}

export interface SystemStatus {
  mode: 'mock' | 'live';
  backend: 'connected' | 'degraded' | 'offline';
  research: 'online' | 'offline';
  version: string;
  baseUrl?: string;
  sources: { name: string; kind: string; status: SourceAvailability; note?: string }[];
  capabilities: SystemCapabilities;
  checkedAt: ISODateTime;
}
