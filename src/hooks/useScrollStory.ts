import { useEffect, useState, type RefObject } from 'react';

/**
 * Scroll choreography for long, pinned story sections.
 *
 * Every `[data-act]` element inside `root` gets a CSS custom property `--p` (0 → 1) for how far the
 * viewport has travelled through it, written straight to the element's style on animation frames —
 * no React render per frame. CSS turns `--p` into transforms and opacity. Only the active chapter
 * index (from `data-chapters`, default 1 per act) goes through React state, and only when it changes.
 *
 * Disabled (reduced motion), every act is pinned at `--p: 1` — the finished state — and nothing listens.
 */
export function useScrollStory(root: RefObject<HTMLElement | null>, enabled: boolean): number {
  const [active, setActive] = useState(0);
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const acts = Array.from(el.querySelectorAll<HTMLElement>('[data-act]'));
    if (!enabled) {
      acts.forEach((a) => a.style.setProperty('--p', '1'));
      return;
    }
    let raf = 0;
    let current = -1;
    const update = () => {
      raf = 0;
      const vh = window.innerHeight;
      const top = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--topbar-h')) || 0;
      let chapterBase = 0;
      let next = current < 0 ? 0 : current;
      for (const a of acts) {
        const r = a.getBoundingClientRect();
        // a pinned stage (height vh − top bar) is stuck from r.top = top until r.bottom = vh
        const span = Math.max(1, r.height - (vh - top));
        const p = Math.min(1, Math.max(0, (top - r.top) / span));
        a.style.setProperty('--p', p.toFixed(4));
        const chapters = Number(a.dataset.chapters ?? 1);
        if (r.top <= vh * 0.5 && r.bottom > vh * 0.5) next = chapterBase + Math.min(chapters - 1, Math.floor(p * chapters));
        chapterBase += chapters;
      }
      if (next !== current) {
        current = next;
        setActive(next);
      }
    };
    const schedule = () => {
      if (!raf) raf = requestAnimationFrame(update);
    };
    update();
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
    };
  }, [root, enabled]);
  return active;
}
