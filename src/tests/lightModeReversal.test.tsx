/**
 * Light mode is the intentional inverse of dark mode.
 *
 * jsdom loads no stylesheets (the Vitest CSS pipeline returns empty text), so the colour system is pinned by reading the CSS files from
 * disk: the token blocks, the mirrored `.on-inverse` / `.flip-in-light` scopes, and the rules that must read tokens rather than colours.
 * Behaviour that does run in jsdom (live theme switching, the globe following the theme, the components carrying the scopes) is tested
 * by rendering. The pages themselves were also checked in a real browser, in both themes, at 1440 and 420 px.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, render } from '@testing-library/react';
// @ts-expect-error -- this project has no @types/node; vitest runs in Node, so the module exists at runtime
import { readFileSync, readdirSync, statSync } from 'node:fs';
// @ts-expect-error -- no @types/node (see above)
import { fileURLToPath } from 'node:url';
// @ts-expect-error -- no @types/node (see above)
import { join } from 'node:path';
import { Providers } from '@/app/providers';
import { usePreferences } from '@/stores/preferences';
import { INTEL_DARK, INTEL_LIGHT } from '@/components/globe/intelPalette';

/* ------------------------------------------------------------------ file helpers -- */
const url = (p: string) => new URL(p, import.meta.url);
const read = (p: string): string => readFileSync(url(p), 'utf8') as string;
const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '');
const tokens = strip(read('../styles/tokens.css'));
const ivory = strip(read('../styles/ivory.css'));
const components = strip(read('../styles/components.css'));

/**
 * All .css and .tsx/.ts files under src (excluding tests), as absolute file-system paths. Paths come from `fileURLToPath` and `path.join`
 * (never `URL.pathname`, which on Windows is `/C:/Users/...` and turns into `C:\C:\Users\...`), so this works on any OS and from any checkout.
 */
function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir) as string[]) {
    const child = join(dir, name) as string;
    if (statSync(child).isDirectory()) {
      if (name !== 'tests') walk(child, out);
    } else if (/\.(css|tsx?)$/.test(name)) out.push(child);
  }
  return out;
}
const SRC = walk(fileURLToPath(url('../')) as string);
const sourceOf = (path: string): string => readFileSync(path, 'utf8') as string;

/** The declaration body of the first rule whose header matches `header` (a regex source), balanced on braces. */
function block(css: string, header: RegExp, contains?: string): string {
  const re = new RegExp(header.source, header.flags.includes('g') ? header.flags : header.flags + 'g');
  for (let m = re.exec(css); m; m = re.exec(css)) {
    const start = css.indexOf('{', m.index) + 1;
    let depth = 1;
    let i = start;
    while (depth && i < css.length) (depth += css[i] === '{' ? 1 : css[i] === '}' ? -1 : 0), i++;
    const body = css.slice(start, i - 1);
    if (!contains || body.includes(contains)) return body;
  }
  throw new Error(`block not found: ${header}`);
}
function decls(body: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const d of body.split(/;\s*(?=--|[a-z-]+\s*:)/)) {
    const i = d.indexOf(':');
    if (i > 0) out[d.slice(0, i).trim()] = d.slice(i + 1).trim().replace(/;$/, '').replace(/\s+/g, ' ');
  }
  return out;
}

