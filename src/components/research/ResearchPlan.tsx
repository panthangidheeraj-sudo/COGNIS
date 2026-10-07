import { Ban, CircleCheck, CircleDashed, CircleX, LoaderCircle, Plus, X } from 'lucide-react';
import type { ResearchPlan as Plan, ResearchStep } from '@/types';
import { SourceIcon } from '@/components/source/SourceIcon';
import { STEP_STATUS } from '@/utils/status';
import { cn } from '@/utils/cn';

const ICON = { pending: CircleDashed, running: LoaderCircle, done: CircleCheck, failed: CircleX, blocked: Ban, skipped: CircleDashed };

export function StepRow({ step }: { step: ResearchStep }) {
  const Icon = ICON[step.status];
  return (
    <li className={cn('step', `step--${step.status}`)}>
      <Icon aria-hidden className="step-icon" />
      <div className="stack" style={{ gap: 2, minWidth: 0, flex: 1 }}>
        <span className="row" style={{ gap: 8 }}>
          <span className="step-label">{step.label}</span>
          {step.optional && step.status === 'pending' && <span className="t-xs t-muted">optional</span>}
        </span>
        {step.sourceName && <span className="t-xs t-muted truncate">{step.sourceName}</span>}
        {step.status === 'done' && (
          <span className="t-xs t-muted t-num">
            {step.factCount ?? 0} facts · {step.evidenceCount ?? 0} evidence{step.durationMs ? ` · ${(step.durationMs / 1000).toFixed(1)}s` : ''}
          </span>
        )}
        {step.message && <span className={cn('t-xs', step.status === 'failed' || step.status === 'blocked' ? 't-err' : 't-muted')}>{step.message}</span>}
      </div>
      <span className="sr-only">{STEP_STATUS[step.status].label}</span>
    </li>
  );
}

/** Live plan: statuses come only from backend events. */
export function ResearchPlanView({ plan }: { plan: Plan }) {
  return (
    <ol className="steps" aria-label="Research plan" aria-live="polite">
      {plan.steps.map((s) => (
        <StepRow key={s.id} step={s} />
      ))}
    </ol>
  );
}

/** Editable plan before a run starts (when the backend asks for confirmation). */
export function PlanEditor({ plan, keys, setKeys, onStart, busy }: { plan: Plan; keys: string[]; setKeys: (k: string[]) => void; onStart: () => void; busy: boolean }) {
  const all = [...plan.steps.map((s) => ({ key: s.key, label: s.label, sourceKind: s.sourceKind, optional: s.optional })), ...plan.availableSteps.map((s) => ({ ...s, optional: true }))];
  const active = all.filter((s) => keys.includes(s.key));
  const addable = all.filter((s) => !keys.includes(s.key));
  return (
    <div className="stack" style={{ gap: 14 }}>
      <ol className="steps steps--edit">
        {active.map((s) => (
          <li key={s.key} className="step">
            <SourceIcon kind={s.sourceKind} />
            <span className="step-label" style={{ flex: 1 }}>
              {s.label}
            </span>
            {s.optional ? (
              <button className="btn btn--ghost btn--icon btn--sm" onClick={() => setKeys(keys.filter((k) => k !== s.key))} aria-label={`Remove step ${s.label}`}>
                <X aria-hidden />
              </button>
            ) : (
              <span className="t-xs t-muted">required</span>
            )}
          </li>
        ))}
      </ol>
      {addable.length > 0 && (
        <div className="row-wrap">
          <span className="t-xs t-muted">Add step</span>
          {addable.map((s) => (
            <button key={s.key} className="chip" style={{ height: 28 }} onClick={() => setKeys([...keys, s.key])}>
              <Plus aria-hidden /> {s.label}
            </button>
          ))}
        </div>
      )}
      <div>
        <button className="btn btn--primary btn--lg" onClick={onStart} disabled={busy}>
          {busy ? 'Starting…' : 'Start research'}
        </button>
      </div>
    </div>
  );
}
