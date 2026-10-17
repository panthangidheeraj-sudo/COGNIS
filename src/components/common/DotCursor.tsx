import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useReducedMotion } from '@/hooks/useMediaQuery';
import '@/styles/cursor.css';

const FINE = '(hover: hover) and (pointer: fine)';
/** Elements that get the subtle "this is interactive" size change. */
const INTERACTIVE = 'a[href], button, summary, select, [role="button"], [role="tab"], [role="option"], [role="menuitem"], [role="switch"], [role="checkbox"], label[for], .flex-carousel, [tabindex]:not([tabindex="-1"]):not(input):not(textarea)';
/** Text entry keeps the native I-beam, and the dot steps aside there. */
const TEXT = 'input:not([type="button"]):not([type="submit"]):not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="color"]), textarea, [contenteditable=""], [contenteditable="true"]';
const SMOOTHING = 0.38; // fraction of the remaining distance covered each frame: smooth, with no visible lag

/**
 * A single small solid dot that follows a mouse. Fine-pointer devices only (touch keeps its native behaviour); `pointer-events: none`,
 * no trail, no ring. Reduced motion: the dot sits exactly under the pointer (no easing) and no size animation. Cleans up completely.
 */
export function DotCursor() {
  const reduced = useReducedMotion();
  const [enabled, setEnabled] = useState(() => typeof window !== 'undefined' && !!window.matchMedia?.(FINE).matches);
  const dot = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const mql = window.matchMedia?.(FINE);
    if (!mql) return;
    const on = () => setEnabled(mql.matches);
    on();
    mql.addEventListener?.('change', on);
    return () => mql.removeEventListener?.('change', on);
  }, []);

  useEffect(() => {
    const el = dot.current;
    if (!enabled || !el) return;
    const html = document.documentElement;
    html.classList.add('cg-cursor-on');
    let raf = 0;
    let x = -100;
    let y = -100;
    let tx = x;
    let ty = y;
    let seen = false;

    const paint = () => {
      el.style.transform = `translate3d(${x}px, ${y}px, 0) translate(-50%, -50%)`;
    };
    const tick = () => {
      raf = 0;
      x += (tx - x) * SMOOTHING;
      y += (ty - y) * SMOOTHING;
      if (Math.abs(tx - x) < 0.1 && Math.abs(ty - y) < 0.1) {
        x = tx;
        y = ty;
      } else raf = requestAnimationFrame(tick);
      paint();
    };
    const state = (target: EventTarget | null) => {
      const t = target instanceof Element ? target : null;
      const text = !!t?.closest(TEXT);
      const hit = t?.closest(INTERACTIVE);
      const dragging = !!t?.closest('.flex-carousel[data-dragging]');
      if (text) el.dataset.hidden = '';
      else delete el.dataset.hidden;
      if (hit && !text) el.dataset.active = dragging ? 'drag' : '';
      else delete el.dataset.active;
    };
    const onMove = (e: PointerEvent) => {
      if (e.pointerType && e.pointerType !== 'mouse') return;
      tx = e.clientX;
      ty = e.clientY;
      if (!seen) {
        seen = true;
        x = tx;
        y = ty;
        paint();
        el.dataset.ready = '';
      }
      state(e.target);
      if (reduced) {
        x = tx;
        y = ty;
        paint();
      } else if (!raf) raf = requestAnimationFrame(tick);
    };
    const onDown = (e: PointerEvent) => {
      if (e.pointerType === 'mouse') {
        el.dataset.down = '';
        state(e.target);
      }
    };
    const onUp = () => delete el.dataset.down;
    const onLeave = (e: MouseEvent) => {
      if (!e.relatedTarget) delete el.dataset.ready;
    };
    const onEnter = () => {
      if (seen) el.dataset.ready = '';
    };
    // the element under a stationary pointer changes when the page scrolls or a route swaps: re-read it, at most once per frame
    let scrollRaf = 0;
    const onScroll = () => {
      if (!seen || scrollRaf) return;
      scrollRaf = requestAnimationFrame(() => {
        scrollRaf = 0;
        state(document.elementFromPoint?.(tx, ty) ?? null);
      });
    };
    window.addEventListener('scroll', onScroll, { passive: true, capture: true });
    window.addEventListener('pointermove', onMove, { passive: true });
    window.addEventListener('pointerdown', onDown, { passive: true });
    window.addEventListener('pointerup', onUp, { passive: true });
    document.documentElement.addEventListener('mouseleave', onLeave);
    document.documentElement.addEventListener('mouseenter', onEnter);
    return () => {
      cancelAnimationFrame(raf);
      cancelAnimationFrame(scrollRaf);
      window.removeEventListener('scroll', onScroll, { capture: true });
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerdown', onDown);
      window.removeEventListener('pointerup', onUp);
      document.documentElement.removeEventListener('mouseleave', onLeave);
      document.documentElement.removeEventListener('mouseenter', onEnter);
      html.classList.remove('cg-cursor-on');
    };
  }, [enabled, reduced]);

  if (!enabled) return null;
  // Portalled to <body>: #root is its own stacking context (z-index 1, isolation: isolate), so a dot rendered inside it can never rise above
  // anything mounted outside it, such as the launch intro. A direct child of <body> sits in the root stacking context with the highest z-index.
  return createPortal(<div ref={dot} className="cg-dot-cursor" aria-hidden data-reduced={reduced || undefined} data-testid="dot-cursor" />, document.body);
}
