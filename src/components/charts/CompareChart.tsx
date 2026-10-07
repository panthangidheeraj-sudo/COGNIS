/** Multi-company trend on one consistent scale (no per-company axes). */
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { ComparisonSeries } from '@/types';
import { formatAxisMoney, formatInteger, formatMoneyExact, isCurrencyUnit } from '@/utils/format';
import { ChartTip } from './ChartTooltip';

export const COMPARE_COLORS = ['#9dbbea', '#f7f3ea', '#3cbfa8', '#d9ac5f', '#a78bfa'];
export const COMPARE_COLORS_LIGHT = ['#3f6fb8', '#102a43', '#13836f', '#9a6a12', '#6d4fd0'];

export default function CompareChart({ series, names, height = 280, colors }: { series: ComparisonSeries; names: string[]; height?: number; colors: string[] }) {
  const data = series.points.map((p) => {
    const row: Record<string, string | number | null> = { period: p.period };
    p.values.forEach((v, i) => (row[`c${i}`] = v));
    return row;
  });
  const money = isCurrencyUnit(series.unit); // a mixed-currency series is never drawn on one axis (see ComparePage)
  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 12, right: 12, bottom: 0, left: 4 }}>
          <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
          <XAxis dataKey="period" tick={{ fill: 'var(--chart-axis)', fontSize: 11.5, fontFamily: 'var(--font-mono)' }} axisLine={{ stroke: 'var(--chart-grid)' }} tickLine={false} />
          <YAxis tickFormatter={(v: number) => (money ? formatAxisMoney(v) : formatInteger(v))} tick={{ fill: 'var(--chart-axis)', fontSize: 11.5, fontFamily: 'var(--font-mono)' }} axisLine={false} tickLine={false} width={56} />
          <Tooltip
            content={({ active, label, payload }) =>
              active && payload?.length ? (
                <ChartTip
                  title={String(label)}
                  rows={payload.map((p) => {
                    const idx = Number(String(p.dataKey).slice(1));
                    return { label: names[idx], value: p.value == null ? 'n/a' : money ? formatMoneyExact(Number(p.value), series.unit) : `${formatInteger(Number(p.value))}`, color: colors[idx] };
                  })}
                  period={String(label)}
                  source="Regnskapsregisteret (filed annual accounts)"
                />
              ) : null
            }
          />
          {names.map((n, i) => (
            <Line key={n} type="monotone" dataKey={`c${i}`} name={n} stroke={colors[i]} strokeWidth={2} dot={{ r: 3, strokeWidth: 0, fill: colors[i] }} connectNulls={false} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
