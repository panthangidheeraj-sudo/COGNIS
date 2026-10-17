/**
 * Monochrome "corporate intelligence" globe: a bright ivory-white sphere with fine navy-ink geography (dots, a crisp coastline, one
 * faint inland contour) and a soft silver rim. The ocean is white, the land is ink, and the shading from lit to shaded side is
 * what makes it a sphere. On the dark workspace the globe is the bright object; on the ivory (light) theme it is the exact
 * inverse: a deep navy sphere with fine ivory geography, so it is the dark object on the light page. No blue glow, no imagery.
 * One palette for the WebGL surface and the static fallback, so the cross-fade between them is invisible.
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
  deep: '#bdbfc3', // the shaded side: silver, still clearly light
  mid: '#faf8f1', // the lit side: bright ivory-white
  ink: '#16243d', // navy ink for the continents
  rim: '#8a94a8', // a soft steel shade at the limb that rounds the sphere
  rimAmount: 0.4,
  rimPower: 3.2,
  dotOpacity: 0.94,
  dotFloor: 0.66,
  dotCore: 0.6,
  fill: 0.1,
  coast: 0.66,
  contour: 0.13,
  halo: '#d9dee7',
  haloStrength: 0.09,
};

/** The mirror of INTEL_DARK: a deep navy sphere with fine ivory geography and a soft steel rim, set on the ivory page. */
export const INTEL_LIGHT: IntelPalette = {
  deep: '#0a1322', // the shaded side: deep ink-navy
  mid: '#22334f', // the lit side: a clear, low-saturation navy
  ink: '#f4efe3', // ivory ink for the continents
  rim: '#8d9bb4', // a soft steel shade at the limb that rounds the sphere
  rimAmount: 0.4,
  rimPower: 3.2,
  dotOpacity: 0.94,
  dotFloor: 0.5,
  dotCore: 0.6,
  fill: 0.1,
  coast: 0.62,
  contour: 0.13,
  halo: '#16243d',
  haloStrength: 0.1,
};

/** Light in view space (upper left, in front): the lit face turns to the reader and the right limb falls into shade. */
export const INTEL_SUN: [number, number, number] = [-0.74, 0.4, 0.54];

/** How lit a surface is, from its normal·sun: the same curve in the shader and in the static fallback. */
export function intelLit(ndl: number) {
  const t = Math.min(1, Math.max(0, (ndl + 0.35) / 1.1));
  return t * t * (3 - 2 * t);
}