const rawPalette = decls(block(tokens, /^:root\s*\{/m));
const DARK = decls(block(tokens, /:root,\s*:root\[data-theme='dark'\],/));
const LIGHT = decls(block(tokens, /:root\[data-theme='light'\]\s*\{/, '--bg-canvas'));

/** A token value as #rrggbb, following one level of var(--c-…) into the raw palette. */
function hexOf(theme: Record<string, string>, name: string): string | null {
  let v = theme[name];
  const ref = v && /^var\((--[a-z0-9-]+)\)$/.exec(v);
  if (ref) v = theme[ref[1]] ?? rawPalette[ref[1]];
  return v && /^#[0-9a-f]{6}$/i.test(v) ? v.toLowerCase() : null;
}
const lum = (h: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a: string, b: string) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};
const need = (theme: Record<string, string>, name: string): string => {
  const h = hexOf(theme, name);
  if (!h) throw new Error(`${name} is not a plain colour`);
  return h;
};

afterEach(() => {
  usePreferences.setState({ theme: 'dark' });
  document.documentElement.removeAttribute('data-theme');
  vi.restoreAllMocks();
});

/* ------------------------------------------------------------ token mapping: parity -- */
describe('light and dark define the same semantic tokens', () => {
  // Only the dark block is also used for the mirrored scope, so anything it defines must exist in light too, except tokens that are
  // explicitly dark-page-only (read by the dark-page `.on-inverse` remap in ivory.css) or paper helpers.
  // `--frost-blur` and `--glass-blur` are sizes, not colours: they are the same in both themes and light simply inherits them.
  const DARK_ONLY = new Set(['--ivory-shadow', '--ivory-shadow-lift', '--text-on-paper', '--text-on-paper-2', '--surface-inverse', '--frost-blur', '--glass-blur']);
  it('has every dark token in light', () => {
    const missing = Object.keys(DARK).filter((k) => k.startsWith('--') && !(k in LIGHT) && !DARK_ONLY.has(k));
    expect(missing).toEqual([]);
  });
  it('has no light-only token without a dark counterpart', () => {
    expect(Object.keys(LIGHT).filter((k) => !(k in DARK))).toEqual([]);
  });
  it('mirrors the dark token set into the light page only through the inverse scopes', () => {
    expect(tokens).toMatch(/:root\[data-theme='light'\] :is\(\.on-inverse, \.flip-in-light\)\s*\{/);
  });
});

/* ------------------------------------------------------- token mapping: the inversion -- */
describe('light is the semantic inverse of dark', () => {
  it('puts a deep navy canvas in dark and an ivory canvas in light', () => {
    expect(lum(need(DARK, '--bg-canvas'))).toBeLessThan(0.02);
    expect(lum(need(LIGHT, '--bg-canvas'))).toBeGreaterThan(0.85);
  });
  it('puts navy surfaces in dark and white/ivory surfaces in light, for every surface step', () => {
    for (const t of ['--surface-1', '--surface-2', '--surface-3', '--solid-card', '--chrome-bg']) {
      expect(lum(need(DARK, t)), `dark ${t}`).toBeLessThan(0.03);
      expect(lum(need(LIGHT, t)), `light ${t}`).toBeGreaterThan(0.8);
    }
  });
  it('puts ivory text in dark and navy text in light, for every text step', () => {
    for (const t of ['--text-1', '--text-2', '--text-3', '--text-4']) {
      expect(lum(need(DARK, t)), `dark ${t}`).toBeGreaterThan(0.2);
      expect(lum(need(LIGHT, t)), `light ${t}`).toBeLessThan(0.3);
    }
  });
  it('swaps the primary action: white on dark, navy on light, with readable labels', () => {
    expect(lum(need(DARK, '--primary-bg'))).toBeGreaterThan(0.8);
    expect(lum(need(LIGHT, '--primary-bg'))).toBeLessThan(0.03);
    expect(contrast(need(DARK, '--primary-bg'), need(DARK, '--primary-fg'))).toBeGreaterThanOrEqual(7);
    expect(contrast(need(LIGHT, '--primary-bg'), need(LIGHT, '--primary-fg'))).toBeGreaterThanOrEqual(7);
  });
  it('swaps the emphasis button: ivory on dark, navy on light, with readable labels', () => {
    expect(lum(need(DARK, '--emphasis-bg'))).toBeGreaterThan(0.8);
    expect(lum(need(LIGHT, '--emphasis-bg'))).toBeLessThan(0.05);
    expect(contrast(need(DARK, '--emphasis-bg'), need(DARK, '--emphasis-fg'))).toBeGreaterThanOrEqual(7);
    expect(contrast(need(LIGHT, '--emphasis-bg'), need(LIGHT, '--emphasis-fg'))).toBeGreaterThanOrEqual(7);
  });
  it('swaps the sidebar: bright ink on the dark rail, navy ink on the ivory rail', () => {
    expect(lum(need(DARK, '--nav-fg'))).toBeGreaterThan(0.8);
    expect(lum(need(LIGHT, '--nav-fg'))).toBeLessThan(0.03);
    expect(contrast(need(DARK, '--nav-fg'), need(DARK, '--chrome-bg'))).toBeGreaterThanOrEqual(7);
    expect(contrast(need(LIGHT, '--nav-fg'), need(LIGHT, '--chrome-bg'))).toBeGreaterThanOrEqual(7);
  });
  it('swaps the selected-control treatment: the focus line is ivory on dark and navy on light', () => {
    // --line-focus is an rgba() value in both themes: its channels must be light in dark and dark in light
    const channels = (v: string) => (/rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(v) ?? []).slice(1, 4).map(Number);
    expect(Math.min(...channels(DARK['--line-focus']))).toBeGreaterThan(200);
    expect(Math.max(...channels(LIGHT['--line-focus']))).toBeLessThan(100);
  });
  it('keeps the chart palette legible against its own card in both themes (graphics need 3:1)', () => {
    for (const [name, theme] of [['dark', DARK], ['light', LIGHT]] as const)
      for (const t of ['--chart-1', '--chart-2', '--chart-axis']) expect(contrast(need(theme, t), need(theme, '--surface-1')), `${name} ${t}`).toBeGreaterThanOrEqual(3);
    expect(hexOf(LIGHT, '--chart-2')).toBe('#102a43'); // the main series is navy in light, ivory in dark
    expect(hexOf(DARK, '--chart-2')).toBe('#f7f3ea');
  });
});

/* ----------------------------------------------------------------- accessibility -- */
describe('contrast holds in both themes', () => {
  for (const [name, theme] of [['dark', DARK], ['light', LIGHT]] as const) {
    it(`${name}: body text steps 1-3 meet 4.5:1 on cards and on the canvas; step 4 (placeholders, captions) meets 3:1`, () => {
      for (const bg of ['--surface-1', '--surface-2', '--bg-canvas']) {
        for (const t of ['--text-1', '--text-2', '--text-3']) expect(contrast(need(theme, t), need(theme, bg)), `${t} on ${bg}`).toBeGreaterThanOrEqual(4.5);
        expect(contrast(need(theme, '--text-4'), need(theme, bg)), `--text-4 on ${bg}`).toBeGreaterThanOrEqual(3);
      }
    });
    it(`${name}: success, warning, error and info colours stay legible on cards (4.5:1) with their own per-theme values`, () => {
      for (const t of ['--ok', '--warn', '--err', '--info', '--link']) expect(contrast(need(theme, t), need(theme, '--surface-1')), `${t}`).toBeGreaterThanOrEqual(4.5);
    });
  }
  it('does not simply reuse one theme\'s status colours in the other', () => {
    for (const t of ['--ok', '--warn', '--err', '--info', '--link']) expect(DARK[t], t).not.toBe(LIGHT[t]);
  });
  it('keeps the inverse-scope focus ring visible on the navy surface and on the ivory canvas in light, on ivory and navy in dark', () => {
    const lightRing = decls(block(tokens, /:root\[data-theme='light'\]\s*\{\s*--inverse-ring/))['--inverse-ring'];
    const darkRing = decls(block(tokens, /:root,\s*:root\[data-theme='dark'\]\s*\{\s*--inverse-ring/))['--inverse-ring'];
    expect(contrast(lightRing, need(LIGHT, '--bg-canvas'))).toBeGreaterThanOrEqual(4.5); // the ring sits on the ivory canvas
    expect(contrast(lightRing, need(DARK, '--surface-2'))).toBeGreaterThanOrEqual(3); // …next to a navy field
    expect(contrast(darkRing, need(LIGHT, '--surface-2'))).toBeGreaterThanOrEqual(3); // ivory field on the dark page
    expect(contrast(darkRing, need(DARK, '--surface-1'))).toBeGreaterThanOrEqual(3);
  });
});

/* ---------------------------------------------------------- the mirrored scopes -- */
describe('the inverse scopes', () => {
  const darkPage = decls(block(ivory, /:root:not\(\[data-theme='light'\]\) \.on-inverse\s*\{/));
  const lightPage = decls(block(ivory, /:root\[data-theme='light'\] :is\(\.on-inverse, \.flip-in-light\)\s*\{/));

  it('on the dark page remaps the semantic tokens to ivory ink on ivory', () => {
    expect(darkPage['--surface-2']).toBe('var(--ivory-field)');
    expect(darkPage['--text-1']).toBe('var(--ivory-ink)');
    expect(darkPage['color-scheme']).toBe('light');
    expect(darkPage['--primary-bg']).toBe('#0f1b2a');
  });
  it('on the light page receives the dark tokens (no second copy of the palette) and keeps its own focus ring and soft navy shadows', () => {
    expect(lightPage['--line-focus']).toBe('var(--inverse-ring)');
    expect(lightPage['--shadow-rgb']).toBe('16 42 67');
    // the dark tokens arrive from tokens.css, so the light-page block must not redefine surfaces or text
    for (const t of ['--surface-1', '--surface-2', '--text-1', '--text-2', '--primary-bg']) expect(lightPage[t], t).toBeUndefined();
  });
  it('paints fields, chips, toggles and bars from semantic tokens only, so one rule serves both directions', () => {
    const afterScopes = ivory.slice(ivory.indexOf('/* fields'.slice(0, 0)) + ivory.indexOf('.on-inverse,\n:root[data-theme=\'light\'] .flip-in-light'));
    const rules = afterScopes.replace(/@media \(forced-colors: active\)[\s\S]*$/, '');
    expect(rules).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(rules).not.toMatch(/rgba?\(/i);
    expect(rules).not.toMatch(/--ivory-/);
    expect(rules).toMatch(/var\(--surface-2\)/);
    expect(rules).toMatch(/var\(--line-focus\)/);
  });
  it('gives chips and toggles the inverted selected state and the focus ring in both themes', () => {
    expect(ivory).toMatch(/\.chip\.on-inverse\[aria-pressed='true'\][^{]*\{[^}]*background: var\(--text-1\);[^}]*color: var\(--surface-2\);/);
    expect(ivory).toMatch(/\.segmented\.on-inverse button\[aria-pressed='true'\]\s*\{[^}]*background: var\(--text-1\);/);
    expect(ivory).toMatch(/\.chip\.on-inverse:focus-visible\s*\{[^}]*var\(--line-focus\)/);
    expect(ivory).toMatch(/forced-colors: active/);
  });
  it('gives the About chapters and the Compare summary band the flip scope, and paints them from tokens in light', () => {
    const about = read('../pages/Settings/AboutPage.tsx');
    expect((about.match(/paper flip-in-light/g) ?? []).length).toBe(3);
    const compare = read('../pages/Compare/ComparePage.tsx');
    expect((compare.match(/paper flip-in-light/g) ?? []).length).toBe(3);
    const aboutCss = strip(read('../pages/Settings/about.css'));
    expect(aboutCss).toMatch(/:root\[data-theme='light'\] \.act\.act--evidence\.paper\s*\{\s*background: var\(--surface-1\)/);
    const compareCss = strip(read('../pages/Compare/compare.css'));
    expect(compareCss).toMatch(/:root\[data-theme='light'\] \.cmp-head\.paper,[^{]*\{\s*background: var\(--surface-1\)/);
  });
  it('lets the research source stack use the light-tile treatment only where the page is light and the surface is not inverse (or the reverse)', () => {
    const css = strip(read('../pages/Research/research.css'));
    expect(css).toMatch(/:root\[data-theme='light'\] \.sstack-tile:not\(\.on-inverse \.sstack-tile\),\s*:root:not\(\[data-theme='light'\]\) \.on-inverse \.sstack-tile\s*\{/);
    expect(css).not.toMatch(/:is\(:root\[data-theme='light'\], \.on-inverse\)/);
  });
});

/* ------------------------------------------------- no hard-coded dark-only colours -- */
describe('components read tokens, not colours', () => {
  const files = SRC.filter((f: string) => f.endsWith('.css') && !/[\\/](tokens|ivory)\.css$/.test(f) && !/[\\/]reactbits[\\/]/.test(f)); // reactbits/* is vendored registry source, kept verbatim
  it('has no leftover `on-ivory` scope or `btn--ivory` class anywhere in the source', () => {
    for (const f of SRC) expect(sourceOf(f), f).not.toMatch(/(?<![\w-])on-ivory|btn--ivory/);
  });
  it('draws no shadow in pure black: shadows take their colour and strength from --shadow-rgb / --shadow-k', () => {
    for (const f of files) expect(strip(sourceOf(f)), f).not.toMatch(/rgba\(\s*0\s*,\s*0\s*,\s*0\s*,/);
    expect(DARK['--shadow-rgb']).toBe('0 0 0');
    expect(LIGHT['--shadow-rgb']).toBe('16 42 67');
    expect(Number(LIGHT['--shadow-k'])).toBeLessThan(Number(DARK['--shadow-k']));
  });
  it('takes the cited-fact pulse ring and focus glows from tokens, so they are visible on both canvases', () => {
    expect(strip(read('../styles/base.css'))).not.toMatch(/rgba\(238, 242, 248/);
    expect(strip(read('../styles/base.css'))).toContain('var(--pulse-ring)');
    expect(contrast('#ffffff', need(LIGHT, '--bg-canvas'))).toBeLessThan(contrast('#0f1b2a', need(LIGHT, '--bg-canvas'))); // sanity: an ivory ring would vanish on light
    expect(LIGHT['--pulse-ring']).toMatch(/16, 42, 67/);
    expect(DARK['--pulse-ring']).toMatch(/238, 242, 248/);
    expect(LIGHT['--glow-focus']).toMatch(/16, 42, 67/);
  });
  it('draws the emphasis button from the emphasis tokens, ivory in dark and navy in light', () => {
    const btn = decls(block(components, /\.btn--inverse\s*\{/));
    expect(btn['background']).toBe('var(--emphasis-bg)');
    expect(btn['color']).toBe('var(--emphasis-fg)');
    expect(btn['border-color']).toBe('var(--emphasis-border)');
    expect(components).not.toMatch(/\.btn--inverse[^{]*\{[^}]*#(?:fff|0f1b2a)/i);
  });
  it('keeps the library artwork palette in tokens, with a navy-on-ivory mirror for the light theme', () => {
    const lib = strip(read('../pages/Library/library.css'));
    const dark = decls(block(lib, /^\.thumb\s*\{/m));
    const light = decls(block(lib, /:root\[data-theme='light'\] \.thumb\s*\{/));
    expect(lum(need(dark, '--th-ink'))).toBeGreaterThan(0.8); // ivory marks…
    expect(lum(need(light, '--th-ink'))).toBeLessThan(0.03); // …navy marks in light
    expect(light['background']).toMatch(/#f6f1e6/); // on an ivory tile
  });
});

/* --------------------------------------------------------------------- the globe -- */
describe('the globe follows the theme', () => {
  it('is the exact inverse: ivory sphere with navy ink in dark, navy sphere with ivory ink in light', () => {
    expect(lum(INTEL_DARK.mid)).toBeGreaterThan(0.8);
    expect(lum(INTEL_DARK.ink)).toBeLessThan(0.03);
    expect(lum(INTEL_LIGHT.mid)).toBeLessThan(0.06);
    expect(lum(INTEL_LIGHT.ink)).toBeGreaterThan(0.8);
    // the geography reads against the ocean in both themes
    expect(contrast(INTEL_DARK.ink, INTEL_DARK.mid)).toBeGreaterThanOrEqual(7);
    expect(contrast(INTEL_LIGHT.ink, INTEL_LIGHT.mid)).toBeGreaterThanOrEqual(7);
  });
  it('re-tints live: the stage reads the resolved theme hook (which subscribes to the system setting), not a one-off media query', () => {
    const stage = read('../components/globe/GlobeStage.tsx');
    expect(stage).toContain('useResolvedTheme()');
    expect(stage).not.toMatch(/matchMedia/);
  });
});

/* ------------------------------------------------------------ live theme switching -- */
describe('switching theme', () => {
  const html = () => document.documentElement;

  it('changes the data-theme attribute immediately and without a reload, in both directions', () => {
    render(
      <Providers>
        <div />
      </Providers>,
    );
    act(() => usePreferences.setState({ theme: 'light' }));
    expect(html().getAttribute('data-theme')).toBe('light');
    act(() => usePreferences.setState({ theme: 'dark' }));
    expect(html().getAttribute('data-theme')).toBe('dark');
  });

  it('follows the operating system live while the preference is "system"', () => {
    let listener: (() => void) | undefined;
    const mql = { matches: false, media: '(prefers-color-scheme: light)', addEventListener: (_: string, cb: () => void) => (listener = cb), removeEventListener: () => undefined };
    vi.spyOn(window, 'matchMedia').mockImplementation(() => mql as unknown as MediaQueryList);
    usePreferences.setState({ theme: 'system' });
    render(
      <Providers>
        <div />
      </Providers>,
    );
    expect(html().getAttribute('data-theme')).toBe('dark');
    mql.matches = true;
    act(() => listener?.());
    expect(html().getAttribute('data-theme')).toBe('light');
  });

  it('is applied before first paint by the inline script in index.html, so there is no flash of the wrong theme', () => {
    const index = read('../../index.html');
    expect(index).toMatch(/data-theme/);
    expect(index).toMatch(/prefers-color-scheme/);
  });
});
