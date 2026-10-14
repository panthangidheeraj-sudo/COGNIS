import { useEffect, type RefObject } from 'react';

/** Longest stagger step that is applied (items past this arrive together, so a long list never drags). */
const MAX_STEP = 6;

/**
 * One-shot scroll reveals.
 *
 * Every `[data-reveal]` element inside `root` is shown the first time it scrolls into view: it gets `data-revealed="true"` once and is then
 * unobserved, so it never animates again when the viewer scrolls back up or down. Related elements arrive one after another — each element's
 * order inside its nearest `[data-reveal-group]` (or inside `root`, when it has none) is written to `--reveal-i`, and the stylesheet turns that
 * into a small delay. The hook only toggles an attribute; what "hidden" and "shown" look like is CSS.
 *
 * `enabled` is false for reduced motion. Then nothing is observed and every element is marked revealed straight away, so the content is simply
 * there. The same happens when the browser has no IntersectionObserver.
 *
 * Returns nothing. Call it once per page, with the element that contains the reveals.
 */
export function useRevealOnScroll(root: RefObject<HTMLElement | null>, enabled: boolean): void {
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const items = Array.from(el.querySelectorAll<HTMLElement>('[data-reveal]'));
    if (items.length === 0) return;

    // stagger order within each group, in document order
    const counts = new Map<Element, number>();
    for (const item of items) {
      const group = item.closest('[data-reveal-group]') ?? el;
      const i = counts.get(group) ?? 0;
      counts.set(group, i + 1);
      item.style.setProperty('--reveal-i', String(Math.min(i, MAX_STEP)));
    }

    const show = (item: Element) => item.setAttribute('data-revealed', 'true');
    if (!enabled || typeof IntersectionObserver === 'undefined') {
      items.forEach(show);
      return;
    }

    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          show(entry.target);
          io.unobserve(entry.target); // once: it is never hidden or animated again
        }
      },
      { threshold: 0.1 }, // no root margin: an item at the very end of the page could otherwise never reach the trigger line
    );
    for (const item of items) if (item.getAttribute('data-revealed') !== 'true') io.observe(item);
    return () => io.disconnect();
  }, [root, enabled]);
}
