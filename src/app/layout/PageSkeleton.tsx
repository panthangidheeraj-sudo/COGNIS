import { Skeleton, LoadingRegion } from '@/components/common/Skeleton';

export function PageSkeleton() {
  return (
    <div className="page">
      <LoadingRegion label="Loading page">
        <Skeleton w={220} h={34} style={{ marginBottom: 12 }} />
        <Skeleton w={360} h={14} style={{ marginBottom: 32 }} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16 }}>
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} h={120} r={12} />
          ))}
        </div>
      </LoadingRegion>
    </div>
  );
}
