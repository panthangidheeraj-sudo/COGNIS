import { CircleAlert } from 'lucide-react';
import type { Fact, Source } from '@/types';
import { formatFactValue, formatUnitLabel } from '@/utils/format';
import { FreshnessLine } from './Freshness';
import { VerificationLine } from './SourceBadge';
import { useOpenEvidence } from './useEvidence';
import { cn } from '@/utils/cn';

/** Key metric. Click opens the evidence drawer. Unknown values stay visibly unknown. */
export function MetricCard({ fact, sourceIndex, context, label, sub }: { fact: Fact; sourceIndex: Record<string, Source>; context?: string; label?: string; sub?: string }) {
  const open = useOpenEvidence(sourceIndex, context);
  const missing = fact.value == null || fact.status !== 'verified';
  return (
    <button className={cn('metric', missing && 'metric--missing', fact.conflict && 'metric--conflict')} onClick={() => open(fact)} aria-label={`${label ?? fact.label}: ${missing ? 'not available' : formatFactValue(fact, { exact: true })}. View evidence.`}>
      <span className="metric-label">
        {label ?? fact.label}
        {fact.conflict && <CircleAlert aria-hidden className="metric-warn" />}
      </span>
      <span className="metric-value t-num">{missing ? 'Not available' : formatFactValue(fact)}</span>
      <span className="metric-meta">
        {missing ? (fact.note ?? 'No verified evidence found') : <FreshnessLine fact={fact} />}
        {!missing && sub && <span>{sub}</span>}
      </span>
      {!missing && (
        <span className="metric-src">
          <VerificationLine fact={fact} sourceIndex={sourceIndex} />
          {formatUnitLabel(fact.unit) && <span className="metric-unit">{formatUnitLabel(fact.unit)}</span>}
        </span>
      )}
    </button>
  );
}
