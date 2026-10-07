import type { ResearchStep, SourceKind } from '@/types';
import { SourceIcon } from '@/components/source/SourceIcon';
import { useReducedMotion } from '@/hooks/useMediaQuery';
import { cn } from '@/utils/cn';

/**
 * Layer states come only from backend step events:
 * idle (not in plan) · queued · researching · verified · unavailable (searched, nothing found) · blocked · failed.
 */
export type LayerState = 'idle' | 'queued' | 'researching' | 'verified' | 'unavailable' | 'blocked' | 'failed';

/** Semantic evidence layers, bottom to top. */
export const LAYERS: { id: string; label: string; kinds: SourceKind[]; icon: SourceKind }[] = [
  { id: 'registry', label: 'Registry', kinds: ['registry'], icon: 'registry' },
  { id: 'financial', label: 'Financials', kinds: ['financial'], icon: 'financial' },
  { id: 'website', label: 'Company Website', kinds: ['website'], icon: 'website' },
  { id: 'people', label: 'People', kinds: ['people'], icon: 'people' },
  { id: 'jobs', label: 'Hiring', kinds: ['jobs'], icon: 'jobs' },
  { id: 'activity', label: 'Public Activity', kinds: ['activity', 'web', 'news', 'regulatory'], icon: 'activity' },
];

export function layerState(steps: ResearchStep[] | null, kinds: SourceKind[]): { state: LayerState; evidence: number } {
  if (!steps) return { state: 'idle', evidence: 0 };
  const mine = steps.filter((s) => kinds.includes(s.sourceKind) && s.status !== 'skipped');
  const evidence = mine.reduce((n, s) => n + (s.evidenceCount ?? 0), 0);
  if (!mine.length) return { state: 'idle', evidence };
  if (mine.some((s) => s.status === 'running')) return { state: 'researching', evidence };
  if (mine.some((s) => s.status === 'failed')) return { state: 'failed', evidence };
  if (mine.some((s) => s.status === 'blocked')) return { state: 'blocked', evidence };
  if (mine.every((s) => s.status === 'done')) return { state: mine.every((s) => s.outcome === 'not_available') ? 'unavailable' : 'verified', evidence };
  if (mine.some((s) => s.status === 'done')) return { state: 'researching', evidence };
  return { state: 'queued', evidence };
}

export const LAYER_STATE_LABEL: Record<LayerState, string> = {
  idle: 'Not in plan',
  queued: 'Queued',
  researching: 'Researching',
  verified: 'Verified',
  unavailable: 'Not available',
  blocked: 'Source blocked',
  failed: 'Failed',
};

/**
 * Signature COGNIS visual: evidence layers as floating glass tiles, each one
 * a named source family. A layer illuminates only when the backend reports
 * that family verified; nothing animates on a timer.
 */
export function SourceStack({ steps, running, compact }: { steps: ResearchStep[] | null; running?: boolean; compact?: boolean }) {
  const reduced = useReducedMotion();
  const states = LAYERS.map((l) => ({ ...l, ...layerState(steps, l.kinds) }));
  const planned = states.filter((s) => s.state !== 'idle');
  const settled = planned.filter((s) => s.state === 'verified' || s.state === 'unavailable').length;
  return (
    <figure className={cn('sstack', compact && 'sstack--compact', running && !reduced && 'is-running')} aria-label="Evidence layers by source family">
      <div className="sstack-scene" aria-hidden>
        {states.map((l, i) => (
          <div key={l.id} className={cn('sstack-tile', `sstack-tile--${l.state}`)} style={{ '--i': i } as React.CSSProperties}>
            <span className="sstack-tile-icon">
              <SourceIcon kind={l.icon} size={18} />
            </span>
          </div>
        ))}
        <ol className="sstack-tags">
          {states.map((l, i) => (
            <li key={l.id} className={`sstack-tag sstack-tag--${l.state}`} style={{ '--i': i } as React.CSSProperties}>
              <i />
              {l.label}
            </li>
          ))}
        </ol>
      </div>
      <figcaption>
        <ul className="sstack-legend">
          {[...states].reverse().map((l) => (
            <li key={l.id} className={`sstack-leg sstack-leg--${l.state}`}>
              <span className="sstack-leg-dot" aria-hidden />
              <span className="sstack-leg-label">{l.label}</span>
              <span className="sstack-leg-state">
                {LAYER_STATE_LABEL[l.state]}
                {l.state === 'verified' && l.evidence ? ` · ${l.evidence} evidence` : ''}
              </span>
            </li>
          ))}
        </ul>
        {steps && (
          <p className="t-xs t-muted" style={{ marginTop: 8 }}>
            {settled}/{planned.length} source families settled
          </p>
        )}
      </figcaption>
    </figure>
  );
}
