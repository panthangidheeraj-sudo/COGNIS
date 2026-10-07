import { Link } from 'react-router-dom';
import { ArrowDownRight, ArrowUpRight, CircleAlert, Clock, History, RefreshCw, Users } from 'lucide-react';
import type { CompanyProfile, ContinueResearchAssessment } from '@/types';
import { useOpenEvidence } from '@/components/evidence/useEvidence';
import { VerificationLine } from '@/components/evidence/SourceBadge';
import { CoverageMeter } from './Coverage';
import { factChange, formatDate, formatInteger, formatMoneyCompact, formatPercent, formatRelative } from '@/utils/format';
import { cn } from '@/utils/cn';

/**
 * Five-second understanding: the facts a senior user needs first, above the
 * fold. Every tile opens its evidence. Values come straight from the profile.
 */
export function Snapshot({ profile, assessment }: { profile: CompanyProfile; assessment?: ContinueResearchAssessment }) {
  const c = profile.company;
  const ctx = c.legalName;
  const open = useOpenEvidence(profile.sourceIndex, ctx);
  const researched = c.researchState !== 'not_researched';
  const revSeries = profile.financials.series.find((s) => s.key === 'revenue');
  const rev = revSeries?.points.at(-1);
  const rev0 = revSeries?.points.at(-2);
  const growth = factChange(rev0?.fact, rev?.fact); // null across a change of reporting currency (never converted)
  const emp = profile.keyMetrics.find((k) => k.field === 'overview.employees');
  const jobs = profile.keyMetrics.find((k) => k.field === 'overview.openPositions');
  const ceo = profile.people.people.find((p) => p.role === 'CEO' && p.current);
  const ceoChanged = profile.changes.changes.some((ch) => ch.category === 'leadership' && ch.label === 'CEO' && ch.material);
  const topCat = profile.hiring.categories[0];
  const fresh = !!assessment && (assessment.staleAreas.length > 0 || assessment.changedSources.length > 0 || assessment.newFilings > 0);
  const q = profile.quality;

  return (
    <section className="snap" aria-label="Company at a glance">
      {/* Revenue */}
      {rev?.fact.value != null ? (
        <button className={cn('snap-tile', rev.fact.conflict && 'snap-tile--warn')} onClick={() => open(rev.fact)} aria-label={`Revenue ${rev.period}: ${formatMoneyCompact(rev.fact.value, rev.fact.currency)}. View evidence.`}>
          <span className="snap-label">
            Revenue <span className="snap-period">{rev.period}</span>
          </span>
          <span className="snap-value t-num">{formatMoneyCompact(rev.fact.value, rev.fact.currency)}</span>
          <span className="snap-sub">
            {growth != null ? (
              <span className={cn('snap-delta', growth >= 0 ? 'is-up' : 'is-down')}>
                {growth >= 0 ? <ArrowUpRight aria-hidden /> : <ArrowDownRight aria-hidden />}
                {formatPercent(Math.abs(growth))} vs {rev0!.period}
              </span>
            ) : (
              <span>Filed annual accounts</span>
            )}
          </span>
          {rev.fact.conflict ? (
            <span className="vline vline--warn">
              <CircleAlert aria-hidden />
              <span>Sources disagree</span>
            </span>
          ) : (
            <VerificationLine fact={rev.fact} sourceIndex={profile.sourceIndex} />
          )}
        </button>
      ) : (
        <div className="snap-tile snap-tile--missing">
          <span className="snap-label">Revenue</span>
          <span className="snap-value snap-value--na">Not available</span>
          <span className="snap-sub">{profile.financials.message ?? 'No filed annual accounts found'}</span>
        </div>
      )}

      {/* Employees */}
      {emp && emp.value != null ? (
        <button className="snap-tile" onClick={() => open(emp)} aria-label={`Employees: ${formatInteger(emp.value as number)}. View evidence.`}>
          <span className="snap-label">Employees</span>
          <span className="snap-value t-num">{formatInteger(emp.value as number)}</span>
          <span className="snap-sub">Registry · {formatDate(emp.verifiedAt)}</span>
          <VerificationLine fact={emp} sourceIndex={profile.sourceIndex} />
        </button>
      ) : (
        <div className="snap-tile snap-tile--missing">
          <span className="snap-label">Employees</span>
          <span className="snap-value snap-value--na">Not available</span>
          <span className="snap-sub">{emp?.note ?? 'Not reported in the registry'}</span>
        </div>
      )}

      {/* CEO */}
      {ceo ? (
        <button className="snap-tile" onClick={() => open(ceo.fact)} aria-label={`CEO: ${ceo.name}. View evidence.`}>
          <span className="snap-label">
            CEO
            {ceoChanged && <span className="snap-flag">Changed</span>}
          </span>
          <span className="snap-value snap-value--text truncate">{ceo.name}</span>
          <span className="snap-sub">{ceo.since ? `Since ${formatDate(ceo.since)}` : 'Registered role'}</span>
          <VerificationLine fact={ceo.fact} sourceIndex={profile.sourceIndex} />
        </button>
      ) : (
        <div className="snap-tile snap-tile--missing">
          <span className="snap-label">CEO</span>
          <span className="snap-value snap-value--na">{researched ? 'Not verified' : 'Not researched'}</span>
          <span className="snap-sub">{researched ? 'No registered CEO found' : 'Run research to verify leadership'}</span>
        </div>
      )}

      {/* Hiring */}
      {jobs && jobs.value != null ? (
        <button className="snap-tile" onClick={() => open(jobs)} aria-label={`Hiring: ${jobs.value} open positions. View evidence.`}>
          <span className="snap-label">Hiring</span>
          <span className="snap-value t-num">
            {String(jobs.value)} <span className="snap-unit">open positions</span>
          </span>
          <span className="snap-sub">{topCat ? `Mostly ${topCat.name} (${topCat.count})` : 'Verified current openings'}</span>
          <VerificationLine fact={jobs} sourceIndex={profile.sourceIndex} />
        </button>
      ) : (
        <div className="snap-tile snap-tile--missing">
          <span className="snap-label">Hiring</span>
          <span className="snap-value snap-value--na">{researched ? 'No verified openings' : 'Not researched'}</span>
          <span className="snap-sub">{researched ? 'None found in searched sources' : 'Run research to check hiring'}</span>
        </div>
      )}

      {/* Coverage */}
      <div className="snap-tile snap-tile--static snap-tile--cov">
        <span className="snap-label">Coverage</span>
        <span className="snap-cov">
          <CoverageMeter coverage={c.coverage} size="sm" />
        </span>
        <span className="snap-sub">
          <Users aria-hidden className="snap-ico" /> {q.primarySources} primary · {q.secondarySources} secondary
        </span>
        <span className={cn('vline', q.conflicts ? 'vline--warn' : '')}>
          {q.conflicts ? <CircleAlert aria-hidden /> : null}
          <span>{q.conflicts ? `${q.conflicts} potential conflict${q.conflicts === 1 ? '' : 's'}` : 'No conflicts'}</span>
        </span>
      </div>

      {/* Freshness */}
      <div className="snap-tile snap-tile--static">
        <span className="snap-label">Last researched</span>
        <span className="snap-value snap-value--text">{researched && c.lastResearchedAt ? capitalize(formatRelative(c.lastResearchedAt)) : 'Not yet'}</span>
        <span className="snap-sub">
          {researched && c.lastResearchedAt ? (
            <>
              <Clock aria-hidden className="snap-ico" /> {formatDate(c.lastResearchedAt)}
            </>
          ) : (
            'Registry data only'
          )}
        </span>
        {!researched ? (
          <Link to={`/research?org=${c.orgNumber}&autostart=1`} className="link-btn snap-link">
            Research now
          </Link>
        ) : fresh ? (
          <Link to={`/research?org=${c.orgNumber}&autostart=1`} className="link-btn snap-link" title="The backend detected newer source data">
            <RefreshCw aria-hidden /> Newer data available · Update
          </Link>
        ) : (
          <span className="vline vline--ok">
            <History aria-hidden />
            <span>{assessment ? 'No newer source data' : 'Saved research'}</span>
          </span>
        )}
      </div>
    </section>
  );
}

function capitalize(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
