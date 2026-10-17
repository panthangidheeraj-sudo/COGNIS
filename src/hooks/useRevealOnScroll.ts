import { useEffect, useLayoutEffect, type RefObject } from 'react';

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

/* ==========================================================================
   Automatic page reveals
   --------------------------------------------------------------------------
   `useAutoReveal` gives every page the same box-by-box entrance without each page marking up its own boxes. It finds the "blocks" of a page
   (the direct children of a page region, looking inside card grids and lists), hides them in a layout effect (before first paint, so there is
   no flash), and shows each one with the same one-shot IntersectionObserver idea as `useRevealOnScroll`: on screen at load → a short staggered
   sequence in document order; below the fold → when it scrolls into view, once. Nothing is hidden by CSS alone, so with no JS the page is just there.

   States on `data-reveal-auto`: `hidden` (waiting), `in` (transitioning) and `done` (settled; no styles, so hover transitions are the element's own).
   ========================================================================== */

/** Selectors that mark a part of a page whose children are its boxes. */
const REGION = '.page, .hero-inner, .home-body, [role="tabpanel"], [data-reveal-region]';
/** Containers that are never animated or entered: overlays, menus, and the hand-authored About story. */
const SKIP = '.story, [data-reveal], [data-reveal-skip], [role="listbox"], [role="menu"], [role="tooltip"], [role="dialog"], [role="alertdialog"], [popover], [hidden], script, style';
/** A grid / list / stack of related boxes: its children are staggered individually. */
const GROUP_CLASS = /(^|-)(grid|list|stack|cards)$/;
/** Inline rows (toolbars, chip rows, form footers) move as one box, however they are styled. */
const ROW_CLASS = /(^|-)(row|row-wrap|bar|foot|head|actions|toolbar|chips|tabs)$/;
const MAX_DEPTH = 4;
/** A wrapper with no paint of its own is looked through only up to this many children; a longer list is looked through too (see MAX_BLOCKS), item by item. */
export const MAX_GROUP = 24;
/** A box taller than this (CSS px) that holds several children is a *section*: its children are the boxes, so a long page is never revealed as one slab. */
export const TALL_PX = 520;
/** At most this many boxes are animated on one page; anything past it is simply shown, so a table of hundreds of rows never queues hundreds of animations. */
export const MAX_BLOCKS = 120;
const STAGGER_CAP = 8;
/** The reveal line sits this far above the bottom edge of the window: a box starts animating once its top edge is inside it, not as it first touches the edge. */
export const TRIGGER_MARGIN = '0px 0px -9% 0px';
/** Longest transition + delay (see reveal.css); after this the element is settled. */
const SETTLE_MS = 1700;

const isGroup = (el: Element) => Array.from(el.classList).some((c) => GROUP_CLASS.test(c));
const isRegion = (el: Element) => el.matches(REGION);

function hasOwnAnimation(el: Element): boolean {
  try {
    const name = getComputedStyle(el).animationName;
    return !!name && name !== 'none';
  } catch {
    return false;
  }
}

/** A pure layout wrapper: no paint of its own (no fill, border or shadow), so its children are the visible boxes. */
function isLayoutWrapper(el: HTMLElement): boolean {
  if (el.children.length < 2) return false;
  if (Array.from(el.classList).some((c) => ROW_CLASS.test(c))) return false;
  if (!/^(DIV|SECTION|FORM|ARTICLE|MAIN)$/.test(el.tagName)) return false;
  try {
    const cs = getComputedStyle(el);
    if (cs.display === 'inline' || cs.display === 'contents') return false;
    const paintless = (cs.backgroundColor === '' || cs.backgroundColor === 'rgba(0, 0, 0, 0)' || cs.backgroundColor === 'transparent') && (cs.backgroundImage === '' || cs.backgroundImage === 'none') && parseFloat(cs.borderTopWidth || '0') === 0 && (cs.boxShadow === '' || cs.boxShadow === 'none');
    return paintless;
  } catch {
    return false;
  }
}

/** A tall box with several children (a results list, a comparison table, a long panel): its children are revealed one by one as they are reached. */
function isSection(el: HTMLElement): boolean {
  if (el.children.length < 1 || !/^(DIV|SECTION|FORM|ARTICLE|UL|OL|TABLE|TBODY|DL)$/.test(el.tagName)) return false;
  try {
    return el.getBoundingClientRect().height > TALL_PX;
  } catch {
    return false;
  }
}

/** The boxes inside `container`, in document order. */
export function collectBlocks(container: Element, out: HTMLElement[] = [], depth = 0): HTMLElement[] {
  for (const child of Array.from(container.children)) {
    if (!(child instanceof HTMLElement) || child.matches(SKIP) || /^(COL|COLGROUP|CAPTION|THEAD|TFOOT)$/.test(child.tagName)) continue;
    const descend = depth < MAX_DEPTH && (((isGroup(child) || isRegion(child)) && child.children.length > 0) || isLayoutWrapper(child) || isSection(child));
    if (descend) {
      collectBlocks(child, out, depth + 1);
    } else if (!child.hasAttribute('data-reveal-auto') && !hasOwnAnimation(child)) {
      out.push(child);
    }
  }
  return out;
}

