import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Columns3, Download, Ellipsis, FileText, History, MapPin, Radar, RefreshCw, Telescope } from 'lucide-react';
import { api, ApiError } from '@/api';
import type { AmbiguousMatch, Change, CompanyProfile, ExplainSubject } from '@/types';
import { useCompare, useUi } from '@/stores/ui';
import { BrandMark } from '@/components/common/BrandMark';
import { Tabs } from '@/components/common/Tabs';
import { Menu } from '@/components/common/Menu';
import { ErrorState, ErrorBoundary } from '@/components/common/ErrorState';
import { Skeleton, LoadingRegion } from '@/components/common/Skeleton';
import { ExportModal } from '@/components/common/ExportModal';
import { ExternalLink } from '@/components/common/ExternalLink';
import { ReportModal } from '@/components/artifacts/ReportModal';
import { Snapshot } from '@/components/company/Snapshot';
import { WhatChanged } from '@/components/company/WhatChanged';
import { ExecutiveBriefModal } from '@/components/company/ExecutiveBriefModal';
import { ExplainModal } from '@/components/company/ExplainModal';
import { AmbientGlobe } from '@/components/globe/AmbientGlobe';
import { useCommand } from '@/hooks/useCommand';
import { OverviewSection } from '@/components/company/sections/OverviewSection';
import { FinancialsSection } from '@/components/company/sections/FinancialsSection';
import { LocationsSection, PeopleSection } from '@/components/company/sections/PeopleLocations';
import { HiringSection, WebsiteSection } from '@/components/company/sections/OnlineHiring';
import { ActivitySection, ChangesSection, SourcesSection } from '@/components/company/sections/ActivitySources';
import { AmbiguousCandidates } from '@/components/research/AmbiguousCandidates';
import { useIsMobile } from '@/hooks/useMediaQuery';
import { formatDate, formatOrgNumber } from '@/utils/format';
import { COMPANY_STATUS_TONE, toneClass } from '@/utils/status';
import { COMPANY_TABS, TAB_LABEL, type CompanyTab } from './tabs';
import '@/styles/sections.css';
import './company.css';

