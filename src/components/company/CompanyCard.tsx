import { Link } from 'react-router-dom';
import { Check, Plus } from 'lucide-react';
import type { CompanySummary } from '@/types';
import { BrandMark } from '@/components/common/BrandMark';
import { CoverageMeter } from './Coverage';
import { MAX_COMPARE, useCompare } from '@/stores/ui';
import { formatDate, formatInteger, formatMoneyCompact, formatOrgNumber } from '@/utils/format';
import { COMPANY_STATUS_TONE, toneClass } from '@/utils/status';
import { cn } from '@/utils/cn';

export function ResearchStateLabel({ c }: { c: CompanySummary }) {
  if (c.researchState === 'not_researched') return <span className="t-xs t-muted">Not researched yet</span>;
  if (c.researchState === 'researching') return <span className="t-xs t-accent">Researching…</span>;
  return <span className="t-xs t-muted">Research updated {formatDate(c.lastResearchedAt)}</span>;
}

export function CompareToggle({ c, small }: { c: CompanySummary; small?: boolean }) {
  const { selected, toggle } = useCompare();
  const on = selected.some((s) => s.orgNumber === c.orgNumber);
  const full = !on && selected.length >= MAX_COMPARE;
  return (
    <button
      className={cn('btn btn--sm', on && 'is-selected', !small && 'cmp-toggle')}
      aria-pressed={on}
      disabled={full}
      title={full ? `Up to ${MAX_COMPARE} companies` : undefined}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        toggle(c);
      }}
    >
      {on ? <Check aria-hidden /> : <Plus aria-hidden />}
      {small ? <span className="sr-only">Compare</span> : 'Compare'}
    </button>
  );
}

/** Discovery result card: identity, 1–2 key metrics, coverage, research state. */
export function CompanyCard({ c }: { c: CompanySummary }) {
  const selected = useCompare((s) => s.selected.some((x) => x.orgNumber === c.orgNumber));
  return (
    <article className={cn('co-card', selected && 'co-card--selected')}>
      <Link to={`/company/${c.orgNumber}`} className="co-card-link" aria-label={`${c.legalName}, ${c.municipality}. Open research.`} />
      <div className="row" style={{ gap: 12, alignItems: 'flex-start' }}>
        <BrandMark name={c.legalName} org={c.orgNumber} logoUrl={c.logoUrl} size={42} />
        <div className="stack" style={{ gap: 2, minWidth: 0, flex: 1 }}>
          <h3 className="co-card-name truncate">{c.legalName}</h3>
          <span className="t-xs t-muted truncate">
            {c.municipality}, Norway · Org <span className="t-mono">{formatOrgNumber(c.orgNumber)}</span>
          </span>
          <span className="t-xs t-soft truncate">{c.industry?.description ?? 'Industry not registered'}</span>
          {c.website && <span className="t-xs t-mono t-muted truncate co-card-web">{c.website}</span>}
        </div>
        {c.status !== 'active' && <span className={`pill pill--sm ${toneClass(COMPANY_STATUS_TONE[c.status])}`}>{c.statusLabel}</span>}
      </div>
      <dl className="co-card-metrics">
        <div>
          <dt>Revenue</dt>
          <dd className="t-num">{c.revenue ? formatMoneyCompact(c.revenue.value, c.revenue.currency) : <span className="co-card-na">Not available</span>}</dd>
          {c.revenue && <span className="freshness">{c.revenue.period}</span>}
        </div>
        <div>
          <dt>Employees</dt>
          <dd className="t-num">{c.employees != null ? formatInteger(c.employees) : <span className="co-card-na">Not available</span>}</dd>
        </div>
        <div>
          <dt>Openings</dt>
          <dd className="t-num">{c.openPositions != null ? c.openPositions : <span className="co-card-na" title="No verified hiring data">Not available</span>}</dd>
        </div>
      </dl>
      <div className="co-card-foot">
        <div className="stack" style={{ gap: 4 }}>
          <CoverageMeter coverage={c.coverage} size="sm" />
          <ResearchStateLabel c={c} />
        </div>
        <span className="spacer" />
        <CompareToggle c={c} />
      </div>
    </article>
  );
}
