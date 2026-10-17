import { useNavigate } from 'react-router-dom';
import { useRouteHandle } from '@/app/routeHandle';
import { Columns3, X } from 'lucide-react';
import { MAX_COMPARE, useCompare } from '@/stores/ui';

/** Whether the tray is on screen: the active route opted in (`handle.compareTray`) and there is a selection. The selection itself lives in the store. */
export function useCompareTrayVisible(): boolean {
  const on = !!useRouteHandle().compareTray;
  const count = useCompare((s) => s.selected.length);
  return on && count > 0;
}

/** Floating selection tray for the comparison workflow. Routes opt in with `handle: { compareTray: true }`; everywhere else it is not rendered. */
export function CompareTray() {
  const { selected, remove, clear } = useCompare();
  const nav = useNavigate();
  const visible = useCompareTrayVisible();
  if (!visible) return null;
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
