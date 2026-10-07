import { Ban, CircleAlert, CircleCheck, CircleDashed, CircleX, LoaderCircle, TriangleAlert, Clock } from 'lucide-react';
import type { ValueStatus } from '@/types';
import { VALUE_STATUS, type Tone, toneClass } from '@/utils/status';
import { cn } from '@/utils/cn';

const ICON: Record<ValueStatus, typeof CircleCheck> = {
  verified: CircleCheck,
  researching: LoaderCircle,
  pending: CircleDashed,
  not_available: CircleDashed,
  ambiguous: CircleAlert,
  blocked: Ban,
  failed: CircleX,
  stale: Clock,
};

/** Icon + text status. Never color-only. */
export function StatusMark({ status, label, className }: { status: ValueStatus; label?: string; className?: string }) {
  const Icon = ICON[status];
  return (
    <span className={cn('status-mark', `status-mark--${status}`, className)} role="status">
      <Icon aria-hidden />
      <span>{label ?? VALUE_STATUS[status].label}</span>
    </span>
  );
}

export function Pill({ tone = 'neutral', children, icon, small, className, title }: { tone?: Tone; children: React.ReactNode; icon?: React.ReactNode; small?: boolean; className?: string; title?: string }) {
  return (
    <span className={cn('pill', toneClass(tone), small && 'pill--sm', className)} title={title}>
      {icon}
      {children}
    </span>
  );
}

export function DotPill({ tone = 'neutral', children, small }: { tone?: Tone; children: React.ReactNode; small?: boolean }) {
  return (
    <span className={cn('pill', toneClass(tone), small && 'pill--sm')}>
      <span className="pill-dot" aria-hidden />
      {children}
    </span>
  );
}

export { TriangleAlert };
