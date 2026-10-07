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
  BatchStatus,
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
  create(input: { title: string; criteria: InterpretedFilter[]; text?: string }): Promise<DataSheetSummary>;
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
  library: LibraryApi;
  sheets: SheetsApi;
  compare: CompareApi;
  watchlist: WatchlistApi;
  exports: ExportsApi;
}
