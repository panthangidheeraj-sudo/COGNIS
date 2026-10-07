import { cn } from '@/utils/cn';

export function Skeleton({ w = '100%', h = 14, r, className, style }: { w?: number | string; h?: number | string; r?: number; className?: string; style?: React.CSSProperties }) {
  return <span aria-hidden className={cn('skeleton', className)} style={{ display: 'block', width: w, height: h, borderRadius: r, ...style }} />;
}

export function SkeletonText({ lines = 3 }: { lines?: number }) {
  return (
    <span style={{ display: 'grid', gap: 8 }} aria-hidden>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} w={i === lines - 1 ? '62%' : '100%'} h={12} />
      ))}
    </span>
  );
}

export function LoadingRegion({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}
