/** COGNIS signal motif: concentric evidence rings + node + ray. A decorative illustration for empty states, loading and the About page — the logo is CognisLogo. */
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
