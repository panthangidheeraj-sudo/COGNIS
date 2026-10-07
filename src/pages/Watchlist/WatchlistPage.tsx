import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, ArrowRight, Banknote, Briefcase, CheckCheck, FileText, MapPin, Megaphone, Radar, Trash2, UsersRound } from 'lucide-react';
import { api } from '@/api';
import type { SignalKind, Watchlist } from '@/types';
import { useUi } from '@/stores/ui';
import { Tabs } from '@/components/common/Tabs';
import { Skeleton } from '@/components/common/Skeleton';
import { EmptyState } from '@/components/common/EmptyState';
import { ErrorState } from '@/components/common/ErrorState';
import { BrandMark } from '@/components/common/BrandMark';
import { CoverageMeter } from '@/components/company/Coverage';
import { CompareToggle } from '@/components/company/CompanyCard';
import { formatDate, formatRelative } from '@/utils/format';
import { SIGNAL_LABEL } from '@/utils/status';
import './watchlist.css';

const SIGNAL_ICON: Record<SignalKind, typeof Activity> = {
  financial: Banknote,
  leadership: UsersRound,
  hiring: Briefcase,
  location: MapPin,
  announcement: Megaphone,
  filing: FileText,
};

export default function WatchlistPage() {
  const [tab, setTab] = useState<'companies' | 'signals'>('companies');
  const [onlyChanged, setOnlyChanged] = useState(false);
  const q = useQuery({ queryKey: ['watchlist'], queryFn: api.watchlist.get });
  const qc = useQueryClient();
  const toast = useUi((s) => s.toast);
  const markChecked = async () => {
    qc.setQueryData(['watchlist'], await api.watchlist.markChecked());
    toast({ tone: 'ok', text: 'Marked as checked' });
  };
  const w = q.data;
  return (
    <div className="page watchlist">
      <div className="page-head">
        <div>
          <h1>{w?.title ?? 'My Watchlist'}</h1>
          <p>
            {w ? (
              <>
                <strong className="t-num">{w.items.length}</strong> companies · <strong className="t-num">{w.changedCount}</strong> changed since last check ({formatDate(w.lastCheckedAt)})
              </>
            ) : (
              'Companies you want to revisit, with backend-detected changes.'
            )}
          </p>
        </div>
        <div className="page-actions">
          {w && w.changedCount > 0 && (
            <button className="btn" onClick={markChecked}>
              <CheckCheck aria-hidden /> Mark all as checked
            </button>
          )}
        </div>
      </div>
      <Tabs
        label="Watchlist views"
        value={tab}
        onChange={(t) => setTab(t as typeof tab)}
        tabs={[
          { id: 'companies', label: 'Companies', count: w?.items.length },
          { id: 'signals', label: 'Signals feed' },
        ]}
      />
      <div role="tabpanel" id={`tabpanel-${tab}`} aria-labelledby={`tab-${tab}`} style={{ marginTop: 20 }}>
        {q.isError ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : !w ? (
          <Skeleton h={400} r={12} />
        ) : tab === 'companies' ? (
          <Companies w={w} onlyChanged={onlyChanged} setOnlyChanged={setOnlyChanged} />
        ) : (
          <Feed />
        )}
      </div>
    </div>
  );
}

