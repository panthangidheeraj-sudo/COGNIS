/**
 * Globe refinement: the workspace globe is the monochrome "intel" look; the natural Earth is for the About story only.
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

  it('is a navy sphere with ivory geography, inverted to paper and ink on the light theme', () => {
    expect(lum(INTEL_DARK.mid)).toBeLessThan(40); // near-black navy
    expect(lum(INTEL_DARK.ink)).toBeGreaterThan(220); // ivory
    expect(lum(INTEL_LIGHT.mid)).toBeGreaterThan(200); // paper
    expect(lum(INTEL_LIGHT.ink)).toBeLessThan(60); // navy ink
    // restrained: a faint rim, a crisp but never solid coast, no glow
    for (const p of [INTEL_DARK, INTEL_LIGHT]) {
      expect(p.rimAmount).toBeLessThan(0.5);
      expect(p.haloStrength).toBeLessThan(0.2);
      expect(p.coast).toBeLessThan(0.95);
    }
  });

  it('makes white / ivory the dominant colour of the dark globe, with deep navy negative space', () => {
    // bright ivory-white geography: warm (red >= blue), not a grey and not a blue
    const [r, , b] = [1, 3, 5].map((i) => parseInt(INTEL_DARK.ink.slice(i, i + 2), 16));
    expect(lum(INTEL_DARK.ink)).toBeGreaterThan(235);
    expect(r).toBeGreaterThanOrEqual(b);
    // dots and the coastline are the bright things: dots stay bright on the shaded side too, the coast is crisp
    expect(INTEL_DARK.dotOpacity).toBe(1);
    expect(INTEL_DARK.dotFloor).toBeGreaterThanOrEqual(0.6);
    expect(INTEL_DARK.coast).toBeGreaterThanOrEqual(0.8);
    expect(INTEL_DARK.contour).toBeGreaterThan(0);
    expect(INTEL_DARK.contour).toBeLessThan(0.35); // a faint echo of the coast, not a second outline
    // the ocean and the shaded side are near-black navy
    expect(lum(INTEL_DARK.deep)).toBeLessThan(12);
    expect(lum(INTEL_DARK.mid)).toBeLessThan(30);
  });

  it('keeps the rim and halo silver: thin, faint and never a blue glow', () => {
    for (const hex of [INTEL_DARK.rim, INTEL_DARK.halo]) {
      expect(lum(hex)).toBeGreaterThan(190); // silver, not a colour
      expect(saturation(hex)).toBeLessThan(0.12); // neutral: no blue cast
    }
    expect(INTEL_DARK.rimAmount).toBeLessThanOrEqual(0.35);
    expect(INTEL_DARK.rimPower).toBeGreaterThanOrEqual(4); // hugs the limb
    expect(INTEL_DARK.haloStrength).toBeLessThanOrEqual(0.1);
  });
});
