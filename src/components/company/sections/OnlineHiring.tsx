import { useState } from 'react';
import { CircleCheck, CircleDashed, Globe } from 'lucide-react';
import type { CompanyProfile } from '@/types';
import { FactValue } from '@/components/evidence/FactValue';
import { useOpenEvidence } from '@/components/evidence/useEvidence';
import { ExternalLink } from '@/components/common/ExternalLink';
import { Segmented } from '@/components/common/Tabs';
import { EmptyState } from '@/components/common/EmptyState';
import { SimpleBarChart } from '@/components/charts/LazyCharts';
import { SectionState } from '../SectionState';
import { formatDate, formatRelative } from '@/utils/format';

export function WebsiteSection({ profile }: { profile: CompanyProfile }) {
  const w = profile.website;
  const ctx = profile.company.legalName;
  return (
    <div className="stack" style={{ gap: 16 }}>
      <SectionState meta={w} sourceIndex={profile.sourceIndex} />
      {w.domain && (
        <section className="web-hero card" data-search-block="website-domain">
          <span className="web-icon">
            <Globe aria-hidden />
          </span>
          <div className="stack" style={{ gap: 4, flex: 1, minWidth: 0 }}>
            <span className="t-micro">Official website</span>
            <span className="web-domain">{w.domain}</span>
            {w.verification && (
              <span className="t-sm t-soft">
                <FactValue fact={w.verification} sourceIndex={profile.sourceIndex} context={ctx} />
              </span>
            )}
          </div>
          <ExternalLink href={w.url} button>
            Open website
          </ExternalLink>
        </section>
      )}
      {w.description && (
        <section className="card" data-search-block="website-description">
          <div className="card-head">
            <h3>Company description</h3>
            <span className="t-xs t-muted">As published on the official website</span>
          </div>
          <p className="about-text">
            <FactValue fact={w.description} sourceIndex={profile.sourceIndex} context={ctx} className="fact--prose" />
          </p>
        </section>
      )}
      {w.pages.length > 0 && (
        <section data-search-block="website-pages">
          <div className="block-head">
            <h3>Key pages</h3>
            <span className="t-micro">{w.pages.filter((p) => p.found).length} found</span>
          </div>
          <div className="pages-grid">
            {w.pages.map((p) =>
              p.found ? (
                <a key={p.kind} className="page-tile" href={p.url} target="_blank" rel="noopener noreferrer nofollow">
                  <CircleCheck aria-hidden className="t-ok" />
                  <span>{p.title}</span>
                  <span className="sr-only">(opens external site)</span>
                </a>
              ) : (
                <span key={p.kind} className="page-tile page-tile--missing">
                  <CircleDashed aria-hidden />
                  <span>{p.title}</span>
                  <span className="t-xs">Not found</span>
                </span>
              ),
            )}
          </div>
        </section>
      )}
      {(w.social.length > 0 || w.signals.length > 0) && (
        <div className="fin-split">
          <section className="card" data-search-block="website-social">
            <div className="card-head">
              <h3>Social presence</h3>
            </div>
            {w.social.length ? (
              <ul className="stack" style={{ gap: 8 }}>
                {w.social.map((s) => (
                  <li key={s.network} className="row" style={{ justifyContent: 'space-between' }}>
                    <span className="t-sm" style={{ textTransform: 'capitalize' }}>
                      {s.network}
                    </span>
                    <ExternalLink href={s.url}>{s.handle}</ExternalLink>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="t-sm t-muted">No verified social profiles.</p>
            )}
          </section>
          <section className="card" data-search-block="website-signals">
            <div className="card-head">
              <h3>Digital signals</h3>
            </div>
            <dl className="kv">
              {w.signals.map((s) => (
                <div key={s.label} style={{ display: 'contents' }}>
                  <dt>{s.label}</dt>
                  <dd>{s.value}</dd>
                </div>
              ))}
            </dl>
          </section>
        </div>
      )}
    </div>
  );
}

export function HiringSection({ profile }: { profile: CompanyProfile }) {
  const h = profile.hiring;
  const [state, setState] = useState<'current' | 'all'>('current');
  const openEv = useOpenEvidence(profile.sourceIndex, profile.company.legalName);
  const jobs = h.jobs.filter((j) => state === 'all' || j.state === 'current');
  if (h.totalCurrent == null)
    return (
      <div className="stack" style={{ gap: 16 }}>
        <SectionState meta={h} sourceIndex={profile.sourceIndex} />
        {h.status !== 'pending' && <EmptyState title="No current verified job openings were found in the searched sources." text="This does not mean the company is not hiring — only that no verified postings were found." />}
      </div>
    );
  return (
    <div className="stack" style={{ gap: 18 }}>
      <div className="hire-stats" data-search-block="hiring-stats">
        <div className="fin-stat">
          <span className="t-xs t-muted">Current openings</span>
          <span className="fin-stat-v t-num">{h.totalCurrent}</span>
          {h.verifiedAt && <span className="freshness">Verified {formatRelative(h.verifiedAt)}</span>}
        </div>
        <div className="fin-stat">
          <span className="t-xs t-muted">Hiring locations</span>
          <span className="fin-stat-v t-num">{h.locations.length}</span>
          <span className="freshness truncate">{h.locations.map((l) => l.name).join(', ') || '—'}</span>
        </div>
        <div className="fin-stat">
          <span className="t-xs t-muted">Role categories</span>
          <span className="fin-stat-v t-num">{h.categories.length}</span>
          <span className="freshness truncate">{h.categories.map((c) => c.name).join(', ') || '—'}</span>
        </div>
      </div>
      {h.totalCurrent === 0 && <div className="state-banner">No current verified job openings were found in the searched sources.</div>}
      {h.history.length >= 2 && (
        <section className="card" data-search-block="hiring-history">
          <div className="card-head">
            <h3>Openings over time</h3>
            <span className="t-xs t-muted">Timestamped postings · monthly snapshot</span>
          </div>
          <SimpleBarChart data={h.history.map((x) => ({ label: x.month, value: x.count }))} unit="Open positions" source="arbeidsplassen.nav.no · official website" />
        </section>
      )}
      <section data-search-block="hiring-jobs">
        <div className="block-head">
          <h3>Positions</h3>
          <span className="spacer" />
          <Segmented
            label="Job state"
            value={state}
            onChange={setState}
            options={[
              { value: 'current', label: 'Current' },
              { value: 'all', label: 'All incl. stale' },
            ]}
          />
        </div>
        <div className="table-wrap">
          <table className="table">
            <caption className="sr-only">Job postings</caption>
            <thead>
              <tr>
                <th className="sticky-col" scope="col">
                  Title
                </th>
                <th scope="col">Department</th>
                <th scope="col">Location</th>
                <th scope="col">Posted</th>
                <th scope="col">Source</th>
                <th scope="col">State</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id}>
                  <td className="sticky-col" style={{ maxWidth: 300 }}>
                    <span className="truncate" style={{ display: 'block' }}>
                      {j.title}
                    </span>
                  </td>
                  <td>{j.department}</td>
                  <td>{j.location}</td>
                  <td className="t-num">{j.postedAt ? formatDate(j.postedAt) : '—'}</td>
                  <td>{profile.sourceIndex[j.sourceId]?.name ?? j.sourceId}</td>
                  <td>
                    <span className={`pill pill--sm ${j.state === 'current' ? 'pill--ok' : 'pill--warn'}`}>{j.state === 'current' ? 'Current' : 'Stale'}</span>
                  </td>
                  <td>
                    <div className="row" style={{ gap: 4 }}>
                      <button className="btn btn--ghost btn--sm" onClick={() => openEv({ title: j.title, value: `${j.location} · ${j.department}`, evidence: j.evidence })}>
                        Evidence
                      </button>
                      <ExternalLink href={j.url}>Open job posting</ExternalLink>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
