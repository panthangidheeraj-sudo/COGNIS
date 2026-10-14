import { CircleAlert, CircleCheck, CircleMinus, CircleX } from 'lucide-react';
import type { EffortWorkflow, ResearchEffort } from '@/types';
import { cn } from '@/utils/cn';

const ICON = { ran: CircleCheck, skipped: CircleMinus, failed: CircleX } as const;
const LABEL = { ran: 'Ran', skipped: 'Not run', failed: 'Failed' } as const;

/** One sentence on what happened to the saved report. Earlier versions are never replaced, and the text says so. */
export function reportNote(report: { newVersion: boolean; factsChanged?: boolean | null }): string {
  if (!report.newVersion) return 'Same evidence as an existing report version, so no new version was created. This run is recorded in the run history.';
  if (report.factsChanged === false) return 'This run found the same facts as the previous report. It was saved as a new version; earlier versions are kept.';
  return 'Saved as a new report version. Earlier versions are kept in the research history.';
}

function Row({ w }: { w: EffortWorkflow }) {
  const Icon = ICON[w.status];
  return (
    <li className={cn('effort-row', `effort-row--${w.status}`)} data-testid={`effort-${w.key}`} data-status={w.status}>
      <Icon aria-hidden />
      <div className="stack" style={{ gap: 1, minWidth: 0 }}>
        <span className="effort-label">
          {w.label} <span className="effort-state">{LABEL[w.status]}</span>
        </span>
        <span className="t-xs t-muted">{w.detail}</span>
      </div>
    </li>
  );
}

/**
 * What a run did beyond the core registers, and why each optional workflow did or did not run. Quick runs list the Deep workflows they skip, so two
 * runs of the same company can be compared honestly. Nothing here promises more facts: it shows effort and what cross-checking found.
 */
export function EffortSummary({ effort, title = 'What this run did', open }: { effort: ResearchEffort; title?: string; open?: boolean }) {
  const cc = effort.crosscheck;
  return (
    <details className="effort" open={open} data-testid="effort-summary">
      <summary>
        <strong>{title}</strong>
        <span className="t-xs t-muted t-num">
          {effort.mode === 'deep' ? 'Deep' : 'Quick'} · {effort.pagesRead} website page{effort.pagesRead === 1 ? '' : 's'} read · {effort.requests} request{effort.requests === 1 ? '' : 's'}
          {effort.llmCalls ? ` · ${effort.llmCalls} AI call${effort.llmCalls === 1 ? '' : 's'}` : ''}
        </span>
      </summary>
      <ul className="effort-list">
        {effort.workflows.map((w) => (
          <Row key={w.key} w={w} />
        ))}
      </ul>
      {cc && cc.checked > 0 && (
        <div className="effort-cc" data-testid="effort-crosscheck">
          <strong className="t-sm">Cross-source check</strong>
          <p className="t-xs t-muted">
            {cc.corroborated} of {cc.checked} published facts are confirmed by two or more independent sources · {cc.singleSource} rest on a single source · {cc.conflicts}{' '}
            disagreement{cc.conflicts === 1 ? '' : 's'}.
          </p>
          {cc.conflictFacts && cc.conflictFacts.length > 0 && (
            <ul className="effort-conflicts">
              {cc.conflictFacts.map((c) => (
                <li key={c.field} className="t-xs">
                  <CircleAlert aria-hidden width={12} height={12} /> <strong>{c.label}</strong>: {c.candidates.map((x) => `${x.value}${x.source ? ` (${x.source})` : ''}`).join(' vs ')}
                  {c.reason ? ` — ${c.reason}` : ''}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <p className="t-xs t-muted effort-note">A deeper run is not guaranteed to find more facts. It shows the extra checks it made; when the evidence does not support more, the report does not grow.</p>
    </details>
  );
}
