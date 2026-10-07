import { Ban, CircleAlert, CircleCheck, CircleDashed, CircleX, Clock, LoaderCircle, ShieldCheck } from 'lucide-react';
import type { Evidence, EvidenceState, Fact, Source, ValueStatus } from '@/types';
import { toneClass, verification, type VerificationKind } from '@/utils/status';
import { cn } from '@/utils/cn';

export const VERIFICATION_ICON: Record<VerificationKind, typeof CircleCheck> = {
  verified: ShieldCheck,
  secondary: CircleCheck,
  conflict: CircleAlert,
  unverified: CircleDashed,
  blocked: Ban,
  researching: LoaderCircle,
  not_available: CircleDashed,
  pending: CircleDashed,
  ambiguous: CircleAlert,
  failed: CircleX,
  stale: Clock,
};

type Verifiable = Pick<Fact, 'status' | 'evidenceState' | 'evidence' | 'conflict'>;

/**
 * Evidence-based verification state as a pill: icon + words, never a
 * confidence percentage. e.g. "Verified by 2 primary sources + 1 secondary source".
 */
export function VerificationBadge({ fact, sourceIndex, small, short }: { fact: Verifiable; sourceIndex: Record<string, Source>; small?: boolean; short?: boolean }) {
  const v = verification(fact, sourceIndex);
  const Icon = VERIFICATION_ICON[v.kind];
  return (
    <span className={cn('pill', toneClass(v.tone), small && 'pill--sm', 'vbadge')} title={v.label}>
      <Icon aria-hidden className={v.kind === 'researching' ? 'spin' : undefined} />
      {short ? v.short : v.label}
    </span>
  );
}

/** Inline (non-pill) verification line for cards and tables. */
export function VerificationLine({ fact, sourceIndex, className }: { fact: Verifiable; sourceIndex: Record<string, Source>; className?: string }) {
  const v = verification(fact, sourceIndex);
  const Icon = VERIFICATION_ICON[v.kind];
  return (
    <span className={cn('vline', `vline--${v.tone}`, className)} title={v.label}>
      <Icon aria-hidden />
      <span>{v.kind === 'verified' ? `Verified · ${v.short}` : v.short}</span>
    </span>
  );
}

/** Convenience for loose evidence lists (timeline events, jobs, changes). */
export function evidenceAsFact(evidence: Evidence[], state: EvidenceState = 'primary', status: ValueStatus = 'verified'): Verifiable {
  return { status, evidenceState: evidence.length ? state : 'unverified', evidence };
}

/** @deprecated kept for callers that only know the state; prefer VerificationBadge. */
export function SourceBadge({ state, count, small }: { state: EvidenceState; count: number; small?: boolean }) {
  return <VerificationBadge fact={{ status: 'verified', evidenceState: state, evidence: Array.from({ length: count }, (_, i) => ({ id: `x${i}`, sourceId: `unknown-${i}`, retrievedAt: '' })) }} sourceIndex={{}} small={small} />;
}
