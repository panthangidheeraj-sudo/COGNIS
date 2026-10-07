import { useMemo, useState } from 'react';
import type { Relationship, RelationshipKind } from '@/types';
import { EmptyState } from '@/components/common/EmptyState';

const KIND_LABEL: Record<RelationshipKind, string> = {
  ceo: 'CEO',
  board: 'Board',
  subsidiary: 'Subsidiary',
  parent: 'Parent',
  related: 'Related',
  investor: 'Investor',
  partner: 'Partner',
  founder: 'Founder',
};

/**
 * Relationship graph. Every edge is a backend relationship with evidence —
 * nothing is inferred from proximity. People = circles, organizations = glass rectangles.
 */
export function CompanyNetwork({ name, relationships, onSelect, height = 360, compact }: { name: string; relationships: Relationship[]; onSelect?: (r: Relationship) => void; height?: number; compact?: boolean }) {
  const [hover, setHover] = useState<string | null>(null);
  const W = 640;
  const H = compact ? 300 : 380;
  const cx = W / 2;
  const cy = H / 2;
  const nodes = useMemo(() => {
    const people = relationships.filter((r) => r.entity.type === 'person');
    const orgs = relationships.filter((r) => r.entity.type === 'organization');
    const place = (list: Relationship[], rx: number, ry: number, offset: number) =>
      list.map((r, i) => {
        const a = offset + (i / Math.max(1, list.length)) * Math.PI * 2;
        return { r, x: cx + Math.cos(a) * rx, y: cy + Math.sin(a) * ry };
      });
    return [...place(people, compact ? 150 : 170, compact ? 92 : 118, -Math.PI / 2), ...place(orgs, compact ? 260 : 280, compact ? 122 : 150, -Math.PI / 2 + Math.PI / Math.max(2, orgs.length))];
  }, [relationships, cx, cy, compact]);

  if (!relationships.length) return <EmptyState compact title="No verified relationships available for this entity." />;

  return (
    <figure className="cnet" style={{ height }}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Relationship graph for ${name} with ${relationships.length} verified relationships`} preserveAspectRatio="xMidYMid meet">
        <defs>
          <radialGradient id="cnet-core" cx="50%" cy="40%" r="60%">
            <stop offset="0%" className="cnet-stop-a" />
            <stop offset="100%" className="cnet-stop-b" />
          </radialGradient>
        </defs>
        <circle cx={cx} cy={cy} r={compact ? 92 : 118} className="cnet-orbit" />
        <ellipse cx={cx} cy={cy} rx={compact ? 260 : 280} ry={compact ? 122 : 150} className="cnet-orbit" />
        {nodes.map(({ r, x, y }) => (
          <line key={`l-${r.id}`} x1={cx} y1={cy} x2={x} y2={y} className={`cnet-edge ${hover === r.id ? 'is-active' : ''}`} />
        ))}
        <g className="cnet-core">
          <circle cx={cx} cy={cy} r={34} fill="url(#cnet-core)" />
          <circle cx={cx} cy={cy} r={42} className="cnet-core-ring" />
          <text x={cx} y={cy + 62} textAnchor="middle" className="cnet-core-label">
            {name.length > 30 ? `${name.slice(0, 28)}…` : name}
          </text>
        </g>
        {nodes.map(({ r, x, y }) => {
          const person = r.entity.type === 'person';
          const label = r.entity.name.length > 24 ? `${r.entity.name.slice(0, 22)}…` : r.entity.name;
          return (
            <g
              key={r.id}
              className={`cnet-node ${person ? 'cnet-node--person' : 'cnet-node--org'} ${hover === r.id ? 'is-active' : ''}`}
              transform={`translate(${x} ${y})`}
              tabIndex={0}
              role="button"
              aria-label={`${KIND_LABEL[r.kind]}: ${r.entity.name}. View evidence.`}
              onMouseEnter={() => setHover(r.id)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(r.id)}
              onBlur={() => setHover(null)}
              onClick={() => onSelect?.(r)}
              onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onSelect?.(r))}
            >
              {person ? <circle r={13} /> : <rect x={-15} y={-11} width={30} height={22} rx={5} />}
              <text y={person ? 30 : 28} textAnchor="middle" className="cnet-label">
                {label}
              </text>
              <text y={person ? 43 : 41} textAnchor="middle" className="cnet-kind">
                {r.label}
              </text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
