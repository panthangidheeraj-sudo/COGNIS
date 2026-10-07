import { useRef, useState } from 'react';
import { ArrowRight, CircleAlert } from 'lucide-react';
import type { Fact, Source } from '@/types';
import { formatDate, formatFactValue } from '@/utils/format';
import { Popover } from '@/components/common/Popover';
import { VerificationBadge } from './SourceBadge';
import { FreshnessLine } from './Freshness';
import { useOpenEvidence } from './useEvidence';
import { VALUE_STATUS } from '@/utils/status';
import { cn } from '@/utils/cn';

/**
 * Inline fact: value + tiny source-count marker. Click → compact evidence
 * popover → "View evidence" opens the full drawer. Unavailable facts say so.
 */
export function FactValue({ fact, sourceIndex, context, showFreshness, exact, className }: { fact: Fact; sourceIndex: Record<string, Source>; context?: string; showFreshness?: boolean; exact?: boolean; className?: string }) {
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const openDrawer = useOpenEvidence(sourceIndex, context);
  if (fact.value == null || fact.status !== 'verified') {
    return (
      <span className={cn('fact fact--missing', className)} title={fact.note}>
        {fact.note ?? VALUE_STATUS[fact.status].label}
      </span>
    );
  }
  const sources = new Set(fact.evidence.map((e) => e.sourceId));
  const first = fact.evidence[0];
  return (
    <span className={cn('fact', className)} data-fact-id={fact.id}>
      <button ref={btn} className={cn('fact-btn', fact.conflict && 'fact-btn--conflict')} onClick={() => setOpen((o) => !o)} aria-haspopup="dialog" aria-expanded={open}>
        <span className="t-num">{formatFactValue(fact, { exact })}</span>
        <sup className="fact-count" aria-label={`${sources.size} source${sources.size === 1 ? '' : 's'}`}>
          {fact.conflict ? <CircleAlert width={11} height={11} aria-hidden /> : sources.size}
        </sup>
      </button>
      {showFreshness && <FreshnessLine fact={fact} />}
      <Popover anchor={btn.current} open={open} onClose={() => setOpen(false)} label={`Evidence for ${fact.label}`}>
        <div className="stack" style={{ gap: 10 }}>
          <span className="t-micro">{fact.label}</span>
          <div className="t-num" style={{ fontSize: 18, fontWeight: 500 }}>
            {formatFactValue(fact, { exact: true })}
          </div>
          <VerificationBadge fact={fact} sourceIndex={sourceIndex} small />
          <dl className="kv" style={{ gridTemplateColumns: '92px 1fr', fontSize: 12.5 }}>
            <dt>Source</dt>
            <dd>
              {first ? (sourceIndex[first.sourceId]?.name ?? first.sourceId) : '—'}
              {sources.size > 1 ? ` +${sources.size - 1}` : ''}
            </dd>
            {fact.reportingPeriod && (
              <>
                <dt>Period</dt>
                <dd>{fact.reportingPeriod}</dd>
              </>
            )}
            <dt>{fact.verifiedAt ? 'Verified' : 'Retrieved'}</dt>
            <dd>{fact.verifiedAt ? formatDate(fact.verifiedAt) : first ? formatDate(first.retrievedAt) : '—'}</dd>
          </dl>
          <button
            className="btn btn--sm"
            onClick={() => {
              setOpen(false);
              openDrawer(fact);
            }}
          >
            View evidence <ArrowRight aria-hidden />
          </button>
        </div>
      </Popover>
    </span>
  );
}
