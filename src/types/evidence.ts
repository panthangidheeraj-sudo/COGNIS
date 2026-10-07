/**
 * COGNIS frontend ↔ backend contract — evidence primitives.
 * These shapes are what the backend must return; the mock backend returns
 * structurally identical data so the live swap is a config change.
 */

/** ISO-8601 calendar date, e.g. "2026-10-03" */
export type ISODate = string;
/** ISO-8601 timestamp with timezone, e.g. "2026-10-03T10:32:01Z" */
export type ISODateTime = string;

/** Families of sources. Drives icons, source stack layers and filters. */
export type SourceKind =
  | 'registry'
  | 'financial'
  | 'website'
  | 'people'
  | 'jobs'
  | 'activity'
  | 'web'
  | 'news'
  | 'regulatory';

/** How authoritative a source is for a fact. */
export type SourceTier = 'primary' | 'secondary' | 'discovery';

export interface Source {
  id: string;
  /** Display name (English or original) – never translated legal names. */
  name: string;
  /** Original (often Norwegian) source title, preserved as published. */
  originalTitle?: string;
  kind: SourceKind;
  tier: SourceTier;
  /** True for government registries and the company's own official channels. */
  official: boolean;
  url?: string;
  domain?: string;
}

/** One concrete piece of evidence supporting (or contradicting) a fact. */
export interface Evidence {
  id: string;
  sourceId: string;
  url?: string;
  documentTitle?: string;
  page?: number;
  excerpt?: string;
  excerptLanguage?: 'no' | 'en';
  /** Optional English summary when the source text is Norwegian. */
  excerptTranslation?: string;
  retrievedAt: ISODateTime;
  reportingPeriod?: string;
  /** Value exactly as stated by this source (used for conflicts). */
  statedValue?: string;
}

/**
 * Evidence quality state. Deliberately NOT a confidence percentage.
 *  verified        – corroborated by ≥2 sources incl. a primary one
 *  primary         – verified from one primary source
 *  secondary       – only secondary sources
 *  conflict        – sources disagree
 *  unverified      – discovered but not verified
 */
export type EvidenceState = 'verified' | 'primary' | 'secondary' | 'conflict' | 'unverified';

/**
 * Availability / research state of a value. Shared by facts and data-sheet cells.
 */
export type ValueStatus =
  | 'verified'
  | 'researching'
  | 'pending'
  | 'not_available'
  | 'ambiguous'
  | 'blocked'
  | 'failed'
  | 'stale';

export type Freshness = 'current' | 'historical' | 'stale';

export type FactPrimitive = string | number | boolean;

export interface ConflictCandidate {
  sourceId: string;
  value: FactPrimitive;
  displayValue?: string;
  /** Currency this candidate is stated in (may differ from the displayed fact's). */
  currency?: string;
  reportingPeriod?: string;
  evidenceId: string;
}

export interface Conflict {
  /** Backend-provided possible reason; frontend never invents one. */
  reason?: string;
  candidates: ConflictCandidate[];
}

/** A single published fact with its full provenance. */
export interface Fact<T extends FactPrimitive = FactPrimitive> {
  id: string;
  /** Dotted field path, e.g. "financials.revenue". */
  field: string;
  label: string;
  status: ValueStatus;
  value: T | null;
  /** Optional backend-formatted value. Frontend formats if absent. */
  displayValue?: string;
  unit?: string;
  currency?: string;
  reportingPeriod?: string;
  freshness?: Freshness;
  verifiedAt?: ISODateTime;
  evidenceState: EvidenceState;
  evidence: Evidence[];
  conflict?: Conflict;
  /** Human explanation when unavailable / blocked / ambiguous. */
  note?: string;
}

export type NumericFact = Fact<number>;
export type TextFact = Fact<string>;
