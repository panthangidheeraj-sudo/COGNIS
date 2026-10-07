import { useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { cn } from '@/utils/cn';

/** Open overlays, topmost last. Only the topmost one handles Esc / Tab. */
const overlayStack: symbol[] = [];

function useFocusTrap(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const me = Symbol('overlay');
    overlayStack.push(me);
    const prev = document.activeElement as HTMLElement | null;
    const el = ref.current;
    const focusables = () => el?.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),input,select,textarea,[tabindex]:not([tabindex="-1"])') ?? [];
    setTimeout(() => {
      const auto = el?.querySelector<HTMLElement>('[data-autofocus]');
      (auto ?? focusables()[0] ?? el)?.focus();
    }, 20);
    const onKey = (e: KeyboardEvent) => {
      if (overlayStack[overlayStack.length - 1] !== me) return;
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
      if (e.key === 'Tab' && el) {
        const f = Array.from(focusables());
        if (!f.length) return;
        const first = f[0];
        const last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      const i = overlayStack.indexOf(me);
      if (i >= 0) overlayStack.splice(i, 1);
      if (!overlayStack.length) document.body.style.overflow = overflow;
      prev?.focus?.();
    };
  }, [open, onClose]);
  return ref;
}

export function Modal({ open, onClose, title, children, footer, wide, labelledBy, className, eyebrow }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean; labelledBy?: string; className?: string; eyebrow?: ReactNode }) {
  const ref = useFocusTrap(open, onClose);
  if (!open) return null;
  const id = labelledBy ?? 'modal-title';
  return createPortal(
    <div className="modal-wrap">
      <div className="scrim" onClick={onClose} aria-hidden />
      <div ref={ref} className={cn('modal', wide && 'modal--wide', className)} role="dialog" aria-modal="true" aria-labelledby={id} tabIndex={-1}>
        <div className="modal-head">
          <div className="stack" style={{ gap: 4, minWidth: 0, flex: 1 }}>
            {eyebrow}
            <h2 id={id}>{title}</h2>
          </div>
          <span className="spacer" />
          <button className="btn btn--ghost btn--icon btn--sm" onClick={onClose} aria-label="Close">
            <X aria-hidden />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function Drawer({ open, onClose, title, subtitle, children, footer, label, className }: { open: boolean; onClose: () => void; title: ReactNode; subtitle?: ReactNode; children: ReactNode; footer?: ReactNode; label: string; className?: string }) {
  const ref = useFocusTrap(open, onClose);
  if (!open) return null;
  return createPortal(
    <>
      <div className="scrim" onClick={onClose} aria-hidden />
      <aside ref={ref} className={cn('drawer', className)} role="dialog" aria-modal="true" aria-label={label} tabIndex={-1}>
        <div className="drawer-head">
          <div className="stack" style={{ gap: 4, minWidth: 0, flex: 1 }}>
            {subtitle}
            <div style={{ fontSize: 18, fontWeight: 500, letterSpacing: '-0.02em' }}>{title}</div>
          </div>
          <button className="btn btn--ghost btn--icon btn--sm" onClick={onClose} aria-label="Close" data-autofocus>
            <X aria-hidden />
          </button>
        </div>
        <div className="drawer-body">{children}</div>
        {footer && <div className="drawer-foot">{footer}</div>}
      </aside>
    </>,
    document.body,
  );
}
