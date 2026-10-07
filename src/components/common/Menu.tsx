import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { cn } from '@/utils/cn';

export interface MenuItem {
  label: string;
  icon?: ReactNode;
  onSelect: () => void;
  danger?: boolean;
  disabled?: boolean;
  separatorBefore?: boolean;
}

/**
 * Accessible dropdown menu (button + role=menu, arrow-key navigation).
 * Rendered in a portal so cards with overflow/stacking never clip it.
 */
export function Menu({ trigger, items, label, align = 'right', className }: { trigger: ReactNode; items: MenuItem[]; label: string; align?: 'left' | 'right'; className?: string }) {
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const id = useId();
  const close = useCallback(() => setOpen(false), []);

  useLayoutEffect(() => {
    if (!open || !btn.current) return;
    const r = btn.current.getBoundingClientRect();
    const w = pop.current?.offsetWidth ?? 220;
    const h = pop.current?.offsetHeight ?? 200;
    const left = align === 'right' ? Math.max(8, r.right - w) : Math.min(r.left, window.innerWidth - w - 8);
    const top = r.bottom + h + 8 > window.innerHeight ? Math.max(8, r.top - h - 6) : r.bottom + 6;
    setPos({ top, left });
  }, [open, align]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!pop.current?.contains(e.target as Node) && !btn.current?.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        close();
        btn.current?.focus();
      }
    };
    const onScroll = (e: Event) => !pop.current?.contains(e.target as Node) && close();
    window.addEventListener('mousedown', onDown);
    window.addEventListener('keydown', onKey);
    window.addEventListener('scroll', onScroll, true);
    setTimeout(() => pop.current?.querySelector<HTMLButtonElement>('[role=menuitem]:not(:disabled)')?.focus(), 10);
    return () => {
      window.removeEventListener('mousedown', onDown);
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', onScroll, true);
    };
  }, [open, close]);

  const onKey = (e: React.KeyboardEvent) => {
    const els = Array.from(pop.current?.querySelectorAll<HTMLButtonElement>('[role=menuitem]:not(:disabled)') ?? []);
    const i = els.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      els[(i + 1) % els.length]?.focus();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      els[(i - 1 + els.length) % els.length]?.focus();
    } else if (e.key === 'Tab') close();
  };

  if (!items.length) return null;
  return (
    <span className={cn('menu-root', className)} style={{ display: 'inline-flex' }}>
      <button
        ref={btn}
        className="btn btn--ghost btn--icon btn--sm"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={label}
        onClick={(e) => {
          e.stopPropagation();
          e.preventDefault();
          setOpen((o) => !o);
        }}
      >
        {trigger}
      </button>
      {open &&
        createPortal(
          <div ref={pop} id={id} role="menu" aria-label={label} className="popover" style={{ position: 'fixed', top: pos?.top ?? -9999, left: pos?.left ?? -9999, zIndex: 75 }} onKeyDown={onKey}>
            {items.map((it) => (
              <div key={it.label}>
                {it.separatorBefore && <div className="menu-sep" role="separator" />}
                <button
                  role="menuitem"
                  className={cn('menu-item', it.danger && 'menu-item--danger')}
                  disabled={it.disabled}
                  onClick={(e) => {
                    e.stopPropagation();
                    setOpen(false);
                    it.onSelect();
                  }}
                >
                  {it.icon}
                  {it.label}
                </button>
              </div>
            ))}
          </div>,
          document.body,
        )}
    </span>
  );
}
