import type { Fact } from '@/types';
import { formatDate, formatDateTime, formatRelative } from '@/utils/format';

/** Fact-level freshness: "FY2025 · Verified 03 Oct 2026" / "Current · Verified today". */
export function FreshnessLine({ fact, className }: { fact: Pick<Fact, 'reportingPeriod' | 'freshness' | 'verifiedAt' | 'status'>; className?: string }) {
  if (fact.status !== 'verified' || !fact.verifiedAt) return null;
  const lead = fact.reportingPeriod ?? (fact.freshness === 'historical' ? 'Historical' : 'Current');
  const rel = formatRelative(fact.verifiedAt);
  const when = rel === 'today' || rel === 'yesterday' || rel.endsWith('ago') ? rel : formatDate(fact.verifiedAt);
  return (
    <span className={`freshness ${className ?? ''}`} title={`Verified ${formatDateTime(fact.verifiedAt)}`}>
      {lead} · Verified {when}
    </span>
  );
}
