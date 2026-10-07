import type { ArtifactSummary } from '@/types';
import { Sparkline } from '@/components/common/Sparkline';
import { Motif } from '@/components/common/Motif';

/** Type-specific generated thumbnails — no screenshots, no stock imagery. */
export function ArtifactThumb({ a }: { a: ArtifactSummary }) {
  switch (a.type) {
    case 'company':
      return (
        <div className="thumb thumb--company" aria-hidden>
          <span className="thumb-initials">
            {a.title
              .replace(/\b(AS|ASA)\b/g, '')
              .split(/\s+/)
              .filter(Boolean)
              .slice(0, 2)
              .map((w) => w[0])
              .join('')}
          </span>
          <div className="thumb-spark">{a.sparkline && a.sparkline.length > 1 && <Sparkline values={a.sparkline} width={120} height={34} />}</div>
          <svg className="thumb-grid" viewBox="0 0 120 70" preserveAspectRatio="none">
            {Array.from({ length: 6 }, (_, i) => (
              <circle key={i} cx={20 * i + 10} cy={10} r="0.9" />
            ))}
          </svg>
        </div>
      );
    case 'report':
      return (
        <div className="thumb thumb--report" aria-hidden>
          <span className="thumb-cover-l1">COGNIS</span>
          <span className="thumb-cover-l2">Company research</span>
          <span className="thumb-cover-rule" />
          <svg viewBox="0 0 60 60" className="thumb-orbit">
            <circle cx="30" cy="30" r="24" />
            <circle cx="30" cy="30" r="14" />
            <circle cx="30" cy="30" r="3" className="fill" />
          </svg>
        </div>
      );
    case 'data_sheet':
      return (
        <div className="thumb thumb--sheet" aria-hidden>
          {Array.from({ length: 5 }, (_, r) => (
            <div key={r} className="thumb-row">
              {Array.from({ length: 5 }, (_, c) => (
                <span key={c} className={r === 0 ? 'h' : (r + c) % 4 === 0 ? 'p' : ''} />
              ))}
            </div>
          ))}
        </div>
      );
    case 'comparison':
      return (
        <div className="thumb thumb--compare" aria-hidden>
          {[0.85, 0.55, 0.7].map((h, i) => (
            <span key={i} style={{ height: `${h * 100}%` }} />
          ))}
        </div>
      );
    case 'watchlist':
      return (
        <div className="thumb thumb--watch" aria-hidden>
          <svg viewBox="0 0 120 70">
            {[
              [20, 40],
              [45, 22],
              [62, 48],
              [88, 30],
              [104, 52],
            ].map(([x, y], i) => (
              <g key={i}>
                <circle cx={x} cy={y} r={i % 2 ? 7 : 5} className="ring" />
                <circle cx={x} cy={y} r="2" className="fill" />
              </g>
            ))}
          </svg>
        </div>
      );
    default:
      return (
        <div className="thumb thumb--search" aria-hidden>
          <Motif size={40} />
        </div>
      );
  }
}
