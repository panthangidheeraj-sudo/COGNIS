/**
 * The official COGNIS logo (Atlas carrying the celestial letter C): the component that draws it, where it is used, and the artwork files.
 *
 * jsdom loads no images and no stylesheets, so the guarantees are pinned from three sides: what the components render (source, size,
 * alt text, theme variant), what the files on disk are (real PNG headers and dimensions, the favicon links all resolve), and where the
 * placeholder mark is gone. The rendering itself was checked in a real browser in dark and light, at 1x and 2x, on desktop and phone widths.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, screen } from '@testing-library/react';
import { renderWithProviders } from './utils';
// @ts-expect-error -- this project has no @types/node; vitest runs in Node, so the module exists at runtime
import { readFileSync, existsSync } from 'node:fs';
import { usePreferences } from '@/stores/preferences';
import { CognisLogo, LOGO_ASPECT, logoSrc } from '@/components/common/CognisLogo';
import { Rail } from '@/components/navigation/Rail';
import { TopBar } from '@/components/navigation/TopBar';

/* ------------------------------------------------------------------ file helpers -- */
const url = (path: string) => new URL(path, import.meta.url);
const text = (path: string): string => readFileSync(url(path), 'utf8') as string;
const bytes = (path: string): Uint8Array => new Uint8Array(readFileSync(url(path)) as ArrayLike<number>);
const exists = (path: string): boolean => existsSync(url(path)) as boolean;
const BRAND = '../../public/brand/';

/** Width, height and colour type read from a PNG's IHDR chunk (and the 8-byte signature checked). */
function png(path: string) {
  const b = bytes(path);
  const sig = [137, 80, 78, 71, 13, 10, 26, 10];
  expect(Array.from(b.slice(0, 8)), `${path} is a PNG`).toEqual(sig);
  const v = new DataView(b.buffer, b.byteOffset, b.byteLength);
  return { width: v.getUint32(16), height: v.getUint32(20), colorType: b[25] }; // colour type 2 = RGB, 6 = RGBA
}

afterEach(() => {
  usePreferences.setState({ theme: 'dark' });
  vi.unstubAllGlobals();
});

/* -------------------------------------------------------------- the component -- */
describe('CognisLogo', () => {
  it('draws the ivory emblem on the dark theme and the navy emblem on the light theme', () => {
    const { container } = renderWithProviders(<CognisLogo height={56} compact />);
    const img = container.querySelector('img')!;
    expect(img.getAttribute('src')).toMatch(/brand\/cognis-atlas-ivory-sm\.png$/);
    expect(img.dataset.logo).toBe('ivory');
    act(() => usePreferences.getState().set({ theme: 'light' }));
    expect(container.querySelector('img')!.getAttribute('src')).toMatch(/brand\/cognis-atlas-navy-sm\.png$/);
    expect(container.querySelector('img')!.dataset.logo).toBe('navy');
  });

  it('follows the operating system when the theme is "system"', () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('light'), media: q, addEventListener: () => undefined, removeEventListener: () => undefined }) as unknown as MediaQueryList);
    usePreferences.setState({ theme: 'system' });
    const { container } = renderWithProviders(<CognisLogo compact />);
    expect(container.querySelector('img')!.dataset.logo).toBe('navy');
  });

  it('lets a placement force one variant', () => {
    const { container } = renderWithProviders(<CognisLogo variant="navy" compact />);
    expect(container.querySelector('img')!.dataset.logo).toBe('navy'); // dark theme, but forced
  });

  it('keeps the artwork proportions and reserves the exact box (no stretching, no layout shift)', () => {
    const { container } = renderWithProviders(<CognisLogo height={100} compact />);
    const img = container.querySelector('img')!;
    expect(Number(img.getAttribute('height'))).toBe(100);
    expect(Number(img.getAttribute('width'))).toBe(Math.round(100 * LOGO_ASPECT));
    expect(img.getAttribute('width')).toBe('62');
  });

  it('uses the pre-sized files for small placements and the full-size files for large ones', () => {
    expect(logoSrc('navy', 24)).toMatch(/cognis-atlas-navy-sm\.png$/);
    expect(logoSrc('navy', 64)).toMatch(/cognis-atlas-navy-sm\.png$/);
    expect(logoSrc('ivory', 65)).toMatch(/cognis-atlas-ivory\.png$/);
    expect(logoSrc('ivory', 240)).not.toMatch(/-sm\./);
  });

  it('has alt text by default and none when a parent already names it', () => {
    const { rerender } = renderWithProviders(<CognisLogo compact />);
    expect(screen.getByRole('img', { name: 'COGNIS' })).toBeInTheDocument();
    rerender(<CognisLogo compact decorative />);
    expect(screen.queryByRole('img')).toBeNull(); // alt="" → presentational
  });

  it('is icon only: the image is never paired with text unless the placement asks for the name', () => {
    const { container, rerender } = renderWithProviders(<CognisLogo compact />);
    expect(container.querySelector('.cg-logo-word')).toBeNull();
    rerender(<CognisLogo />);
    expect(container.querySelector('.cg-logo-word')?.textContent).toBe('COGNIS'); // live text beside the emblem, not part of the artwork
  });
});

