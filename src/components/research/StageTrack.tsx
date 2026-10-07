import { Check } from 'lucide-react';
import type { ResearchStage } from '@/types';
import { cn } from '@/utils/cn';

export const STAGES: { id: ResearchStage; label: string }[] = [
  { id: 'discover', label: 'Discover' },
  { id: 'identify', label: 'Identify' },
  { id: 'gather', label: 'Gather' },
  { id: 'verify', label: 'Verify' },
  { id: 'reconcile', label: 'Reconcile' },
  { id: 'synthesize', label: 'Synthesize' },
  { id: 'save', label: 'Save' },
];

/** Pipeline position as reported by backend `stage.changed` events. */
export function StageTrack({ stage, done }: { stage?: ResearchStage; done?: boolean }) {
  const idx = stage ? STAGES.findIndex((s) => s.id === stage) : -1;
  return (
    <ol className="stages" aria-label="Research pipeline">
      {STAGES.map((s, i) => {
        const state = done || i < idx ? 'done' : i === idx ? 'active' : 'pending';
        return (
          <li key={s.id} className={cn('stage', `stage--${state}`)} aria-current={state === 'active' ? 'step' : undefined}>
            <span className="stage-dot" aria-hidden>
              {state === 'done' && <Check width={10} height={10} strokeWidth={3} />}
            </span>
            <span className="stage-label">{s.label}</span>
            <span className="sr-only">{state === 'done' ? '(done)' : state === 'active' ? '(in progress)' : '(waiting)'}</span>
          </li>
        );
      })}
    </ol>
  );
}
