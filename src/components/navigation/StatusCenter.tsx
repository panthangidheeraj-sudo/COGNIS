import { useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '@/api';
import { Popover } from '@/components/common/Popover';
import { formatTime } from '@/utils/format';
import { SOURCE_AVAILABILITY, toneClass } from '@/utils/status';

/**
 * Small global status indicator: backend + research availability.
 * "Backend offline" is only shown when the backend really cannot be reached: if the status report fails, the liveness endpoint (/health) is asked
 * first, and a backend that answers it is shown as running with a failed status check instead.
 */
export function StatusCenter() {
  const { data, isError, error } = useQuery({ queryKey: ['status'], queryFn: api.system.status, refetchInterval: 60_000, retry: 1 });
  const health = useQuery({ queryKey: ['health'], queryFn: api.system.health, enabled: isError, retry: 0, refetchInterval: isError ? 30_000 : false });
  const reachable = isError && health.isSuccess;
  const probing = isError && !health.isSuccess && !health.isError;
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLButtonElement>(null);
  const tone = (isError && !reachable) || data?.backend === 'offline' ? 'err' : reachable || data?.backend === 'degraded' || data?.sources.some((s) => s.status !== 'available') ? 'warn' : 'ok';
  const label = isError
    ? reachable
      ? 'Status check failed'
      : probing
        ? 'Connecting…'
        : 'Backend offline'
    : !data
      ? 'Connecting…'
      : data.mode === 'mock'
        ? 'Mock backend'
        : data.backend === 'connected'
          ? 'Connected'
          : 'Degraded';
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
          {isError && reachable ? (
            <p className="t-sm" data-testid="status-check-failed">
              The backend is running (version <span className="t-mono">{health.data?.version}</span>), but its status report failed
              {error instanceof Error && error.message ? `: ${error.message}` : '.'} Research and saved data may still work; the backend console shows the cause.
            </p>
          ) : isError ? (
            <p className="t-sm">{probing ? 'Checking whether the backend is running…' : 'The COGNIS backend could not be reached. Saved research shown from cache may be out of date.'}</p>
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
              {data.capabilities?.pdfReportsNote && <p className="t-xs t-muted">{data.capabilities.pdfReportsNote}</p>}
              <div className="stack" style={{ gap: 6 }}>
                <span className="t-micro">Sources</span>
                {data.sources.map((s) => (
                  <div key={s.name} className="row t-sm" style={{ justifyContent: 'space-between', gap: 8 }}>
                    <span className="truncate">{s.name}</span>
                    <span className={`pill pill--sm ${toneClass((SOURCE_AVAILABILITY[s.status] ?? SOURCE_AVAILABILITY.unavailable).tone)}`} title={s.note}>
                      {(SOURCE_AVAILABILITY[s.status] ?? SOURCE_AVAILABILITY.unavailable).label}
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
