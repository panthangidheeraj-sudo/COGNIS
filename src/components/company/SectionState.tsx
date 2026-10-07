import { Ban, CircleAlert, CircleDashed, Info, TriangleAlert } from 'lucide-react';
import type { SectionMeta, Source } from '@/types';

/** Honest banner for any section that is not fully available. */
export function SectionState({ meta, sourceIndex, action }: { meta: SectionMeta; sourceIndex?: Record<string, Source>; action?: React.ReactNode }) {
  if (meta.status === 'available' && !meta.message) return null;
  const Icon = meta.status === 'blocked' ? Ban : meta.status === 'partial' ? TriangleAlert : meta.status === 'ambiguous' ? CircleAlert : meta.status === 'pending' ? CircleDashed : Info;
  const cls = meta.status === 'blocked' ? 'state-banner--blocked' : meta.status === 'partial' || meta.status === 'ambiguous' ? 'state-banner--partial' : '';
  const searched = meta.searchedSourceIds?.map((id) => sourceIndex?.[id]?.name ?? id).filter(Boolean);
  return (
    <div className={`state-banner ${cls}`} role="status">
      <Icon aria-hidden />
      <div className="stack" style={{ gap: 2, flex: 1 }}>
        <span>
          {meta.status === 'blocked' && <strong style={{ fontWeight: 500 }}>Source access blocked. </strong>}
          {meta.message ?? 'No verified evidence found in the searched permitted sources.'}
        </span>
        {searched && searched.length > 0 && <span className="t-xs t-muted">Searched: {searched.join(', ')}</span>}
      </div>
      {action}
    </div>
  );
}
