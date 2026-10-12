import { useEffect, useRef } from 'react';
import { decodeLandDots } from './landDots';
import { DOT_LIMB, dotCountForRadius, dotSeed, dotSizeForRadius, orderedLandDots } from './dotLattice';
import { INTEL_DARK, INTEL_LIGHT, INTEL_SUN, intelLit } from './intelPalette';
import { SPHERE_RADIUS } from './globeMath';

/**
 * Static orthographic globe drawn once on a 2D canvas, in the same palette as the WebGL globe it stands in for.
 * Used when WebGL is unavailable, while the 3D chunk loads (the stage cross-fades), or if it fails.
 *  - `intel`: deep navy sphere, bright ivory dots, thin silver rim: the workspace globe (the coastline appears with WebGL).
 *  - `earth`: the natural Earth (blue ocean, green/brown land, white ice, thin atmosphere), for the About story.
 */
export function GlobeFallback({ lat = 25, lon = 14, theme, variant = 'intel' }: { lat?: number; lon?: number; theme: 'dark' | 'light'; variant?: 'intel' | 'earth' }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const size = c.clientWidth || 600;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    c.width = size * dpr;
    c.height = size * dpr;
    const ctx = c.getContext('2d');
    if (!ctx) return;
    if (variant === 'earth') drawEarth(ctx, size, dpr, lat, lon, theme);
    else drawIntel(ctx, size, dpr, lat, lon, theme);
  }, [lat, lon, theme, variant]);
  return <canvas ref={ref} className="globe-fallback" aria-hidden />;
}

const hexRgb = (hex: string): [number, number, number] => [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)];
const mix = (a: number, b: number, t: number) => a + (b - a) * t;

