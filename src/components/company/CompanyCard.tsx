import { Link } from 'react-router-dom';
import { Check, Globe, Plus } from 'lucide-react';
import type { CompanyEnrichment, CompanySummary } from '@/types';
import { BrandMark } from '@/components/common/BrandMark';
import { CoverageMeter } from './Coverage';
import { FigureValue, figureView } from './CompanyFigure';
import { MAX_COMPARE, useCompare } from '@/stores/ui';
import { formatDate, formatOrgNumber } from '@/utils/format';
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

/**
 * Discovery result card, set editorially: a quiet place/org kicker, the company name as the headline,
 * the industry as a standfirst, the website domain, then three key figures and the research state.
 * A figure without a verified value says why (see CompanyFigure); `lookup` carries what a Discover lookup established, `checking` that one is running.
 */
export function CompanyCard({ c, lookup, checking = false }: { c: CompanySummary; lookup?: CompanyEnrichment; checking?: boolean }) {
  const selected = useCompare((s) => s.selected.some((x) => x.orgNumber === c.orgNumber));
  const revenue = figureView('revenue', c, lookup, checking);
  const employees = figureView('employees', c, lookup, checking);
  const openings = figureView('openPositions', c, lookup, checking);
  return (
    <article className={cn('co-card', selected && 'co-card--selected', c.researchState === 'not_researched' && 'co-card--registry')}>
      <Link to={`/company/${c.orgNumber}`} className="co-card-link" aria-label={`${c.legalName}, ${c.municipality}. Open research.`} />
      <div className="co-card-head">
        <BrandMark name={c.legalName} org={c.orgNumber} logoUrl={c.logoUrl} size={40} />
        <div className="co-card-id">
          <span className="co-card-kicker truncate">
            {c.municipality}, Norway · Org <span className="t-mono">{formatOrgNumber(c.orgNumber)}</span>
          </span>
          <h3 className="co-card-name">{c.legalName}</h3>
          <span className="co-card-industry truncate">{c.industry?.description ?? 'Industry not registered'}</span>
          {c.website && (
            <span className="co-card-web truncate">
              <Globe aria-hidden />
              {c.website}
            </span>
          )}
        </div>
        {c.status !== 'active' && <span className={`pill pill--sm ${toneClass(COMPANY_STATUS_TONE[c.status])}`}>{c.statusLabel}</span>}
      </div>
      <dl className="co-card-metrics">
        <div>
          <dt>Revenue</dt>
          <dd className="t-num">
            <FigureValue view={revenue} />
          </dd>
          {revenue.detail && <span className="freshness">{revenue.detail}</span>}
        </div>
        <div>
          <dt>Employees</dt>
          <dd className="t-num">
            <FigureValue view={employees} />
          </dd>
        </div>
        <div>
          <dt>Openings</dt>
          <dd className="t-num">
            <FigureValue view={openings} />
          </dd>
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
