import { Rows3, Rows4 } from 'lucide-react';
import { usePreferences } from '@/stores/preferences';

/** Comfortable ↔ Compact. Compact tightens tables, sheets, compare, financials and research views. */
export function DensityToggle() {
  const density = usePreferences((s) => s.density);
  const set = usePreferences((s) => s.set);
  const compact = density === 'compact';
  return (
    <button
      className="btn btn--ghost btn--icon topbar-density"
      onClick={() => set({ density: compact ? 'comfortable' : 'compact' })}
      aria-pressed={compact}
      aria-label={compact ? 'Compact density on. Switch to comfortable' : 'Switch to compact density'}
      title={compact ? 'Density: Compact (click for Comfortable)' : 'Density: Comfortable (click for Compact)'}
    >
      {compact ? <Rows4 aria-hidden /> : <Rows3 aria-hidden />}
    </button>
  );
}
