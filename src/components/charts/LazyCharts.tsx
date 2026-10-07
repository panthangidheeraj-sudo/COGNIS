import { lazy, Suspense } from 'react';
import { Skeleton } from '@/components/common/Skeleton';
import { ErrorBoundary } from '@/components/common/ErrorState';
import type { FinancialChartProps } from './FinancialChart';

const FinancialChartImpl = lazy(() => import('./FinancialChart'));
const SimpleBarChartImpl = lazy(() => import('./SimpleBarChart'));
const CompareChartImpl = lazy(() => import('./CompareChart'));
const LandscapeChartImpl = lazy(() => import('./LandscapeChart'));

export function ChartSkeleton({ height = 260 }: { height?: number }) {
  return <Skeleton h={height} r={10} />;
}

/** Charts are code-split and wrapped so a broken chart can't break the page. */
export function FinancialChart(props: FinancialChartProps) {
  return (
    <ErrorBoundary label="Chart">
      <Suspense fallback={<ChartSkeleton height={props.height} />}>
        <FinancialChartImpl {...props} />
      </Suspense>
    </ErrorBoundary>
  );
}
export function SimpleBarChart(props: React.ComponentProps<typeof SimpleBarChartImpl>) {
  return (
    <ErrorBoundary label="Chart">
      <Suspense fallback={<ChartSkeleton height={props.height ?? 180} />}>
        <SimpleBarChartImpl {...props} />
      </Suspense>
    </ErrorBoundary>
  );
}
export function CompareChart(props: React.ComponentProps<typeof CompareChartImpl>) {
  return (
    <ErrorBoundary label="Chart">
      <Suspense fallback={<ChartSkeleton height={props.height ?? 280} />}>
        <CompareChartImpl {...props} />
      </Suspense>
    </ErrorBoundary>
  );
}
export function LandscapeChart(props: React.ComponentProps<typeof LandscapeChartImpl>) {
  return (
    <ErrorBoundary label="Landscape">
      <Suspense fallback={<ChartSkeleton height={420} />}>
        <LandscapeChartImpl {...props} />
      </Suspense>
    </ErrorBoundary>
  );
}
