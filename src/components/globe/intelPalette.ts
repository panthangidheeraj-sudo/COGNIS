/**
 * Monochrome "corporate intelligence" globe: deep navy negative space, bright ivory-white geography, a fine silver rim.
 * White/ivory is the dominant colour: land is drawn in ivory dots, a crisp coastline and a faint inland contour, and the
 * ocean stays near-black so the continents carry the picture. No blue glow, no imagery.
 * One palette for the WebGL surface and the static fallback, so the cross-fade between them is invisible.
 * On the ivory (light) theme the same drawing is inverted: a pale paper sphere with navy ink.
 */
export interface IntelPalette {
  deep: string; // the shaded side of the sphere
  mid: string; // the lit side
  ink: string; // dots, coastline, contour
  rim: string; // limb
  rimAmount: number;
  rimPower: number; // higher = a thinner rim hugging the limb
  dotOpacity: number;
  dotFloor: number; // brightness of a dot on the shaded side, as a share of a dot on the lit side
  dotCore: number; // where a dot's soft edge begins (0..1 of its radius): higher = a brighter, crisper dot
  fill: number; // faint tone on land
  coast: number;
  contour: number;
  halo: string;
  haloStrength: number;
}

export const INTEL_DARK: IntelPalette = {
  deep: '#03060c',
  mid: '#0a1220',
  ink: '#f8f4e9',
  rim: '#d6dbe5',
  rimAmount: 0.3,
  rimPower: 4.4,
  dotOpacity: 1,
  dotFloor: 0.72,
  dotCore: 0.76,
  fill: 0.2,
  coast: 0.9,
  contour: 0.24,
  halo: '#d3d9e2',
  haloStrength: 0.08,
};

export const INTEL_LIGHT: IntelPalette = {
  deep: '#cbc7bb',
  mid: '#e6e2d7',
  ink: '#16243d',
  rim: '#556178',
  rimAmount: 0.4,
  rimPower: 3.4,
  dotOpacity: 0.9,
  dotFloor: 0.34,
  dotCore: 0.5,
  fill: 0.07,
  coast: 0.42,
  contour: 0.08,
  halo: '#44516a',
  haloStrength: 0.1,
};

/** Light in view space (upper left, in front): the lit face turns to the reader and the right limb falls into shade. */
export const INTEL_SUN: [number, number, number] = [-0.74, 0.4, 0.54];

/** How lit a surface is, from its normal·sun: the same curve in the shader and in the static fallback. */
export function intelLit(ndl: number) {
  const t = Math.min(1, Math.max(0, (ndl + 0.35) / 1.1));
  return t * t * (3 - 2 * t);
}