function Companies({ w, onlyChanged, setOnlyChanged }: { w: Watchlist; onlyChanged: boolean; setOnlyChanged: (b: boolean) => void }) {
  const qc = useQueryClient();
  const items = w.items.filter((i) => !onlyChanged || i.signals.length).sort((a, b) => b.signals.length - a.signals.length);
  if (!w.items.length)
    return (
      <EmptyState
        title="Your watchlist is empty."
        text="Add companies from their profile to track filings, leadership, hiring and location changes."
        action={
          <Link to="/discover" className="btn">
            Find companies
          </Link>
        }
      />
    );
  return (
    <div className="stack" style={{ gap: 12 }}>
      <label className="checkbox">
        <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} />
        Show only companies with changes
      </label>
      <ul className="watch-list">
        {items.map((i) => (
          <li key={i.company.orgNumber} className={`watch-item ${i.signals.length ? 'has-signals' : ''}`}>
            <div className="watch-co">
              <BrandMark name={i.company.legalName} org={i.company.orgNumber} size={40} />
              <div className="stack" style={{ gap: 2, minWidth: 0 }}>
                <Link to={`/company/${i.company.orgNumber}`} className="watch-name truncate">
                  {i.company.legalName}
                </Link>
                <span className="t-xs t-muted">
                  {i.company.municipality} · {i.company.statusLabel} · checked {formatRelative(i.lastCheckedAt)}
                </span>
                <CoverageMeter coverage={i.company.coverage} size="sm" />
              </div>
            </div>
            <div className="watch-signals">
              {i.signals.length === 0 ? (
                <span className="t-xs t-muted">No changes detected since last check</span>
              ) : (
                i.signals.slice(0, 3).map((s) => {
                  const I = SIGNAL_ICON[s.kind];
                  return (
                    <Link key={s.id} to={`/company/${s.orgNumber}?tab=changes`} className="signal-chip" title={`${SIGNAL_LABEL[s.kind]} · detected ${formatDate(s.detectedAt)}`}>
                      <I aria-hidden />
                      <span className="truncate">{s.title}</span>
                    </Link>
                  );
                })
              )}
              {i.signals.length > 3 && <span className="t-xs t-muted">+{i.signals.length - 3} more</span>}
            </div>
            <div className="watch-actions">
              <CompareToggle c={i.company} small />
              <button
                className="btn btn--ghost btn--icon btn--sm"
                aria-label={`Remove ${i.company.legalName} from watchlist`}
                onClick={async () => qc.setQueryData(['watchlist'], await api.watchlist.remove(i.company.orgNumber))}
              >
                <Trash2 aria-hidden />
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Feed() {
  const q = useQuery({ queryKey: ['signals'], queryFn: api.watchlist.feed });
  const [expanded, setExpanded] = useState<string | null>(null);
  const openEvidence = useUi((s) => s.openEvidence);
  if (q.isLoading) return <Skeleton h={300} r={12} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data?.length) return <EmptyState title="No signals yet." text="Signals appear when the backend detects a verified change for a watched company." />;
  return (
    <div className="stack" style={{ gap: 18 }}>
      {q.data.map((g) => (
        <section key={g.label} className="card feed-group" aria-labelledby={`fg-${g.label}`}>
          <div className="card-head">
            <h2 id={`fg-${g.label}`}>{g.label}</h2>
            <span className="t-xs t-muted">{g.signals.length} signals</span>
          </div>
          <ul className="feed-summary">
            {g.summary.map((s) => {
              const I = SIGNAL_ICON[s.kind];
              return (
                <li key={s.kind}>
                  <I aria-hidden />
                  <span>{s.label}</span>
                </li>
              );
            })}
          </ul>
          <button className="link-btn" onClick={() => setExpanded(expanded === g.label ? null : g.label)} aria-expanded={expanded === g.label}>
            {expanded === g.label ? 'Hide' : 'View'} affected companies <ArrowRight aria-hidden />
          </button>
          {expanded === g.label && (
            <ul className="feed-list anim-fade-up">
              {g.signals.map((s) => {
                const I = SIGNAL_ICON[s.kind];
                return (
                  <li key={s.id}>
                    <I aria-hidden className="t-accent" />
                    <div className="stack" style={{ gap: 0, flex: 1, minWidth: 0 }}>
                      <Link to={`/company/${s.orgNumber}?tab=changes`} className="t-sm" style={{ fontWeight: 500 }}>
                        {s.companyName}
                      </Link>
                      <span className="t-xs t-soft">{s.title}</span>
                    </div>
                    <span className="t-xs t-muted nowrap">{formatDate(s.detectedAt)}</span>
                    <button className="btn btn--ghost btn--sm" onClick={() => openEvidence({ title: s.title, value: s.companyName, evidence: s.evidence, sourceIndex: g.sourceIndex ?? {}, context: s.companyName })}>
                      Evidence
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      ))}
      <p className="t-xs t-muted">
        <Radar width={12} height={12} style={{ display: 'inline', marginRight: 6 }} aria-hidden />
        Signals are produced only when the backend detects a verified source change.
      </p>
    </div>
  );
}
