/** COGNIS signal motif: concentric evidence rings + node + ray. Used in logo, empty states and loading. */
export function Motif({ size = 44, animated = false, className }: { size?: number; animated?: boolean; className?: string }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 48 48" fill="none" aria-hidden>
      <circle cx="24" cy="24" r="19" stroke="currentColor" strokeOpacity=".22" strokeDasharray="2 3" />
      <circle cx="24" cy="24" r="12.5" stroke="currentColor" strokeOpacity=".45">
        {animated && <animate attributeName="stroke-opacity" values=".2;.6;.2" dur="2.4s" repeatCount="indefinite" />}
      </circle>
      <circle cx="24" cy="24" r="6.5" stroke="currentColor" strokeOpacity=".8" />
      <circle cx="24" cy="24" r="2.4" fill="currentColor" />
      <path d="M26.5 22.4 37 15.6" stroke="currentColor" strokeLinecap="round" strokeOpacity=".8" />
      <circle cx="38.6" cy="14.6" r="2" fill="currentColor" />
    </svg>
  );
}

export function CognisLogo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="cg-logo">
      <svg width="28" height="28" viewBox="0 0 32 32" fill="none" aria-hidden>
        <circle cx="16" cy="16" r="13" stroke="var(--accent-soft)" strokeOpacity=".45" strokeWidth="1.2" />
        <circle cx="16" cy="16" r="7" stroke="var(--accent-ice)" strokeOpacity=".85" strokeWidth="1.2" />
        <circle cx="16" cy="16" r="2.6" fill="var(--c-ivory)" />
        <path d="M18.2 14.6 25.4 10.2" stroke="var(--accent-soft)" strokeWidth="1.2" strokeLinecap="round" />
        <circle cx="26.4" cy="9.6" r="1.7" fill="var(--accent-soft)" />
      </svg>
      {!compact && <span className="cg-logo-word">COGNIS</span>}
    </span>
  );
}
