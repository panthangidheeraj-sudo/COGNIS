/**
 * THE frontend ↔ backend contract.
 * Both the live HTTP client and the mock backend implement `CognisApi`.
 * REST paths for the live client are documented next to each method in
 * the domain modules (companies.ts, research.ts, …) and in API_CONTRACT.md.
 */
import type {
  AddColumnInput,
  Artifact,
  ArtifactCapabilities,
  ArtifactSummary,
  BackendHealth,
  BatchStatus,
  ChatContext,
  ChatProgress,
  ChatReply,
  ChatThread,
  ChatThreadSummary,
  ThreadAskInput,
  ThreadAskResult,
  ChatRequest,
  ChangeExplanation,
  ColumnPreview,
  CompanyArtifact,
  CompanyProfile,
  CompanySummary,
  Comparison,
  ContinueResearchAssessment,
  DataSheet,
  DataSheetColumn,
  DataSheetSummary,
  DiscoverQuery,
  DiscoverResult,
  EnrichmentField,
  EnrichmentResult,
  ExecutiveBrief,
  ExplainSubject,
  ExportRequest,
  ExportResult,
  InterpretedFilter,
  LibraryPage,
  LibraryQuery,
  QueryInterpretation,
  ReportKind,
  ReportSection,
  ResearchAnswer,
  ResearchEvent,
  ResearchRun,
  SearchResult,
  SheetEvent,
  SignalFeedGroup,
  StartResearchInput,
  SystemStatus,
  VersionComparison,
  Watchlist,
} from '@/types';
import type { StreamHandlers, Unsubscribe } from './http';

export interface SystemApi {
  status(): Promise<SystemStatus>;
  /** Liveness only (GET /health): is the backend process up? Used to tell "offline" apart from "the status report failed". */
  health(): Promise<BackendHealth>;
}

export interface SearchApi {
  global(query: string, signal?: AbortSignal): Promise<SearchResult>;
}

export interface CompaniesApi {
  discover(query: DiscoverQuery, signal?: AbortSignal): Promise<DiscoverResult>;
  interpret(text: string, signal?: AbortSignal): Promise<QueryInterpretation>;
  get(orgNumber: string): Promise<CompanyProfile>;
  recent(): Promise<CompanySummary[]>;
  /** One-screen factual brief compiled from saved evidence. */
  brief(orgNumber: string): Promise<ExecutiveBrief>;
  /** Backend-researched explanation, with observed / reported / synthesis kept apart. */
  explain(orgNumber: string, subject: ExplainSubject, opts?: { fresh?: boolean }): Promise<ChangeExplanation>;
  /** Targeted, bounded lookups for the figures Discover cards are missing (at most 12 companies per call). Not research: nothing is saved. */
  enrich(orgNumbers: string[], opts?: { fields?: EnrichmentField[]; signal?: AbortSignal }): Promise<EnrichmentResult>;
}

export interface ResearchApi {
  start(input: StartResearchInput): Promise<ResearchRun>;
  confirm(runId: string, stepKeys: string[]): Promise<ResearchRun>;
  get(runId: string): Promise<ResearchRun>;
  pause(runId: string): Promise<ResearchRun>;
  cancel(runId: string): Promise<ResearchRun>;
  retryFailed(runId: string): Promise<ResearchRun>;
  stream(runId: string, handlers: StreamHandlers<ResearchEvent>, opts?: { lastSeq?: number }): Unsubscribe;
  ask(input: { orgNumber: string; artifactId?: string; question: string; fresh: boolean }): Promise<ResearchAnswer>;
  assess(artifactId: string): Promise<ContinueResearchAssessment>;
}

export interface ChatApi {
  /** Identity, suggested questions, per-area coverage and capabilities for the Ask AI panel. */
  context(orgNumber: string): Promise<ChatContext>;
  /** Company-specific, source-grounded answer. Never switches company; citations point to real evidence. */
  ask(input: ChatRequest, onProgress?: (p: ChatProgress) => void): Promise<ChatReply>;
  /** Durable conversations for the AI Chat page. */
  threads: ChatThreadsApi;
}

export interface ChatThreadsApi {
  list(): Promise<ChatThreadSummary[]>;
  get(id: string): Promise<ChatThread>;
  /** Idempotent: creating an id that exists returns it. */
  create(input: { id: string; orgNumber?: string; title?: string }): Promise<ChatThreadSummary>;
  rename(id: string, title: string): Promise<ChatThreadSummary>;
  remove(id: string): Promise<void>;
  ask(input: ThreadAskInput): Promise<ThreadAskResult>;
}

export interface LibraryApi {
  list(query: LibraryQuery, signal?: AbortSignal): Promise<LibraryPage>;
  recent(): Promise<ArtifactSummary[]>;
  get(id: string): Promise<Artifact>;
  getVersion(id: string, versionId: string): Promise<CompanyArtifact>;
  compareVersions(id: string, fromVersionId: string, toVersionId: string): Promise<VersionComparison>;
  update(id: string, patch: { title?: string; tags?: string[]; pinned?: boolean; archived?: boolean }): Promise<ArtifactSummary>;
  duplicate(id: string): Promise<ArtifactSummary>;
  capabilities(): Promise<ArtifactCapabilities>;
  saveRun(runId: string): Promise<ArtifactSummary>;
  generateReport(input: { orgNumber: string; kind: ReportKind; sections: ReportSection[] }): Promise<ArtifactSummary>;
  findByOrg(orgNumber: string): Promise<ArtifactSummary | null>;
}

export interface SheetsApi {
  list(): Promise<DataSheetSummary[]>;
  get(id: string): Promise<DataSheet>;
  interpret(text: string): Promise<QueryInterpretation>;
  /**
   * `fallback: 'verified'` is the user's explicit choice to continue from companies COGNIS has already verified when (and only when) the
   * Enhetsregisteret search is unavailable; the returned summary then carries `discovery`.
   */
  create(input: { title: string; criteria: InterpretedFilter[]; text?: string; fallback?: 'verified' }): Promise<DataSheetSummary>;
  rename(id: string, title: string): Promise<DataSheetSummary>;
  /** Interpret an AI-column instruction without adding it. */
  previewColumn(id: string, input: AddColumnInput): Promise<ColumnPreview>;
  addColumn(id: string, input: AddColumnInput): Promise<DataSheetColumn>;
  updateColumn(id: string, columnId: string, patch: { title?: string; width?: number; frozen?: boolean }): Promise<DataSheetColumn>;
  removeColumn(id: string, columnId: string): Promise<void>;
  reorderColumns(id: string, columnIds: string[]): Promise<void>;
  researchAll(id: string, opts?: { columnIds?: string[] }): Promise<BatchStatus>;
  stream(id: string, handlers: StreamHandlers<SheetEvent>): Unsubscribe;
}

export interface CompareApi {
  get(orgNumbers: string[]): Promise<Comparison>;
}

export interface WatchlistApi {
  get(): Promise<Watchlist>;
  add(orgNumber: string): Promise<Watchlist>;
  remove(orgNumber: string): Promise<Watchlist>;
  markChecked(): Promise<Watchlist>;
  feed(): Promise<SignalFeedGroup[]>;
}

export interface ExportsApi {
  request(req: ExportRequest): Promise<ExportResult>;
}

export interface CognisApi {
  system: SystemApi;
  search: SearchApi;
  companies: CompaniesApi;
  research: ResearchApi;
  chat: ChatApi;
  library: LibraryApi;
  sheets: SheetsApi;
  compare: CompareApi;
  watchlist: WatchlistApi;
  exports: ExportsApi;
}
