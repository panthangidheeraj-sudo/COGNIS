import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, ArrowRight, ArrowUp, Download, GitCompareArrows, History, LoaderCircle, Printer, RefreshCw, Search, Send, Sparkle, Telescope, X } from 'lucide-react';
import { api } from '@/api';
import type { CompanyArtifact, CompanyProfile, ReportArtifact, ResearchAnswer, VersionComparison } from '@/types';
import { ErrorState, ErrorBoundary } from '@/components/common/ErrorState';
import { Skeleton, LoadingRegion } from '@/components/common/Skeleton';
import { Modal } from '@/components/common/Overlay';
import { ExportModal } from '@/components/common/ExportModal';
import { CoverageMeter } from '@/components/company/Coverage';
import { ExecutiveSummary, KnownUnknown, ResearchQualityCard } from '@/components/company/sections/OverviewSection';
import { FinancialsSection } from '@/components/company/sections/FinancialsSection';
import { LocationsSection, PeopleSection } from '@/components/company/sections/PeopleLocations';
import { HiringSection, WebsiteSection } from '@/components/company/sections/OnlineHiring';
import { ActivitySection, ChangesSection, SourcesSection } from '@/components/company/sections/ActivitySources';
import { MetricCard } from '@/components/evidence/MetricCard';
import { AnswerView } from '@/components/research/AnswerView';
import { CompanyNetwork } from '@/components/network/CompanyNetwork';
import { AmbientGlobe } from '@/components/globe/AmbientGlobe';
import { buildIndex, DOSSIER_SECTIONS, revealInSection, searchIndex, type DossierSection, type SearchHit } from '@/components/artifacts/artifactSearch';
import { useOpenEvidence } from '@/components/evidence/useEvidence';
import { useCommand } from '@/hooks/useCommand';
import { useDebounce } from '@/hooks/useDebounce';
import { formatDate, formatDateLong, formatOrgNumber, formatRelative } from '@/utils/format';
import { cn } from '@/utils/cn';
import '@/styles/sections.css';
import './artifact.css';

export default function ArtifactPage() {
  const { artifactId = '' } = useParams();
  const [params] = useSearchParams();
  const versionId = params.get('version');
  const base = useQuery({ queryKey: ['artifact', artifactId], queryFn: () => api.library.get(artifactId) });
  const version = useQuery({
    queryKey: ['artifact', artifactId, 'version', versionId],
    queryFn: () => api.library.getVersion(artifactId, versionId!),
    enabled: !!versionId && base.data?.type === 'company' && base.data.versionId !== versionId,
  });
  if (base.isLoading || version.isLoading)
    return (
      <div className="page">
        <LoadingRegion label="Loading research">
          <Skeleton h={260} r={18} style={{ marginBottom: 20 }} />
          <Skeleton h={600} r={12} />
        </LoadingRegion>
      </div>
    );
  if (base.isError)
    return (
      <div className="page">
        <ErrorState error={base.error} onRetry={() => base.refetch()} />
      </div>
    );
  const a = base.data!;
  if (a.type === 'report') return <ReportView report={a} />;
  return <Dossier artifact={a} viewing={version.data ?? null} />;
}

/* ============================== Dossier ============================== */

