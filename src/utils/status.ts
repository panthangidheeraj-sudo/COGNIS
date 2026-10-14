/**
 * Single place that maps backend states to UI language.
 * Every state has a text label so status is never communicated by color only.
 */
import type { Coverage, ChangeCategory, CompanyStatus, CoverageArea, CoverageAreaStatus, Evidence, EvidenceState, Fact, ResearchStepStatus, RunSnapshotStatus, SectionStatus, Source, SourceKind, SourceTier, ValueStatus, ArtifactType, SignalKind, SourceAvailability, TimelineEvent, TimelineEventType, EventSignificance, EventSourceType, ActivityCheckStatus } from '@/types';

export type Tone = 'ok' | 'warn' | 'err' | 'info' | 'neutral';

export const VALUE_STATUS: Record<ValueStatus, { label: string; tone: Tone }> = {
  verified: { label: 'Verified', tone: 'ok' },
  researching: { label: 'Researching', tone: 'info' },
  pending: { label: 'Pending', tone: 'neutral' },
  not_available: { label: 'Not available', tone: 'neutral' },
  ambiguous: { label: 'Ambiguous', tone: 'warn' },
  blocked: { label: 'Source blocked', tone: 'err' },
  failed: { label: 'Failed', tone: 'err' },
  stale: { label: 'Stale', tone: 'warn' },
};

/** Fallback label when source tiers are unknown (e.g. before a profile loads). */
export function evidenceStateLabel(state: EvidenceState, sourceCount: number): string {
  switch (state) {
    case 'verified':
      return `Verified by ${sourceCount} sources`;
    case 'primary':
      return 'Verified by 1 primary source';
    case 'secondary':
      return 'Secondary-source evidence';
    case 'conflict':
      return 'Potential conflict';
    default:
      return 'Not verified';
  }
}

/** Distinct sources behind a set of evidence, split by authority. */
export function sourceCounts(evidence: Evidence[], sourceIndex: Record<string, Source>) {
  const ids = [...new Set(evidence.map((e) => e.sourceId))];
  let primary = 0;
  let secondary = 0;
  let unknown = 0;
  for (const id of ids) {
    const tier = sourceIndex[id]?.tier;
    if (tier === 'primary') primary += 1;
    else if (tier) secondary += 1;
    else unknown += 1;
  }
  return { primary, secondary, unknown, total: ids.length };
}

export type VerificationKind = 'verified' | 'secondary' | 'conflict' | 'unverified' | 'blocked' | 'researching' | 'not_available' | 'pending' | 'ambiguous' | 'failed' | 'stale';

