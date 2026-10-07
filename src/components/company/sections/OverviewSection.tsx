import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Ban, CircleCheck, CircleDashed, CircleAlert, Telescope } from 'lucide-react';
import type { CompanyProfile, KnownItem } from '@/types';
import { MetricCard } from '@/components/evidence/MetricCard';
import { FactValue } from '@/components/evidence/FactValue';
import { useOpenEvidence } from '@/components/evidence/useEvidence';
import { CoverageList } from '@/components/company/Coverage';
import { ExternalLink } from '@/components/common/ExternalLink';
import { collectEvidence } from '@/utils/evidence';
import { formatDate, formatOrgNumber, formatRelative } from '@/utils/format';
import { EVENT_LABEL } from '@/utils/status';
import type { CompanyTab } from '@/pages/Company/tabs';

export function ExecutiveSummary({ profile, paper }: { profile: CompanyProfile; paper?: boolean }) {
  const open = useOpenEvidence(profile.sourceIndex, profile.company.legalName);
  const evIndex = useMemo(() => collectEvidence(profile), [profile]);
  const s = profile.summary;
  if (!s) return null;
  const evidence = s.evidenceIds.map((id) => evIndex.get(id)).filter((e): e is NonNullable<typeof e> => !!e);
  return (
    <section className={`exec ${paper ? 'exec--paper' : ''}`} aria-labelledby="exec-h" data-search-block="summary">
      <div className="row" style={{ gap: 10 }}>
        <span className="eyebrow" id="exec-h">
          Executive summary
        </span>
        <span className="spacer" />
        <span className="pill pill--sm">AI synthesis · source-anchored</span>
      </div>
      <p className="exec-text">{s.text}</p>
      <div className="exec-foot">
        <span>
          Sources: <strong className="t-num">{s.sourceIds.length}</strong>
        </span>
        <span>
          Last researched: <strong>{formatDate(s.generatedAt)}</strong>
        </span>
        <span className="spacer" />
        <button className="link-btn" onClick={() => open({ title: 'Executive summary — supporting evidence', evidence })}>
          View supporting evidence <ArrowRight aria-hidden />
        </button>
      </div>
    </section>
  );
}

