/**
 * Financial trend chart (lazy-loaded with Recharts).
 * Only rendered when ≥ 2 real data points exist; every point carries its
 * reporting period and source in the tooltip.
 */
import { Area, Bar, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { FinancialSeries, Source } from '@/types';
import { formatAxisMoney, formatInteger, formatMoneyCompact, formatMoneyExact, formatPercent, isCurrencyUnit, isMoneyUnit } from '@/utils/format';
import { ChartTip } from './ChartTooltip';

export interface FinancialChartProps {
  series: FinancialSeries[];
  sourceIndex: Record<string, Source>;
  kind?: 'line' | 'bar';
  height?: number;
  onSelectPoint?: (seriesKey: string, period: string) => void;
}

const COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)'];

export default function FinancialChart({ series, sourceIndex, kind = 'line', height = 260, onSelectPoint }: FinancialChartProps) {
  const periods = [...new Set(series.flatMap((s) => s.points.map((p) => p.period)))].sort();
  const data = periods.map((period) => {
    const row: Record<string, number | string | null> = { period };
    for (const s of series) row[s.key] = s.points.find((p) => p.period === period)?.fact.value ?? null;
    return row;
  });
  const isMoney = isMoneyUnit(series[0]?.unit);
  const isPct = series[0]?.unit === '%';
  const fmtAxis = (v: number) => (isMoney ? formatAxisMoney(v) : isPct ? `${v}%` : formatInteger(v));
  // Each amount is labelled with the currency its own filing states (a series may span a change of reporting currency).
  const currencyAt = (s: FinancialSeries, period: string) => s.points.find((p) => p.period === period)?.fact.currency ?? (isCurrencyUnit(s.unit) ? s.unit : undefined);
  const fmtValue = (s: FinancialSeries, v: number, period: string) => (isMoneyUnit(s.unit) || s.unit === 'currency not stated' ? formatMoneyExact(v, currencyAt(s, period)) : s.unit === '%' ? formatPercent(v) : `${formatInteger(v)} ${s.unit === 'people' ? 'FTEs' : s.unit}`);
  const hasNeg = data.some((d) => series.some((s) => typeof d[s.key] === 'number' && (d[s.key] as number) < 0));
  return (
    <div className="chart-wrap" style={{ width: '100%', height }}>
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 12, right: 12, bottom: 0, left: 4 }} onClick={(e) => e?.activeLabel && onSelectPoint?.(series[0].key, String(e.activeLabel))}>
          <defs>
            <linearGradient id="cg-area" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.28} />
              <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
          <XAxis dataKey="period" tick={{ fill: 'var(--chart-axis)', fontSize: 11.5, fontFamily: 'var(--font-mono)' }} axisLine={{ stroke: 'var(--chart-grid)' }} tickLine={false} />
          <YAxis tickFormatter={fmtAxis} tick={{ fill: 'var(--chart-axis)', fontSize: 11.5, fontFamily: 'var(--font-mono)' }} axisLine={false} tickLine={false} width={56} />
          {hasNeg && <ReferenceLine y={0} stroke="var(--line-strong)" />}
          <Tooltip
            cursor={{ stroke: 'var(--accent-soft)', strokeOpacity: 0.35, fill: 'var(--accent-wash)' }}
            content={({ active, label }) => {
              if (!active || !label) return null;
              const rows = series
                .map((s, i) => {
                  const pt = s.points.find((p) => p.period === label);
                  if (!pt) return null;
                  return { label: s.label, value: pt.fact.value == null ? 'Not available' : fmtValue(s, pt.fact.value, String(label)), color: COLORS[i] };
                })
                .filter(Boolean) as { label: string; value: string; color: string }[];
              const first = series[0].points.find((p) => p.period === label)?.fact.evidence[0];
              return <ChartTip title={String(label)} rows={rows} period={String(label)} source={first ? (sourceIndex[first.sourceId]?.name ?? first.sourceId) : undefined} />;
            }}
          />
          {series.map((s, i) =>
            kind === 'bar' ? (
              <Bar key={s.key} dataKey={s.key} name={s.label} fill={COLORS[i]} radius={[4, 4, 0, 0]} maxBarSize={36} fillOpacity={i === 0 ? 0.9 : 0.55} isAnimationActive={false} />
            ) : i === 0 ? (
              <Area key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={COLORS[i]} strokeWidth={2} fill="url(#cg-area)" dot={{ r: 3, fill: COLORS[i], strokeWidth: 0 }} activeDot={{ r: 5 }} connectNulls={false} isAnimationActive={false} />
            ) : (
              <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={COLORS[i]} strokeWidth={1.6} strokeDasharray={i === 2 ? '4 4' : undefined} dot={{ r: 2.5, fill: COLORS[i], strokeWidth: 0 }} connectNulls={false} isAnimationActive={false} />
            ),
          )}
        </ComposedChart>
      </ResponsiveContainer>
      {series.length > 1 && (
        <div className="chart-legend" aria-hidden>
          {series.map((s, i) => (
            <span key={s.key}>
              <i style={{ background: COLORS[i] }} />
              {s.label}
            </span>
          ))}
        </div>
      )}
      <table className="sr-only">
        <caption>{series.map((s) => s.label).join(', ')} by reporting period</caption>
        <thead>
          <tr>
            <th>Period</th>
            {series.map((s) => (
              <th key={s.key}>{s.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((d) => (
            <tr key={String(d.period)}>
              <td>{d.period}</td>
              {series.map((s) => (
                <td key={s.key}>{d[s.key] == null ? 'n/a' : isMoney ? formatMoneyCompact(d[s.key] as number, currencyAt(s, String(d.period))) : isPct ? formatPercent(d[s.key] as number) : d[s.key]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
