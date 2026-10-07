import { Activity, Banknote, Briefcase, Globe, Landmark, Newspaper, Scale, Search, UsersRound } from 'lucide-react';
import type { SourceKind } from '@/types';

const MAP: Record<SourceKind, typeof Globe> = {
  registry: Landmark,
  financial: Banknote,
  website: Globe,
  people: UsersRound,
  jobs: Briefcase,
  activity: Activity,
  web: Search,
  news: Newspaper,
  regulatory: Scale,
};

export function SourceIcon({ kind, size = 15 }: { kind: SourceKind; size?: number }) {
  const I = MAP[kind] ?? Globe;
  return <I width={size} height={size} aria-hidden />;
}