export default function CompanyPage() {
  const { orgNumber = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const q = useQuery({ queryKey: ['company', orgNumber], queryFn: () => api.companies.get(orgNumber) });
  const [exportOpen, setExportOpen] = useState(params.get('export') === '1');

  useEffect(() => {
    if (params.get('export') === '1') {
      setExportOpen(true);
      params.delete('export');
      setParams(params, { replace: true });
    }
  }, [params, setParams]);

  if (q.isLoading) return <CompanySkeleton />;
  if (q.isError) {
    const err = q.error;
    if (err instanceof ApiError && err.code === 'ambiguous' && err.details)
      return (
        <div className="page">
          <AmbiguousCandidates match={err.details as AmbiguousMatch} />
        </div>
      );
    return (
      <div className="page">
        <ErrorState error={err} onRetry={() => q.refetch()} />
      </div>
    );
  }
  return <CompanyView profile={q.data!} exportOpen={exportOpen} setExportOpen={setExportOpen} />;
}

function CompanyView({ profile, exportOpen, setExportOpen }: { profile: CompanyProfile; exportOpen: boolean; setExportOpen: (b: boolean) => void }) {
  const c = profile.company;
  const [params, setParams] = useSearchParams();
  const tab = (COMPANY_TABS as readonly string[]).includes(params.get('tab') ?? '') ? (params.get('tab') as CompanyTab) : 'overview';
  const setTab = (t: CompanyTab) => {
    const p = new URLSearchParams(params);
    if (t === 'overview') p.delete('tab');
    else p.set('tab', t);
    setParams(p, { replace: true });
  };
  const nav = useNavigate();
  const mobile = useIsMobile();
  const { selected, toggle } = useCompare();
  const inCompare = selected.some((s) => s.orgNumber === c.orgNumber);
  const qc = useQueryClient();
  const toast = useUi((s) => s.toast);
  const watch = useQuery({ queryKey: ['watchlist'], queryFn: api.watchlist.get });
  const watched = watch.data?.items.some((i) => i.company.orgNumber === c.orgNumber);
  const assess = useQuery({ queryKey: ['assess', profile.artifactId], queryFn: () => api.research.assess(profile.artifactId!), enabled: !!profile.artifactId });
  const [reportOpen, setReportOpen] = useState(false);
  const [briefOpen, setBriefOpen] = useState(params.get('brief') === '1');
  const [explain, setExplain] = useState<{ subject: ExplainSubject; title: string } | null>(null);
  const researched = c.researchState !== 'not_researched';
  useCommand('export', () => setExportOpen(true));
  useCommand('brief', () => setBriefOpen(true));

  const toggleWatch = async () => {
    const res = watched ? await api.watchlist.remove(c.orgNumber) : await api.watchlist.add(c.orgNumber);
    qc.setQueryData(['watchlist'], res);
    toast({ tone: 'ok', text: watched ? 'Removed from watchlist' : 'Added to watchlist', action: watched ? undefined : { label: 'Open', href: '/watchlist' } });
  };
  const researchHref = `/research?org=${c.orgNumber}${researched ? '' : '&autostart=1'}`;
  const onExplainChange = (ch: Change) => setExplain({ subject: { kind: 'change', changeId: ch.id }, title: ch.headline ?? ch.label });

  const counts: Partial<Record<CompanyTab, number>> = {
    people: profile.people.people.filter((p) => p.current).length || undefined,
    locations: profile.locations.locations.length || undefined,
    hiring: profile.hiring.totalCurrent ?? undefined,
    activity: profile.activity.events.filter((e) => e.significance === 'major').length || undefined,
    changes: profile.changes.changes.filter((ch) => ch.material).length || undefined,
    sources: profile.sources.length || undefined,
  };
  const hq = profile.locations.locations.find((l) => l.kind === 'headquarters' && l.geo)?.geo ?? c.geo;

  return (
    <div className="page company">
      <header className="co-head">
        {!mobile && hq && <AmbientGlobe lat={hq.lat} lon={hq.lon} className="co-ambient" />}
        <div className="co-id">
          <BrandMark name={c.legalName} org={c.orgNumber} logoUrl={c.logoUrl} size={mobile ? 48 : 60} />
          <div className="stack" style={{ gap: 8, minWidth: 0 }}>
            <div className="row-wrap" style={{ gap: 10 }}>
              <h1 className="co-name">{c.legalName}</h1>
              <span className={`pill ${toneClass(COMPANY_STATUS_TONE[c.status])}`} title="Legal status from Brønnøysundregistrene">
                <span className="pill-dot" aria-hidden />
                {c.statusLabel ?? c.status}
              </span>
            </div>
            <div className="co-meta">
              <span title={profile.identity.headquarters ? 'Headquarters (verified)' : 'Registered address'}>
                <MapPin aria-hidden className="co-meta-ico" />
                {c.municipality}, Norway <span className="t-muted">· {profile.identity.headquarters ? 'HQ verified' : 'Registered address'}</span>
              </span>
              <span>
                Org. no. <span className="t-mono">{formatOrgNumber(c.orgNumber)}</span>
              </span>
              {c.industry && (
                <span>
                  {c.industry.description} <span className="t-mono t-muted">{c.industry.code}</span>
                </span>
              )}
              {c.website && <ExternalLink href={`https://${c.website}`}>{c.website}</ExternalLink>}
            </div>
          </div>
        </div>
        <div className="co-actions">
          <button className="btn btn--ivory" onClick={() => setBriefOpen(true)}>
            <FileText aria-hidden /> {mobile ? 'Brief' : 'Executive brief'}
          </button>
          <Link to={researchHref} className={researched ? 'btn' : 'btn btn--primary'}>
            <Telescope aria-hidden /> {researched ? (mobile ? 'Continue' : 'Continue research') : mobile ? 'Research' : 'Research this company'}
          </Link>
          {!mobile && (
            <button className={`btn ${inCompare ? 'is-selected' : ''}`} aria-pressed={inCompare} onClick={() => toggle(c)}>
              <Columns3 aria-hidden /> {inCompare ? 'In compare' : 'Compare'}
            </button>
          )}
          {!mobile && (
            <>
              <button className="btn" aria-pressed={!!watched} onClick={toggleWatch}>
                <Radar aria-hidden /> {watched ? 'Watching' : 'Watchlist'}
              </button>
              <button className="btn" onClick={() => setExportOpen(true)}>
                <Download aria-hidden /> Export
              </button>
            </>
          )}
          <Menu
            label="More actions"
            trigger={<Ellipsis aria-hidden />}
            items={[
              ...(mobile
                ? [
                    { label: inCompare ? 'Remove from compare' : 'Add to compare', icon: <Columns3 aria-hidden />, onSelect: () => toggle(c) },
                    { label: watched ? 'Remove from watchlist' : 'Add to watchlist', icon: <Radar aria-hidden />, onSelect: toggleWatch },
                    { label: 'Export', icon: <Download aria-hidden />, onSelect: () => setExportOpen(true) },
                  ]
                : []),
              { label: 'Generate report', icon: <FileText aria-hidden />, onSelect: () => setReportOpen(true), disabled: !researched },
              { label: 'Refresh research', icon: <RefreshCw aria-hidden />, onSelect: () => nav(`/research?org=${c.orgNumber}&autostart=1`) },
              ...(profile.artifactId ? [{ label: 'Open saved research', icon: <History aria-hidden />, onSelect: () => nav(`/library/${profile.artifactId}`) }] : []),
            ]}
          />
        </div>
      </header>

      <Snapshot profile={profile} assessment={assess.data} />
      <WhatChanged profile={profile} onAllChanges={() => setTab('changes')} onExplain={onExplainChange} />

      <div className="co-tabs">
        <Tabs label="Company sections" value={tab} onChange={(t) => setTab(t as CompanyTab)} tabs={COMPANY_TABS.map((t) => ({ id: t, label: TAB_LABEL[t], count: counts[t] }))} />
      </div>

      <section id={`tabpanel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`} className="co-panel" key={tab}>
        <ErrorBoundary label={TAB_LABEL[tab]}>
          {tab === 'overview' && <OverviewSection profile={profile} onTab={setTab} hideSnapshotMetrics />}
          {tab === 'financials' && <FinancialsSection profile={profile} onExplain={(subject, title) => setExplain({ subject, title })} />}
          {tab === 'people' && <PeopleSection profile={profile} />}
          {tab === 'locations' && <LocationsSection profile={profile} />}
          {tab === 'website' && <WebsiteSection profile={profile} />}
          {tab === 'hiring' && <HiringSection profile={profile} />}
          {tab === 'activity' && <ActivitySection profile={profile} />}
          {tab === 'changes' && <ChangesSection profile={profile} onExplain={onExplainChange} />}
          {tab === 'sources' && <SourcesSection profile={profile} />}
        </ErrorBoundary>
      </section>

      {c.lastResearchedAt && (
        <p className="t-xs t-muted" style={{ marginTop: 28 }}>
          Research date {formatDate(c.lastResearchedAt)}. Every fact shows its own source, reporting period and verification date.
        </p>
      )}

      <ExportModal open={exportOpen} onClose={() => setExportOpen(false)} target={{ type: 'company', id: c.orgNumber }} title={c.legalName} />
      <ReportModal open={reportOpen} onClose={() => setReportOpen(false)} orgNumber={c.orgNumber} name={c.legalName} />
      <ExecutiveBriefModal open={briefOpen} onClose={() => setBriefOpen(false)} orgNumber={c.orgNumber} companyName={c.legalName} />
      {explain && <ExplainModal orgNumber={c.orgNumber} companyName={c.legalName} subject={explain.subject} title={explain.title} sourceIndex={profile.sourceIndex} onClose={() => setExplain(null)} />}
    </div>
  );
}

function CompanySkeleton() {
  return (
    <div className="page">
      <LoadingRegion label="Loading company profile">
        <div className="row" style={{ gap: 16, marginBottom: 24 }}>
          <Skeleton w={60} h={60} r={12} />
          <div className="stack" style={{ gap: 10, flex: 1 }}>
            <Skeleton w="40%" h={30} />
            <Skeleton w="60%" h={14} />
          </div>
        </div>
        <Skeleton h={44} r={10} style={{ marginBottom: 24 }} />
        <Skeleton h={140} r={12} style={{ marginBottom: 20 }} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 12, marginBottom: 20 }}>
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} h={110} r={12} />
          ))}
        </div>
        <Skeleton h={260} r={12} />
      </LoadingRegion>
    </div>
  );
}
