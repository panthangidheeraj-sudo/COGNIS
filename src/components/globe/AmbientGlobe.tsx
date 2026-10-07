import { useEffect, useRef } from 'react';
import { decodeLandDots } from './landDots';

/**
 * Ambient globe motif for information-dense pages (Company, Financials,
 * artifacts). A static dotted hemisphere centred on the company's
 * headquarters — identity, not spectacle. Drawn once; never animated.
 */
export function AmbientGlobe({ lat = 62, lon = 12, className }: { lat?: number; lon?: number; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const size = c.clientWidth || 320;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    c.width = size * dpr;
    c.height = size * dpr;
    const ctx = c.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    const ink = getComputedStyle(c).color || '#c8d0da';
    const r = size * 0.46;
    const cx = size / 2;
    const cy = size / 2;
    ctx.strokeStyle = ink;
    ctx.globalAlpha = 0.35;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();
    const d = decodeLandDots();
    const lat0 = (lat * Math.PI) / 180;
    const lon0 = (lon * Math.PI) / 180;
    ctx.fillStyle = ink;
    for (let i = 0; i < d.length; i += 2) {
      const la = (d[i] * Math.PI) / 180;
      const lo = (d[i + 1] * Math.PI) / 180;
      const cosc = Math.sin(lat0) * Math.sin(la) + Math.cos(lat0) * Math.cos(la) * Math.cos(lo - lon0);
      if (cosc < 0.04) continue;
      const x = cx + r * Math.cos(la) * Math.sin(lo - lon0);
      const y = cy - r * (Math.cos(lat0) * Math.sin(la) - Math.sin(lat0) * Math.cos(la) * Math.cos(lo - lon0));
      ctx.globalAlpha = Math.min(1, cosc * 1.3) * 0.7;
      ctx.fillRect(x - 0.6, y - 0.6, 1.2, 1.2);
    }
    // headquarters marker at the centre of view
    ctx.globalAlpha = 0.9;
    ctx.beginPath();
    ctx.arc(cx, cy, 2.6, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 0.35;
    ctx.beginPath();
    ctx.arc(cx, cy, 8, 0, Math.PI * 2);
    ctx.stroke();
  }, [lat, lon]);
  return <canvas ref={ref} className={`ambient-globe ${className ?? ''}`} aria-hidden />;
}
