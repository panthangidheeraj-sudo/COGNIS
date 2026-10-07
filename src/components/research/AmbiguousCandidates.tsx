import { Link } from 'react-router-dom';
import { CircleAlert } from 'lucide-react';
import type { AmbiguousMatch } from '@/types';
import { BrandMark } from '@/components/common/BrandMark';
import { formatOrgNumber, formatMoneyCompact } from '@/utils/format';

/** Shown when identity cannot be established. Never silently picks a match. */
export function AmbiguousCandidates({ match, onPick }: { match: AmbiguousMatch; onPick?: (org: string) => void }) {
  return (
    <section className="ambig" aria-labelledby="ambig-h">
      <div className="notice notice--warn">
        <CircleAlert aria-hidden />
        <div className="stack" style={{ gap: 4 }}>
          <strong id="ambig-h">{match.message || 'We found possible matches, but could not establish exact-company identity.'}</strong>
          <span>“{match.query}” matches {match.candidates.length} registered companies. Choose the right one to continue — nothing has been researched yet.</span>
        </div>
      </div>
      <ul className="ambig-list">
        {match.candidates.map((c) => (
          <li key={c.orgNumber} className="ambig-item">
            <BrandMark name={c.legalName} org={c.orgNumber} size={40} />
            <div className="stack" style={{ gap: 2, flex: 1, minWidth: 0 }}>
              <strong style={{ fontWeight: 500 }}>{c.legalName}</strong>
              <span className="t-xs t-muted">
                {c.municipality} · Org <span className="t-mono">{formatOrgNumber(c.orgNumber)}</span> · {c.industry?.description}
              </span>
              <span className="t-xs t-muted">
                {c.employees != null ? `${c.employees} employees` : 'Employees not reported'} · {c.revenue ? `${formatMoneyCompact(c.revenue.value, c.revenue.currency)} (${c.revenue.period})` : 'No filed revenue'}
              </span>
            </div>
            {onPick ? (
              <button className="btn btn--sm" onClick={() => onPick(c.orgNumber)}>
                Research this one
              </button>
            ) : (
              <Link className="btn btn--sm" to={`/company/${c.orgNumber}`}>
                Open
              </Link>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
