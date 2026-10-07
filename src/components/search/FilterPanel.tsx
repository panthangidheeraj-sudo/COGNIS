import type { DiscoverFilters, FilterCapability } from '@/types';

/** Renders only the filters the backend declares it supports. */
export function FilterPanel({ caps, value, onChange }: { caps: FilterCapability[]; value: DiscoverFilters; onChange: (f: DiscoverFilters) => void }) {
  const set = (k: keyof DiscoverFilters, v: unknown) => onChange({ ...value, [k]: v === '' || v === undefined || v === false ? undefined : v });
  return (
    <div className="filters">
      {caps.map((c) => {
        const v = value[c.key];
        const id = `flt-${c.key}`;
        if (c.type === 'select')
          return (
            <div key={c.key} className="field">
              <label htmlFor={id}>{c.label}</label>
              <select id={id} className="select" value={v == null ? '' : String(v)} onChange={(e) => set(c.key, e.target.value)}>
                <option value="">Any</option>
                {c.options?.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
          );
        if (c.type === 'boolean')
          return (
            <label key={c.key} className="checkbox">
              <input type="checkbox" checked={!!v} onChange={(e) => set(c.key, e.target.checked)} />
              {c.label}
            </label>
          );
        return (
          <div key={c.key} className="field">
            <label htmlFor={id}>
              {c.label}
              {c.unit ? ` (${c.unit})` : ''}
            </label>
            <input id={id} className="input" type="number" inputMode="numeric" min={0} value={v == null ? '' : String(v)} onChange={(e) => set(c.key, e.target.value === '' ? undefined : Number(e.target.value))} placeholder="Any" />
          </div>
        );
      })}
    </div>
  );
}