export interface Verification {
  kind: VerificationKind;
  /** Full sentence, e.g. "Verified by 2 primary sources + 1 secondary source". */
  label: string;
  /** Card-sized form, e.g. "2 primary + 1 secondary". */
  short: string;
  tone: Tone;
}

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`;

/**
 * Evidence-based verification state. Deliberately never a confidence
 * percentage: it counts the primary and secondary sources behind a value.
 */
export function verification(fact: Pick<Fact, 'status' | 'evidenceState' | 'evidence' | 'conflict'>, sourceIndex: Record<string, Source>): Verification {
  switch (fact.status) {
    case 'blocked':
      return { kind: 'blocked', label: 'Source blocked', short: 'Source blocked', tone: 'err' };
    case 'researching':
      return { kind: 'researching', label: 'Researching', short: 'Researching', tone: 'info' };
    case 'pending':
      return { kind: 'pending', label: 'Pending', short: 'Pending', tone: 'neutral' };
    case 'not_available':
      return { kind: 'not_available', label: 'Not available', short: 'Not available', tone: 'neutral' };
    case 'ambiguous':
      return { kind: 'ambiguous', label: 'Ambiguous', short: 'Ambiguous', tone: 'warn' };
    case 'failed':
      return { kind: 'failed', label: 'Failed', short: 'Failed', tone: 'err' };
    case 'stale':
      return { kind: 'stale', label: 'Stale', short: 'Stale', tone: 'warn' };
    default:
      break;
  }
  if (fact.conflict || fact.evidenceState === 'conflict') return { kind: 'conflict', label: 'Potential conflict', short: 'Potential conflict', tone: 'warn' };
  if (fact.evidenceState === 'unverified' || !fact.evidence.length) return { kind: 'unverified', label: 'Not verified', short: 'Not verified', tone: 'neutral' };
  const c = sourceCounts(fact.evidence, sourceIndex);
  if (c.unknown) {
    const label = evidenceStateLabel(fact.evidenceState, c.total);
    return { kind: fact.evidenceState === 'secondary' ? 'secondary' : 'verified', label, short: label.replace(/^Verified by /, ''), tone: fact.evidenceState === 'secondary' ? 'neutral' : 'ok' };
  }
  if (c.primary > 0) {
    const tail = c.secondary ? ` + ${plural(c.secondary, 'secondary source')}` : '';
    return {
      kind: 'verified',
      label: `Verified by ${plural(c.primary, 'primary source')}${tail}`,
      short: `${c.primary} primary${c.secondary ? ` + ${c.secondary} secondary` : ''}`,
      tone: 'ok',
    };
  }
  return { kind: 'secondary', label: 'Secondary-source evidence', short: 'Secondary sources only', tone: 'neutral' };
}

export const EVIDENCE_TONE: Record<EvidenceState, Tone> = {
  verified: 'ok',
  primary: 'ok',
  secondary: 'neutral',
  conflict: 'warn',
  unverified: 'neutral',
};

export const COVERAGE_AREAS: { area: CoverageArea; label: string; short: string }[] = [
  { area: 'company_record', label: 'Company record', short: 'Record' },
  { area: 'financials', label: 'Financials', short: 'Financials' },
  { area: 'people_locations', label: 'People & locations', short: 'People' },
  { area: 'website', label: 'Company website', short: 'Website' },
  { area: 'hiring_activity', label: 'Hiring & public activity', short: 'Hiring' },
];

export const COVERAGE_STATUS: Record<CoverageAreaStatus, { label: string; tone: Tone }> = {
  complete: { label: 'Complete', tone: 'ok' },
  partial: { label: 'Partial', tone: 'warn' },
  unavailable: { label: 'Unavailable', tone: 'neutral' },
  blocked: { label: 'Blocked', tone: 'err' },
  pending: { label: 'Not researched', tone: 'neutral' },
};

export interface ResearchOutcome {
  /** True only when coverage was reported, every area is complete and no source was blocked or failed. */
  complete: boolean;
  reported: boolean;
  verified: number;
  total: number;
  gaps: { area: CoverageArea; label: string; status: string; note?: string }[];
  unreachableSources: number;
}

/** What a finished run actually verified. "Complete" is only claimed when the reported coverage says so. */
export function researchOutcome(run: { coverage?: Coverage; summary?: { coverage?: Coverage; blockedSources?: number; failedSources?: number } }): ResearchOutcome {
  const cov = run.summary?.coverage ?? run.coverage;
  const unreachableSources = (run.summary?.blockedSources ?? 0) + (run.summary?.failedSources ?? 0);
  const gaps = (cov?.areas ?? [])
    .filter((a) => a.status !== 'complete')
    .map((a) => ({ area: a.area, label: COVERAGE_AREAS.find((x) => x.area === a.area)?.label ?? a.area, status: COVERAGE_STATUS[a.status]?.label ?? a.status, note: a.note }));
  const verified = cov?.complete ?? 0;
  const total = cov?.total ?? 0;
  const complete = !!cov && total > 0 && verified === total && gaps.length === 0 && unreachableSources === 0;
  return { complete, reported: !!cov, verified, total, gaps, unreachableSources };
}

export const SECTION_STATUS: Record<SectionStatus, { label: string; tone: Tone }> = {
  available: { label: 'Available', tone: 'ok' },
  partial: { label: 'Partial', tone: 'warn' },
  not_available: { label: 'Not available', tone: 'neutral' },
  blocked: { label: 'Source blocked', tone: 'err' },
  ambiguous: { label: 'Ambiguous', tone: 'warn' },
  pending: { label: 'Not researched yet', tone: 'neutral' },
};

export const RUN_STATUS: Record<RunSnapshotStatus, { label: string; tone: Tone }> = {
  completed: { label: 'Completed', tone: 'ok' },
  partial: { label: 'Partial', tone: 'warn' },
  failed: { label: 'Failed', tone: 'err' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
};

export const STEP_STATUS: Record<ResearchStepStatus, { label: string; tone: Tone }> = {
  pending: { label: 'Waiting', tone: 'neutral' },
  running: { label: 'In progress', tone: 'info' },
  done: { label: 'Done', tone: 'ok' },
  failed: { label: 'Failed', tone: 'err' },
  blocked: { label: 'Blocked', tone: 'err' },
  skipped: { label: 'Skipped', tone: 'neutral' },
  cancelled: { label: 'Stopped', tone: 'neutral' },
};

export const COMPANY_STATUS_TONE: Record<CompanyStatus, Tone> = {
  active: 'ok',
  inactive: 'neutral',
  dissolved: 'neutral',
  bankruptcy: 'warn',
  under_liquidation: 'warn',
  other: 'neutral',
};

export const SOURCE_KIND_LABEL: Record<SourceKind, string> = {
  registry: 'Registry',
  financial: 'Financial',
  website: 'Website',
  people: 'People',
  jobs: 'Jobs',
  activity: 'Public activity',
  web: 'Web',
  news: 'News',
  regulatory: 'Regulatory',
  verification: 'Verification',
};

export const SOURCE_TIER_LABEL: Record<SourceTier, string> = {
  primary: 'Primary',
  secondary: 'Secondary',
  discovery: 'Discovery',
};

export const ARTIFACT_TYPE_LABEL: Record<ArtifactType, string> = {
  company: 'Company',
  report: 'Report',
  data_sheet: 'Data sheet',
  comparison: 'Comparison',
  watchlist: 'Watchlist',
  saved_search: 'Saved search',
};

export const SIGNAL_LABEL: Record<SignalKind, string> = {
  financial: 'Financial update',
  leadership: 'Leadership change',
  hiring: 'Hiring change',
  location: 'New location',
  announcement: 'Announcement',
  filing: 'New filing',
};

export const EVENT_LABEL: Record<TimelineEventType, string> = {
  filing: 'Filing',
  jobs: 'Job postings',
  leadership: 'Leadership',
  contract: 'Contract',
  acquisition: 'Acquisition',
  location: 'Location',
  announcement: 'Announcement',
  registration: 'Registration',
  funding: 'Capital',
  results: 'Results',
  partnership: 'Partnership',
  discovery: 'Discovery',
  project: 'Project',
  production: 'Production',
  regulatory: 'Regulatory',
  restructuring: 'Restructuring',
};

/** Legacy saved data used 'minor'; it reads as routine. */
export function eventTier(e: Pick<TimelineEvent, 'significance'>): EventSignificance {
  return e.significance === 'minor' ? 'routine' : e.significance;
}

export const SIGNIFICANCE_LABEL: Record<EventSignificance, string> = { major: 'Major', relevant: 'Relevant', routine: 'Routine' };
export const SIGNIFICANCE_HINT: Record<EventSignificance, string> = {
  major: 'Acquisitions, material contracts, results, discoveries, top-level leadership changes and similar developments',
  relevant: 'Worth knowing, but not by itself a change to the picture of the company',
  routine: 'Register entries, invitations and other routine notices. Kept for completeness; not counted as developments',
};

export const EVENT_SOURCE_LABEL: Record<EventSourceType, string> = {
  investor_relations: 'Investor relations',
  company_newsroom: 'Company newsroom',
  public_procurement: 'Public procurement',
  official_registry: 'Official register',
  secondary_news: 'Press coverage',
};

export const ACTIVITY_CHECK_LABEL: Record<ActivityCheckStatus, string> = {
  read: 'Read',
  blocked: 'Blocked',
  not_found: 'Nothing found',
  failed: 'Could not be read',
  not_run: 'Not checked',
  no_dated_items: 'No dated items',
  not_checked: 'Not checked',
};

/** "What changed?" priority: leadership, status, financial, ownership, locations, hiring, public activity, website. */
export const CHANGE_ORDER: ChangeCategory[] = ['leadership', 'status', 'financial', 'filing', 'ownership', 'location', 'address', 'hiring', 'employees', 'event', 'website'];

export const CHANGE_CATEGORY_LABEL: Record<ChangeCategory, string> = {
  leadership: 'Leadership',
  status: 'Legal status',
  financial: 'Financials',
  filing: 'Filings',
  ownership: 'Ownership',
  location: 'Locations',
  address: 'Address',
  hiring: 'Hiring',
  employees: 'Employees',
  event: 'Public activity',
  website: 'Website',
};

/**
 * Backend source availability (Settings, status center). `alternative` (a free source covers it) and `not_used`
 * (deliberately not collected) are choices, not failures, so they never read as "Unavailable".
 */
export const SOURCE_AVAILABILITY: Record<SourceAvailability, { label: string; tone: Tone }> = {
  available: { label: 'Available', tone: 'ok' },
  degraded: { label: 'Degraded', tone: 'warn' },
  unavailable: { label: 'Unavailable', tone: 'err' },
  alternative: { label: 'Free alternative', tone: 'info' },
  not_used: { label: 'Not used', tone: 'neutral' },
};

export function toneClass(tone: Tone) {
  return tone === 'neutral' ? '' : `pill--${tone}`;
}
