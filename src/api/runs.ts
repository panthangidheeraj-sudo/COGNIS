/**
 * Research-run streaming helpers shared by the live and mock transports.
 * The reducer is pure so it can be unit tested and reused for replay.
 */
import type { ResearchEvent, ResearchRun, ResearchStreamState } from '@/types';

export const initialStreamState: ResearchStreamState = {
  run: null,
  lastSeq: 0,
  events: [],
  facts: [],
  synthesisText: '',
  answer: null,
  connection: 'idle',
};

/** Applies one backend event. Duplicate or out-of-order events are ignored. */
export function reduceResearchEvent(state: ResearchStreamState, event: ResearchEvent): ResearchStreamState {
  if (event.seq <= state.lastSeq) return state;
  const run = state.run ? applyToRun(state.run, event) : state.run;
  const next: ResearchStreamState = { ...state, run, lastSeq: event.seq, events: [...state.events, event] };
  switch (event.type) {
    case 'fact.confirmed':
      if (!state.facts.some((f) => f.id === event.fact.id)) next.facts = [...state.facts, event.fact];
      break;
    case 'synthesis.delta':
      next.synthesisText = state.synthesisText + event.text;
      break;
    case 'synthesis.completed':
      next.answer = event.answer;
      break;
    case 'run.failed':
      next.error = event.message;
      break;
    default:
      break;
  }
  return next;
}

function applyToRun(run: ResearchRun, event: ResearchEvent): ResearchRun {
  const steps = run.plan.steps;
  const patchStep = (stepId: string, patch: Partial<ResearchRun['plan']['steps'][number]>) => ({
    ...run,
    plan: { ...run.plan, steps: steps.map((s) => (s.id === stepId ? { ...s, ...patch } : s)) },
  });
  switch (event.type) {
    case 'run.started':
      return { ...run, status: 'running' };
    case 'stage.changed':
      return { ...run, stage: event.stage };
    case 'step.started':
      return patchStep(event.stepId, { status: 'running', sourceName: event.sourceName, startedAt: event.at, detail: undefined, message: undefined });
    case 'step.progress':
      // Only a step that is really running has a "doing now" line; a late progress event never revives a finished step.
      return steps.find((s) => s.id === event.stepId)?.status === 'running' ? patchStep(event.stepId, { detail: event.message }) : run;
    case 'step.completed':
      return patchStep(event.stepId, {
        status: 'done',
        sourceName: event.sourceName,
        finishedAt: event.at,
        durationMs: event.durationMs,
        factCount: event.factCount,
        evidenceCount: event.evidenceCount,
        outcome: event.outcome,
        message: event.message,
        detail: undefined,
      });
    case 'step.failed':
      return patchStep(event.stepId, { status: 'failed', message: event.message, retryable: event.retryable, finishedAt: event.at, detail: undefined });
    case 'step.blocked':
      return patchStep(event.stepId, { status: 'blocked', message: event.message, finishedAt: event.at, detail: undefined });
    case 'step.skipped':
      return patchStep(event.stepId, { status: 'skipped', message: event.message, finishedAt: event.at, detail: undefined });
    case 'step.cancelled':
      return patchStep(event.stepId, { status: 'cancelled', message: event.message, finishedAt: event.at, detail: undefined });
    case 'run.paused':
      return { ...run, status: 'paused' };
    case 'run.completed':
      return {
        ...run,
        status: 'completed',
        finishedAt: event.at,
        artifactId: event.artifactId,
        autoSaved: event.autoSaved,
        coverage: event.coverage,
        summary: event.summary,
        outcome: event.outcome ?? event.summary?.outcome,
        issues: event.issues ?? event.summary?.issues,
        stage: 'save',
      };
    case 'run.failed':
      return { ...run, status: event.cancelled || run.status === 'cancelled' ? 'cancelled' : 'failed', finishedAt: event.at };
    default:
      return run;
  }
}
