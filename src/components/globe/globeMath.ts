/**
 * Pure globe maths. No three.js import: the static fallback and the stage use this, and three must stay in the lazy chunk.
 */
export const DEG = Math.PI / 180;

/** On-screen radius of the sphere as a fraction of the canvas size (the static fallback is drawn to match). */
export const SPHERE_RADIUS = 0.375;

/** Position of a WGS84 coordinate on a sphere of radius r, in the globe's own (unrotated) frame. */
export function latLonXYZ(lat: number, lon: number, r = 1): [number, number, number] {
  const phi = (90 - lat) * DEG;
  const theta = (lon + 180) * DEG;
  return [-r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta)];
}

/** Globe yaw/pitch that brings a coordinate to the centre of the view. */
export function targetRotation(lat: number, lon: number) {
  const [x, , z] = latLonXYZ(0, lon);
  const alpha = Math.atan2(x, z);
  return { y: -alpha, x: Math.max(-0.9, Math.min(0.9, lat * DEG * 0.82)) };
}

export const wrap = (a: number) => Math.atan2(Math.sin(a), Math.cos(a));
export const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
