import { cn } from '@/utils/cn';

/**
 * Company mark. Uses a backend-provided logo when available; otherwise an
 * abstract generated mark (initials + deterministic signal motif). Never a
 * fake logo.
 */
export function BrandMark({ name, org, logoUrl, size = 40, className }: { name: string; org: string; logoUrl?: string | null; size?: number; className?: string }) {
  if (logoUrl) return <img src={logoUrl} alt="" width={size} height={size} className={cn('brand-mark', className)} style={{ width: size, height: size }} />;
  const h = [...org].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);
  const initials = name
    .replace(/\b(AS|ASA|AB|Holding)\b/g, '')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0])
    .join('')
    .toUpperCase();
  const angle = (h % 360) * (Math.PI / 180);
  const r = 15;
  const x = 20 + Math.cos(angle) * r;
  const y = 20 + Math.sin(angle) * r;
  return (
    <span className={cn('brand-mark', className)} style={{ width: size, height: size }} aria-hidden>
      <svg viewBox="0 0 40 40" width={size} height={size}>
        <circle cx="20" cy="20" r="15" fill="none" stroke="currentColor" strokeOpacity=".18" />
        <line x1="20" y1="20" x2={x} y2={y} stroke="var(--accent-soft)" strokeOpacity=".55" />
        <circle cx={x} cy={y} r="2" fill="var(--accent-soft)" />
        <text x="20" y="24.5" textAnchor="middle" fontSize="12.5" fontWeight="600" fill="currentColor" style={{ fontFamily: 'var(--font-sans)', letterSpacing: '-0.02em' }}>
          {initials}
        </text>
      </svg>
    </span>
  );
}
