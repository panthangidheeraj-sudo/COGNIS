import { useNavigate, useLocation } from 'react-router-dom';
import { Columns3, X } from 'lucide-react';
import { MAX_COMPARE, useCompare } from '@/stores/ui';

/** Floating selection tray. Appears when companies are selected for comparison. */
export function CompareTray() {
  const { selected, remove, clear } = useCompare();
  const nav = useNavigate();
  const loc = useLocation();
  if (!selected.length || loc.pathname.startsWith('/compare')) return null;
  return (
    <div className="compare-tray glass" role="region" aria-label="Companies selected for comparison">
      <span className="t-xs t-muted nowrap">
        {selected.length}/{MAX_COMPARE}
      </span>
      <div className="compare-tray-list">
        {selected.map((c) => (
          <span key={c.orgNumber} className="chip is-active" style={{ height: 30 }}>
            <span className="truncate" style={{ maxWidth: 160 }}>
              {c.legalName}
            </span>
            <button className="chip-x" onClick={() => remove(c.orgNumber)} aria-label={`Remove ${c.legalName} from comparison`}>
              <X width={12} height={12} aria-hidden />
            </button>
          </span>
        ))}
      </div>
      <button className="btn btn--ghost btn--sm" onClick={clear}>
        Clear
      </button>
      <button className="btn btn--primary btn--sm" disabled={selected.length < 2} onClick={() => nav(`/compare?orgs=${selected.map((s) => s.orgNumber).join(',')}`)} title={selected.length < 2 ? 'Select at least two companies' : undefined}>
        <Columns3 aria-hidden /> Compare
      </button>
    </div>
  );
}
