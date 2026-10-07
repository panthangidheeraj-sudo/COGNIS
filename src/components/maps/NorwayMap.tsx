import { useState } from 'react';
import type { CompanyLocation } from '@/types';
import { NORWAY_PATH, NORWAY_VIEWBOX, projectNorway } from './norwayOutline';

const KIND_LABEL: Record<CompanyLocation['kind'], string> = {
  registered_address: 'Registered address',
  headquarters: 'Headquarters (verified)',
  operating: 'Operating location',
  postal: 'Postal address',
};

/**
 * Polished but compact location map (offline SVG, no tile server).
 * Only plots locations that have backend-provided coordinates.
 */
export function NorwayMap({ locations, onSelect, height = 380 }: { locations: CompanyLocation[]; onSelect?: (l: CompanyLocation) => void; height?: number }) {
  const [hover, setHover] = useState<string | null>(null);
  const pad = 30;
  const vb = `${-pad} ${-pad} ${NORWAY_VIEWBOX.width + pad * 2} ${NORWAY_VIEWBOX.height + pad * 2}`;
  const plotted = locations.filter((l) => l.geo);
  return (
    <figure className="nmap" style={{ height }}>
      <svg viewBox={vb} role="img" aria-label={`Map of Norway with ${plotted.length} verified location${plotted.length === 1 ? '' : 's'}`} preserveAspectRatio="xMidYMid meet">
        <defs>
          <radialGradient id="nmap-glow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--accent-soft)" stopOpacity="0.45" />
            <stop offset="100%" stopColor="var(--accent-soft)" stopOpacity="0" />
          </radialGradient>
          <pattern id="nmap-grid" width="20" height="20" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="0.9" fill="var(--line-strong)" />
          </pattern>
        </defs>
        <rect x={-pad} y={-pad} width={NORWAY_VIEWBOX.width + pad * 2} height={NORWAY_VIEWBOX.height + pad * 2} fill="url(#nmap-grid)" opacity="0.6" />
        <path d={NORWAY_PATH} className="nmap-land" />
        {plotted.map((l) => {
          const [x, y] = projectNorway(l.geo!.lat, l.geo!.lon);
          const main = l.kind === 'registered_address' || l.kind === 'headquarters';
          const active = hover === l.id;
          return (
            <g
              key={l.id}
              transform={`translate(${x} ${y})`}
              className="nmap-pt"
              tabIndex={0}
              role="button"
              aria-label={`${KIND_LABEL[l.kind]}: ${l.address}, ${l.municipality}${l.verified ? '' : ' (not verified)'}`}
              onMouseEnter={() => setHover(l.id)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(l.id)}
              onBlur={() => setHover(null)}
              onClick={() => onSelect?.(l)}
              onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onSelect?.(l))}
            >
              <circle r={main ? 26 : 18} fill="url(#nmap-glow)" />
              <circle r={main ? 7 : 5} className={main ? 'nmap-dot nmap-dot--main' : l.verified ? 'nmap-dot' : 'nmap-dot nmap-dot--unverified'} />
              {(active || main) && (
                <g transform={`translate(${x > NORWAY_VIEWBOX.width * 0.6 ? -14 : 14} 4)`}>
                  <text className="nmap-label" textAnchor={x > NORWAY_VIEWBOX.width * 0.6 ? 'end' : 'start'}>
                    {l.municipality}
                  </text>
                </g>
              )}
            </g>
          );
        })}
      </svg>
      <figcaption className="nmap-legend">
        <span>
          <i className="nmap-key nmap-key--main" /> Registered / HQ
        </span>
        <span>
          <i className="nmap-key" /> Operating location
        </span>
        {plotted.some((l) => !l.verified) && (
          <span>
            <i className="nmap-key nmap-key--unverified" /> Not verified
          </span>
        )}
      </figcaption>
    </figure>
  );
}
