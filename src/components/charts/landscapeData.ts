/**
 * What the company landscape can plot — kept out of the (lazy, recharts) chart module so the page can decide between the chart and an
 * explanation without loading the chart. Only verified values are plotted; nothing is filled in, estimated or converted.
 */
import type { CompanySummary } from '@/types';

export type LandscapeMetric = 'revenue' | 'employees' | 'openPositions';

export const METRIC_LABEL = (currency: string): Record<LandscapeMetric, string> => ({
  revenue: `Revenue (${currency || 'as filed'}, latest FY)`,
  employees: 'Employees (registry)',
  openPositions: 'Open positions (verified)',
});

export const METRIC_NAME: Record<LandscapeMetric, string> = { revenue: 'Revenue', employees: 'Employees', openPositions: 'Open positions' };

/** Where a verified value of each metric comes from, and why a company may have none (shown when the chart cannot be drawn). */
export const METRIC_SOURCE: Record<LandscapeMetric, string> = {
  revenue:
    'Revenue comes from filed annual accounts (Regnskapsregisteret). Companies that file no accounts, or file in another currency than the chart, are not plotted — amounts are never converted.',
  employees: 'Employees come from the employee count registered in Enhetsregisteret. Companies with no registered count are not plotted (that is not zero).',
  openPositions:
    'Open positions are counted only when a NAV ad or the company’s own careers page is verified for that organisation. Companies with no verified opening are not plotted — that is not the same as zero.',
};

/** The most common filing currency (NOK first on a tie): revenue is only plotted in one currency. */
export function chartCurrency(companies: CompanySummary[]): string {
  const counts = new Map<string, number>();
  for (const c of companies) if (c.revenue?.currency) counts.set(c.revenue.currency, (counts.get(c.revenue.currency) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || (a[0] === 'NOK' ? -1 : 1))[0]?.[0] ?? '';
}

export function metricValue(c: CompanySummary, m: LandscapeMetric, currency: string): number | null {
  if (m === 'revenue') return c.revenue && c.revenue.currency === currency ? c.revenue.value : null;
  if (m === 'employees') return c.employees ?? null;
  // a researched company's count is a value only when research verified openings (a "none found" 0 is not a data point)
  if (c.openPositionsStatus && c.openPositionsStatus !== 'verified') return null;
  return c.openPositions ?? null;
}

export interface LandscapePoint {
  c: CompanySummary;
  x: number;
  y: number;
  name: string;
  org: string;
}

export interface LandscapeData {
  currency: string;
  points: LandscapePoint[];
  /** companies with a verified, plottable (> 0, log scale) value per axis */
  withX: number;
  withY: number;
  total: number;
  /** companies whose revenue is filed in another currency than the chart's */
  otherCurrency: number;
}

/** Companies with verified values for both metrics. Values must be > 0 (log scale): a zero is not plotted, and is never invented either. */
export function landscapeData(companies: CompanySummary[], x: LandscapeMetric, y: LandscapeMetric): LandscapeData {
  const currency = chartCurrency(companies);
  const ok = (v: number | null): v is number => v != null && v > 0;
  let withX = 0;
  let withY = 0;
  const points: LandscapePoint[] = [];
  for (const c of companies) {
    const vx = metricValue(c, x, currency);
    const vy = metricValue(c, y, currency);
    if (ok(vx)) withX++;
    if (ok(vy)) withY++;
    if (ok(vx) && ok(vy)) points.push({ c, x: vx, y: vy, name: c.legalName, org: c.orgNumber });
  }
  const otherCurrency = x === 'revenue' || y === 'revenue' ? companies.filter((c) => c.revenue && c.revenue.currency !== currency).length : 0;
  return { currency, points, withX, withY, total: companies.length, otherCurrency };
}

/** Fewer than this many companies with both values: an explanation is shown instead of an empty or one-dot chart. */
export const MIN_POINTS = 2;
