import type { AmbiguousMatch, Coverage, CompanySummary } from './company';
import type { Evidence, Fact, ISODateTime, SourceKind } from './evidence';

export type ResearchMode = 'quick' | 'deep';

/** `skipped`: the backend decided not to run it (with the reason in `message`). `cancelled`: it was running when the run was cancelled. */
export type ResearchStepStatus = 'pending' | 'running' | 'done' | 'failed' | 'blocked' | 'skipped' | 'cancelled';

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
  /** The final note: why it failed, was blocked or skipped, or what it found. */
  message?: string;
  /** What a running step is doing right now (from step.progress events). */
  detail?: string;
  retryable?: boolean;
}

/** An optional workflow a run did or did not perform, with the reason (the run's "effort" report). */
export interface EffortWorkflow {
  key: string;
  label: string;
  status: 'ran' | 'skipped' | 'failed';
  detail: string;
}

/** How well independent sources agreed on what was published (Deep research). It reports; it never adds facts. */
export interface CrossCheckResult {
  checked: number;
  corroborated: number;
  singleSource: number;
  conflicts: number;
  corroboratedFacts?: { field: string; label: string; sources: string[] }[];
  conflictFacts?: { field: string; label: string; reason?: string; candidates: { source?: string; value: string }[] }[];
}

/** The limits a run was held to. Quick has a smaller budget than Deep on every axis; the backend reports the values it actually enforced. */
export interface ResearchBudget {
  maxRequests: number;
  maxSeconds: number;
  maxSearches: number;
  maxLlmCalls: number;
  maxSitePages: number;
  followUpRounds: number;
  /** Search-engine discovery of job pages: always in Deep, in Quick only when the focus is about hiring. */
  jobPageSearch: boolean;
}

export interface ResearchEffort {
  mode: ResearchMode;
  requests: number;
  llmCalls: number;
  pagesRead: number;
  timedOut?: boolean;
  workflows: EffortWorkflow[];
  crosscheck?: CrossCheckResult | null;
  focusKinds?: string[];
  budget?: ResearchBudget;
}

/** How a finished run ended: `completed` = every area verified and every source reachable; `partial` = it finished and saved, with the gaps listed. */
export type RunOutcome = 'completed' | 'partial';

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
  outcome?: RunOutcome;
  issues?: string[];
  effort?: ResearchEffort | null;
  /** What happened to the saved report: a run always keeps earlier versions; `factsChanged` false means it found the same facts as before. */
  report?: { newVersion: boolean; factsChanged?: boolean | null; versionId?: string };
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
  outcome?: RunOutcome;
  issues?: string[];
}

/** How a saved research run ended. Only `completed` means every area was verified and every source was reachable. */
export type RunSnapshotStatus = 'completed' | 'partial' | 'failed' | 'cancelled';

/** One research run of a company, kept in the Library beside the report version it produced. */
export interface ResearchRunSnapshot {
  id: string;
  mode: ResearchMode;
  /** The focus or custom question; empty for the plain company brief. */
  prompt?: string | null;
  status: RunSnapshotStatus;
  startedAt: ISODateTime;
  finishedAt?: ISODateTime | null;
  /** The Library version (report) this run produced; absent for failed/cancelled runs that saved nothing. */
  versionId?: string | null;
  versionNumber?: number | null;
  hasReport: boolean;
  /** True for the newest run whose report is the current one the dossier shows. */
  isLatestReport: boolean;
  /** False when the run found exactly the same facts as the run before it. */
  evidenceChanged?: boolean | null;
  summary?: ResearchRunSummary | null;
  effort?: ResearchEffort | null;
  steps: { key: string; label: string; status: ResearchStepStatus; sourceName?: string; message?: string; durationMs?: number; factCount?: number; evidenceCount?: number; outcome?: 'verified' | 'not_available' }[];
  answer?: ResearchAnswer | null;
  issues: string[];
}

export interface StartResearchInput {
  orgNumber?: string;
  /** Legal name the user confirmed for `orgNumber`; the backend rejects the run if the registry says otherwise. */
  expectedName?: string;
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
  /** Set when the question cannot be answered from verified public evidence (e.g. confidential or future matters, or nothing relevant on record). */
  limitation?: string;
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
  | (EventBase & { type: 'step.progress'; stepId: string; message: string })
  | (EventBase & { type: 'step.failed'; stepId: string; sourceName?: string; message: string; retryable: boolean })
  | (EventBase & { type: 'step.blocked'; stepId: string; sourceName?: string; message: string })
  | (EventBase & { type: 'step.skipped'; stepId: string; sourceName?: string; message: string })
  | (EventBase & { type: 'step.cancelled'; stepId: string; sourceName?: string; message: string })
  | (EventBase & { type: 'fact.confirmed'; fact: Fact })
  | (EventBase & { type: 'synthesis.delta'; text: string })
  | (EventBase & { type: 'synthesis.completed'; answer: ResearchAnswer })
  | (EventBase & { type: 'run.paused'; message: string })
  | (EventBase & { type: 'run.completed'; artifactId?: string; autoSaved: boolean; coverage: Coverage; summary?: ResearchRunSummary; outcome?: RunOutcome; issues?: string[] })
  | (EventBase & { type: 'run.failed'; message: string; cancelled?: boolean });

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
