import { useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '@/api';
import { Popover } from '@/components/common/Popover';
import { formatTime } from '@/utils/format';

/** Small global status indicator: backend + research availability. */
export function StatusCenter() {
  const { data, isError } = useQuery({ queryKey: ['status'], queryFn: api.system.status, refetchInterval: 60_000, retry: 1 });
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLButtonElement>(null);
  const tone = isError || data?.backend === 'offline' ? 'err' : data?.backend === 'degraded' || data?.sources.some((s) => s.status !== 'available') ? 'warn' : 'ok';
  const label = isError ? 'Backend offline' : !data ? 'Connecting…' : data.mode === 'mock' ? 'Mock backend' : data.backend === 'connected' ? 'Connected' : 'Degraded';
  return (
    <>
      <button ref={ref} className="status-capsule" onClick={() => setOpen((o) => !o)} aria-haspopup="dialog" aria-expanded={open} aria-label={`System status: ${label}`}>
        <span className={`status-dot ${tone !== 'ok' ? `status-dot--${tone}` : ''}`} aria-hidden />
        <span className="sc-label">{label}</span>
      </button>
      <Popover anchor={ref.current} open={open} onClose={() => setOpen(false)} label="System status" width={320}>
        <div className="stack" style={{ gap: 12 }}>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span className="t-micro">Status</span>
            {data && <span className="t-xs t-muted">Checked {formatTime(data.checkedAt, false)}</span>}
          </div>
          {isError ? (
            <p className="t-sm">The COGNIS backend could not be reached. Saved research shown from cache may be out of date.</p>
          ) : data ? (
            <>
              <dl className="kv" style={{ gridTemplateColumns: '110px 1fr' }}>
                <dt>Backend</dt>
                <dd>{data.mode === 'mock' ? 'Mock (demo data)' : data.backend}</dd>
                <dt>Research</dt>
                <dd>{data.research === 'online' ? 'Online' : 'Offline'}</dd>
                <dt>Version</dt>
                <dd className="t-mono">{data.version}</dd>
              </dl>
              <div className="stack" style={{ gap: 6 }}>
                <span className="t-micro">Sources</span>
                {data.sources.map((s) => (
                  <div key={s.name} className="row t-sm" style={{ justifyContent: 'space-between', gap: 8 }}>
                    <span className="truncate">{s.name}</span>
                    <span className={`pill pill--sm ${s.status === 'available' ? 'pill--ok' : s.status === 'degraded' ? 'pill--warn' : 'pill--err'}`} title={s.note}>
                      {s.status === 'available' ? 'Available' : s.status === 'degraded' ? 'Degraded' : 'Unavailable'}
                    </span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <p className="t-sm t-muted">Checking…</p>
          )}
          <Link to="/settings" className="link-btn" onClick={() => setOpen(false)}>
            Backend settings
          </Link>
        </div>
      </Popover>
    </>
  );
}
