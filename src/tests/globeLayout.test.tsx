/**
 * Home hero globe: sized and anchored from the hero's own width/height (not the viewport); a dominant Earth on the right that runs past the edge on purpose.
 * jsdom does no layout, so the stylesheet contract is pinned by reading it from disk; the real geometry was measured in Chromium (sphere
 * 1250 / 1020 / 822 / 547 px at 1920×1080 / 1440×900 / 1366×768 / 1100×560, i.e. 1.6–1.85x the previous size; its left edge 16 px clear of the
 * search column; no horizontal page overflow at any of those sizes, nor at 1024×768, 900×800 or 420×860).
 */
import { describe, expect, it } from 'vitest';
// @ts-expect-error -- no @types/node in this project; vitest runs in Node, so the module exists at runtime
import { readFileSync } from 'node:fs';

const css = (p: string): string => readFileSync(new URL(p, import.meta.url), 'utf8') as string;
const home = css('../pages/Home/home.css');
const globe = css('../components/globe/globe.css');
const rule = (src: string, sel: string) => {
  const i = src.indexOf(`${sel} {`);
  return i < 0 ? '' : src.slice(i, src.indexOf('}', i));
};

describe('Home hero globe layout', () => {
  it('the hero is a size container, so the globe follows the space beside the sidebar', () => {
    expect(rule(home, '.hero')).toMatch(/container:\s*hero\s*\/\s*inline-size/);
  });

  it('is sized by container width and by the hero height — never by viewport width — and is clamped', () => {
    const r = rule(home, '.hero .hero-globe');
    expect(r).toMatch(/--globe-s:\s*clamp\(/);
    expect(r).toMatch(/cqw/);
    expect(r).toMatch(/var\(--hero-h\)/);
    expect(r).not.toMatch(/\bvw\b/);
    expect(r).toMatch(/--globe-d:\s*calc\(var\(--globe-s\) \* 4 \/ 3\)/); // the canvas box: the sphere leaves ~1/8 margin on each side inside it
    expect(r).toMatch(/width:\s*var\(--globe-d\)/);
    expect(r).toMatch(/aspect-ratio:\s*1/);
  });

  it('is dramatically larger: up to 1.5x the hero height below the top bar and 1250px (it was capped by the hero height and 900px)', () => {
    const r = rule(home, '.hero .hero-globe');
    expect(r).toMatch(/calc\(\(var\(--hero-h\) - var\(--topbar-h\)\) \* 1\.5\)/);
    expect(r).toMatch(/1250px\);/);
    expect(rule(home, '.hero')).toMatch(/--hero-h:\s*clamp\(460px,[^;]*100px\),\s*920px\)/);
  });

  it('starts just right of the headline and search column, stays at least 60% visible, and sits behind the text', () => {
    const r = rule(home, '.hero .hero-globe');
    expect(r).toMatch(/--globe-left:\s*max\(688px/); // 32px padding + 640px text column + 16px gap
    expect(r).toMatch(/left:\s*calc\(var\(--globe-left\) - var\(--globe-s\) \/ 6\)/);
    expect(r).toMatch(/\/ 0\.6\)/);
    expect(r).toMatch(/z-index:\s*-1/); // behind the heading and search, never over them
  });

  it('runs past the right edge on purpose without a horizontal scroll, and dissolves below the hero instead of ending on a hard line', () => {
    const hero = rule(home, '.hero');
    expect(hero).toMatch(/overflow:\s*hidden;\s*overflow:\s*clip visible/); // clipped sideways (hidden as the fallback), open downwards
    const r = rule(home, '.hero .hero-globe');
    expect(r).toMatch(/mask-image:\s*var\(--globe-mask\)/);
    expect(home).toMatch(/--globe-mask:\s*linear-gradient\(to bottom, #fff 62%[\s\S]*transparent 90%\)/);
    // the rotation control sits on the right of the VISIBLE Earth: 52px in from the hero's right edge, or 60px inside the sphere's right edge if that comes first
    // (measured in Chromium: 35px from the window's right edge, on the sphere and clickable at 1920, 1680, 1440, 1366, 1280, 1100 and 1024 px wide; no sideways scroll)
    const toggle = /\.hero \.hero-globe \.globe-toggle\s*{([^}]*)}/.exec(home)?.[1] ?? '';
    expect(toggle).toMatch(/left:\s*min\(calc\(100cqw \+ 64px - var\(--globe-left\) \+ var\(--globe-s\) \/ 6 - 52px\),\s*calc\(var\(--globe-s\) \* 7 \/ 6 - 60px\)\)/);
    expect(toggle).toMatch(/top:\s*56%/);
    expect(toggle).not.toMatch(/\bvw\b|right:\s*-/);
  });

  it('scales down in a narrow hero (top-right corner, inside the edge, no mask) and stacks above the heading on phones', () => {
    expect(home).toMatch(/@container hero \(max-width: 860px\)\s*{[^}]*\.hero \.hero-globe\s*{[^}]*--globe-d[^}]*left:\s*auto;\s*right:\s*clamp\(8px[^}]*mask-image:\s*none/s);
    expect(home).toMatch(/@media \(max-width: 640px\)[\s\S]*\.hero \.hero-globe\s*{[^}]*position:\s*relative[^}]*width:\s*clamp\(260px,\s*88cqw[^}]*mask-image:\s*none/);
  });

  it('the canvas fills its stage and is resized with it (ResizeObserver)', () => {
    expect(globe).toMatch(/\.globe-canvas canvas\s*{[^}]*width:\s*100%/);
    expect(css('../components/globe/GlobeCanvas.tsx')).toMatch(/new ResizeObserver/);
  });
});
