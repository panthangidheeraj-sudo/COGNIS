import { useRef, useState } from 'react';
import { Ban, CircleCheck, CircleDashed, CircleMinus, TriangleAlert } from 'lucide-react';
import type { Coverage, CoverageAreaStatus } from '@/types';
import { COVERAGE_AREAS, COVERAGE_STATUS } from '@/utils/status';
import { Popover } from '@/components/common/Popover';
import { cn } from '@/utils/cn';

const ICON: Record<CoverageAreaStatus, typeof CircleCheck> = {
  complete: CircleCheck,
  partial: TriangleAlert,
  unavailable: CircleMinus,
  blocked: Ban,
  pending: CircleDashed,
};

/** "4/5 areas" + segmented bar. Missing areas are never hidden. Click → details. */
export function CoverageMeter({ coverage, size = 'md', interactive = true }: { coverage: Coverage; size?: 'sm' | 'md'; interactive?: boolean }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLButtonElement>(null);
  const missing = coverage.areas.filter((a) => a.status !== 'complete');
  const firstMissing = missing[0];
  const label = `${coverage.complete}/${coverage.total} areas`;
  const body = (
    <>
      <span className="cov-bar" aria-hidden>
        {COVERAGE_AREAS.map(({ area }) => {
          const a = coverage.areas.find((x) => x.area === area);
          return <span key={area} className={cn('cov-seg', `cov-seg--${a?.status ?? 'pending'}`)} />;
        })}
      </span>
      <span className="cov-label t-num">{label}</span>
      {size === 'md' && firstMissing && (
        <span className="cov-note">
          {firstMissing.note ?? `${COVERAGE_AREAS.find((x) => x.area === firstMissing.area)?.label} ${COVERAGE_STATUS[firstMissing.status].label.toLowerCase()}`}
          {missing.length > 1 ? ` +${missing.length - 1}` : ''}
        </span>
      )}
    </>
  );
  if (!interactive)
    return (
      <span className={cn('cov', `cov--${size}`)} aria-label={`Coverage ${label}`}>
        {body}
      </span>
    );
  return (
    <>
      <button ref={ref} className={cn('cov', `cov--${size}`, 'cov--btn')} onClick={(e) => (e.preventDefault(), e.stopPropagation(), setOpen((o) => !o))} aria-haspopup="dialog" aria-expanded={open} aria-label={`Coverage ${label}. Show details.`}>
        {body}
      </button>
      <Popover anchor={ref.current} open={open} onClose={() => setOpen(false)} label="Coverage details" width={320}>
        <CoverageList coverage={coverage} />
      </Popover>
    </>
  );
}

export function CoverageList({ coverage }: { coverage: Coverage }) {
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <span className="t-micro">Coverage</span>
        <span className="t-num t-sm">
          {coverage.complete}/{coverage.total} areas complete
        </span>
      </div>
      <ul className="cov-list">
        {COVERAGE_AREAS.map(({ area, label }) => {
          const a = coverage.areas.find((x) => x.area === area);
          const st = a?.status ?? 'pending';
          const Icon = ICON[st];
          return (
            <li key={area} className={`cov-item cov-item--${st}`}>
              <Icon aria-hidden />
              <span className="stack" style={{ gap: 0, flex: 1 }}>
                <span>{label}</span>
                {a?.note && <span className="t-xs t-muted">{a.note}</span>}
              </span>
              <span className="t-xs cov-item-status">{COVERAGE_STATUS[st].label}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
