import { decodeLandDots } from './landDots';

/**
 * The land dots share one lattice (scripts/generate-geo.mjs): rows STEP degrees apart from -58 to 82, and along a
 * row the dots sit STEP / cos(lat) degrees apart, so they stay evenly spaced on the sphere.
 *
 * The WebGL globe and the static fallback both draw these dots. Big globes use all of them; small ones (Discover,
 * phones) would turn the same dots into grain, so they use every other row and column (a 2.2° lattice). The dots
 * are ordered so that the coarse lattice comes first: a draw range picks the density without a second buffer.
 */
const STEP = 1.1;
const LAT0 = -58;

/** Sphere radius, in CSS pixels, from which the full lattice is legible (dots are about 3.6 px apart or more). */
export const FULL_LATTICE_MIN_RADIUS = 190;

export interface OrderedDots {
  /** flat [lat, lon, ...] in degrees; the first `coarse` dots form the 2.2° lattice */
  positions: Float32Array;
  coarse: number;
  total: number;
}

let cached: OrderedDots | null = null;

export function orderedLandDots(): OrderedDots {
  if (cached) return cached;
  const d = decodeLandDots();
  const a: number[] = [];
  const b: number[] = [];
  for (let i = 0; i < d.length; i += 2) {
    const lat = d[i];
    const lon = d[i + 1];
    const row = Math.round((lat - LAT0) / STEP);
    const lonStep = STEP / Math.max(0.18, Math.cos((lat * Math.PI) / 180));
    const col = Math.round((lon + 180) / lonStep);
    (row % 2 === 0 && col % 2 === 0 ? a : b).push(lat, lon);
  }
  const positions = new Float32Array(a.length + b.length);
  positions.set(a, 0);
  positions.set(b, a.length);
  cached = { positions, coarse: a.length / 2, total: positions.length / 2 };
  return cached;
}

/** How many of the ordered dots a sphere of this on-screen radius (CSS px) should draw. */
export function dotCountForRadius(dots: OrderedDots, radiusPx: number) {
  return radiusPx >= FULL_LATTICE_MIN_RADIUS ? dots.total : dots.coarse;
}

/** Dot diameter in CSS pixels for a sphere of this on-screen radius: fine, never smaller than a legible speck, and large
 *  enough (about 40% of the spacing on the big globe) that the land reads as bright ivory rather than grey dust. */
export function dotSizeForRadius(radiusPx: number) {
  return Math.min(2.9, Math.max(1.4, radiusPx * 0.0086));
}

/** Deterministic per-dot value in [0, 1): slight variation in size and brightness, identical in WebGL and the fallback. */
export function dotSeed(i: number) {
  const v = (Math.sin(i * 12.9898) * 43758.5453) % 1;
  return v < 0 ? v + 1 : v;
}

/**
 * How a dot behaves towards the limb, where the lattice foreshortens into dense bands: it dissolves between these
 * facing values (1 = facing the viewer, 0 = on the edge) and shrinks to `sizeFloor` of its size. One set of numbers for
 * the WebGL points and the static fallback.
 */
export const DOT_LIMB = { fadeStart: 0.09, fadeEnd: 0.56, sizeFloor: 0.45 } as const;
