import { useMemo, useState } from 'react';
import { ChevronDown, Lightbulb } from 'lucide-react';
import type { ActivitySection as ActivitySectionData, Change, CompanyProfile, EventSignificance, SourceKind, TimelineEvent } from '@/types';
import { Segmented } from '@/components/common/Tabs';
import { useOpenEvidence } from '@/components/evidence/useEvidence';
import { EmptyState } from '@/components/common/EmptyState';
import { ExternalLink } from '@/components/common/ExternalLink';
import { SourceIcon } from '@/components/source/SourceIcon';
import { SectionState } from '../SectionState';
import { formatDate, formatDateTime, formatRelative, pluralize } from '@/utils/format';
import { ACTIVITY_CHECK_LABEL, CHANGE_CATEGORY_LABEL, CHANGE_ORDER, EVENT_LABEL, EVENT_SOURCE_LABEL, SIGNIFICANCE_HINT, SIGNIFICANCE_LABEL, SOURCE_KIND_LABEL, SOURCE_TIER_LABEL, eventTier } from '@/utils/status';
import { cn } from '@/utils/cn';

type ActivityView = 'major' | 'relevant' | 'all';
type ActivitySort = 'date' | 'significance';
const TIER_ORDER: Record<EventSignificance, number> = { major: 0, relevant: 1, routine: 2 };

function countTiers(events: TimelineEvent[]): Record<EventSignificance, number> {
  const out: Record<EventSignificance, number> = { major: 0, relevant: 0, routine: 0 };
  for (const e of events) out[eventTier(e)] += 1;
  return out;
}

function rankOrder(a: TimelineEvent, b: TimelineEvent): number {
  if (a.rank != null && b.rank != null) return a.rank - b.rank;
  return TIER_ORDER[eventTier(a)] - TIER_ORDER[eventTier(b)] || (b.score ?? 0) - (a.score ?? 0) || b.date.localeCompare(a.date);
}

