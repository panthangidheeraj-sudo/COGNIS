import { useMemo, useState } from 'react';
import { ChevronDown, Lightbulb } from 'lucide-react';
import type { Change, CompanyProfile, SourceKind } from '@/types';
import { Segmented } from '@/components/common/Tabs';
import { useOpenEvidence } from '@/components/evidence/useEvidence';
import { EmptyState } from '@/components/common/EmptyState';
import { ExternalLink } from '@/components/common/ExternalLink';
import { SourceIcon } from '@/components/source/SourceIcon';
import { SectionState } from '../SectionState';
import { formatDate, formatDateTime, formatRelative, pluralize } from '@/utils/format';
import { CHANGE_CATEGORY_LABEL, CHANGE_ORDER, EVENT_LABEL, SOURCE_KIND_LABEL, SOURCE_TIER_LABEL } from '@/utils/status';
import { cn } from '@/utils/cn';

export function ActivitySection({ profile }: { profile: CompanyProfile }) {
  const all = profile.activity.events;
  const majorCount = all.filter((e) => e.significance === 'major').length;
  const [view, setView] = useState<'executive' | 'all'>('executive');
  const events = view === 'executive' ? all.filter((e) => e.significance === 'major') : all;
  const [open, setOpen] = useState<string | null>(null);
  const openEv = useOpenEvidence(profile.sourceIndex, profile.company.legalName);
  const byYear = useMemo(() => {
    const m = new Map<string, typeof events>();
    for (const e of events) m.set(e.date.slice(0, 4), [...(m.get(e.date.slice(0, 4)) ?? []), e]);
    return [...m.entries()];
  }, [events]);
  return (
    <div className="stack" style={{ gap: 14 }}>
      <SectionState meta={profile.activity} sourceIndex={profile.sourceIndex} />
      {all.length > 0 && (
        <div className="row-wrap tl-bar">
          <Segmented
            label="Timeline view"
            value={view}
            onChange={setView}
            options={[
              { value: 'executive', label: 'Major events', title: 'CEO changes, filings, ownership, acquisitions, new locations, major contracts, expansions and significant hiring' },
              { value: 'all', label: 'All events' },
            ]}
          />
          <span className="t-xs t-muted">
            {view === 'executive' ? `${majorCount} major of ${all.length} events` : `${all.length} events`}
          </span>
          {view === 'executive' && majorCount < all.length && (
            <button className="link-btn" onClick={() => setView('all')}>
              Show all events
            </button>
          )}
        </div>
      )}
      {!events.length && profile.activity.status !== 'pending' && <EmptyState compact title={view === 'executive' && all.length ? 'No major events recorded. Show all events for minor updates.' : 'No verified major public changes were found in the searched sources.'} />}
      <div className="timeline" data-search-block="timeline">
        {byYear.map(([year, list]) => (
          <div key={year}>
            <div className="tl-year">{year}</div>
            {list.map((e) => {
              const expanded = open === e.id;
              return (
                <div key={e.id} className="tl-item">
                  <span className="tl-dot" aria-hidden />
                  <div className="tl-body">
                    <button className="tl-toggle" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : e.id)}>
                      <span className="tl-title">{e.title}</span>
                      <ChevronDown aria-hidden className={cn('tl-chev', expanded && 'is-open')} />
                    </button>
                    <div className="tl-meta">
                      <time dateTime={e.date}>{formatDate(e.date)}</time>
                      <span className="pill pill--sm">{EVENT_LABEL[e.type]}</span>
                      {view === 'all' && e.significance === 'minor' && <span className="t-xs t-muted">Minor</span>}
                      <span>{e.sourceIds.map((s) => profile.sourceIndex[s]?.name ?? s).join(', ')}</span>
                    </div>
                    {expanded && (
                      <div className="tl-detail anim-fade-up">
                        {e.description && <p className="t-sm t-soft">{e.description}</p>}
                        <div className="row-wrap">
                          <button className="btn btn--sm" onClick={() => openEv({ title: e.title, value: formatDate(e.date), evidence: e.evidence })}>
                            View evidence
                          </button>
                          <ExternalLink href={e.evidence[0]?.url}>Open source</ExternalLink>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ChangesSection({ profile, onExplain }: { profile: CompanyProfile; onExplain?: (c: Change) => void }) {
  const ch = profile.changes;
  const openEv = useOpenEvidence(profile.sourceIndex, profile.company.legalName);
  const [showMinor, setShowMinor] = useState(false);
  const material = [...ch.changes.filter((c) => c.material)].sort((a, b) => CHANGE_ORDER.indexOf(a.category) - CHANGE_ORDER.indexOf(b.category) || b.detectedAt.localeCompare(a.detectedAt));
  const minor = ch.changes.filter((c) => !c.material);
  const list = showMinor ? [...material, ...minor] : material;
  return (
    <div className="stack" style={{ gap: 14 }}>
      <div className="block-head" style={{ marginBottom: 0 }}>
        <h2 className="t-h2">What changed?</h2>
        {ch.since && <span className="t-micro">Since the {ch.baselineLabel ?? 'previous research'} · {formatDate(ch.since)}</span>}
      </div>
      <SectionState meta={ch} sourceIndex={profile.sourceIndex} />
      {ch.status !== 'pending' && material.length === 0 && ch.changes.length > 0 && <p className="t-sm t-soft">No verified material changes were detected. Minor updates are listed below.</p>}
      {list.length > 0 && (
        <ul className="card" style={{ padding: '4px 20px' }} data-search-block="changes">
          {list.map((c) => (
            <li key={c.id} className={cn('change', !c.material && 'change--minor')}>
              <span className={cn('change-sym', c.kind === 'removed' && 'change-sym--removed')} aria-label={c.kind}>
                {c.kind === 'added' ? '+' : c.kind === 'removed' ? '−' : '↕'}
              </span>
              <div className="stack" style={{ gap: 4, minWidth: 0 }}>
                <span className="row-wrap" style={{ gap: 8 }}>
                  <span style={{ fontWeight: 500 }}>{c.label}</span>
                  <span className="pill pill--sm">{CHANGE_CATEGORY_LABEL[c.category]}</span>
                  {!c.material && <span className="t-xs t-muted">Minor</span>}
                </span>
                <span className="change-vals">
                  {c.previous && <span className="change-prev">{c.previous}</span>}
                  {c.previous && (
                    <span className="change-arrow" aria-label="changed to">
                      →
                    </span>
                  )}
                  {c.current && <span className="change-cur">{c.current}</span>}
                </span>
                <span className="t-xs t-muted" title={formatDateTime(c.detectedAt)}>
                  Detected {formatRelative(c.detectedAt)} · {c.evidence.map((e) => profile.sourceIndex[e.sourceId]?.name).join(', ')}
                </span>
              </div>
              <div className="row" style={{ gap: 4 }}>
                {c.explainable && onExplain && (
                  <button className="btn btn--ghost btn--sm" onClick={() => onExplain(c)}>
                    <Lightbulb aria-hidden /> Explain
                  </button>
                )}
                <button className="btn btn--ghost btn--sm" onClick={() => openEv({ title: c.label, value: c.previous ? `${c.previous} → ${c.current}` : c.current, evidence: c.evidence })}>
                  Evidence
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {minor.length > 0 && (
        <button className="link-btn" onClick={() => setShowMinor((x) => !x)} style={{ alignSelf: 'flex-start' }}>
          {showMinor ? 'Hide minor updates' : `Show ${minor.length} minor update${minor.length === 1 ? '' : 's'}`}
        </button>
      )}
    </div>
  );
}

const FILTERS: { id: string; label: string; test: (k: SourceKind, tier: string, official: boolean) => boolean }[] = [
  { id: 'all', label: 'All', test: () => true },
  { id: 'primary', label: 'Primary', test: (_, t) => t === 'primary' },
  { id: 'secondary', label: 'Secondary', test: (_, t) => t !== 'primary' },
  { id: 'official', label: 'Official', test: (_, __, o) => o },
  { id: 'web', label: 'Web', test: (k) => k === 'web' || k === 'website' || k === 'news' },
  { id: 'financial', label: 'Financial', test: (k) => k === 'financial' },
  { id: 'jobs', label: 'Jobs', test: (k) => k === 'jobs' },
  { id: 'regulatory', label: 'Regulatory', test: (k) => k === 'regulatory' || k === 'registry' || k === 'activity' },
];

export function SourcesSection({ profile }: { profile: CompanyProfile }) {
  const [filter, setFilter] = useState('all');
  const [sort, setSort] = useState<'authority' | 'newest' | 'section'>('authority');
  const f = FILTERS.find((x) => x.id === filter)!;
  const list = profile.sources
    .filter((s) => f.test(s.source.kind, s.source.tier, s.source.official))
    .sort((a, b) =>
      sort === 'newest' ? b.lastRetrievedAt.localeCompare(a.lastRetrievedAt) : sort === 'section' ? (a.sections[0] ?? '').localeCompare(b.sections[0] ?? '') : ['primary', 'secondary', 'discovery'].indexOf(a.source.tier) - ['primary', 'secondary', 'discovery'].indexOf(b.source.tier) || b.factCount - a.factCount,
    );
  const tiers = sort === 'authority' ? (['primary', 'secondary', 'discovery'] as const) : null;
  const q = profile.quality;
  return (
    <div className="stack" style={{ gap: 16 }}>
      <p className="t-sm t-soft">
        Every published fact is linked to source evidence. {pluralize(q.primarySources, 'primary source')}, {pluralize(q.secondarySources, 'secondary source')}
        {q.conflicts ? `, ${pluralize(q.conflicts, 'conflict')} flagged` : ', no conflicts'}.
      </p>
      <div className="row-wrap" style={{ justifyContent: 'space-between' }}>
        <div className="row-wrap" role="group" aria-label="Filter sources">
          {FILTERS.map((x) => (
            <button key={x.id} className="chip" aria-pressed={filter === x.id} onClick={() => setFilter(x.id)} style={{ height: 30 }}>
              {x.label}
            </button>
          ))}
        </div>
        <label className="row t-sm t-muted" style={{ gap: 8 }}>
          Sort
          <select className="select" style={{ width: 170, height: 34 }} value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
            <option value="authority">Most authoritative</option>
            <option value="newest">Newest retrieval</option>
            <option value="section">Section</option>
          </select>
        </label>
      </div>
      {list.length === 0 && <EmptyState compact title="No sources match this filter." />}
      {(tiers ?? [null]).map((tier) => {
        const items = tier ? list.filter((s) => s.source.tier === tier) : list;
        if (!items.length) return null;
        return (
          <section key={tier ?? 'all'} aria-label={tier ? `${SOURCE_TIER_LABEL[tier]} sources` : 'Sources'} data-search-block={`sources-${tier ?? 'all'}`}>
            {tier && <h3 className="t-micro" style={{ margin: '6px 0 10px' }}>{SOURCE_TIER_LABEL[tier]} sources</h3>}
            <div className="sources-grid">
              {items.map((s) => (
                <div key={s.source.id} className="source-card">
                  <div className="row" style={{ gap: 10, alignItems: 'flex-start' }}>
                    <span className="ev-src-icon">
                      <SourceIcon kind={s.source.kind} />
                    </span>
                    <div className="stack" style={{ gap: 2, minWidth: 0, flex: 1 }}>
                      <strong className="ev-src-name truncate">{s.source.name}</strong>
                      {s.source.originalTitle && <span className="t-xs t-muted truncate">{s.source.originalTitle}</span>}
                    </div>
                  </div>
                  <div className="row-wrap" style={{ gap: 6 }}>
                    <span className={`pill pill--sm ${s.source.tier === 'primary' ? 'pill--ok' : ''}`}>{SOURCE_TIER_LABEL[s.source.tier]}</span>
                    <span className="pill pill--sm">{SOURCE_KIND_LABEL[s.source.kind]}</span>
                    {s.source.official && <span className="pill pill--sm">Official</span>}
                  </div>
                  <dl className="kv" style={{ gridTemplateColumns: '100px 1fr', fontSize: 12.5, gap: 4 }}>
                    <dt>Facts</dt>
                    <dd className="t-num">{s.factCount}</dd>
                    <dt>Last retrieved</dt>
                    <dd title={formatDateTime(s.lastRetrievedAt)}>{formatDate(s.lastRetrievedAt)}</dd>
                    <dt>Sections</dt>
                    <dd className="truncate">{s.sections.join(', ')}</dd>
                  </dl>
                  <ExternalLink href={s.source.url}>Open source</ExternalLink>
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
