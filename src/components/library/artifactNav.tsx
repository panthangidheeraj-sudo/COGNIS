import { Columns3, FileText, History, Radar, Search, Table2 } from 'lucide-react';
import type { ArtifactSummary } from '@/types';

export function artifactHref(a: ArtifactSummary) {
  switch (a.type) {
    case 'data_sheet':
      return `/sheets/${a.targetId ?? a.id}`;
    case 'comparison':
      return `/compare?orgs=${a.targetId}`;
    case 'watchlist':
      return '/watchlist';
    case 'saved_search':
      return `/discover?q=${encodeURIComponent(a.targetId ?? a.title)}`;
    default:
      return `/library/${a.id}`;
  }
}

export function ArtifactIcon({ type }: { type: ArtifactSummary['type'] }) {
  const I = { company: History, report: FileText, data_sheet: Table2, comparison: Columns3, watchlist: Radar, saved_search: Search }[type];
  return <I width={16} height={16} aria-hidden style={{ color: 'var(--accent-soft)', flexShrink: 0 }} />;
}
