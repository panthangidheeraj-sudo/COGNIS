import type { ResearchEvent } from '@/types';
import { formatFactValue, formatTime } from '@/utils/format';
import { STAGES } from './StageTrack';

function describe(e: ResearchEvent, labels: Record<string, string>): { text: string; tone?: 'ok' | 'err' | 'muted' } | null {
  switch (e.type) {
    case 'run.started':
      return { text: 'Research started' };
    case 'stage.changed':
      return { text: `${STAGES.find((s) => s.id === e.stage)?.label ?? e.stage}`, tone: 'muted' };
    case 'step.started':
      return { text: `Checking ${e.sourceName}`, tone: 'muted' };
    case 'step.completed':
      return { text: `${labels[e.stepId] ?? 'Step'}: ${e.factCount} facts${e.message ? ` · ${e.message}` : ''}`, tone: 'ok' };
    case 'step.failed':
      return { text: e.message, tone: 'err' };
    case 'step.blocked':
      return { text: e.message, tone: 'err' };
    case 'fact.confirmed':
      return { text: `Confirmed · ${e.fact.label}: ${formatFactValue(e.fact)}` };
    case 'synthesis.completed':
      return { text: 'Synthesis complete', tone: 'ok' };
    case 'run.completed':
      return { text: e.autoSaved ? 'Saved to Library' : 'Research complete', tone: 'ok' };
    case 'run.failed':
      return { text: e.message, tone: 'err' };
    case 'run.paused':
      return { text: e.message, tone: 'err' };
    default:
      return null;
  }
}

/** Source-event timeline. Small timestamps, not raw logs. */
export function EventTimeline({ events, stepLabels }: { events: ResearchEvent[]; stepLabels: Record<string, string> }) {
  const rows = events.map((e) => ({ e, d: describe(e, stepLabels) })).filter((r) => r.d);
  if (!rows.length) return <p className="t-xs t-muted">Waiting for the first source event…</p>;
  return (
    <ol className="evtl" aria-label="Source activity" aria-live="polite">
      {rows
        .slice()
        .reverse()
        .map(({ e, d }) => (
          <li key={e.seq} className={`evtl-row evtl-row--${d!.tone ?? 'default'}`}>
            <time className="evtl-time" dateTime={e.at}>
              {formatTime(e.at)}
            </time>
            <span className="evtl-text">{d!.text}</span>
          </li>
        ))}
    </ol>
  );
}
