/** Small bar chart for counts (hiring history, categories). Lazy-loaded. */
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { ChartTip } from './ChartTooltip';

export default function SimpleBarChart({ data, unit, source, height = 180, xLabel }: { data: { label: string; value: number }[]; unit: string; source?: string; height?: number; xLabel?: string }) {
  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: 'var(--chart-axis)', fontSize: 11, fontFamily: 'var(--font-mono)' }} axisLine={{ stroke: 'var(--chart-grid)' }} tickLine={false} />
          <YAxis allowDecimals={false} tick={{ fill: 'var(--chart-axis)', fontSize: 11, fontFamily: 'var(--font-mono)' }} axisLine={false} tickLine={false} />
          <Tooltip cursor={{ fill: 'var(--accent-wash)' }} content={({ active, payload, label }) => (active && payload?.length ? <ChartTip title={`${xLabel ? `${xLabel} ` : ''}${label}`} rows={[{ label: unit, value: String(payload[0].value) }]} source={source} /> : null)} />
          <Bar dataKey="value" fill="var(--chart-1)" radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
      <table className="sr-only">
        <caption>{unit}</caption>
        <tbody>
          {data.map((d) => (
            <tr key={d.label}>
              <th>{d.label}</th>
              <td>{d.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
