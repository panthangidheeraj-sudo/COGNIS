import type { AmbiguousMatch, Coverage, CompanySummary } from './company';
import type { Evidence, Fact, ISODateTime, SourceKind } from './evidence';

export type ResearchMode = 'quick' | 'deep';

export type ResearchStepStatus = 'pending' | 'running' | 'done' | 'failed' | 'blocked' | 'skipped';

/** Pipeline stages mirrored from the backend architecture. */
export type ResearchStage = 'discover' | 'identify' | 'gather' | 'verify' | 'reconcile' | 'synthesize' | 'save';

export interface ResearchStep {
  id: string;
  key: string;
  label: string;
  sourceKind: SourceKind;
  optional: boolean;
  status: ResearchStepStatus;
  /** Only filled from real backend events. */
  sourceName?: string;
  startedAt?: ISODateTime;
  finishedAt?: ISODateTime;
  durationMs?: number;
  factCount?: number;
  evidenceCount?: number;
  outcome?: 'verified' | 'not_available';
  message?: string;
  retryable?: boolean;
}

/**
 * Completion summary sent by the backend with run.completed. Every count is a
 * backend value; the UI shows only the fields that are present.
 */
export interface ResearchRunSummary {
  coverage: Coverage;
  sourcesVerified?: number;
  primarySources?: number;
  secondarySources?: number;
  factsVerified?: number;
  /** Unresolved fact-level conflicts between sources. */
  conflicts?: number;
  /** Unresolved identity conflicts (e.g. a similarly named entity could not be ruled out). */
  identityConflicts?: number;
  changesDetected?: number;
  blockedSources?: number;
  failedSources?: number;
  elapsedMs?: number;
}

export interface ResearchPlan {
  steps: ResearchStep[];
  /** Backend decides whether a plan merits confirmation (e.g. deep runs). */
  requiresConfirmation: boolean;
  /** Optional steps the user can add. */
  availableSteps: { key: string; label: string; sourceKind: SourceKind }[];
}

export type ResearchRunStatus =
  | 'planning'
  | 'awaiting_confirmation'
  | 'running'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'ambiguous';

export interface ResearchRunCapabilities {
  pause: boolean;
  cancel: boolean;
  retryFailed: boolean;
  editPlan: boolean;
}

export interface ResearchRun {
  id: string;
  query: string;
  prompt?: string;
  mode: ResearchMode;
  status: ResearchRunStatus;
  company?: CompanySummary;
  ambiguity?: AmbiguousMatch;
  plan: ResearchPlan;
  stage?: ResearchStage;
  startedAt: ISODateTime;
  finishedAt?: ISODateTime;
  capabilities: ResearchRunCapabilities;
  /** Set when the backend saved/auto-saved the run as a Library artifact. */
  artifactId?: string;
  autoSaved: boolean;
  coverage?: Coverage;
  summary?: ResearchRunSummary;
}

export interface StartResearchInput {
  orgNumber?: string;
  query: string;
  prompt?: string;
  mode: ResearchMode;
  /** Plan step keys when the user edited the plan. */
  stepKeys?: string[];
}

export interface AnswerCitation {
  evidence: Evidence;
  sourceName: string;
}

export interface AnswerBlock {
  id: string;
  text: string;
  reportingPeriod?: string;
  factIds?: string[];
  citations: AnswerCitation[];
  detail?: string;
}

/** A research answer. `origin` keeps saved vs fresh evidence honest. */
export interface ResearchAnswer {
  id: string;
  question: string;
  origin: 'saved_evidence' | 'fresh_research';
  blocks: AnswerBlock[];
  /** Sources newly queried (only for fresh research). */
  newSourceIds?: string[];
  generatedAt: ISODateTime;
  /** Things the evidence cannot answer. */
  gaps?: string[];
}

interface EventBase {
  /** Monotonic sequence number used for de-duplication and reconnect. */
  seq: number;
  runId: string;
  at: ISODateTime;
}

export type ResearchEvent =
  | (EventBase & { type: 'run.started' })
  | (EventBase & { type: 'stage.changed'; stage: ResearchStage })
  | (EventBase & { type: 'step.started'; stepId: string; sourceName: string })
  | (EventBase & {
      type: 'step.completed';
      stepId: string;
      sourceName: string;
      factCount: number;
      evidenceCount: number;
      durationMs: number;
      /** 'not_available' when the source answered but held no verifiable data. */
      outcome?: 'verified' | 'not_available';
      /** e.g. "No current openings found in searched sources" */
      message?: string;
    })
  | (EventBase & { type: 'step.failed'; stepId: string; sourceName?: string; message: string; retryable: boolean })
  | (EventBase & { type: 'step.blocked'; stepId: string; sourceName?: string; message: string })
  | (EventBase & { type: 'fact.confirmed'; fact: Fact })
  | (EventBase & { type: 'synthesis.delta'; text: string })
  | (EventBase & { type: 'synthesis.completed'; answer: ResearchAnswer })
  | (EventBase & { type: 'run.paused'; message: string })
  | (EventBase & { type: 'run.completed'; artifactId?: string; autoSaved: boolean; coverage: Coverage; summary?: ResearchRunSummary })
  | (EventBase & { type: 'run.failed'; message: string });

export type ResearchEventType = ResearchEvent['type'];

/** Live research-state the UI keeps for a streaming run. */
export interface ResearchStreamState {
  run: ResearchRun | null;
  lastSeq: number;
  events: ResearchEvent[];
  facts: Fact[];
  synthesisText: string;
  answer: ResearchAnswer | null;
  connection: 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed' | 'error';
  error?: string;
}

/** Backend's "continue research" assessment of a saved artifact. */
export interface ContinueResearchAssessment {
  staleAreas: { area: string; reason: string }[];
  changedSources: { sourceId: string; sourceName: string; detail: string }[];
  newFilings: number;
  missingFields: string[];
  checkedAt: ISODateTime;
}
