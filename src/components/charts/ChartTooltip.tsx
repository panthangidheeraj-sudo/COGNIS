/** Tooltip body used by all charts: exact value, unit, period, source. */
export function ChartTip({ title, rows, source, period }: { title: string; rows: { label: string; value: string; color?: string }[]; source?: string; period?: string }) {
  return (
    <div className="chart-tip">
      <span className="t-micro">{title}</span>
      {rows.map((r) => (
        <div key={r.label} className="row" style={{ justifyContent: 'space-between', gap: 14 }}>
          <span className="row" style={{ gap: 6 }}>
            {r.color && <i style={{ width: 8, height: 8, borderRadius: 2, background: r.color, display: 'inline-block' }} />}
            {r.label}
          </span>
          <strong className="t-num">{r.value}</strong>
        </div>
      ))}
      {period && <span>Reporting period: {period}</span>}
      {source && <span>Source: {source}</span>}
    </div>
  );
}
