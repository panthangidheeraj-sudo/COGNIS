import { useEffect, useState } from 'react';
import { Ban, CircleAlert, CircleCheck, CircleDashed, CircleMinus, CircleSlash, CircleX, LoaderCircle } from 'lucide-react';
import type { ResearchRun, ResearchStep, ResearchStepStatus, ResearchStreamState } from '@/types';
import { SourceIcon } from '@/components/source/SourceIcon';
import { useReducedMotion } from '@/hooks/useMediaQuery';
import { cn } from '@/utils/cn';

const ICON: Record<ResearchStepStatus, typeof CircleCheck> = {
  pending: CircleDashed,
  running: LoaderCircle,
  done: CircleCheck,
  failed: CircleX,
  blocked: Ban,
  skipped: CircleMinus,
  cancelled: CircleSlash,
};

/** What the person sees for a step. "Succeeded" is a source that answered; one that answered with nothing verifiable says so. */
export function stepStateLabel(step: ResearchStep): string {
  switch (step.status) {
    case 'pending':
      return 'Pending';
    case 'running':
      return 'Running';
    case 'done':
      return step.outcome === 'not_available' ? 'Succeeded · no data' : 'Succeeded';
    case 'failed':
      return 'Failed';
    case 'blocked':
      return 'Blocked';
    case 'skipped':
      return 'Skipped';
    case 'cancelled':
      return 'Stopped';
  }
}

export function formatElapsed(ms: number): string {
  const s = Math.max(0, ms) / 1000;
  if (s < 10) return `${s.toFixed(1)} s`;
  if (s < 60) return `${Math.round(s)} s`;
  return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

/** Elapsed time for a step, from backend values only: the reported duration once it finished, the time since the backend started it while it runs. */
export function stepElapsedMs(step: ResearchStep, now: number): number | undefined {
  if (step.status === 'running') return step.startedAt ? Math.max(0, now - Date.parse(step.startedAt)) : undefined;
  if (step.durationMs) return step.durationMs;
  if (step.startedAt && step.finishedAt) return Math.max(0, Date.parse(step.finishedAt) - Date.parse(step.startedAt));
  return undefined;
}

export function countSteps(steps: ResearchStep[]): Record<ResearchStepStatus, number> {
  const out: Record<ResearchStepStatus, number> = { pending: 0, running: 0, done: 0, failed: 0, blocked: 0, skipped: 0, cancelled: 0 };
  for (const s of steps) out[s.status] += 1;
  return out;
}

/** One line on how the run as a whole stands, from the run status and what the stream is doing — never from a timer. */
export function runStateLine(run: ResearchRun, connection: ResearchStreamState['connection'], error?: string): { tone: 'info' | 'ok' | 'warn' | 'err' | 'neutral'; text: string } {
  const c = countSteps(run.plan.steps);
  const settled = run.plan.steps.length - c.pending - c.running;
  switch (run.status) {
    case 'cancelled':
      return { tone: 'neutral', text: 'Cancelled — running sources were stopped and the rest were not started.' };
    case 'failed':
      return { tone: 'err', text: error ?? 'The research run failed.' };
    case 'completed':
      if (run.summary?.effort?.timedOut) return { tone: 'warn', text: 'Time limit reached — sources that had not finished were not used.' };
      if (run.outcome === 'partial' || c.failed + c.blocked > 0) return { tone: 'warn', text: `Finished with gaps — ${c.failed + c.blocked} source${c.failed + c.blocked === 1 ? '' : 's'} could not be read.` };
      return { tone: 'ok', text: 'Finished — every planned source reported.' };
    case 'running':
      if (connection === 'reconnecting') return { tone: 'warn', text: 'Connection to the research stream was interrupted — reconnecting. The sources below show the last state received.' };
      if (connection === 'error') return { tone: 'err', text: 'Lost the research stream. The sources below show the last state received.' };
      if (run.plan.steps.length && c.running === 0 && settled === 0) return { tone: 'info', text: 'Starting — waiting for the first source to report.' };
      return { tone: 'info', text: `Researching — ${settled} of ${run.plan.steps.length} sources reported.` };
    default:
      return { tone: 'neutral', text: '' };
  }
}

/** Re-renders every second while `active`, so elapsed times of running sources keep moving; nothing else ticks. */
function useNow(active: boolean, override?: number): number {
  const [now, setNow] = useState(() => override ?? Date.now());
  useEffect(() => {
    if (override != null) return;
    if (!active) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active, override]);
  return override ?? now;
}

/**
 * Per-source activity for a research run. Every row is a planned step and every state, time and message on it came from a backend event:
 * a source is "Running" only between its step.started and its end event, and pending sources are not animated.
 */
export function SourceActivity({ run, connection, error, now: nowOverride }: { run: ResearchRun; connection: ResearchStreamState['connection']; error?: string; now?: number }) {
  const reduced = useReducedMotion();
  const steps = run.plan.steps;
  const running = steps.some((s) => s.status === 'running');
  const now = useNow(running, nowOverride);
  const counts = countSteps(steps);
  const line = runStateLine(run, connection, error);
  const summary = [
    counts.done && `${counts.done} succeeded`,
    counts.running && `${counts.running} running`,
    counts.failed && `${counts.failed} failed`,
    counts.blocked && `${counts.blocked} blocked`,
    counts.skipped && `${counts.skipped} skipped`,
    counts.cancelled && `${counts.cancelled} stopped`,
    counts.pending && `${counts.pending} pending`,
  ].filter(Boolean) as string[];

  return (
    <div className="sact" data-testid="source-activity">
      {line.text && (
        <p className={cn('sact-line', `sact-line--${line.tone}`)} role="status" data-testid="source-activity-state">
          {line.tone === 'warn' || line.tone === 'err' ? <CircleAlert aria-hidden /> : null}
          {line.text}
        </p>
      )}
      {summary.length > 0 && (
        <p className="t-xs t-muted sact-counts" aria-live="polite" data-testid="source-activity-counts">
          {summary.join(' · ')}
        </p>
      )}
      <ol className="sact-list" aria-label="Sources in this research run">
        {steps.map((s) => {
          const Icon = ICON[s.status];
          const ms = stepElapsedMs(s, now);
          const detailLine = s.status === 'running' ? s.detail : s.message;
          return (
            <li key={s.id} className={cn('sact-row', `sact-row--${s.status}`)} data-status={s.status} data-testid={`source-row-${s.key}`}>
              <Icon aria-hidden className={cn('sact-icon', s.status === 'running' && !reduced && 'is-spinning')} />
              <div className="sact-body">
                <div className="sact-top">
                  <SourceIcon kind={s.sourceKind} size={13} />
                  <span className="sact-name">{s.sourceName ?? s.label}</span>
                  <span className={cn('sact-state', `sact-state--${s.status}`)}>{stepStateLabel(s)}</span>
                </div>
                {s.sourceName && s.sourceName !== s.label && <span className="t-xs t-muted">{s.label}</span>}
                <div className="t-xs t-muted t-num sact-meta">
                  {s.status === 'done' && (
                    <span>
                      {s.factCount ?? 0} facts · {s.evidenceCount ?? 0} evidence
                    </span>
                  )}
                  {ms != null && (s.status === 'running' || s.status === 'done' || s.status === 'failed' || s.status === 'blocked') && (
                    <span data-testid={`elapsed-${s.key}`}>{s.status === 'running' ? `running ${formatElapsed(ms)}` : formatElapsed(ms)}</span>
                  )}
                </div>
                {detailLine && <span className={cn('t-xs', s.status === 'failed' || s.status === 'blocked' ? 't-err' : 't-muted')}>{detailLine}</span>}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
