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
      return patchStep(event.stepId, { status: 'running', sourceName: event.sourceName, startedAt: event.at });
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
      });
    case 'step.failed':
      return patchStep(event.stepId, { status: 'failed', message: event.message, retryable: event.retryable, finishedAt: event.at });
    case 'step.blocked':
      return patchStep(event.stepId, { status: 'blocked', message: event.message, finishedAt: event.at });
    case 'run.paused':
      return { ...run, status: 'paused' };
    case 'run.completed':
      return { ...run, status: 'completed', finishedAt: event.at, artifactId: event.artifactId, autoSaved: event.autoSaved, coverage: event.coverage, summary: event.summary, stage: 'save' };
    case 'run.failed':
      return { ...run, status: run.status === 'cancelled' ? 'cancelled' : 'failed', finishedAt: event.at };
    default:
      return run;
  }
}
