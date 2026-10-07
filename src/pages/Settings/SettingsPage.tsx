import { useQuery } from '@tanstack/react-query';
import { Monitor, Moon, Sun } from 'lucide-react';
import { api } from '@/api';
import { usePreferences } from '@/stores/preferences';
import { Segmented } from '@/components/common/Tabs';
import { Skeleton } from '@/components/common/Skeleton';
import { formatDateTime } from '@/utils/format';
import './settings.css';

export default function SettingsPage() {
  const p = usePreferences();
  const status = useQuery({ queryKey: ['status'], queryFn: api.system.status });
  return (
    <div className="page settings">
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p>Preferences are stored on this device. No account is required.</p>
        </div>
      </div>
      <div className="settings-grid">
        <section className="card set-sec" aria-labelledby="s-appearance">
          <h2 id="s-appearance">Appearance</h2>
          <div className="set-row">
            <div>
              <strong>Theme</strong>
              <p>Dark is the primary COGNIS design. Light uses an ivory canvas with the same hierarchy.</p>
            </div>
            <Segmented
              label="Theme"
              value={p.theme}
              onChange={(theme) => p.set({ theme })}
              options={[
                { value: 'dark', label: 'Dark', icon: <Moon aria-hidden /> },
                { value: 'light', label: 'Light', icon: <Sun aria-hidden /> },
                { value: 'system', label: 'System', icon: <Monitor aria-hidden /> },
              ]}
            />
          </div>
          <div className="set-row">
            <div>
              <strong>Motion</strong>
              <p>Reduced motion stops globe rotation, parallax and floating layers and shortens transitions. All features keep working. The globe's play button on Home can still start the rotation.</p>
            </div>
            <Segmented
              label="Motion"
              value={p.motion}
              onChange={(motion) => p.set({ motion })}
              options={[
                { value: 'system', label: 'System' },
                { value: 'reduced', label: 'Reduced' },
                { value: 'full', label: 'Full' },
              ]}
            />
          </div>
          <div className="set-row">
            <div>
              <strong>Data density</strong>
              <p>Compact tightens rows, cards and charts so more fits on screen — most useful in Data Sheets, Compare, Financials and research views. Shortcut: command menu → Toggle compact mode.</p>
            </div>
            <Segmented
              label="Data density"
              value={p.density}
              onChange={(density) => p.set({ density })}
              options={[
                { value: 'comfortable', label: 'Comfortable' },
                { value: 'compact', label: 'Compact' },
              ]}
            />
          </div>
        </section>

        <section className="card set-sec" aria-labelledby="s-research">
          <h2 id="s-research">Research</h2>
          <div className="set-row">
            <div>
              <strong>Default research mode</strong>
              <p>Quick starts immediately with core sources. Deep shows the plan for review first.</p>
            </div>
            <Segmented
              label="Default research mode"
              value={p.researchMode}
              onChange={(researchMode) => p.set({ researchMode })}
              options={[
                { value: 'quick', label: 'Quick' },
                { value: 'deep', label: 'Deep' },
              ]}
            />
          </div>
          <div className="set-row">
            <div>
              <strong>Recent searches</strong>
              <p>{p.recentSearches.length ? p.recentSearches.join(' · ') : 'None saved on this device.'}</p>
            </div>
            <button className="btn btn--sm" disabled={!p.recentSearches.length} onClick={() => p.set({ recentSearches: [] })}>
              Clear
            </button>
          </div>
        </section>

        <section className="card set-sec" aria-labelledby="s-backend">
          <h2 id="s-backend">Backend status</h2>
          {status.isLoading ? (
            <Skeleton h={160} />
          ) : status.isError ? (
            <p className="t-sm t-err">The backend could not be reached.</p>
          ) : (
            status.data && (
              <>
                <dl className="kv">
                  <dt>Mode</dt>
                  <dd>{status.data.mode === 'mock' ? 'Mock backend (fictional demo data)' : 'Live backend'}</dd>
                  {status.data.baseUrl && (
                    <>
                      <dt>API base URL</dt>
                      <dd className="t-mono">{status.data.baseUrl}</dd>
                    </>
                  )}
                  <dt>Backend</dt>
                  <dd>{status.data.backend}</dd>
                  <dt>Research</dt>
                  <dd>{status.data.research}</dd>
                  <dt>Version</dt>
                  <dd className="t-mono">{status.data.version}</dd>
                  <dt>Checked</dt>
                  <dd>{formatDateTime(status.data.checkedAt)}</dd>
                  <dt>Exports</dt>
                  <dd>{status.data.capabilities.exports.map((e) => e.toUpperCase()).join(', ') || 'None'}</dd>
                </dl>
                {status.data.mode === 'mock' && (
                  <p className="t-xs t-muted" style={{ marginTop: 12 }}>
                    To connect the real backend set <span className="t-mono">VITE_API_MODE=live</span> and <span className="t-mono">VITE_API_BASE_URL</span> in <span className="t-mono">.env.local</span>, then restart the dev server.
                  </p>
                )}
              </>
            )
          )}
        </section>

        <section className="card set-sec" aria-labelledby="s-sources">
          <h2 id="s-sources">Source availability</h2>
          {status.data ? (
            <ul className="stack" style={{ gap: 8 }}>
              {status.data.sources.map((s) => (
                <li key={s.name} className="row" style={{ justifyContent: 'space-between', gap: 10 }}>
                  <span className="stack" style={{ gap: 0 }}>
                    <span className="t-sm">{s.name}</span>
                    {s.note && <span className="t-xs t-muted">{s.note}</span>}
                  </span>
                  <span className={`pill pill--sm ${s.status === 'available' ? 'pill--ok' : s.status === 'degraded' ? 'pill--warn' : 'pill--err'}`}>{s.status === 'available' ? 'Available' : s.status === 'degraded' ? 'Degraded' : 'Unavailable'}</span>
                </li>
              ))}
            </ul>
          ) : (
            <Skeleton h={200} />
          )}
        </section>
      </div>
    </div>
  );
}