export function ActivitySection({ profile }: { profile: CompanyProfile }) {
  const act = profile.activity;
  const all = act.events;
  const counts = useMemo(() => countTiers(all), [all]);
  const [view, setView] = useState<ActivityView>(counts.major ? 'major' : counts.relevant ? 'relevant' : 'all');
  const [sort, setSort] = useState<ActivitySort>('date');
  const events = useMemo(() => {
    const kept = all.filter((e) => view === 'all' || (view === 'major' ? eventTier(e) === 'major' : eventTier(e) !== 'routine'));
    return sort === 'significance' ? [...kept].sort(rankOrder) : kept;
  }, [all, view, sort]);
  const [open, setOpen] = useState<string | null>(null);
  const openEv = useOpenEvidence(profile.sourceIndex, profile.company.legalName);
  const byYear = useMemo(() => {
    const m = new Map<string, typeof events>();
    for (const e of events) m.set(e.date.slice(0, 4), [...(m.get(e.date.slice(0, 4)) ?? []), e]);
    return [...m.entries()];
  }, [events]);
  const groups: [string | null, TimelineEvent[]][] = sort === 'date' ? byYear : [[null, events]];
  const hidden = all.length - events.length;
  return (
    <div className="stack" style={{ gap: 14 }}>
      <SectionState meta={act} sourceIndex={profile.sourceIndex} />
      {all.length > 0 && (
        <div className="row-wrap tl-bar">
          <Segmented
            label="Timeline view"
            value={view}
            onChange={setView}
            options={[
              { value: 'major', label: 'Major', title: SIGNIFICANCE_HINT.major },
              { value: 'relevant', label: 'Major + relevant', title: `${SIGNIFICANCE_HINT.major}; ${SIGNIFICANCE_HINT.relevant}` },
              { value: 'all', label: 'All events', title: SIGNIFICANCE_HINT.routine },
            ]}
          />
          <Segmented
            label="Sort events"
            value={sort}
            onChange={setSort}
            options={[
              { value: 'date', label: 'Newest first' },
              { value: 'significance', label: 'Most significant', title: 'Ranked by business impact, financial importance, operational consequence, strategic relevance and recency' },
            ]}
          />
          <span className="t-xs t-muted" data-testid="activity-counts">
            {counts.major} major · {counts.relevant} relevant · {counts.routine} routine
          </span>
          {hidden > 0 && (
            <button className="link-btn" onClick={() => setView(view === 'major' && counts.relevant ? 'relevant' : 'all')}>
              {view === 'major' && counts.relevant ? `Show ${counts.relevant} relevant` : `Show all ${all.length}`}
            </button>
          )}
        </div>
      )}
      {!events.length && act.status !== 'pending' && (
        <EmptyState
          compact
          title={
            all.length
              ? `No ${view === 'major' ? 'major' : 'major or relevant'} developments were found in the sources that could be read. ${hidden} other event${hidden === 1 ? ' is' : 's are'} available.`
              : 'No dated public events were found in the sources that could be read. This does not mean that nothing happened.'
          }
        />
      )}
      <div className="timeline" data-search-block="timeline">
        {groups.map(([year, list]) => (
          <div key={year ?? 'ranked'}>
            {year && <div className="tl-year">{year}</div>}
            {list.map((e) => {
              const expanded = open === e.id;
              const tier = eventTier(e);
              const link = e.url ?? e.sources?.find((x) => x.url)?.url ?? e.evidence[0]?.url;
              const places = e.sources && e.sources.length > 1 ? e.sources : null;
              return (
                <div key={e.id} className={cn('tl-item', `tl-item--${tier}`)}>
                  <span className="tl-dot" aria-hidden />
                  <div className="tl-body">
                    <button className="tl-toggle" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : e.id)}>
                      <span className="tl-title">{e.title}</span>
                      <ChevronDown aria-hidden className={cn('tl-chev', expanded && 'is-open')} />
                    </button>
                    <div className="tl-meta">
                      <time dateTime={e.date}>{formatDate(e.date)}</time>
                      <span className={cn('tag', `tag--${tier}`)} title={SIGNIFICANCE_HINT[tier]}>
                        {SIGNIFICANCE_LABEL[tier]}
                      </span>
                      <span className="tag">{EVENT_LABEL[e.type]}</span>
                      {e.sourceType && <span className="tag">{EVENT_SOURCE_LABEL[e.sourceType]}</span>}
                      <span>{e.sourceIds.map((s) => profile.sourceIndex[s]?.name ?? s).join(', ')}</span>
                      {places && <span className="t-muted">Found in {places.length} places</span>}
                    </div>
                    {expanded && (
                      <div className="tl-detail anim-fade-up">
                        {e.description && <p className="t-sm t-soft">{e.description}</p>}
                        {e.reasons && e.reasons.length > 0 && (
                          <div className="tl-why">
                            <span className="t-micro">Why {SIGNIFICANCE_LABEL[tier].toLowerCase()}</span>
                            <ul>
                              {e.reasons.map((r) => (
                                <li key={r}>{r}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {places && (
                          <div className="tl-why">
                            <span className="t-micro">Also stated at</span>
                            <ul>
                              {places.map((x, i) => (
                                <li key={`${x.url ?? i}`}>
                                  {EVENT_SOURCE_LABEL[x.sourceType]}
                                  {x.url && (
                                    <>
                                      {' · '}
                                      <ExternalLink href={x.url}>{x.url.replace(/^https?:\/\//, '').slice(0, 70)}</ExternalLink>
                                    </>
                                  )}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                        <div className="row-wrap">
                          <button className="btn btn--sm" onClick={() => openEv({ title: e.title, value: formatDate(e.date), evidence: e.evidence })}>
                            View evidence
                          </button>
                          <ExternalLink href={link}>Open source</ExternalLink>
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
      <ActivityNotes activity={act} />
    </div>
  );
}

/** What was and was not read for this section, duplicates that were merged, and candidates that could not be supported. */
function ActivityNotes({ activity }: { activity: ActivitySectionData }) {
  const checks = activity.sourcesChecked ?? [];
  const problems = checks.filter((c) => c.status === 'blocked' || c.status === 'failed').length;
  const excluded = activity.excluded;
  if (!checks.length && !excluded?.count && !activity.consolidated) return null;
  return (
    <div className="stack" style={{ gap: 8 }} data-testid="activity-notes">
      {checks.length > 0 && (
        <details className="tl-checks" open={problems > 0}>
          <summary>
            Sources checked ({checks.length}){problems > 0 ? ` · ${problems} could not be read` : ''}
          </summary>
          <ul>
            {checks.map((c) => (
              <li key={c.id} className={cn(`tl-check--${c.status}`)}>
                <strong>{c.name}</strong> — {ACTIVITY_CHECK_LABEL[c.status]}
                {c.items ? ` (${c.items} item${c.items === 1 ? '' : 's'})` : ''}
                {c.note ? `. ${c.note.replace(/\.$/, '')}` : ''}
                {c.url && (
                  <>
                    {' · '}
                    <ExternalLink href={c.url}>{c.url.replace(/^https?:\/\//, '').slice(0, 60)}</ExternalLink>
                  </>
                )}
              </li>
            ))}
          </ul>
          <p className="t-xs t-muted">A source that could not be read, or a search that found nothing, is a limit of this research. It is not evidence that nothing happened.</p>
        </details>
      )}
      {!!activity.consolidated && (
        <p className="t-xs t-muted">
          {activity.consolidated} duplicate report{activity.consolidated === 1 ? '' : 's'} of the same announcement {activity.consolidated === 1 ? 'was' : 'were'} merged; each event lists every place it was found.
        </p>
      )}
      {!!excluded?.count && (
        <details className="tl-checks">
          <summary>
            {excluded.count} candidate event{excluded.count === 1 ? '' : 's'} not shown
          </summary>
          <ul>
            {excluded.items.map((x, i) => (
              <li key={`${x.title}-${i}`}>
                <strong>{x.title}</strong>
                {x.date ? ` (${formatDate(x.date)})` : ''} — {x.reason}
              </li>
            ))}
          </ul>
          <p className="t-xs t-muted">Events need a valid date, a source link and matching evidence to be shown.</p>
        </details>
      )}
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
                  <span className="tag">{CHANGE_CATEGORY_LABEL[c.category]}</span>
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
                    <span className="tag">{SOURCE_KIND_LABEL[s.source.kind]}</span>
                    {s.source.official && <span className="tag">Official</span>}
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
