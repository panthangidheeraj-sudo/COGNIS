import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowUpRight, Compass, Library, Search, Table2, Telescope } from 'lucide-react';
import { ArtifactIcon, artifactHref } from '@/components/library/artifactNav';
import { api } from '@/api';
import { useGlobe } from '@/stores/ui';
import { GlobeStage } from '@/components/globe/GlobeStage';
import { HeroSearch } from '@/components/search/HeroSearch';
import { BrandMark } from '@/components/common/BrandMark';
import { CoverageMeter } from '@/components/company/Coverage';
import { Skeleton } from '@/components/common/Skeleton';
import { EmptyState } from '@/components/common/EmptyState';
import { ErrorState } from '@/components/common/ErrorState';
import { formatOrgNumber, formatRelative } from '@/utils/format';
import { ARTIFACT_TYPE_LABEL, SIGNAL_LABEL } from '@/utils/status';
import './home.css';

const EXAMPLES = ['Nordvik Helseteknologi', '921604337', 'SaaS companies in Oslo', 'Healthcare companies with revenue above 200M NOK'];

const ACTIONS = [
  { to: '/research', icon: Telescope, title: 'Research a company', text: 'Deep research with verified sources' },
  { to: '/discover', icon: Compass, title: 'Find companies', text: 'Natural-language search and filters' },
  { to: '/sheets?new=1', icon: Table2, title: 'Create a data sheet', text: 'AI columns and custom research' },
  { to: '/library', icon: Library, title: 'Explore the library', text: 'Saved research, reports and artifacts' },
];

