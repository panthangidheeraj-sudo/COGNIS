/** Minimal sparkline. Only drawn from real values; needs ≥ 2 points. */
export function Sparkline({ values, width = 84, height = 26, label }: { values: number[]; width?: number; height?: number; label?: string }) {
  if (!values || values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * (width - 4) + 2, height - 3 - ((v - min) / span) * (height - 6)]);
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join('');
  const last = pts[pts.length - 1];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <path d={`${d}L${last[0]} ${height}L2 ${height}Z`} fill="var(--accent-wash)" />
      <path d={d} fill="none" stroke="var(--accent-soft)" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r="2.2" fill="var(--accent-soft)" />
    </svg>
  );
}
