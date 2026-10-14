import { Plus, Sparkle } from 'lucide-react';
import type { InterpretedFilter } from '@/types';

/**
 * Filters the interpreter read out of free text. They are only offered here: nothing restricts the results until the user
 * adds one (selected filters then show as chips, elsewhere). Used by Discover and by the Data Sheet creator.
 */
export function SuggestedFilters({
  suggestions,
  onAdd,
  onAddAll,
  label = 'Suggested from your search',
}: {
  suggestions: InterpretedFilter[];
  onAdd: (s: InterpretedFilter) => void;
  onAddAll?: () => void;
  label?: string;
}) {
  if (suggestions.length === 0) return null;
  return (
    <div className="suggest-row" role="group" aria-label="Suggested filters">
      <span className="suggest-label">
        <Sparkle aria-hidden /> {label} <span className="suggest-note">· not applied</span>
      </span>
      {suggestions.map((s) => (
        <button key={s.key} type="button" className="chip chip--suggest" onClick={() => onAdd(s)} aria-label={`Add ${s.label} filter: ${s.display}`}>
          <Plus aria-hidden />
          <span className="t-muted">{s.label}:</span> {s.display}
        </button>
      ))}
      {onAddAll && suggestions.length > 1 && (
        <button type="button" className="link-btn t-xs" onClick={onAddAll}>
          Add all
        </button>
      )}
    </div>
  );
}
