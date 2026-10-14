import type { Evidence, EvidenceState, Fact, ISODate, ISODateTime, NumericFact, Source, TextFact, ValueStatus } from './evidence';

export type CompanyStatus =
  | 'active'
  | 'inactive'
  | 'dissolved'
  | 'bankruptcy'
  | 'under_liquidation'
  | 'other';

export type CoverageArea = 'company_record' | 'financials' | 'people_locations' | 'website' | 'hiring_activity';

export type CoverageAreaStatus = 'complete' | 'partial' | 'unavailable' | 'blocked' | 'pending';

export interface CoverageAreaState {
  area: CoverageArea;
  status: CoverageAreaStatus;
  factCount: number;
  /** e.g. "Hiring data unavailable" */
  note?: string;
}

export interface Coverage {
  complete: number;
  total: number;
  areas: CoverageAreaState[];
}

export type ResearchState = 'not_researched' | 'researching' | 'researched' | 'stale' | 'failed';

export interface GeoPoint {
  lat: number;
  lon: number;
}

export interface Industry {
  /** NACE / SN2007 code */
  code: string;
  description: string;
}

/** Compact company shape for cards, search results and lists. */
export interface CompanySummary {
  orgNumber: string;
  legalName: string;
  municipality?: string;
  county?: string;
  country: string;
  industry?: Industry;
  status: CompanyStatus;
  statusLabel?: string;
  employees?: number | null;
  employeesPeriod?: string;
  /** `currency` is the one the latest filing states; empty when the filing states none. */
  revenue?: { value: number; currency: string; period: string } | null;
  openPositions?: number | null;
  /** What hiring research established (researched companies): a count is only meaningful when this is 'verified'. 'none_found' is not "0 openings". */
  openPositionsStatus?: 'verified' | 'none_found' | 'source_unavailable' | 'incomplete' | 'pending' | null;
  coverage: Coverage;
  lastResearchedAt?: ISODateTime | null;
  researchState: ResearchState;
  logoUrl?: string | null;
  website?: string | null;
  geo?: GeoPoint | null;
  /** Backend-detected changes since the user's last check. */
  changeCount?: number;
  tags?: string[];
}

/* -------------------------------------------------------------------------- */
/*  Discover enrichment (POST /companies/enrich)                              */
/* -------------------------------------------------------------------------- */

/**
 * What a targeted lookup established for one figure of a result card:
 * `verified` the named source states it · `none_found` (openings) sources checked, none verified — not "0" ·
 * `not_reported` the official source holds no value (no filed accounts, no registered count) — not a zero ·
 * `unavailable` a source could not be reached now · `not_checked` no permitted source could be checked · `unverified` data exists but could not be verified.
 */
export type EnrichmentState = 'verified' | 'none_found' | 'not_reported' | 'unavailable' | 'not_checked' | 'unverified';
export type EnrichmentField = 'revenue' | 'employees' | 'openPositions';

export interface EnrichmentSource {
  name: string;
  state: 'checked' | 'unavailable' | 'not_checked';
  url?: string;
  retrievedAt?: ISODateTime;
  note?: string;
}

export interface EnrichedFigure {
  state: EnrichmentState;
  /** Shown as the explanation (tooltip / screen-reader text). */
  note: string;
  sources: EnrichmentSource[];
  value?: number;
  currency?: string;
  period?: string;
  asOf?: string;
  /** The filing's own line the value was read from (revenue). */
  evidence?: string;
  /** Openings: not every job source could be checked, so the count is "at least". */
  lowerBound?: boolean;
}

export interface CompanyEnrichment {
  orgNumber: string;
  checkedAt: ISODateTime;
  cached?: boolean;
  fields: Partial<Record<EnrichmentField, EnrichedFigure>>;
}

export interface EnrichmentResult {
  items: CompanyEnrichment[];
  enabled: boolean;
  checkedAt: ISODateTime;
  note?: string;
}

/* -------------------------------------------------------------------------- */
/*  Profile sections                                                          */
/* -------------------------------------------------------------------------- */

export type SectionStatus = 'available' | 'partial' | 'not_available' | 'blocked' | 'ambiguous' | 'pending';

export interface SectionMeta {
  status: SectionStatus;
  /** Shown verbatim when status is not 'available'. */
  message?: string;
  searchedSourceIds?: string[];
}

export interface ExecutiveSummary {
  text: string;
  sourceIds: string[];
  evidenceIds: string[];
  generatedAt: ISODateTime;
}

