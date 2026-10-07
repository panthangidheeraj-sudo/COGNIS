import { useRef, type ReactNode } from 'react';

export interface TabDef {
  id: string;
  label: ReactNode;
  count?: number;
  icon?: ReactNode;
}

/** WAI-ARIA tablist with roving focus. Panels are rendered by the caller with id `tabpanel-${id}`. */
export function Tabs({ tabs, value, onChange, label, className }: { tabs: TabDef[]; value: string; onChange: (id: string) => void; label: string; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const onKey = (e: React.KeyboardEvent) => {
    const i = tabs.findIndex((t) => t.id === value);
    let n = -1;
    if (e.key === 'ArrowRight') n = (i + 1) % tabs.length;
    if (e.key === 'ArrowLeft') n = (i - 1 + tabs.length) % tabs.length;
    if (e.key === 'Home') n = 0;
    if (e.key === 'End') n = tabs.length - 1;
    if (n >= 0) {
      e.preventDefault();
      onChange(tabs[n].id);
      ref.current?.querySelectorAll<HTMLButtonElement>('[role=tab]')[n]?.focus();
    }
  };
  return (
    <div ref={ref} className={`tabs ${className ?? ''}`} role="tablist" aria-label={label} onKeyDown={onKey}>
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          id={`tab-${t.id}`}
          aria-selected={t.id === value}
          aria-controls={`tabpanel-${t.id}`}
          tabIndex={t.id === value ? 0 : -1}
          className="tab"
          onClick={() => onChange(t.id)}
        >
          {t.icon}
          {t.label}
          {t.count != null && <span className="tab-count">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Segmented<T extends string>({ options, value, onChange, label }: { options: { value: T; label: ReactNode; icon?: ReactNode; title?: string }[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} aria-pressed={o.value === value} onClick={() => onChange(o.value)} title={o.title}>
          {o.icon}
          {o.label}
        </button>
      ))}
    </div>
  );
}