export default function HomePage() {
  const recentCompanies = useQuery({ queryKey: ['companies', 'recent'], queryFn: api.companies.recent });
  const recentArtifacts = useQuery({ queryKey: ['library', 'recent'], queryFn: api.library.recent });
  const watch = useQuery({ queryKey: ['watchlist'], queryFn: api.watchlist.get });
  const setPoints = useGlobe((s) => s.setPoints);
  const setFocus = useGlobe((s) => s.setFocus);

  // Globe signal nodes = locations of recently researched companies (backend geo only).
  useEffect(() => {
    const pts = (recentCompanies.data ?? []).filter((c) => c.geo).map((c) => ({ id: c.orgNumber, lat: c.geo!.lat, lon: c.geo!.lon }));
    setPoints(pts);
    return () => {
      setPoints([]);
      setFocus(null);
    };
  }, [recentCompanies.data, setPoints, setFocus]);

  const signals = (watch.data?.items ?? []).flatMap((i) => i.signals).sort((a, b) => b.detectedAt.localeCompare(a.detectedAt));

  return (
    <div className="home">
      <section className="hero" aria-labelledby="hero-title">
        <GlobeStage className="hero-globe" />
        <div className="hero-inner">
          <span className="eyebrow">Research · Discover · Verify</span>
          <h1 id="hero-title" className="hero-title t-display">
            <span className="t-gradient">Find.</span> <span className="t-gradient">Understand.</span>{' '}
            <em className="t-serif hero-accent">Verify.</em>
          </h1>
          <p className="hero-sub">Company intelligence built from public evidence.</p>
          <HeroSearch autoFocus={false} />
          <div className="hero-examples" aria-label="Example searches">
            <span className="t-xs t-muted">Try</span>
            {EXAMPLES.map((e) => (
              <Link key={e} className="chip" to={/^\d{9}$/.test(e) ? `/company/${e}` : /companies/.test(e) ? `/discover?q=${encodeURIComponent(e)}` : `/discover?q=${encodeURIComponent(e)}`}>
                <Search aria-hidden />
                {e}
              </Link>
            ))}
          </div>
        </div>
      </section>

      <div className="page home-body">
        <section aria-label="Start" className="action-grid">
          {ACTIONS.map(({ to, icon: Icon, title, text }, i) => (
            <Link key={to} to={to} className="action-card" style={{ animationDelay: `${80 + i * 50}ms` }}>
              <span className="action-icon">
                <Icon aria-hidden />
              </span>
              <span className="action-title">{title}</span>
              <span className="action-text">{text}</span>
              <ArrowUpRight className="action-arrow" aria-hidden />
            </Link>
          ))}
        </section>

        <div className="home-grid">
          <section className="card home-recent" aria-labelledby="recent-co">
            <div className="card-head">
              <h2 id="recent-co">Recently researched</h2>
              <span className="spacer" />
              <Link to="/library?type=company" className="link-btn">
                All research
              </Link>
            </div>
            {recentCompanies.isLoading ? (
              <div className="stack">
                {Array.from({ length: 4 }, (_, i) => (
                  <Skeleton key={i} h={52} r={10} />
                ))}
              </div>
            ) : recentCompanies.isError ? (
              <ErrorState error={recentCompanies.error} onRetry={() => recentCompanies.refetch()} compact />
            ) : !recentCompanies.data?.length ? (
              <EmptyState compact title="No research yet." text="Start with a company or create a research sheet." />
            ) : (
              <ul className="recent-list">
                {recentCompanies.data.map((c) => (
                  <li key={c.orgNumber}>
                    <Link
                      to={`/company/${c.orgNumber}`}
                      className="recent-row"
                      onMouseEnter={() => c.geo && setFocus({ id: c.orgNumber, lat: c.geo.lat, lon: c.geo.lon, label: `${c.legalName} · ${c.municipality}` })}
                      onFocus={() => c.geo && setFocus({ id: c.orgNumber, lat: c.geo.lat, lon: c.geo.lon, label: `${c.legalName} · ${c.municipality}` })}
                      onMouseLeave={() => setFocus(null)}
                      onBlur={() => setFocus(null)}
                    >
                      <BrandMark name={c.legalName} org={c.orgNumber} logoUrl={c.logoUrl} size={38} />
                      <span className="stack" style={{ gap: 2, minWidth: 0, flex: 1 }}>
                        <span className="recent-title truncate">{c.legalName}</span>
                        <span className="t-xs t-muted truncate">
                          {c.municipality} · <span className="t-mono">{formatOrgNumber(c.orgNumber)}</span>
                        </span>
                      </span>
                      <span className="recent-meta">
                        <CoverageMeter coverage={c.coverage} size="sm" interactive={false} />
                        <span className="t-xs t-muted">{formatRelative(c.lastResearchedAt)}</span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <div className="stack" style={{ gap: 16 }}>
            <section className="card" aria-labelledby="recent-art">
              <div className="card-head">
                <h2 id="recent-art">Recent artifacts</h2>
                <span className="spacer" />
                <Link to="/library" className="link-btn">
                  Library
                </Link>
              </div>
              {recentArtifacts.isLoading ? (
                <Skeleton h={160} r={10} />
              ) : (
                <ul className="artifact-mini-list">
                  {(recentArtifacts.data ?? [])
                    .filter((a) => a.type !== 'company')
                    .slice(0, 5)
                    .map((a) => (
                      <li key={a.id}>
                        <Link to={artifactHref(a)} className="artifact-mini">
                          <ArtifactIcon type={a.type} />
                          <span className="truncate" style={{ flex: 1 }}>
                            {a.title}
                          </span>
                          <span className="t-xs t-muted nowrap">{ARTIFACT_TYPE_LABEL[a.type]}</span>
                        </Link>
                      </li>
                    ))}
                </ul>
              )}
            </section>

            <section className="card" aria-labelledby="watch-up">
              <div className="card-head">
                <h2 id="watch-up">Watchlist updates</h2>
                <span className="spacer" />
                <Link to="/watchlist" className="link-btn">
                  Watchlist
                </Link>
              </div>
              {watch.isLoading ? (
                <Skeleton h={120} r={10} />
              ) : signals.length === 0 ? (
                <EmptyState compact title="No new changes since your last check." />
              ) : (
                <ul className="signal-mini-list">
                  {signals.slice(0, 5).map((s) => (
                    <li key={s.id}>
                      <Link to={`/company/${s.orgNumber}?tab=changes`} className="signal-mini">
                        <span className="signal-dot" aria-hidden />
                        <span className="stack" style={{ gap: 0, minWidth: 0, flex: 1 }}>
                          <span className="truncate t-sm">{s.title}</span>
                          <span className="t-xs t-muted truncate">
                            {s.companyName} · {SIGNAL_LABEL[s.kind]}
                          </span>
                        </span>
                        <span className="t-xs t-muted nowrap">{formatRelative(s.detectedAt)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