export type FinancialMetricKey =
  | 'revenue'
  | 'operating_result'
  | 'annual_result'
  | 'total_assets'
  | 'equity'
  | 'debt'
  | 'cash'
  | 'employees';

export interface FinancialPoint {
  period: string; // "FY2025"
  year: number;
  fact: NumericFact;
}

export interface FinancialSeries {
  key: FinancialMetricKey;
  label: string;
  /** An ISO currency code ("NOK", "USD" — the currency the filings state), "mixed currencies", "currency not stated", or "people" / "%". */
  unit: string;
  /** Distinct currencies the series' filings are stated in, in period order. */
  currencies?: string[];
  points: FinancialPoint[];
}

export interface FinancialRatio {
  key: string;
  label: string;
  value: number; // already a percentage value, e.g. 12.4
  period: string;
  /** Deterministic formula used by backend, e.g. "Operating result / Revenue" */
  formula: string;
}

/** A deterministic ratio computed by the backend for every period it can. */
export interface FinancialRatioSeries {
  key: string;
  label: string;
  formula: string;
  points: { period: string; value: number }[];
}

export interface FinancialsSection extends SectionMeta {
  /** Currency code shared by every filing, else "mixed currencies" / "currency not stated" (never converted). */
  currency: string;
  currencies?: string[];
  latestPeriod?: string;
  series: FinancialSeries[];
  /** Latest-period ratios. */
  ratios: FinancialRatio[];
  /** Same ratios across periods, when the backend can compute them. */
  ratioHistory?: FinancialRatioSeries[];
}

export interface Person {
  id: string;
  name: string;
  role: string; // normalised: "CEO", "Chair of the board", "Board member"
  roleGroup: 'executive' | 'board' | 'founder' | 'other';
  current: boolean;
  since?: ISODate;
  until?: ISODate;
  fact: TextFact;
  otherRoles?: { orgNumber?: string; companyName: string; role: string; current: boolean; evidence: Evidence[] }[];
}

export interface PeopleSection extends SectionMeta {
  people: Person[];
}

export type LocationKind = 'registered_address' | 'headquarters' | 'operating' | 'postal';

export interface CompanyLocation {
  id: string;
  kind: LocationKind;
  label: string;
  address: string;
  postalCode?: string;
  municipality: string;
  geo?: GeoPoint;
  verified: boolean;
  fact: TextFact;
}

export interface LocationsSection extends SectionMeta {
  locations: CompanyLocation[];
}

export interface WebsitePage {
  kind: 'about' | 'products' | 'contact' | 'careers' | 'news' | 'investors' | 'sustainability';
  title: string;
  url?: string;
  found: boolean;
}

export interface SocialProfile {
  network: 'linkedin' | 'facebook' | 'x' | 'instagram' | 'youtube' | 'github';
  url: string;
  handle?: string;
  fact: TextFact;
}

export interface WebsiteSection extends SectionMeta {
  domain?: string;
  url?: string;
  verification?: TextFact;
  description?: TextFact;
  pages: WebsitePage[];
  social: SocialProfile[];
  signals: { label: string; value: string; fact?: Fact }[];
}

export interface Job {
  id: string;
  title: string;
  department?: string;
  location?: string;
  postedAt?: ISODate;
  /** Last update stated by the source, when it states one. */
  updatedAt?: ISODate;
  /** End of the posting's validity (application deadline / expiry), when stated. */
  validThrough?: ISODate;
  /** When COGNIS last read the listing. */
  checkedAt?: ISODateTime;
  sourceId: string;
  url?: string;
  /** Anything but 'current' is never counted as an opening. */
  state: 'current' | 'stale' | 'closed';
  /** The same opening found on other sources (merged and counted once). */
  alsoListed?: { source: 'company' | 'discovered' | 'nav'; url: string; state?: string; posted_at?: string; updated_at?: string }[];
  evidence: Evidence[];
}

/**
 * What the hiring research established. Missing data is never "not hiring":
 * verified → at least one verified current opening · none_found → sources were checked and returned none ·
 * source_unavailable → a source could not be reached or read (e.g. a NAV timeout) · incomplete → not every source was checked.
 */
export type HiringOutcome = 'verified' | 'none_found' | 'source_unavailable' | 'incomplete' | 'pending';

export interface HiringCheck {
  id: string;
  name: string;
  state: 'checked' | 'unavailable' | 'incomplete';
  note: string;
  required: boolean;
}

