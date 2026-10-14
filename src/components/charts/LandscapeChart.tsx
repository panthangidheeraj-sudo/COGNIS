/**
 * Company landscape: two user-selected metrics, log scales, companies as nodes. Only verified values are plotted (see ./landscapeData.ts);
 * the page shows an explanation instead of this chart when fewer than two companies have both values.
 */
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts';
import type { CompanySummary } from '@/types';
import { formatAxisMoney, formatInteger, formatMoneyCompact } from '@/utils/format';
import { ChartTip } from './ChartTooltip';
import { landscapeData, METRIC_LABEL, type LandscapeMetric } from './landscapeData';

export type { LandscapeMetric } from './landscapeData';

export default function LandscapeChart({ companies, x, y, onSelect }: { companies: CompanySummary[]; x: LandscapeMetric; y: LandscapeMetric; onSelect: (org: string) => void }) {
  // The plotted currency is the most common one among the companies' latest filings (NOK for most Norwegian companies).
  const { currency, points: pts, otherCurrency } = landscapeData(companies, x, y);
  const LABELS = METRIC_LABEL(currency);
  const fmt = (m: LandscapeMetric) => (v: number) => (m === 'revenue' ? formatAxisMoney(v) : formatInteger(v));
  return (
    <div className="landscape">
      <div style={{ width: '100%', height: 440 }}>
        <ResponsiveContainer>
          <ScatterChart margin={{ top: 16, right: 16, bottom: 24, left: 8 }}>
            <CartesianGrid stroke="var(--chart-grid)" />
            <XAxis type="number" dataKey="x" scale="log" domain={['auto', 'auto']} tickFormatter={fmt(x)} name={LABELS[x]} tick={{ fill: 'var(--chart-axis)', fontSize: 11, fontFamily: 'var(--font-mono)' }} label={{ value: `${LABELS[x]} · log scale`, position: 'insideBottom', dy: 18, fill: 'var(--chart-axis)', fontSize: 11 }} />
            <YAxis type="number" dataKey="y" scale="log" domain={['auto', 'auto']} tickFormatter={fmt(y)} name={LABELS[y]} tick={{ fill: 'var(--chart-axis)', fontSize: 11, fontFamily: 'var(--font-mono)' }} width={64} />
            <ZAxis range={[60, 60]} />
            <Tooltip
              cursor={{ strokeDasharray: '3 3', stroke: 'var(--line-strong)' }}
              content={({ active, payload }) => {
                const p = active && payload?.[0]?.payload;
                if (!p) return null;
                return (
                  <ChartTip
                    title={p.name}
                    rows={[
                      { label: LABELS[x], value: x === 'revenue' ? formatMoneyCompact(p.x, currency) : formatInteger(p.x) },
                      { label: LABELS[y], value: y === 'revenue' ? formatMoneyCompact(p.y, currency) : formatInteger(p.y) },
                    ]}
                    period={p.c.revenue?.period}
                    source={x === 'revenue' || y === 'revenue' ? 'Regnskapsregisteret' : 'Brønnøysundregistrene'}
                  />
                );
              }}
            />
            <Scatter data={pts} fill="var(--chart-1)" fillOpacity={0.75} stroke="var(--accent-ice)" strokeOpacity={0.6} onClick={(d: unknown) => onSelect((d as { org: string }).org)} cursor="pointer" isAnimationActive={false} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <p className="t-xs t-muted">
        {pts.length} of {companies.length} companies plotted. Companies without verified values for both metrics are not shown.
        {otherCurrency > 0 && ` ${otherCurrency} ${otherCurrency === 1 ? 'company files' : 'companies file'} revenue in a currency other than ${currency || 'the chart currency'} and ${otherCurrency === 1 ? 'is' : 'are'} not plotted (amounts are never converted).`}{' '}
        Click a node to open the company.
      </p>
    </div>
  );
}
