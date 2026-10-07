import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

/**
 * Anchored popover rendered in a portal with fixed positioning, so it is never
 * clipped by scrolling tables. Closes on Escape, outside click and scroll.
 */
export function Popover({ anchor, open, onClose, children, width = 300, label }: { anchor: HTMLElement | null; open: boolean; onClose: () => void; children: ReactNode; width?: number; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number; up: boolean } | null>(null);
  const place = useCallback(() => {
    if (!anchor) return;
    const r = anchor.getBoundingClientRect();
    const h = ref.current?.offsetHeight ?? 200;
    const up = r.bottom + h + 12 > window.innerHeight && r.top > h + 12;
    const left = Math.min(Math.max(8, r.left), window.innerWidth - width - 8);
    setPos({ top: up ? r.top - h - 6 : r.bottom + 6, left, up });
  }, [anchor, width]);
  useLayoutEffect(() => {
    if (open) place();
  }, [open, place]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
        anchor?.focus();
      }
    };
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node) && !anchor?.contains(e.target as Node)) onClose();
    };
    const onScroll = (e: Event) => {
      if (!ref.current?.contains(e.target as Node)) onClose();
    };
    window.addEventListener('keydown', onKey);
    window.addEventListener('mousedown', onDown);
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onClose);
    setTimeout(() => ref.current?.querySelector<HTMLElement>('button,a')?.focus(), 10);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('mousedown', onDown);
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onClose);
    };
  }, [open, onClose, anchor]);
  if (!open) return null;
  return createPortal(
    <div
      ref={ref}
      role="dialog"
      aria-label={label}
      className="popover"
      style={{ position: 'fixed', top: pos?.top ?? -9999, left: pos?.left ?? -9999, width, zIndex: 'var(--z-modal)' as unknown as number, padding: 14 }}
    >
      {children}
    </div>,
    document.body,
  );
}
