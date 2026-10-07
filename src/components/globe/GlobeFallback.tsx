import { useEffect, useRef } from 'react';
import { decodeLandDots } from './landDots';

/**
 * Static orthographic Earth drawn once on a 2D canvas, in the same natural palette as the WebGL globe
 * (blue ocean, green/brown land, white ice, thin atmosphere, light from the upper left).
 * Used when WebGL is unavailable, while the 3D chunk and imagery load (the stage cross-fades), or if it fails.
 */
export function GlobeFallback({ lat = 25, lon = 14, theme }: { lat?: number; lon?: number; theme: 'dark' | 'light' }) {
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
    ctx.scale(dpr, dpr);
    const r = size * 0.375; // matches the WebGL sphere's on-screen radius for a seamless cross-fade
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
  }, [lat, lon, theme]);
  return <canvas ref={ref} className="globe-fallback" aria-hidden />;
}
