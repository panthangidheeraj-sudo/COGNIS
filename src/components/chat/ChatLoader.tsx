import { ChevronDown } from 'lucide-react';
import type { ChatProgress } from '@/types';
import { cn } from '@/utils/cn';

/**
 * The answer loader: a small rotating COGNIS orbit and a few plain-language stages that follow what the server REALLY reports.
 *
 * The server streams fine-grained progress (`understand`, `identity`, `evidence`, `research`, `answer`, plus one `source` event per source looked at). This turns
 * it into at most four stages in their natural order. A stage is shown as done only once the server has moved on to a later stage; the stage it is in now is
 * "in progress"; later ones are "waiting". If the server goes back to an earlier stage (the saved evidence did not answer, so it checks current sources and writes
 * again), the stages after it go back to waiting — nothing ever looks finished before it is. Per-source detail is kept out of the list, in a collapsed
 * "Sources checked" section for anyone who wants it.
 *
 * Motion is CSS transforms only (no canvas, no blur, no JavaScript animation loop) and stops under reduced motion (OS setting or the app's motion setting).
 */
export type Phase = 'understand' | 'evidence' | 'research' | 'answer';
export const PHASE_LABEL: Record<Phase, string> = {
  understand: 'Understanding your question',
  evidence: 'Checking relevant evidence',
  research: 'Checking current sources',
  answer: 'Preparing your sourced answer',
};
const ORDER: Phase[] = ['understand', 'evidence', 'research', 'answer'];
const STAGE_PHASE: Record<string, Phase> = {
  understand: 'understand',
  identity: 'understand',
  evidence: 'evidence',
  audit: 'evidence',
  compare: 'evidence',
  research: 'research',
  news: 'research',
  answer: 'answer',
};

export interface StageRow {
  phase: Phase;
  label: string;
  state: 'done' | 'active' | 'waiting';
  /** What the server says it is doing right now, for the active stage only. */
  detail?: string;
}
export interface SourceRow {
  name: string;
  url?: string | null;
  state: string;
  reason?: string | null;
}

export function phaseOf(stage: string): Phase | null {
  return STAGE_PHASE[stage] ?? null;
}

/** The stage rows for the progress events received so far (pure: easy to test). */
export function chatStages(steps: ChatProgress[]): StageRow[] {
  let current: Phase = 'understand';
  let detail: string | undefined;
  const seen = new Set<Phase>(['understand']);
  for (const s of steps) {
    const p = phaseOf(s.stage);
    if (!p) {
      if (s.stage !== 'source' && s.label) detail = s.label; // a step the loader has no stage for: shown as what is happening now, never as a new stage
      continue;
    }
    seen.add(p);
    if (p !== current) detail = undefined;
    current = p;
    if (s.label && s.label !== PHASE_LABEL[p]) detail = s.label;
  }
  const at = ORDER.indexOf(current);
  return ORDER.filter((p) => p !== 'research' || seen.has('research')).map((p) => {
    const i = ORDER.indexOf(p);
    // done = it really started AND the server has since moved on to a later stage; a stage that never started is never shown as done
    const state = p === current ? 'active' : seen.has(p) && i < at ? 'done' : 'waiting';
    return { phase: p, label: PHASE_LABEL[p], state, ...(state === 'active' && detail ? { detail } : {}) };
  });
}

/** One row per source looked at; a later report about the same source replaces the earlier one. */
export function chatSources(steps: ChatProgress[]): SourceRow[] {
  const rows = new Map<string, SourceRow>();
  for (const s of steps) {
    if (s.stage !== 'source' || !s.source || typeof s.source !== 'object') continue;
    const src = s.source as SourceRow;
    rows.set(`${src.name}|${src.url ?? ''}`, { name: String(src.name ?? s.label), url: src.url ?? null, state: String(src.state ?? ''), reason: src.reason ?? null });
  }
  return [...rows.values()];
}

const SOURCE_STATE: Record<string, string> = {
  used: 'used',
  checking: 'checking',
  skipped: 'not used',
  rejected: 'not about this company',
  unreadable: 'could not be read',
  nothing_relevant: 'nothing relevant',
  nothing_found: 'nothing found',
  unavailable: 'unavailable',
  not_configured: 'not configured',
};

export function OrbitLoader({ size = 52, className }: { size?: number; className?: string }) {
  return (
    <span className={cn('cg-orbit', className)} style={{ width: size, height: size }} aria-hidden data-testid="chat-orbit">
      <span className="cg-orbit__globe">
        <i className="cg-orbit__meridian" />
        <i className="cg-orbit__meridian cg-orbit__meridian--b" />
      </span>
      <span className="cg-orbit__tilt">
        <span className="cg-orbit__ring cg-orbit__ring--a">
          <i className="cg-orbit__moon" />
        </span>
      </span>
      <span className="cg-orbit__tilt cg-orbit__tilt--b">
        <span className="cg-orbit__ring cg-orbit__ring--b">
          <i className="cg-orbit__moon cg-orbit__moon--b" />
        </span>
      </span>
    </span>
  );
}

export function ChatLoader({ steps, label }: { steps: ChatProgress[]; label?: string }) {
  const rows = chatStages(steps);
  const sources = chatSources(steps);
  const active = rows.find((r) => r.state === 'active');
  return (
    <div className="askai-msg askai-msg--bot cg-loader" role="status" aria-live="polite" aria-label={active?.label ?? label ?? 'Working on your answer'} data-testid="chat-progress">
      <OrbitLoader />
      <div className="cg-loader__body">
        <ol className="cg-loader__stages" aria-label="Progress">
          {rows.map((r) => (
            <li key={r.phase} className={cn('cg-loader__stage', `is-${r.state}`)} data-state={r.state} aria-current={r.state === 'active' ? 'step' : undefined}>
              <span className="cg-loader__mark" aria-hidden />
              <span className="cg-loader__text">
                {r.label}
                {r.state === 'done' && <span className="sr-only"> (done)</span>}
                {r.state === 'waiting' && <span className="sr-only"> (waiting)</span>}
                {r.detail && <span className="cg-loader__detail">{r.detail}</span>}
              </span>
            </li>
          ))}
        </ol>
        {sources.length > 0 && (
          <details className="cg-loader__sources">
            <summary>
              Sources checked ({sources.length}) <ChevronDown aria-hidden />
            </summary>
            <ul>
              {sources.map((s) => (
                <li key={`${s.name}|${s.url ?? ''}`} data-state={s.state}>
                  <span className="cg-loader__src">{s.url ? <a href={s.url} target="_blank" rel="noreferrer noopener">{s.name}</a> : s.name}</span>
                  <span className="cg-loader__src-state">{SOURCE_STATE[s.state] ?? s.state.replace(/_/g, ' ')}</span>
                  {s.reason && <span className="cg-loader__src-why">{s.reason}</span>}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}