export function KnownUnknown({ items }: { items: KnownItem[] }) {
  const known = items.filter((k) => k.status === 'verified');
  const unknown = items.filter((k) => k.status !== 'verified');
  const icon = (k: KnownItem) =>
    k.status === 'verified' ? <CircleCheck aria-hidden className="ku-ok" /> : k.status === 'blocked' ? <Ban aria-hidden className="ku-err" /> : k.status === 'conflict' ? <CircleAlert aria-hidden className="ku-warn" /> : <CircleDashed aria-hidden className="ku-muted" />;
  return (
    <div className="ku">
      <div>
        <h3 className="t-micro" style={{ marginBottom: 10 }}>
          Verified information
        </h3>
        <ul className="ku-list">
          {known.map((k) => (
            <li key={k.id}>
              {icon(k)}
              <span>
                <strong>{k.label}</strong> <span className="t-soft">{k.text}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h3 className="t-micro" style={{ marginBottom: 10 }}>
          Unknown / unavailable
        </h3>
        {unknown.length ? (
          <ul className="ku-list">
            {unknown.map((k) => (
              <li key={k.id}>
                {icon(k)}
                <span>
                  <strong>{k.label}</strong> <span className="t-soft">{k.text}</span>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="t-sm t-muted">Nothing material is currently marked unknown.</p>
        )}
      </div>
    </div>
  );
}

export function ResearchQualityCard({ profile }: { profile: CompanyProfile }) {
  const q = profile.quality;
  return (
    <dl className="quality">
      <div>
        <dt>Coverage</dt>
        <dd className="t-num">
          {q.coverage.complete}/{q.coverage.total} areas
        </dd>
      </div>
      <div>
        <dt>Primary sources</dt>
        <dd className="t-num">{q.primarySources}</dd>
      </div>
      <div>
        <dt>Secondary sources</dt>
        <dd className="t-num">{q.secondarySources}</dd>
      </div>
      <div>
        <dt>Conflicts</dt>
        <dd className={`t-num ${q.conflicts ? 't-warn' : ''}`}>{q.conflicts}</dd>
      </div>
      <div>
        <dt>Last refreshed</dt>
        <dd>{q.lastRefreshedAt ? formatDate(q.lastRefreshedAt) : 'Not researched'}</dd>
      </div>
    </dl>
  );
}

const SNAPSHOT_FIELDS = (f: { field: string }) => f.field.startsWith('financials.revenue.') || f.field === 'overview.employees' || f.field === 'overview.openPositions';

export function OverviewSection({ profile, onTab, hideSnapshotMetrics }: { profile: CompanyProfile; onTab: (t: CompanyTab) => void; hideSnapshotMetrics?: boolean }) {
  const metrics = hideSnapshotMetrics ? profile.keyMetrics.filter((f) => !SNAPSHOT_FIELDS(f)) : profile.keyMetrics;
  const majorEvents = profile.activity.events.filter((e) => e.significance === 'major');
  const c = profile.company;
  const id = profile.identity;
  const ctx = c.legalName;
  const ceo = profile.people.people.find((p) => p.role === 'CEO' && p.current);
  const chair = profile.people.people.find((p) => p.role === 'Chair of the board' && p.current);
  const researched = c.researchState !== 'not_researched';
  return (
    <div className="overview">
      <div className="overview-main">
        {researched ? (
          <ExecutiveSummary profile={profile} />
        ) : (
          <section className="research-cta">
            <Telescope aria-hidden />
            <div className="stack" style={{ gap: 4, flex: 1 }}>
              <strong>This company has not been researched yet.</strong>
              <span className="t-sm t-soft">Registry identity and filed accounts are shown. Research gathers leadership, locations, website, hiring and public activity — with evidence for every fact.</span>
            </div>
            <Link to={`/research?org=${c.orgNumber}&autostart=1`} className="btn btn--primary">
              Research this company
            </Link>
          </section>
        )}

        <section aria-labelledby="km-h" data-search-block="metrics">
          <div className="block-head">
            <h2 id="km-h">{hideSnapshotMetrics ? 'More key figures' : 'Key metrics'}</h2>
            <span className="t-micro">Click any figure for evidence</span>
          </div>
          <div className="metrics-grid">
            {metrics.map((f) => (
              <MetricCard key={f.id} fact={f} sourceIndex={profile.sourceIndex} context={ctx} label={f.field === 'identity.founded' ? 'Founded' : undefined} />
            ))}
          </div>
        </section>

        <section className="card" aria-labelledby="about-h" data-search-block="about">
          <div className="card-head">
            <h2 id="about-h">About</h2>
          </div>
          {profile.description ? (
            <p className="about-text">
              <FactValue fact={profile.description} sourceIndex={profile.sourceIndex} context={ctx} className="fact--prose" />
            </p>
          ) : (
            <p className="t-sm t-muted" style={{ marginBottom: 16 }}>
              No verified company description. {profile.website.status === 'blocked' ? 'The official website blocked automated access.' : 'An official website description was not found in the searched sources.'}
            </p>
          )}
          <dl className="kv about-kv">
            <dt>Legal name</dt>
            <dd>
              <FactValue fact={id.legalName} sourceIndex={profile.sourceIndex} context={ctx} />
            </dd>
            <dt>Organization number</dt>
            <dd className="t-mono">{formatOrgNumber(id.orgNumber)}</dd>
            {id.legalForm && (
              <>
                <dt>Legal form</dt>
                <dd>
                  <FactValue fact={id.legalForm} sourceIndex={profile.sourceIndex} context={ctx} />
                </dd>
              </>
            )}
            {id.founded && (
              <>
                <dt>Founded</dt>
                <dd>
                  <FactValue fact={id.founded} sourceIndex={profile.sourceIndex} context={ctx} exact />
                </dd>
              </>
            )}
            {id.industry && (
              <>
                <dt>Industry (NACE)</dt>
                <dd>
                  <FactValue fact={id.industry} sourceIndex={profile.sourceIndex} context={ctx} />
                </dd>
              </>
            )}
            {id.registeredAddress && (
              <>
                <dt>Registered address</dt>
                <dd>
                  <FactValue fact={id.registeredAddress} sourceIndex={profile.sourceIndex} context={ctx} />
                </dd>
              </>
            )}
            <dt>Headquarters</dt>
            <dd>{id.headquarters ? <FactValue fact={id.headquarters} sourceIndex={profile.sourceIndex} context={ctx} /> : <span className="fact--missing">Not verified — only the registered address is known</span>}</dd>
            {id.website && (
              <>
                <dt>Website</dt>
                <dd className="row-wrap" style={{ gap: 8 }}>
                  <FactValue fact={id.website} sourceIndex={profile.sourceIndex} context={ctx} />
                  <ExternalLink href={`https://${id.website.value}`}>Open website</ExternalLink>
                </dd>
              </>
            )}
          </dl>
        </section>

        <div className="overview-split">
          <section className="card" aria-labelledby="ov-hiring" data-search-block="hiring-snippet">
            <div className="card-head">
              <h2 id="ov-hiring">Hiring</h2>
              <span className="spacer" />
              <button className="link-btn" onClick={() => onTab('hiring')}>
                Details <ArrowRight aria-hidden />
              </button>
            </div>
            {profile.hiring.totalCurrent != null ? (
              <>
                <p className="t-num" style={{ fontSize: 28, letterSpacing: '-0.03em' }}>
                  {profile.hiring.totalCurrent} <span className="t-sm t-muted">verified openings</span>
                </p>
                <ul className="mini-bars">
                  {profile.hiring.categories.slice(0, 4).map((cat) => (
                    <li key={cat.name}>
                      <span className="truncate">{cat.name}</span>
                      <span className="mini-bar">
                        <i style={{ width: `${(cat.count / Math.max(...profile.hiring.categories.map((x) => x.count))) * 100}%` }} />
                      </span>
                      <span className="t-num t-xs">{cat.count}</span>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="t-sm t-muted">{profile.hiring.message ?? 'No current verified job openings were found in the searched sources.'}</p>
            )}
          </section>
          <section className="card" aria-labelledby="ov-activity" data-search-block="activity-snippet">
            <div className="card-head">
              <h2 id="ov-activity">Major recent events</h2>
              <span className="spacer" />
              <button className="link-btn" onClick={() => onTab('activity')}>
                Timeline <ArrowRight aria-hidden />
              </button>
            </div>
            {majorEvents.length ? (
              <ul className="mini-events">
                {majorEvents.slice(0, 4).map((e) => (
                  <li key={e.id}>
                    <span className="t-mono t-xs t-muted nowrap">{formatDate(e.date)}</span>
                    <span className="stack" style={{ gap: 0, minWidth: 0 }}>
                      <span className="truncate t-sm">{e.title}</span>
                      <span className="t-xs t-muted">{EVENT_LABEL[e.type]}</span>
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="t-sm t-muted">{profile.activity.message ?? 'No verified major public changes were found in the searched sources.'}</p>
            )}
          </section>
        </div>
      </div>

      <aside className="overview-aside" aria-label="Research transparency">
        <section className="card">
          <CoverageList coverage={c.coverage} />
        </section>
        <section className="card" aria-labelledby="rq-h">
          <div className="card-head" style={{ marginBottom: 10 }}>
            <h3 id="rq-h" className="t-micro">
              Research quality
            </h3>
          </div>
          <ResearchQualityCard profile={profile} />
          <button className="link-btn" style={{ marginTop: 12 }} onClick={() => onTab('sources')}>
            Inspect sources <ArrowRight aria-hidden />
          </button>
        </section>
        <section className="card" aria-labelledby="lead-h">
          <div className="card-head" style={{ marginBottom: 10 }}>
            <h3 id="lead-h" className="t-micro">
              Who runs it
            </h3>
          </div>
          <dl className="kv" style={{ gridTemplateColumns: '90px 1fr' }}>
            <dt>CEO</dt>
            <dd>{ceo ? <FactValue fact={ceo.fact} sourceIndex={profile.sourceIndex} context={ctx} /> : <span className="fact--missing">{researched ? 'Not verified' : 'Not researched yet'}</span>}</dd>
            <dt>Chair</dt>
            <dd>{chair ? <FactValue fact={chair.fact} sourceIndex={profile.sourceIndex} context={ctx} /> : <span className="fact--missing">{researched ? 'Not verified' : 'Not researched yet'}</span>}</dd>
            <dt>Locations</dt>
            <dd>
              <button className="link-btn" onClick={() => onTab('locations')}>
                {new Set(profile.locations.locations.map((l) => l.municipality)).size} municipality(ies)
              </button>
            </dd>
          </dl>
        </section>
        <section className="card">
          <KnownUnknown items={profile.knowns} />
        </section>
        {c.lastResearchedAt && <p className="t-xs t-muted">Research updated {formatRelative(c.lastResearchedAt)} · facts carry their own verification dates.</p>}
      </aside>
    </div>
  );
}