export interface HiringSection extends SectionMeta {
  outcome?: HiringOutcome;
  /** One entry per hiring source: what it returned in this research. */
  checks?: HiringCheck[];
  totalCurrent: number | null;
  locations: { name: string; count: number }[];
  categories: { name: string; count: number }[];
  jobs: Job[];
  /** Timestamped history of openings — only when backend has it. */
  history: { month: string; count: number }[];
  verifiedAt?: ISODateTime;
}

export type TimelineEventType =
  | 'filing'
  | 'jobs'
  | 'leadership'
  | 'contract'
  | 'acquisition'
  | 'location'
  | 'announcement'
  | 'registration'
  | 'funding'
  | 'results'
  | 'partnership'
  | 'discovery'
  | 'project'
  | 'production'
  | 'regulatory'
  | 'restructuring';

/**
 * How much an event matters to an assessment of the company.
 * - major: acquisitions, material contracts, results, discoveries, top-level leadership changes … (backend scores impact, money, operations, strategy, recency)
 * - relevant: worth knowing, but not by itself a change to the picture of the company
 * - routine: register entries (registrations, establishments), invitations, webinars and other routine notices — kept, but never counted as developments
 * Older saved data may still say 'minor'; it is shown as routine.
 */
export type EventSignificance = 'major' | 'relevant' | 'routine';

/** Where an event was found. Official sources outrank press coverage when the same announcement appears in several places. */
export type EventSourceType = 'investor_relations' | 'company_newsroom' | 'public_procurement' | 'official_registry' | 'secondary_news';

export interface EventSourceRef {
  sourceIds: string[];
  sourceType: EventSourceType;
  url?: string | null;
  title?: string;
  date?: ISODate;
}

export interface TimelineEvent {
  id: string;
  date: ISODate;
  type: TimelineEventType;
  title: string;
  description?: string;
  /** Backend classification (see EventSignificance). Legacy 'minor' is read as 'routine'. */
  significance: EventSignificance | 'minor';
  /** 0–100 ranking score and 1-based rank within the section (1 = most significant). Present for researched profiles. */
  score?: number;
  rank?: number;
  /** Plain-language reasons for the classification, e.g. "Contract or order (decisive wording)". */
  reasons?: string[];
  sourceType?: EventSourceType;
  /** The announcement itself, when the source links to it. */
  url?: string;
  /** Every place the same announcement was found (the event is shown once). */
  sources?: EventSourceRef[];
  /** How many duplicate reports were merged into this event. */
  duplicates?: number;
  sourceIds: string[];
  evidence: Evidence[];
}

/** What was looked at for the Recent activity section and what came of it. A source that could not be read is a limitation, never "no events". */
export type ActivityCheckStatus = 'read' | 'blocked' | 'not_found' | 'failed' | 'not_run' | 'no_dated_items' | 'not_checked';
export interface ActivityCheck {
  id: string;
  kind: 'newsroom' | 'investor_relations' | 'feed' | 'news_search' | 'registry' | 'procurement';
  name: string;
  status: ActivityCheckStatus;
  note: string;
  url?: string;
  items?: number;
  sourceId?: string;
}

export interface ActivitySection extends SectionMeta {
  events: TimelineEvent[];
  counts?: Record<EventSignificance, number>;
  /** Duplicate reports of the same announcement that were merged into one event. */
  consolidated?: number;
  sourcesChecked?: ActivityCheck[];
  /** Candidates that were not shown because they had no valid date, source URL or matching evidence. */
  excluded?: { count: number; items: { title: string; date?: string | null; reason: string; sourceType?: EventSourceType }[] };
  /** Lowest-ranked routine events beyond the display limit. */
  omitted?: number;
}

export type ChangeKind = 'added' | 'removed' | 'modified';
/**
 * Change categories. "What changed?" orders material changes as:
 * leadership → status → financial/filing → ownership → location/address →
 * hiring → employees → event (public activity) → website.
 */
export type ChangeCategory = 'leadership' | 'status' | 'financial' | 'filing' | 'ownership' | 'location' | 'address' | 'hiring' | 'employees' | 'event' | 'website';

export interface Change {
  id: string;
  detectedAt: ISODateTime;
  kind: ChangeKind;
  category: ChangeCategory;
  label: string;
  previous?: string;
  current?: string;
  /** Short backend-written chip text, e.g. "CEO changed". */
  headline?: string;
  /** Backend flags changes that matter to a decision-maker. Only these appear in the strip. */
  material: boolean;
  /** Direction for numeric changes (up = increase). */
  direction?: 'up' | 'down';
  /** True when the backend can research an explanation for this change. */
  explainable?: boolean;
  evidence: Evidence[];
}