export function collectPageBlocks(root: Element): HTMLElement[] {
  const regions = Array.from(root.querySelectorAll(REGION)).filter((r) => !r.parentElement?.closest(REGION) || !root.contains(r.parentElement.closest(REGION)));
  const set = new Set<HTMLElement>();
  for (const r of regions) if (!r.closest('.story')) collectBlocks(r).forEach((b) => set.add(b));
  return Array.from(set).filter((b) => !b.parentElement?.closest('[data-reveal-auto]'));
}

/**
 * @param root    the element that holds the page (remount it, e.g. with a `key`, to treat a navigation as a new page)
 * @param enabled false for reduced motion: nothing is hidden or animated
 */
export function useAutoReveal(root: RefObject<HTMLElement | null>, enabled: boolean): void {
  // layout effect: the boxes are hidden before the browser paints the page
  useLayoutEffect(() => {
    const el = root.current;
    if (!el || !enabled || typeof IntersectionObserver === 'undefined') return;
    const timers = new Set<number>();
    const tagged = new Set<HTMLElement>();

    const settle = (b: HTMLElement) => {
      const t = window.setTimeout(() => {
        timers.delete(t);
        if (b.getAttribute('data-reveal-auto') === 'in') b.setAttribute('data-reveal-auto', 'done');
      }, SETTLE_MS);
      timers.add(t);
    };

    const io = new IntersectionObserver(
      (entries) => {
      const shown = entries.filter((e) => e.isIntersecting).map((e) => e.target as HTMLElement);
      shown.sort((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1));
      shown.forEach((b, i) => {
        io.unobserve(b);
        if (b.getAttribute('data-reveal-auto') !== 'hidden') return;
        b.style.setProperty('--reveal-i', String(Math.min(i, STAGGER_CAP)));
        b.setAttribute('data-reveal-auto', 'in');
        settle(b);
      });
      },
      { rootMargin: TRIGGER_MARGIN, threshold: 0 },
    );

    const tag = () => {
      // a box that was small when it was first seen (a loading placeholder) and has since grown into a section hands over to its children, so the content
      // that arrived is revealed piece by piece instead of being treated as part of an already-revealed slab
      tagged.forEach((b) => {
        const st = b.getAttribute('data-reveal-auto');
        if (st === 'in' || !isSection(b)) return;
        io.unobserve(b);
        b.removeAttribute('data-reveal-auto');
        b.style.removeProperty('--reveal-i');
        tagged.delete(b);
      });
      for (const b of collectPageBlocks(el)) {
        if (b.hasAttribute('data-reveal-auto')) continue;
        if (tagged.size >= MAX_BLOCKS) break; // the rest of a very long page is simply there
        b.setAttribute('data-reveal-auto', 'hidden');
        tagged.add(b);
        io.observe(b);
      }
    };
    tag();

    // content that arrives later (data loaded, a tab opened) gets the same treatment; existing boxes are never replayed
    const onScrollRef = { current: () => undefined as void };
    let raf = 0;
    const mo = new MutationObserver(() => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        tag();
        onScrollRef.current();
      });
    });
    mo.observe(el, { childList: true, subtree: true });

    // a box already scrolled past (a jump to the bottom, End key, a restored position) is simply shown: animating what nobody sees would only wait for them to scroll back
    let sweepRaf = 0;
    const sweep = () => {
      sweepRaf = 0;
      // at the very end of the page the reveal line (above the window's bottom edge) can no longer be reached by the last boxes: show them as they come into view
      const root = document.scrollingElement ?? document.documentElement;
      const atEnd = root.scrollHeight - (root.scrollTop + window.innerHeight) < 4;
      tagged.forEach((b) => {
        if (b.getAttribute('data-reveal-auto') !== 'hidden') return;
        const top = b.getBoundingClientRect().top;
        const bottom = b.getBoundingClientRect().bottom;
        if (bottom <= 0) {
          io.unobserve(b);
          b.setAttribute('data-reveal-auto', 'done');
        } else if (atEnd && top < window.innerHeight) {
          io.unobserve(b);
          b.setAttribute('data-reveal-auto', 'in');
          settle(b);
        }
      });
    };
    const onScroll = () => {
      if (!sweepRaf) sweepRaf = requestAnimationFrame(sweep);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    onScrollRef.current = onScroll;
    onScroll(); // a short page that cannot scroll still needs its last boxes shown

    return () => {
      mo.disconnect();
      io.disconnect();
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
      if (raf) cancelAnimationFrame(raf);
      if (sweepRaf) cancelAnimationFrame(sweepRaf);
      timers.forEach((t) => window.clearTimeout(t));
      tagged.forEach((b) => {
        b.removeAttribute('data-reveal-auto');
        b.style.removeProperty('--reveal-i');
      });
    };
  }, [root, enabled]);
}
