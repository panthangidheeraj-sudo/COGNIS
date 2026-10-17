/**
 * Globe refinement: the workspace globe is the monochrome "intel" look: a bright ivory-white sphere (white oceans) with navy-ink
 * geography. The natural Earth (blue ocean) is for the About story only.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import { renderWithProviders } from './utils';
import { GlobeStage } from '@/components/globe/GlobeStage';
import AboutPage from '@/pages/Settings/AboutPage';
import { DEG, latLonXYZ, SPHERE_RADIUS, targetRotation } from '@/components/globe/globeMath';
import { DOT_LIMB, dotCountForRadius, dotSeed, dotSizeForRadius, FULL_LATTICE_MIN_RADIUS, orderedLandDots } from '@/components/globe/dotLattice';
import { INTEL_DARK, INTEL_LIGHT, intelLit } from '@/components/globe/intelPalette';
import intelSurfaceSource from '@/components/globe/surfaces/intelSurface.ts?raw';
import intelGlobeSource from '@/components/globe/IntelGlobe.tsx?raw';
import fallbackSource from '@/components/globe/GlobeFallback.tsx?raw';
import earthSurfaceSource from '@/components/globe/surfaces/earthSurface.ts?raw';
import { GlobeFallback } from '@/components/globe/GlobeFallback';

describe('GlobeStage variants', () => {
  beforeEach(() => {
    // jsdom has no canvas: the static fallback simply has nothing to draw into
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  });
  afterEach(() => vi.restoreAllMocks());

  it('is the monochrome intelligence globe by default', () => {
    const { container } = render(<GlobeStage className="hero-globe" />);
    const stage = container.querySelector('.globe-stage')!;
    expect(stage).toHaveClass('globe-stage--intel');
    expect(stage).not.toHaveClass('globe-stage--earth');
    expect(stage).toHaveClass('hero-globe');
  });

  it('keeps the natural Earth available as the earth variant', () => {
    const { container } = render(<GlobeStage variant="earth" />);
    expect(container.querySelector('.globe-stage')).toHaveClass('globe-stage--earth');
  });

  it('uses the natural Earth only in the About story', () => {
    const { container } = renderWithProviders(<AboutPage />);
    const globe = container.querySelector('.story-globe')!;
    expect(globe).toHaveClass('globe-stage--earth');
    expect(container.querySelectorAll('.globe-stage--intel')).toHaveLength(0);
  });

  it('never pulls the Earth imagery into the monochrome globe', () => {
    for (const src of [intelSurfaceSource, intelGlobeSource, fallbackSource.split('function drawEarth')[0]]) {
      expect(src).not.toMatch(/earth-(day|clouds)/);
    }
    expect(intelSurfaceSource).toContain('land-mask-2k.png');
  });
});

describe('globe maths', () => {
  it('places a coordinate where the shader reads it back: x = cos(lat)cos(lon), y = sin(lat), z = -cos(lat)sin(lon)', () => {
    for (const [lat, lon] of [
      [59.9, 10.7],
      [-33.9, 151.2],
      [0, -180],
      [40.7, -74],
    ]) {
      const [x, y, z] = latLonXYZ(lat, lon);
      expect(Math.hypot(x, y, z)).toBeCloseTo(1, 6);
      expect(x).toBeCloseTo(Math.cos(lat * DEG) * Math.cos(lon * DEG), 6);
      expect(y).toBeCloseTo(Math.sin(lat * DEG), 6);
      expect(z).toBeCloseTo(-Math.cos(lat * DEG) * Math.sin(lon * DEG), 6);
    }
  });

  it('turns towards a location and clamps the tilt', () => {
    expect(targetRotation(60, 10).x).toBeCloseTo(60 * DEG * 0.82, 6);
    expect(targetRotation(89, 0).x).toBeLessThanOrEqual(0.9);
    expect(targetRotation(-89, 0).x).toBeGreaterThanOrEqual(-0.9);
  });

  it('keeps the static fallback the same size as the WebGL sphere', () => {
    expect(SPHERE_RADIUS).toBe(0.375);
  });
});

describe('land dot lattice', () => {
  const dots = orderedLandDots();

  it('orders the coarse lattice first, about a quarter of the dots', () => {
    expect(dots.total).toBeGreaterThan(8000);
    expect(dots.coarse).toBeGreaterThan(dots.total * 0.18);
    expect(dots.coarse).toBeLessThan(dots.total * 0.32);
    expect(dots.positions).toHaveLength(dots.total * 2);
  });

  it('draws the full lattice on big globes and the coarse one on small globes', () => {
    expect(dotCountForRadius(dots, FULL_LATTICE_MIN_RADIUS)).toBe(dots.total);
    expect(dotCountForRadius(dots, 307)).toBe(dots.total); // Home hero
    expect(dotCountForRadius(dots, 105)).toBe(dots.coarse); // Discover
  });

  it('keeps dots fine at every size, and big enough on the hero globe for the land to read as ivory', () => {
    for (const r of [60, 105, 190, 307, 600]) {
      const d = dotSizeForRadius(r);
      expect(d).toBeGreaterThanOrEqual(1.4);
      expect(d).toBeLessThanOrEqual(2.9);
    }
    expect(dotSizeForRadius(307)).toBeGreaterThan(2.2); // Home hero: about 40% of the dot spacing
    expect(dotSizeForRadius(307)).toBeLessThan(3); // still dots, never blobs
  });

  it('fades dots out towards the limb with one set of numbers for WebGL and the static fallback', () => {
    expect(DOT_LIMB.fadeStart).toBeGreaterThan(0);
    expect(DOT_LIMB.fadeEnd).toBeGreaterThan(DOT_LIMB.fadeStart);
    expect(DOT_LIMB.sizeFloor).toBeGreaterThan(0);
    expect(DOT_LIMB.sizeFloor).toBeLessThan(1);
    expect(intelSurfaceSource).toContain('DOT_LIMB');
    expect(fallbackSource).toContain('DOT_LIMB');
  });

  it('is deterministic', () => {
    expect(dotSeed(12)).toBe(dotSeed(12));
    for (let i = 0; i < 500; i++) {
      const s = dotSeed(i);
      expect(s).toBeGreaterThanOrEqual(0);
      expect(s).toBeLessThan(1);
    }
  });
});

describe('intel palette', () => {
  it('shades from the dark side to the lit side', () => {
    expect(intelLit(-1)).toBe(0);
    expect(intelLit(1)).toBe(1);
    expect(intelLit(0.2)).toBeGreaterThan(intelLit(-0.1));
  });

  const lum = (hex: string) => parseInt(hex.slice(1, 3), 16) * 0.299 + parseInt(hex.slice(3, 5), 16) * 0.587 + parseInt(hex.slice(5, 7), 16) * 0.114;
  const saturation = (hex: string) => {
    const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
    return (Math.max(...c) - Math.min(...c)) / Math.max(...c);
  };

  it('is an ivory-white sphere with navy-ink geography, and the exact inverse (a navy sphere with ivory-ink geography) on the light theme', () => {
    expect(lum(INTEL_DARK.mid)).toBeGreaterThan(235); // bright ivory-white ocean (the lit side)
    expect(lum(INTEL_DARK.deep)).toBeGreaterThan(170); // even the shaded side is light: the ocean never reads as dark blue
    expect(lum(INTEL_DARK.ink)).toBeLessThan(60); // navy land, coast and dots
    expect(lum(INTEL_LIGHT.mid)).toBeLessThan(80); // navy ocean (the lit side)
    expect(lum(INTEL_LIGHT.deep)).toBeLessThan(lum(INTEL_LIGHT.mid)); // the shaded side is deeper still
    expect(lum(INTEL_LIGHT.ink)).toBeGreaterThan(200); // ivory land, coast and dots
    // restrained: a soft rim, a crisp but never solid coast, no glow
    for (const p of [INTEL_DARK, INTEL_LIGHT]) {
      expect(p.rimAmount).toBeLessThan(0.5);
      expect(p.haloStrength).toBeLessThan(0.2);
      expect(p.coast).toBeLessThan(0.95);
    }
  });

  const contrast = (a: string, b: string) => {
    const channel = (v: number) => (v / 255 <= 0.03928 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4);
    const rl = (hex: string) => [1, 3, 5].map((i) => channel(parseInt(hex.slice(i, i + 2), 16))).reduce((acc, c, i) => acc + c * [0.2126, 0.7152, 0.0722][i], 0);
    const [hi, lo] = [rl(a), rl(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
  };

  it('makes the ocean of the dark theme white, with enough contrast against the land for the geography to stay readable', () => {
    // bright ivory-white: warm (red >= blue), not a grey and not a blue
    const [r, , b] = [1, 3, 5].map((i) => parseInt(INTEL_DARK.mid.slice(i, i + 2), 16));
    expect(r).toBeGreaterThanOrEqual(b);
    expect(lum(INTEL_DARK.mid)).toBeGreaterThan(lum(INTEL_LIGHT.mid)); // brighter than the ivory theme's paper sphere
    // land against ocean: the lit and the shaded side both keep strong contrast
    expect(contrast(INTEL_DARK.ink, INTEL_DARK.mid)).toBeGreaterThan(12);
    expect(contrast(INTEL_DARK.ink, INTEL_DARK.deep)).toBeGreaterThan(7);
    // the dots, the coast and the faint inland contour are the dark things on the white
    expect(INTEL_DARK.dotOpacity).toBeGreaterThanOrEqual(0.9);
    expect(INTEL_DARK.dotFloor).toBeGreaterThanOrEqual(0.55); // dots stay clear on the shaded side too
    expect(INTEL_DARK.coast).toBeGreaterThanOrEqual(0.5);
    expect(INTEL_DARK.fill).toBeGreaterThan(0); // land carries a faint tone so the continents read before the dots do
    expect(INTEL_DARK.contour).toBeGreaterThan(0);
    expect(INTEL_DARK.contour).toBeLessThan(0.35); // a faint echo of the coast, not a second outline
    // no navy ocean left anywhere in the dark palette
    for (const hex of [INTEL_DARK.deep, INTEL_DARK.mid]) expect(lum(hex)).toBeGreaterThan(170);
  });

  it('keeps the rim a soft neutral shade and the halo a faint silver: never a blue glow', () => {
    expect(saturation(INTEL_DARK.halo)).toBeLessThan(0.12); // neutral: no blue cast
    expect(lum(INTEL_DARK.halo)).toBeGreaterThan(190);
    expect(saturation(INTEL_DARK.rim)).toBeLessThan(0.25);
    expect(lum(INTEL_DARK.rim)).toBeGreaterThan(100); // a shade that rounds the limb, not a dark outline
    expect(INTEL_DARK.rimAmount).toBeLessThanOrEqual(0.45);
    expect(INTEL_DARK.rimPower).toBeGreaterThanOrEqual(3); // hugs the limb
    expect(INTEL_DARK.haloStrength).toBeLessThanOrEqual(0.1);
  });
});

describe('white oceans on the Home and Discover globe', () => {
  /** A 2D context that keeps what the globe puts on it: the shaded sphere (ImageData) and every gradient stop. */
  function recordingContext() {
    const rec = { image: null as ImageData | null, stops: [] as string[] };
    const gradient = { addColorStop: (_o: number, c: string) => void rec.stops.push(c) };
    const ctx = {
      createImageData: (w: number, h: number) => ({ data: new Uint8ClampedArray(w * h * 4), width: w, height: h }),
      putImageData: (img: ImageData) => void (rec.image = img),
      createRadialGradient: () => gradient,
      createLinearGradient: () => gradient,
      save() {}, restore() {}, scale() {}, beginPath() {}, arc() {}, fill() {},
      fillStyle: '', globalAlpha: 1, globalCompositeOperation: 'source-over',
    };
    return { ctx, rec };
  }
  const paint = (theme: 'dark' | 'light', variant: 'intel' | 'earth') => {
    const { ctx, rec } = recordingContext();
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(ctx as unknown as CanvasRenderingContext2D);
    render(<GlobeFallback variant={variant} theme={theme} lat={25} lon={14} />);
    vi.restoreAllMocks();
    return rec;
  };
  const lumAt = (img: ImageData, x: number, y: number) => {
    const i = (y * img.width + x) * 4;
    return img.data[i] * 0.299 + img.data[i + 1] * 0.587 + img.data[i + 2] * 0.114;
  };
  /** Mean luminance of the opaque sphere pixels. */
  const sphereLum = (img: ImageData) => {
    let sum = 0;
    let n = 0;
    for (let i = 0; i < img.data.length; i += 4) {
      if (img.data[i + 3] < 250) continue;
      sum += img.data[i] * 0.299 + img.data[i + 1] * 0.587 + img.data[i + 2] * 0.114;
      n++;
    }
    return { mean: sum / n, n };
  };

  it('paints the dark-theme sphere bright ivory-white, from the lit face to the shaded limb', () => {
    const { image } = paint('dark', 'intel');
    expect(image).not.toBeNull();
    const img = image!;
    const c = img.width / 2;
    const R = img.width * SPHERE_RADIUS;
    expect(lumAt(img, Math.round(c - R * 0.35), Math.round(c - R * 0.3))).toBeGreaterThan(225); // lit face: ivory-white
    expect(lumAt(img, Math.round(c + R * 0.6), Math.round(c + R * 0.4))).toBeGreaterThan(170); // shaded side: still light, never navy
    const { mean, n } = sphereLum(img);
    expect(n).toBeGreaterThan(100000);
    expect(mean).toBeGreaterThan(205); // the sphere as a whole is white, not a dark ball with white dots
  });

  it('is not the navy ocean any more, and is still lit from one side so it reads as a sphere', () => {
    const { image } = paint('dark', 'intel');
    const img = image!;
    const c = img.width / 2;
    const R = img.width * SPHERE_RADIUS;
    const litSide = lumAt(img, Math.round(c - R * 0.5), Math.round(c - R * 0.4));
    const shadeSide = lumAt(img, Math.round(c + R * 0.75), Math.round(c + R * 0.45));
    expect(litSide - shadeSide).toBeGreaterThan(15); // subtle lighting survives: visible fall-off across the sphere
    expect(litSide - shadeSide).toBeLessThan(120); // ... but it is shading, not a dark half
  });

  it('makes the light theme the inverse of the dark one: a navy sphere, far darker than the dark theme white', () => {
    const light = sphereLum(paint('light', 'intel').image!).mean;
    const dark = sphereLum(paint('dark', 'intel').image!).mean;
    expect(light).toBeLessThan(90);
    expect(dark).toBeGreaterThan(190);
    expect(light).toBeLessThan(dark);
  });

  it('draws no hard-coded ocean, and gives the markers the ink of the sphere they sit on (navy on the pale sphere, ivory on the navy one)', () => {
    expect(intelSurfaceSource).not.toMatch(/#03060c/i); // the old ocean colour
    expect(intelSurfaceSource).toMatch(/uMid/); // the ocean colour comes from the palette
    expect(intelSurfaceSource).toMatch(/pal\.mid/);
    // ivory markers exist only in the light-theme branch; the dark-theme branch keeps navy ink
    const markers = /markers:\s*light\s*\?\s*\{([^}]*)\}\s*:\s*\{([^}]*)\}/.exec(intelSurfaceSource);
    expect(markers).not.toBeNull();
    expect(markers![1]).toMatch(/#f4efe3/i);
    expect(markers![2]).not.toMatch(/#f4efe3|#ffffff/i);
    expect(markers![2]).toMatch(/#16243d/i);
  });

  it('leaves the natural Earth of the About page unchanged: blue ocean, its own surface, none of the intel palette', () => {
    expect(earthSurfaceSource).not.toMatch(/intelPalette|INTEL_/);
    expect(fallbackSource).toContain("'#14467f'"); // the blue ocean gradient of drawEarth
    const { stops } = paint('dark', 'earth');
    expect(stops).toEqual(expect.arrayContaining(['#2a6db0', '#14467f', '#071d3a']));
    const { stops: lightStops } = paint('light', 'earth');
    expect(lightStops).toEqual(expect.arrayContaining(['#2a6db0', '#14467f', '#071d3a']));
  });
});