export interface ChangesSection extends SectionMeta {
  since?: ISODateTime;
  /** What "since" refers to, e.g. "previous research". */
  baselineLabel?: string;
  changes: Change[];
}

export type RelationshipKind = 'ceo' | 'board' | 'subsidiary' | 'parent' | 'related' | 'investor' | 'partner' | 'founder';

export interface Relationship {
  id: string;
  kind: RelationshipKind;
  label: string;
  entity: { type: 'person' | 'organization'; name: string; orgNumber?: string };
  evidence: Evidence[];
}

export interface SourceUsage {
  source: Source;
  factCount: number;
  lastRetrievedAt: ISODateTime;
  sections: string[];
  evidenceIds: string[];
}

export interface ResearchQuality {
  coverage: Coverage;
  primarySources: number;
  secondarySources: number;
  conflicts: number;
  lastRefreshedAt: ISODateTime | null;
}

export interface KnownItem {
  id: string;
  label: string;
  text: string;
  status: 'verified' | 'unknown' | 'blocked' | 'conflict';
  factId?: string;
}

export interface CompanyIdentity {
  legalName: TextFact;
  orgNumber: string;
  status: TextFact;
  legalForm?: TextFact;
  founded?: TextFact;
  industry?: TextFact;
  registeredAddress?: TextFact;
  headquarters?: TextFact;
  website?: TextFact;
}

/** Full company intelligence profile. Every section can be partial. */
export interface CompanyProfile {
  company: CompanySummary;
  identity: CompanyIdentity;
  summary: ExecutiveSummary | null;
  description?: TextFact;
  keyMetrics: Fact[];
  financials: FinancialsSection;
  people: PeopleSection;
  locations: LocationsSection;
  website: WebsiteSection;
  hiring: HiringSection;
  activity: ActivitySection;
  changes: ChangesSection;
  relationships: Relationship[];
  sources: SourceUsage[];
  /** All sources referenced anywhere in this profile, by id. */
  sourceIndex: Record<string, Source>;
  quality: ResearchQuality;
  knowns: KnownItem[];
  /** If set, profile belongs to a saved Library artifact. */
  artifactId?: string;
}

/* -------------------------------------------------------------------------- */
/*  Executive brief & change explanations                                     */
/* -------------------------------------------------------------------------- */

export type BriefSectionId = 'what' | 'scale' | 'financials' | 'leadership' | 'locations' | 'hiring' | 'changes';

/** One factual line in an executive brief. Never an opinion or score. */
export interface BriefItem {
  id: string;
  label?: string;
  text: string;
  value?: string;
  reportingPeriod?: string;
  status: ValueStatus;
  evidenceState?: EvidenceState;
  /** When the line restates a profile fact, its id (so the UI can open evidence). */
  factId?: string;
  evidence: Evidence[];
}

export interface BriefSection {
  id: BriefSectionId;
  title: string;
  items: BriefItem[];
  /** Shown when the section has no verified items. */
  emptyText?: string;
}

/** A one-screen factual brief compiled by the backend from saved evidence. */
export interface ExecutiveBrief {
  orgNumber: string;
  companyName: string;
  statusLabel: string;
  location?: string;
  generatedAt: ISODateTime;
  /** Research the brief is based on; null for registry-only companies. */
  researchedAt: ISODateTime | null;
  artifactId?: string;
  coverage: Coverage;
  sections: BriefSection[];
  /** What the evidence does not establish. */
  gaps: string[];
  sourceIds: string[];
  sourceIndex: Record<string, Source>;
}

export type ExplainSubject =
  | { kind: 'change'; changeId: string }
  | { kind: 'metric'; metric: FinancialMetricKey; fromPeriod: string; toPeriod: string };

/**
 * An explanation keeps three layers visibly separate:
 *  observed  – verified facts from the profile
 *  reported  – explanations a source itself states (quoted, attributed)
 *  synthesis – AI synthesis across the above; never presented as established fact
 */
export interface ChangeExplanation {
  subject: ExplainSubject;
  question: string;
  observed: { id: string; text: string; evidence: Evidence[] }[];
  reported: { id: string; text: string; sourceId: string; quote?: string; evidence: Evidence[] }[];
  synthesis: { text: string; basis: string[]; caveat: string } | null;
  gaps: string[];
  origin: 'saved_evidence' | 'fresh_research';
  generatedAt: ISODateTime;
}

/** Returned when an identifier/name can't be resolved to exactly one company. */
export interface AmbiguousMatch {
  query: string;
  candidates: CompanySummary[];
  message: string;
}
