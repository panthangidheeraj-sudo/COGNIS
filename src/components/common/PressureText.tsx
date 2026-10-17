import { createElement, useEffect, useRef, type ElementType } from 'react';
import { useReducedMotion } from '@/hooks/useMediaQuery';

/**
 * Pressure text: every letter's variable-font weight follows the pointer. Letters near the cursor get heavy, letters far away relax to
 * the resting weight, and the cursor is eased towards the pointer so the change flows rather than snaps.
 *
 * This is a re-implementation of the React Bits "Text Pressure" behaviour (per-letter distance to a smoothed pointer, weight mapped
 * linearly from distance, widths/italic optional), written for COGNIS in TypeScript; it is not the original source. The original also
 * animates a width axis and italics through the Compressa font. COGNIS's own typeface (Geist Variable) has a weight axis only, so
 * only weight responds here.
 *
 * Layout never moves: each letter is held at a fixed width (a heavier glyph grows symmetrically inside it), so lines never re-wrap.
 * The text is exposed to assistive tech once, as plain text. With reduced motion (the COGNIS Motion setting or the OS) nothing is bound
 * and the text is static.
 */
export interface PressureSegment {
  text: string;
  /** class on the wrapping element for this run (e.g. a gradient) */
  className?: string;
  /** element for this run; default `span` */
  as?: 'span' | 'em' | 'strong';
  /** false: the run is drawn as plain text and ignores the pointer (e.g. a serif italic that has no weight axis) */
  pressure?: boolean;
}

/** distance → axis value: far = min, on the cursor = max */
export const pressureValue = (distance: number, maxDist: number, min: number, max: number) =>
  Math.round(Math.min(max, Math.max(min, max - Math.abs((max * distance) / maxDist) + min)));

/** Pointer smoothing: the cursor covers 1/EASE of the remaining distance per frame (React Bits uses 15). */
const EASE = 15;

export function PressureText({
  segments,
  as = 'span',
  className,
  id,
  minWeight = 450,
  maxWeight = 800,
}: {
  segments: PressureSegment[];
  as?: ElementType;
  className?: string;
  id?: string;
  minWeight?: number;
  maxWeight?: number;
}) {
  const root = useRef<HTMLElement>(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    const el = root.current;
    if (!el || reduced) return;
    const chars = Array.from(el.querySelectorAll<HTMLElement>('[data-pressure-char]'));
    if (chars.length === 0) return;

    const mouse = { x: 0, y: 0 };
    const cursor = { x: 0, y: 0 };
    let active = false;
    let raf = 0;
    let lastWeights: number[] = [];

    const lock = () => {
      // hold each letter at a fixed width (measured a little above the resting weight) so a heavier weight can never move or re-wrap the line
      const holdWeight = Math.round(minWeight + (maxWeight - minWeight) * 0.35);
      chars.forEach((c) => {
        c.style.width = '';
        c.style.fontVariationSettings = `'wght' ${holdWeight}`;
      });
      chars.forEach((c) => {
        const w = c.getBoundingClientRect().width;
        if (w > 0) c.style.width = `${w}px`;
        c.style.fontVariationSettings = '';
      });
      lastWeights = [];
    };

    const paint = () => {
      raf = 0;
      cursor.x += (mouse.x - cursor.x) / EASE;
      cursor.y += (mouse.y - cursor.y) / EASE;
      const box = el.getBoundingClientRect();
      const maxDist = Math.max(1, box.width / 2);
      const next = chars.map((c) => {
        const r = c.getBoundingClientRect();
        const d = Math.hypot(cursor.x - (r.left + r.width / 2), cursor.y - (r.top + r.height / 2));
        return pressureValue(d, maxDist, minWeight, maxWeight);
      });
      next.forEach((w, i) => {
        if (w !== lastWeights[i]) chars[i].style.fontVariationSettings = `'wght' ${w}`;
      });
      lastWeights = next;
      const settled = Math.abs(mouse.x - cursor.x) < 0.5 && Math.abs(mouse.y - cursor.y) < 0.5;
      if (!settled && active) raf = requestAnimationFrame(paint);
    };
    const kick = () => {
      if (!raf) raf = requestAnimationFrame(paint);
    };
    const move = (x: number, y: number) => {
      if (!active) {
        active = true;
        cursor.x = x;
        cursor.y = y;
      }
      mouse.x = x;
      mouse.y = y;
      kick();
    };
    const onMouse = (e: MouseEvent) => move(e.clientX, e.clientY);
    const onTouch = (e: TouchEvent) => {
      const t = e.touches[0];
      if (t) move(t.clientX, t.clientY);
    };
    const onLeave = () => {
      // pointer left the window: relax every letter to its resting weight
      active = false;
      mouse.x = mouse.y = cursor.x = cursor.y = -99999;
      kick();
    };
    let resizeRaf = 0;
    const onResize = () => {
      cancelAnimationFrame(resizeRaf);
      resizeRaf = requestAnimationFrame(() => {
        lock();
        lastWeights = [];
        if (active) kick();
      });
    };

    lock();
    void document.fonts?.ready.then(() => onResize());
    window.addEventListener('mousemove', onMouse, { passive: true });
    window.addEventListener('touchmove', onTouch, { passive: true });
    document.documentElement.addEventListener('mouseleave', onLeave);
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('mousemove', onMouse);
      window.removeEventListener('touchmove', onTouch);
      document.documentElement.removeEventListener('mouseleave', onLeave);
      window.removeEventListener('resize', onResize);
      cancelAnimationFrame(raf);
      cancelAnimationFrame(resizeRaf);
      chars.forEach((c) => {
        c.style.width = '';
        c.style.fontVariationSettings = '';
      });
    };
  }, [reduced, minWeight, maxWeight]);

  const plain = segments.map((s) => s.text).join(' ');
  return createElement(
    as,
    { id, className, ref: root, 'data-pressure': reduced ? 'static' : 'on', 'aria-label': plain },
    segments.map((seg, si) => {
      const Tag = seg.as ?? 'span';
      const animated = seg.pressure !== false;
      return (
        <span key={si}>
          {si > 0 ? ' ' : null}
          <Tag className={seg.className} aria-hidden="true">
            {animated
              ? // a word is an unbreakable run of letters; the wrapper keeps `Find.` from splitting across lines
                <span className="pressure-word">
                  {Array.from(seg.text).map((ch, ci) => (
                    <span key={ci} className="pressure-char" data-pressure-char="">
                      {ch}
                    </span>
                  ))}
                </span>
              : seg.text}
          </Tag>
        </span>
      );
    }),
  );
}
