import { cn } from '@/utils/cn';
import { useResolvedTheme } from '@/hooks/useResolvedTheme';

/**
 * The official COGNIS logo: Atlas carrying the celestial letter C. Icon only — the image never contains the name.
 *
 * Artwork lives in public/brand/ (see scripts/prepare-brand-assets.py and the Logo section of DESIGN_SYSTEM.md):
 *   navy  = the supplied ink on a transparent ground  → light theme
 *   ivory = the same silhouette in the supplied paper colour → dark theme
 * `-sm` files are the same artwork pre-sized for the small placements so thin lines stay crisp.
 */
export type LogoVariant = 'auto' | 'navy' | 'ivory';

/** Width ÷ height of the cropped emblem (612 × 984 px). Used to reserve the exact box so nothing shifts or stretches. */
export const LOGO_ASPECT = 612 / 984;
/** Placements up to this tall use the pre-sized files. */
const SMALL_MAX_HEIGHT = 64;

export function logoSrc(variant: Exclude<LogoVariant, 'auto'>, height: number): string {
  return `${import.meta.env.BASE_URL}brand/cognis-atlas-${variant}${height <= SMALL_MAX_HEIGHT ? '-sm' : ''}.png`;
}

export function CognisLogo({
  height = 44,
  variant = 'auto',
  compact = false,
  decorative = false,
  alt = 'COGNIS',
  className,
}: {
  /** Emblem height in px; the width follows the artwork's proportions. */
  height?: number;
  /** `auto` follows the active theme: ivory emblem on the dark theme, navy on the light one. */
  variant?: LogoVariant;
  /** Hide the text name that sits beside the emblem (the emblem itself never carries text). */
  compact?: boolean;
  /** Set when a parent already names the image (a labelled link, for instance), so it is not announced twice. */
  decorative?: boolean;
  alt?: string;
  className?: string;
}) {
  const theme = useResolvedTheme();
  const resolved = variant === 'auto' ? (theme === 'dark' ? 'ivory' : 'navy') : variant;
  const width = Math.round(height * LOGO_ASPECT);
  return (
    <span className={cn('cg-logo', className)}>
      <img className="cg-logo-img" src={logoSrc(resolved, height)} width={width} height={height} alt={decorative ? '' : alt} decoding="async" draggable={false} data-logo={resolved} />
      {!compact && (
        <span className="cg-logo-word" aria-hidden={decorative || undefined}>
          COGNIS
        </span>
      )}
    </span>
  );
}