/** Monochrome intelligence globe. The sphere is shaded per pixel with the WebGL shader's own formula, so the cross-fade is seamless. */
function drawIntel(ctx: CanvasRenderingContext2D, size: number, dpr: number, lat: number, lon: number, theme: 'dark' | 'light') {
  const pal = theme === 'light' ? INTEL_LIGHT : INTEL_DARK;
  const sun = INTEL_SUN;
  const sl = Math.hypot(...sun);
  const s: [number, number, number] = [sun[0] / sl, sun[1] / sl, sun[2] / sl];
  const px = size * dpr;
  const R = size * SPHERE_RADIUS * dpr; // device px
  const c = px / 2;
  const deep = hexRgb(pal.deep);
  const mid = hexRgb(pal.mid);
  const rim = hexRgb(pal.rim);

  // sphere: matte fall-off from the lit face into the shade, plus the silver rim
  const img = ctx.createImageData(px, px);
  const lo = Math.max(0, Math.floor(c - R - 2));
  const hi = Math.min(px - 1, Math.ceil(c + R + 2));
  for (let y = lo; y <= hi; y++) {
    for (let x = lo; x <= hi; x++) {
      const nx = (x + 0.5 - c) / R;
      const ny = -(y + 0.5 - c) / R;
      const rr = nx * nx + ny * ny;
      const edge = (1 - Math.sqrt(rr)) * R + 0.5; // pixels inside the silhouette: anti-aliased edge
      if (edge <= 0) continue;
      const nz = Math.sqrt(Math.max(0, 1 - rr));
      const lit = intelLit(nx * s[0] + ny * s[1] + nz * s[2]);
      const fres = Math.pow(1 - nz, pal.rimPower) * pal.rimAmount * (0.35 + 0.65 * lit);
      const i = (y * px + x) * 4;
      for (let k = 0; k < 3; k++) img.data[i + k] = Math.round(mix(mix(deep[k], mid[k], lit), rim[k], fres));
      img.data[i + 3] = Math.round(255 * Math.min(1, edge));
    }
  }
  ctx.putImageData(img, 0, 0);

  // restrained halo, behind the sphere
  ctx.save();
  ctx.scale(dpr, dpr);
  const r = size * SPHERE_RADIUS;
  const cx = size / 2;
  const halo = ctx.createRadialGradient(cx, cx, r * 0.98, cx, cx, r * 1.1);
  const [hr, hg, hb] = hexRgb(pal.halo);
  halo.addColorStop(0, `rgba(${hr},${hg},${hb},${pal.haloStrength * 0.8})`);
  halo.addColorStop(1, `rgba(${hr},${hg},${hb},0)`);
  ctx.globalCompositeOperation = 'destination-over';
  ctx.fillStyle = halo;
  ctx.beginPath();
  ctx.arc(cx, cx, r * 1.1, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalCompositeOperation = 'source-over';

  // land dots: the same lattice, size, fade and shading as the WebGL points
  const dots = orderedLandDots();
  const count = dotCountForRadius(dots, r);
  const diameter = dotSizeForRadius(r);
  const [ir, ig, ib] = hexRgb(pal.ink);
  ctx.fillStyle = `rgb(${ir},${ig},${ib})`;
  const lat0 = (lat * Math.PI) / 180;
  const lon0 = (lon * Math.PI) / 180;
  for (let i = 0; i < count; i++) {
    const la = (dots.positions[i * 2] * Math.PI) / 180;
    const lo2 = (dots.positions[i * 2 + 1] * Math.PI) / 180;
    const f = Math.sin(lat0) * Math.sin(la) + Math.cos(lat0) * Math.cos(la) * Math.cos(lo2 - lon0); // facing
    if (f < DOT_LIMB.fadeStart) continue;
    const x = Math.cos(la) * Math.sin(lo2 - lon0);
    const y = Math.cos(lat0) * Math.sin(la) - Math.sin(lat0) * Math.cos(la) * Math.cos(lo2 - lon0);
    const seed = dotSeed(i);
    const t = Math.min(1, Math.max(0, (f - DOT_LIMB.fadeStart) / (DOT_LIMB.fadeEnd - DOT_LIMB.fadeStart)));
    const vis = t * t * (3 - 2 * t) * (0.86 + 0.14 * seed);
    const tone = pal.dotFloor + (1 - pal.dotFloor) * intelLit(x * s[0] + y * s[1] + f * s[2]);
    ctx.globalAlpha = vis * tone * pal.dotOpacity;
    const d = diameter * (0.85 + 0.3 * seed) * (DOT_LIMB.sizeFloor + (1 - DOT_LIMB.sizeFloor) * f);
    ctx.beginPath();
    ctx.arc(cx + r * x, cx - r * y, d / 2, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  ctx.restore();
}

/** The natural Earth: the About story's special moment. */
function drawEarth(ctx: CanvasRenderingContext2D, size: number, dpr: number, lat: number, lon: number, theme: 'dark' | 'light') {
  ctx.scale(dpr, dpr);
  const r = size * SPHERE_RADIUS; // matches the WebGL sphere's on-screen radius for a seamless cross-fade
  const cx = size / 2;
  const cy = size / 2;

  // atmosphere
  const halo = ctx.createRadialGradient(cx, cy, r * 0.96, cx, cy, r * 1.12);
  halo.addColorStop(0, theme === 'dark' ? 'rgba(106,168,255,0.38)' : 'rgba(95,143,214,0.28)');
  halo.addColorStop(1, 'rgba(106,168,255,0)');
  ctx.fillStyle = halo;
  ctx.beginPath();
  ctx.arc(cx, cy, r * 1.12, 0, Math.PI * 2);
  ctx.fill();

  // ocean, lit from the upper left
  const sea = ctx.createRadialGradient(cx - r * 0.38, cy - r * 0.32, r * 0.05, cx, cy, r);
  sea.addColorStop(0, '#2a6db0');
  sea.addColorStop(0.55, '#14467f');
  sea.addColorStop(1, '#071d3a');
  ctx.fillStyle = sea;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fill();

  // land samples in natural tones (ice, arid belt, vegetation), shaded by the same light
  const d = decodeLandDots();
  const lat0 = (lat * Math.PI) / 180;
  const lon0 = (lon * Math.PI) / 180;
  const sun = [-0.74, 0.4, 0.54];
  const dot = Math.max(1.25, r / 115); // land samples are ~2° apart: scale dots with the sphere so land reads as land
  for (let i = 0; i < d.length; i += 2) {
    const la = (d[i] * Math.PI) / 180;
    const lo = (d[i + 1] * Math.PI) / 180;
    const cosc = Math.sin(lat0) * Math.sin(la) + Math.cos(lat0) * Math.cos(la) * Math.cos(lo - lon0);
    if (cosc < 0.02) continue;
    const px = Math.cos(la) * Math.sin(lo - lon0);
    const py = Math.cos(lat0) * Math.sin(la) - Math.sin(lat0) * Math.cos(la) * Math.cos(lo - lon0);
    const shade = 0.45 + 0.55 * Math.max(0, px * sun[0] + py * sun[1] + cosc * sun[2]);
    const a = Math.abs(d[i]);
    const h = (Math.sin(i * 12.9898) * 43758.5453) % 1;
    const rgb = a > 64 ? [226, 232, 238] : a > 14 && a < 34 && Math.abs(h) > 0.35 ? [168, 140, 96] : a < 14 ? [70, 112, 58] : [96, 124, 72];
    ctx.globalAlpha = Math.min(1, cosc * 2.2);
    ctx.fillStyle = `rgb(${Math.round(rgb[0] * shade)},${Math.round(rgb[1] * shade)},${Math.round(rgb[2] * shade)})`;
    ctx.beginPath();
    ctx.arc(cx + r * px, cy - r * py, dot, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;

  // terminator: the right limb falls into shade
  const night = ctx.createLinearGradient(cx - r * 0.2, cy - r * 0.2, cx + r, cy + r * 0.4);
  night.addColorStop(0, 'rgba(3,10,22,0)');
  night.addColorStop(1, theme === 'dark' ? 'rgba(3,10,22,0.72)' : 'rgba(3,10,22,0.5)');
  ctx.fillStyle = night;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fill();
}