/* --------------------------------------------------------------- placements -- */
describe('where the logo appears', () => {
  it('sidebar: the home link carries the emblem, is still named "COGNIS home" and is not announced twice', () => {
    renderWithProviders(<Rail />, { route: '/library' });
    const home = screen.getByRole('link', { name: 'COGNIS home' });
    const img = home.querySelector('img')!;
    expect(img).toBeTruthy();
    expect(img.getAttribute('src')).toMatch(/brand\/cognis-atlas-ivory-sm\.png$/);
    expect(img.getAttribute('alt')).toBe('');
    expect(Number(img.getAttribute('height'))).toBe(56);
    expect(home.querySelector('.cg-logo-word')).toBeNull(); // the rail is icon only
    expect(home.querySelector('svg')).toBeNull(); // the old placeholder rings are gone
  });

  it('application header (phone widths): the emblem with the COGNIS name as live text, linked home', () => {
    renderWithProviders(<TopBar />);
    const home = screen.getByRole('link', { name: 'COGNIS home' });
    const img = home.querySelector('img')!;
    expect(img.getAttribute('src')).toMatch(/brand\/cognis-atlas-ivory-sm\.png$/);
    expect(Number(img.getAttribute('height'))).toBe(34);
    expect(home.querySelector('svg')).toBeNull();
    expect(home.textContent).toBe('COGNIS');
  });

  it('the placeholder logo is gone and the old favicon is no longer linked', () => {
    expect(text('../components/common/Motif.tsx')).not.toMatch(/export function CognisLogo/); // the ring placeholder logo lived here
    expect(text('../components/navigation/Rail.tsx')).toMatch(/from '@\/components\/common\/CognisLogo'/);
    expect(text('../components/navigation/TopBar.tsx')).toMatch(/from '@\/components\/common\/CognisLogo'/);
    expect(text('../../index.html')).not.toMatch(/cognis-mark/);
  });

  it('the rail slot is tall enough for a portrait emblem and the image is contained, not cropped', () => {
    const css = (p: string) => text(p).replace(/\/\*[\s\S]*?\*\//g, '');
    expect(css('../styles/shell.css')).toMatch(/\.rail-logo\s*\{[^}]*height:\s*66px/);
    expect(css('../styles/app.css')).toMatch(/\.cg-logo-img\s*\{[^}]*object-fit:\s*contain/);
  });
});

/* ------------------------------------------------------------- the files -- */
describe('logo artwork in public/brand', () => {
  it('keeps the supplied artwork untouched as the source', () => {
    expect(png(`${BRAND}cognis-atlas-reference.png`)).toEqual({ width: 1254, height: 1254, colorType: 2 });
  });

  it('has transparent navy and ivory versions of the same cropped emblem', () => {
    for (const name of ['navy', 'ivory']) {
      const full = png(`${BRAND}cognis-atlas-${name}.png`);
      const small = png(`${BRAND}cognis-atlas-${name}-sm.png`);
      expect(full.colorType, `${name} has an alpha channel`).toBe(6);
      expect(small.colorType).toBe(6);
      expect(full.width / full.height).toBeCloseTo(LOGO_ASPECT, 3);
      expect(small.width / small.height).toBeCloseTo(LOGO_ASPECT, 2);
      expect(small.height).toBe(160);
    }
    const navy = png(`${BRAND}cognis-atlas-navy.png`);
    const ivory = png(`${BRAND}cognis-atlas-ivory.png`);
    expect([navy.width, navy.height]).toEqual([ivory.width, ivory.height]); // same silhouette, colours swapped
  });

  it('has favicon and app-icon files at the right sizes', () => {
    const sizes: Record<string, number> = { 'favicon-16.png': 16, 'favicon-32.png': 32, 'favicon-48.png': 48, 'apple-touch-icon.png': 180, 'icon-192.png': 192, 'icon-512.png': 512 };
    for (const [file, size] of Object.entries(sizes)) {
      const p = png(`${BRAND}${file}`);
      expect([p.width, p.height], file).toEqual([size, size]);
    }
    const ico = bytes(`${BRAND}favicon.ico`);
    expect(Array.from(ico.slice(0, 4))).toEqual([0, 0, 1, 0]); // ICONDIR: reserved 0, type 1 (icon)
    expect(ico[4]).toBe(3); // 16, 32 and 48 px
  });

  it('wires every icon through index.html and the manifest, and every referenced file exists', () => {
    const html = text('../../index.html');
    const hrefs = [...html.matchAll(/<link[^>]+rel="(?:icon|apple-touch-icon)"[^>]+href="([^"]+)"/g)].map((m) => m[1]);
    expect(hrefs.sort()).toEqual(['/brand/apple-touch-icon.png', '/brand/favicon-16.png', '/brand/favicon-32.png', '/brand/favicon.ico']);
    for (const href of hrefs) expect(exists(`../../public${href}`), href).toBe(true);
    expect(html).toMatch(/<link rel="manifest" href="\/manifest\.webmanifest"/);
    const manifest = JSON.parse(text('../../public/manifest.webmanifest')) as { icons: { src: string; sizes: string }[] };
    expect(manifest.icons.map((i) => i.sizes)).toEqual(['192x192', '512x512']);
    for (const icon of manifest.icons) expect(exists(`../../public${icon.src}`), icon.src).toBe(true);
  });
});