function Dossier({ artifact, viewing }: { artifact: CompanyArtifact; viewing: CompanyArtifact | null }) {
  const profile = (viewing ?? artifact).profile;
  const c = profile.company;
  const isOld = !!viewing && viewing.versionId !== artifact.versionId;
  const currentVersion = artifact.versions.find((v) => v.id === (viewing?.versionId ?? artifact.versionId))!;
  const [active, setActive] = useState<DossierSection>('summary');
  const [exportOpen, setExportOpen] = useState(false);
  const [cmpOpen, setCmpOpen] = useState(false);
  const nav = useNavigate();
  useCommand('export', () => setExportOpen(true));
  const assess = useQuery({ queryKey: ['assess', artifact.id], queryFn: () => api.research.assess(artifact.id), enabled: !isOld });

  // Active section tracking for the in-page navigation
  useEffect(() => {
    const els = DOSSIER_SECTIONS.map((s) => document.getElementById(`sec-${s.id}`)).filter(Boolean) as HTMLElement[];
    const io = new IntersectionObserver(
      (entries) => {
        const vis = entries.filter((e) => e.isIntersecting).sort((x, y) => x.boundingClientRect.top - y.boundingClientRect.top);
        if (vis[0]) setActive(vis[0].target.id.replace('sec-', '') as DossierSection);
      },
      { rootMargin: '-20% 0px -65% 0px' },
    );
    els.forEach((e) => io.observe(e));
    return () => io.disconnect();
  }, [profile]);

  const a = assess.data;
  const needs = a ? a.staleAreas.length + a.changedSources.length + a.newFilings : 0;
  const hq = profile.locations.locations.find((l) => l.kind === 'headquarters' && l.geo)?.geo ?? c.geo ?? undefined;

  return (
    <div className="page page--wide dossier">
      <header className="dos-cover">
        <AmbientGlobe lat={hq?.lat} lon={hq?.lon} className="dos-cover-globe" />
        <div className="dos-cover-body">
          <Link to="/library" className="link-btn dos-back">
            <ArrowLeft aria-hidden /> Library
          </Link>
          <span className="eyebrow">COGNIS · Company research</span>
          <h1 className="dos-title">{c.legalName}</h1>
          <div className="dos-meta">
            <span>{c.municipality}, Norway</span>
            <span>
              Org. no. <span className="t-mono">{formatOrgNumber(c.orgNumber)}</span>
            </span>
            <span>{c.industry?.description}</span>
            <span>{c.statusLabel}</span>
          </div>
          <div className="dos-cover-row">
            <CoverageMeter coverage={c.coverage} />
            <span className="pill pill--glass">
              <History aria-hidden /> {isOld ? 'Previous version' : 'Saved research'} · {formatDate(currentVersion.createdAt)}
            </span>
          </div>
          <div className="row-wrap" style={{ gap: 8 }}>
            <Link to={`/research?org=${c.orgNumber}`} className="btn btn--ivory">
              <Telescope aria-hidden /> Continue research
            </Link>
            {artifact.versions.length > 1 && (
              <button className="btn" onClick={() => setCmpOpen(true)}>
                <GitCompareArrows aria-hidden /> Compare versions
              </button>
            )}
            <button className="btn" onClick={() => setExportOpen(true)}>
              <Download aria-hidden /> Export
            </button>
            <Link to={`/company/${c.orgNumber}`} className="btn btn--ghost">
              Company profile <ArrowRight aria-hidden />
            </Link>
          </div>
        </div>
      </header>

      {isOld ? (
        <div className="notice notice--info dos-banner" role="status">
          <History aria-hidden />
          <span style={{ flex: 1 }}>
            You are viewing research from <strong>{formatDateLong(currentVersion.createdAt)}</strong>. Facts reflect what was verified at that time.
          </span>
          <button className="btn btn--sm" onClick={() => nav(`/library/${artifact.id}`)}>
            Back to current
          </button>
        </div>
      ) : (
        <div className={cn('dos-continue', needs > 0 && 'has-updates')} role="status">
          {assess.isLoading ? (
            <span className="row t-sm t-muted" style={{ gap: 8 }}>
              <LoaderCircle className="spin" width={15} height={15} aria-hidden /> Checking sources for newer data…
            </span>
          ) : a && needs > 0 ? (
            <>
              <Sparkle aria-hidden className="t-accent" />
              <span className="dos-continue-items">
                {a.staleAreas.length > 0 && (
                  <span title={a.staleAreas.map((s) => `${s.area}: ${s.reason}`).join('\n')}>
                    <strong>{a.staleAreas.length}</strong> area{a.staleAreas.length === 1 ? '' : 's'} need refresh
                  </span>
                )}
                {a.changedSources.length > 0 && (
                  <span title={a.changedSources.map((s) => `${s.sourceName}: ${s.detail}`).join('\n')}>
                    <strong>{a.changedSources.length}</strong> source{a.changedSources.length === 1 ? ' has' : 's have'} changed
                  </span>
                )}
                {a.newFilings > 0 && (
                  <span>
                    <strong>{a.newFilings}</strong> new filing detected
                  </span>
                )}
              </span>
              <span className="spacer" />
              <Link to={`/research?org=${c.orgNumber}&autostart=1`} className="btn btn--primary btn--sm">
                <RefreshCw aria-hidden /> Update research
              </Link>
            </>
          ) : (
            <span className="t-sm t-soft">
              Saved research is current · last updated {formatRelative(artifact.freshness.lastUpdatedAt)}. No newer source data detected.
            </span>
          )}
        </div>
      )}

      <div className="dos-grid">
        <nav className="dos-nav" aria-label="Sections">
          <ol>
            {DOSSIER_SECTIONS.map((s, i) => (
              <li key={s.id}>
                <a
                  href={`#sec-${s.id}`}
                  className={cn('dos-nav-link', active === s.id && 'is-active')}
                  aria-current={active === s.id ? 'location' : undefined}
                  onClick={(e) => {
                    e.preventDefault();
                    document.getElementById(`sec-${s.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                  }}
                >
                  <span className="t-mono">{String(i + 1).padStart(2, '0')}</span> {s.label}
                </a>
              </li>
            ))}
          </ol>
        </nav>

        <div className="dos-main">
          <ArtifactSearch profile={profile} />
          <article className="paper dos-paper">
            <DossierBody profile={profile} />
          </article>
        </div>

        <aside className="dos-side">
          <section className="card" aria-labelledby="hist-h">
            <h2 id="hist-h" className="t-micro" style={{ marginBottom: 12 }}>
              Research history
            </h2>
            <ol className="versions">
              {artifact.versions.map((v) => {
                const sel = v.id === (viewing?.versionId ?? artifact.versionId);
                return (
                  <li key={v.id}>
                    <Link to={v.isCurrent ? `/library/${artifact.id}` : `/library/${artifact.id}?version=${v.id}`} className={cn('version', sel && 'is-active')} aria-current={sel ? 'true' : undefined}>
                      <span className="version-dot" aria-hidden />
                      <span className="stack" style={{ gap: 0 }}>
                        <span className="t-sm">{v.isCurrent ? 'Current' : v.label}</span>
                        <span className="t-xs t-muted">{formatDate(v.createdAt)}</span>
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ol>
            {artifact.versions.length > 1 && (
              <button className="btn btn--sm btn--block" style={{ marginTop: 12 }} onClick={() => setCmpOpen(true)}>
                <GitCompareArrows aria-hidden /> Compare versions
              </button>
            )}
          </section>
          <AskResearch profile={profile} artifactId={artifact.id} />
        </aside>
      </div>

      <ExportModal open={exportOpen} onClose={() => setExportOpen(false)} target={{ type: 'artifact', id: artifact.id }} title={c.legalName} />
      {cmpOpen && <VersionCompareModal artifact={artifact} onClose={() => setCmpOpen(false)} />}
    </div>
  );
}

function SectionHead({ id, index }: { id: DossierSection; index: number }) {
  const s = DOSSIER_SECTIONS.find((x) => x.id === id)!;
  return (
    <div className="dos-sec-head">
      <span className="dos-sec-num t-mono">{String(index + 1).padStart(2, '0')}</span>
      <h2>{s.label}</h2>
    </div>
  );
}

export function DossierBody({ profile, sections }: { profile: CompanyProfile; sections?: DossierSection[] }) {
  const show = (id: DossierSection) => !sections || sections.includes(id);
  const list = DOSSIER_SECTIONS.filter((s) => show(s.id));
  const idx = (id: DossierSection) => list.findIndex((s) => s.id === id);
  return (
    <>
      {show('summary') && (
        <section id="sec-summary" className="dos-sec block">
          <SectionHead id="summary" index={idx('summary')} />
          <ExecutiveSummary profile={profile} paper />
          <div className="metrics-grid" style={{ marginTop: 18 }}>
            {profile.keyMetrics.map((f) => (
              <MetricCard key={f.id} fact={f} sourceIndex={profile.sourceIndex} context={profile.company.legalName} />
            ))}
          </div>
          <div className="dos-two" style={{ marginTop: 18 }}>
            <div className="card">
              <KnownUnknown items={profile.knowns} />
            </div>
            <div className="card">
              <h3 className="t-micro" style={{ marginBottom: 10 }}>
                Research quality
              </h3>
              <ResearchQualityCard profile={profile} />
            </div>
          </div>
        </section>
      )}
      {show('financials') && (
        <section id="sec-financials" className="dos-sec block">
          <SectionHead id="financials" index={idx('financials')} />
          <ErrorBoundary label="Financials">
            <FinancialsSection profile={profile} compactCharts />
          </ErrorBoundary>
        </section>
      )}
      {show('people') && (
        <section id="sec-people" className="dos-sec block">
          <SectionHead id="people" index={idx('people')} />
          <PeopleSection profile={profile} showNetwork={false} />
          {profile.relationships.length > 0 && (
            <div className="card" style={{ marginTop: 16 }}>
              <h3 className="t-micro" style={{ marginBottom: 8 }}>
                Relationship network
              </h3>
              <CompanyNetwork name={profile.company.legalName} relationships={profile.relationships} compact height={300} />
            </div>
          )}
        </section>
      )}
      {show('locations') && (
        <section id="sec-locations" className="dos-sec block">
          <SectionHead id="locations" index={idx('locations')} />
          <LocationsSection profile={profile} mapHeight={320} />
        </section>
      )}
      {show('website') && (
        <section id="sec-website" className="dos-sec block">
          <SectionHead id="website" index={idx('website')} />
          <WebsiteSection profile={profile} />
        </section>
      )}
      {show('hiring') && (
        <section id="sec-hiring" className="dos-sec block">
          <SectionHead id="hiring" index={idx('hiring')} />
          <HiringSection profile={profile} />
        </section>
      )}
      {show('activity') && (
        <section id="sec-activity" className="dos-sec block">
          <SectionHead id="activity" index={idx('activity')} />
          <ActivitySection profile={profile} />
        </section>
      )}
      {show('changes') && (
        <section id="sec-changes" className="dos-sec block">
          <SectionHead id="changes" index={idx('changes')} />
          <ChangesSection profile={profile} />
        </section>
      )}
      {show('sources') && (
        <section id="sec-sources" className="dos-sec block">
          <SectionHead id="sources" index={idx('sources')} />
          <SourcesSection profile={profile} />
        </section>
      )}
    </>
  );
}

/* ---------------------------- internal search ---------------------------- */

function ArtifactSearch({ profile }: { profile: CompanyProfile }) {
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [returnY, setReturnY] = useState<number | null>(null);
  const dq = useDebounce(q, 120);
  const index = useMemo(() => buildIndex(profile), [profile]);
  const hits = useMemo(() => searchIndex(index, dq), [index, dq]);
  const wrap = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const openEv = useOpenEvidence(profile.sourceIndex, profile.company.legalName);
  useEffect(() => {
    const on = (e: MouseEvent) => !wrap.current?.contains(e.target as Node) && setOpen(false);
    window.addEventListener('mousedown', on);
    return () => window.removeEventListener('mousedown', on);
  }, []);
  useEffect(() => setActive(0), [dq]);
  useCommand('search-research', () => {
    wrap.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setTimeout(() => input.current?.focus(), 250);
    setOpen(true);
  });

  // Results grouped by section (in dossier order); the flat order drives keyboard navigation.
  const grouped = DOSSIER_SECTIONS.map((s) => ({ ...s, hits: hits.filter((h) => h.section === s.id).slice(0, 8) })).filter((g) => g.hits.length);
  const flat = grouped.flatMap((g) => g.hits);
  const terms = dq.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const mark = (text: string) => {
    if (!terms.length) return text;
    const re = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi');
    return text.split(re).map((part, i) => (terms.includes(part.toLowerCase()) ? <mark key={i}>{part}</mark> : part));
  };
  const choose = (h: SearchHit, term = dq) => {
    setReturnY(window.scrollY);
    setOpen(false);
    // Financial figures may sit in a chart view rather than as text, and evidence
    // excerpts are not printed in the dossier: scroll to the section, then open the evidence.
    const direct = h.kind === 'Evidence' || (h.kind === 'Metric' && h.section === 'financials');
    const found = direct ? (revealInSection(h.section, ''), false) : revealInSection(h.section, h.kind === 'Section' ? '' : term);
    if (h.evidence && !found) setTimeout(() => openEv({ title: h.evidence!.title, value: h.evidence!.value, evidence: h.evidence!.items }), 450);
  };

  return (
    <div className="art-search" ref={wrap}>
      <div className="input-wrap">
        <Search aria-hidden />
        <label htmlFor="art-q" className="sr-only">
          Search this research
        </label>
        <input
          ref={input}
          id="art-q"
          className="input"
          value={q}
          role="combobox"
          aria-expanded={open && flat.length > 0}
          aria-controls="art-results"
          aria-activedescendant={open && flat[active] ? `art-hit-${flat[active].index}` : undefined}
          onChange={(e) => (setQ(e.target.value), setOpen(true))}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setOpen(false);
            else if (e.key === 'ArrowDown') (e.preventDefault(), setOpen(true), setActive((a) => Math.min(a + 1, flat.length - 1)));
            else if (e.key === 'ArrowUp') (e.preventDefault(), setActive((a) => Math.max(a - 1, 0)));
            else if (e.key === 'Enter') {
              e.preventDefault();
              // Typed faster than the debounce: search the current text directly.
              const target = q.trim() === dq.trim() ? flat[active] : searchIndex(index, q)[0];
              if (target) choose(target, q);
            }
          }}
          placeholder="Search this research… values, people, events, dates, sources, evidence"
          autoComplete="off"
        />
        {q && (
          <button className="btn btn--ghost btn--icon btn--sm art-search-x" onClick={() => (setQ(''), input.current?.focus())} aria-label="Clear">
            <X aria-hidden />
          </button>
        )}
      </div>
      {open && dq.trim().length >= 2 && (
        <div className="art-search-results" id="art-results" role="listbox" aria-label="Matches in this research">
          <div className="art-search-count" role="status">
            {hits.length ? `${hits.length} match${hits.length === 1 ? '' : 'es'} in ${grouped.length} section${grouped.length === 1 ? '' : 's'}` : `No matches for “${dq.trim()}” in this research`}
            <span className="spacer" />
            {hits.length > 0 && <span className="kbd-hint">↑↓ to move · Enter to open</span>}
          </div>
          {grouped.map((g) => (
            <div key={g.id} role="group" aria-label={g.label}>
              <div className="art-search-sec">
                {g.label}
                <span className="t-num">{hits.filter((h) => h.section === g.id).length}</span>
              </div>
              {g.hits.map((h) => {
                const i = flat.indexOf(h);
                return (
                  <button
                    key={h.index}
                    id={`art-hit-${h.index}`}
                    role="option"
                    aria-selected={i === active}
                    className={cn('art-hit', i === active && 'is-active')}
                    onMouseEnter={() => setActive(i)}
                    onClick={() => choose(h)}
                  >
                    <span className="art-hit-kind">{h.kind}</span>
                    <span className="art-hit-body">
                      <span className="art-hit-text">{mark(h.text)}</span>
                      {h.meta && <span className="art-hit-meta">{mark(h.meta)}</span>}
                    </span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}
      {returnY != null && (
        <button
          className="art-return"
          onClick={() => {
            window.scrollTo({ top: returnY, behavior: 'smooth' });
            setReturnY(null);
          }}
        >
          <ArrowUp aria-hidden /> Back to where you were
          <span
            className="art-return-x"
            role="button"
            tabIndex={0}
            aria-label="Dismiss"
            onClick={(e) => (e.stopPropagation(), setReturnY(null))}
            onKeyDown={(e) => e.key === 'Enter' && (e.stopPropagation(), setReturnY(null))}
          >
            <X aria-hidden />
          </span>
        </button>
      )}
    </div>
  );
}

/* ---------------------------- ask this research ---------------------------- */

const ASK = ['What changed?', 'What are the latest financials?', 'Who runs the company?', 'Show evidence for revenue.', 'What hiring activity exists?', 'What do we still not know?'];

function AskResearch({ profile, artifactId }: { profile: CompanyProfile; artifactId: string }) {
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState<false | 'saved' | 'fresh'>(false);
  const [answers, setAnswers] = useState<ResearchAnswer[]>([]);
  const ask = async (question: string, fresh = false) => {
    if (!question.trim()) return;
    setBusy(fresh ? 'fresh' : 'saved');
    try {
      const a = await api.research.ask({ orgNumber: profile.company.orgNumber, artifactId, question, fresh });
      setAnswers((xs) => [a, ...xs]);
      setQ('');
    } finally {
      setBusy(false);
    }
  };
  const last = answers[0];
  return (
    <section className="card ask" aria-labelledby="ask-h">
      <h2 id="ask-h" className="t-micro" style={{ marginBottom: 6 }}>
        Ask about this research
      </h2>
      <p className="t-xs t-muted" style={{ marginBottom: 10 }}>
        Answers come from the evidence saved in this research first. “Research more” queries sources live.
      </p>
      <form
        className="ask-form"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(q);
        }}
      >
        <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask Cognis about this research" aria-label="Ask about this research" />
        <button className="btn btn--primary btn--icon" aria-label="Ask" disabled={!!busy || !q.trim()}>
          {busy === 'saved' ? <LoaderCircle className="spin" aria-hidden /> : <Send aria-hidden />}
        </button>
      </form>
      <div className="row-wrap" style={{ gap: 6, marginTop: 10 }}>
        {ASK.map((s) => (
          <button key={s} className="chip" style={{ height: 26, fontSize: 12 }} onClick={() => void ask(s)} disabled={!!busy}>
            {s}
          </button>
        ))}
      </div>
      {answers.length > 0 && (
        <div className="stack" style={{ gap: 16, marginTop: 16 }}>
          {answers.map((a) => (
            <AnswerView key={a.id + a.generatedAt + a.origin} answer={a} sourceIndex={profile.sourceIndex} context={profile.company.legalName} />
          ))}
          {last && last.origin === 'saved_evidence' && (
            <button className="btn btn--sm" onClick={() => void ask(last.question, true)} disabled={!!busy}>
              {busy === 'fresh' ? <LoaderCircle className="spin" aria-hidden /> : <Telescope aria-hidden />} Research more (live sources)
            </button>
          )}
        </div>
      )}
    </section>
  );
}

/* ---------------------------- version comparison ---------------------------- */

function VersionCompareModal({ artifact, onClose }: { artifact: CompanyArtifact; onClose: () => void }) {
  const vs = artifact.versions;
  const [from, setFrom] = useState(vs[vs.length - 1].id);
  const [to, setTo] = useState(vs[0].id);
  const q = useQuery<VersionComparison>({ queryKey: ['vcmp', artifact.id, from, to], queryFn: () => api.library.compareVersions(artifact.id, from, to), enabled: from !== to });
  const label = (id: string) => {
    const v = vs.find((x) => x.id === id)!;
    return `${v.isCurrent ? 'Current' : v.label} · ${formatDate(v.createdAt)}`;
  };
  return (
    <Modal open onClose={onClose} title={`Compare versions · ${artifact.title}`} wide>
      <div className="row-wrap" style={{ gap: 12, marginBottom: 16 }}>
        <label className="field" style={{ minWidth: 220 }}>
          <span className="field-label">From</span>
          <select className="select" value={from} onChange={(e) => setFrom(e.target.value)}>
            {vs.map((v) => (
              <option key={v.id} value={v.id}>
                {label(v.id)}
              </option>
            ))}
          </select>
        </label>
        <ArrowRight aria-hidden style={{ marginTop: 22 }} className="t-muted" />
        <label className="field" style={{ minWidth: 220 }}>
          <span className="field-label">To</span>
          <select className="select" value={to} onChange={(e) => setTo(e.target.value)}>
            {vs.map((v) => (
              <option key={v.id} value={v.id}>
                {label(v.id)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {from === to ? (
        <p className="t-sm t-muted">Choose two different versions.</p>
      ) : q.isLoading ? (
        <Skeleton h={240} />
      ) : q.data ? (
        <div className="table-wrap">
          <table className="table vcmp">
            <caption className="sr-only">Differences between versions</caption>
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col">{formatDate(q.data.from.createdAt)}</th>
                <th scope="col">{formatDate(q.data.to.createdAt)}</th>
                <th scope="col">
                  <span className="sr-only">Changed</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {q.data.rows.map((r) => (
                <tr key={r.key} className={r.changed ? 'is-changed' : ''}>
                  <th scope="row" style={{ fontWeight: 400 }}>
                    {r.label}
                  </th>
                  <td className="t-num">{r.from ?? <span className="t-muted">Not available</span>}</td>
                  <td className="t-num" style={{ fontWeight: r.changed ? 500 : 400 }}>
                    {r.to ?? <span className="t-muted">Not available</span>}
                  </td>
                  <td>{r.changed ? <span className="pill pill--sm pill--info">Changed</span> : <span className="t-xs t-muted">Same</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <ErrorState error={q.error} />
      )}
    </Modal>
  );
}

/* ============================== Report ============================== */

function ReportView({ report }: { report: ReportArtifact }) {
  const p = report.profile;
  const map: Record<string, DossierSection> = { summary: 'summary', financials: 'financials', people: 'people', locations: 'locations', hiring: 'hiring', activity: 'activity', sources: 'sources' };
  const sections = report.sections.map((s) => map[s]).filter(Boolean);
  const [exportOpen, setExportOpen] = useState(false);
  return (
    <div className="page report">
      <div className="row-wrap report-actions" style={{ marginBottom: 16 }}>
        <Link to="/library?type=report" className="link-btn">
          <ArrowLeft aria-hidden /> Library
        </Link>
        <span className="spacer" />
        <button className="btn btn--sm" onClick={() => window.print()}>
          <Printer aria-hidden /> Print
        </button>
        <button className="btn btn--sm" onClick={() => setExportOpen(true)}>
          <Download aria-hidden /> Export data
        </button>
      </div>
      <section className="report-cover" aria-label="Report cover">
        <svg className="report-cover-art" viewBox="0 0 600 600" aria-hidden>
          {Array.from({ length: 9 }, (_, i) => (
            <ellipse key={i} cx="430" cy="300" rx={60 + i * 28} ry={(60 + i * 28) * 0.98} />
          ))}
          {Array.from({ length: 12 }, (_, i) => (
            <ellipse key={`m${i}`} cx="430" cy="300" rx={Math.abs(Math.cos((i / 12) * Math.PI)) * 290} ry="290" />
          ))}
        </svg>
        <span className="report-brand t-mono">COGNIS</span>
        <span className="report-kind">{report.kind === 'company_brief' ? 'Company brief' : 'Deep research report'}</span>
        <h1 className="report-title">{p.company.legalName}</h1>
        <div className="report-meta">
          <span>{p.company.municipality}, Norway</span>
          <span>Org. no. {formatOrgNumber(p.company.orgNumber)}</span>
        </div>
        <div className="report-date">
          <span className="t-micro">Research date</span>
          <span>{formatDateLong(p.company.lastResearchedAt ?? report.createdAt)}</span>
        </div>
      </section>
      <article className="paper dos-paper report-body">
        <DossierBody profile={p} sections={sections} />
      </article>
      <ExportModal open={exportOpen} onClose={() => setExportOpen(false)} target={{ type: 'company', id: p.company.orgNumber }} title={report.title} />
    </div>
  );
}
