import { useMemo, useState } from 'react';
import { ArrowUpRight, ChevronDown, CircleAlert, Languages, Quote, Scale } from 'lucide-react';
import { API_MODE } from '@/api/http';
import type { Evidence, Fact, Source } from '@/types';
import { useUi } from '@/stores/ui';
import { Drawer } from '@/components/common/Overlay';
import { EmptyState } from '@/components/common/EmptyState';
import { SourceIcon } from '@/components/source/SourceIcon';
import { VerificationBadge, evidenceAsFact } from './SourceBadge';
import { formatDate, formatDateTime, formatFactValue } from '@/utils/format';
import { SOURCE_KIND_LABEL, SOURCE_TIER_LABEL, sourceCounts } from '@/utils/status';
import { cn } from '@/utils/cn';

const tierRank = (s?: Source) => (s?.tier === 'primary' ? 0 : s?.tier === 'secondary' ? 1 : 2);

/**
 * The evidence panel — part of the ivory knowledge layer.
 * Executive-first: the answer, its verification state, period, date and
 * source count come first; supporting evidence and direct source links
 * follow; raw technical metadata sits behind "More technical details".
 * Right-side panel on desktop, bottom sheet on mobile.
 */
export function EvidenceDrawer() {
  const target = useUi((s) => s.evidence);
  const close = useUi((s) => s.closeEvidence);
  if (!target) return null;
  return <EvidencePanel key={target.fact?.id ?? target.title} target={target} onClose={close} />;
}

function EvidencePanel({ target, onClose }: { target: NonNullable<ReturnType<typeof useUi.getState>['evidence']>; onClose: () => void }) {
  const { fact, sourceIndex } = target;
  const evidence = useMemo(() => [...(fact?.evidence ?? target.evidence ?? [])].sort((a, b) => tierRank(sourceIndex[a.sourceId]) - tierRank(sourceIndex[b.sourceId])), [fact, target.evidence, sourceIndex]);
  const title = fact?.label ?? target.title ?? 'Evidence';
  const value = fact ? formatFactValue(fact, { exact: true }) : target.value;
  const verifiable = fact ?? evidenceAsFact(evidence);
  const counts = sourceCounts(evidence, sourceIndex);
  const lastRetrieved = evidence.reduce<string | undefined>((m, e) => (!m || e.retrievedAt > m ? e.retrievedAt : m), undefined);
  const period = fact?.reportingPeriod ?? evidence.find((e) => e.reportingPeriod)?.reportingPeriod;
  const links = [...new Map(evidence.filter((e) => e.url).map((e) => [e.url!, e])).values()];

  return (
    <Drawer
      open
      onClose={onClose}
      className="paper drawer--paper"
      label={`Evidence: ${title}`}
      subtitle={<span className="eyebrow">Evidence{target.context ? ` · ${target.context}` : ''}</span>}
      title={title}
    >
      <div className="stack ev-stack">
        {/* 1 — the answer */}
        <section className="ev-answer" aria-label="Answer">
          {value && <div className="t-num ev-value-num">{value}</div>}
          <VerificationBadge fact={verifiable} sourceIndex={sourceIndex} />
          <dl className="ev-facts">
            {period && (
              <div>
                <dt>Reporting period</dt>
                <dd>{period}</dd>
              </div>
            )}
            <div>
              <dt>{fact?.verifiedAt ? 'Last verified' : 'Last retrieved'}</dt>
              <dd title={formatDateTime(fact?.verifiedAt ?? lastRetrieved)}>{formatDate(fact?.verifiedAt ?? lastRetrieved)}</dd>
            </div>
            <div>
              <dt>Sources</dt>
              <dd>
                {counts.total}
                {counts.total > 0 && !counts.unknown && (
                  <span className="t-muted">
                    {' '}
                    · {counts.primary} primary{counts.secondary ? `, ${counts.secondary} secondary` : ''}
                  </span>
                )}
              </dd>
            </div>
            <div>
              <dt>Evidence items</dt>
              <dd>{evidence.length}</dd>
            </div>
          </dl>
        </section>

        {fact?.conflict && <ConflictBlock fact={fact} sourceIndex={sourceIndex} evidence={evidence} />}
        {fact?.note && (
          <div className="notice notice--info">
            <CircleAlert aria-hidden />
            <span>{fact.note}</span>
          </div>
        )}

        {/* 2 — supporting evidence */}
        <section aria-labelledby="ev-support-h" className="stack" style={{ gap: 10 }}>
          <h3 id="ev-support-h" className="t-micro">
            Supporting evidence
          </h3>
          {API_MODE === 'mock' && evidence.length > 0 && <p className="t-xs t-muted ev-demo">Demo fixture · the mock backend shows sample excerpts for fictional companies, not text retrieved from the live source.</p>}
          {evidence.length === 0 ? (
            <EmptyState compact title="No verified evidence found for this field." text="No verified evidence was found in the searched permitted sources." />
          ) : (
            <ol className="ev-list" aria-label="Evidence items">
              {evidence.map((e) => (
                <EvidenceItem key={e.id} e={e} source={sourceIndex[e.sourceId]} fact={fact} />
              ))}
            </ol>
          )}
        </section>

        {/* 3 — direct source links */}
        {links.length > 0 && (
          <section aria-labelledby="ev-links-h">
            <h3 id="ev-links-h" className="t-micro" style={{ marginBottom: 8 }}>
              Source links
            </h3>
            <ul className="ev-links">
              {links.map((e) => {
                const s = sourceIndex[e.sourceId];
                return (
                  <li key={e.url}>
                    <a href={e.url} target="_blank" rel="noopener noreferrer nofollow">
                      <span className="ev-link-name">{e.documentTitle ?? s?.name ?? e.sourceId}</span>
                      <span className="ev-link-host">{safeHost(e.url!)}</span>
                      <ArrowUpRight aria-hidden />
                      <span className="sr-only">(opens external site in a new tab)</span>
                    </a>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        {/* 4 — technical details, collapsed by default */}
        <details className="ev-tech">
          <summary>
            <ChevronDown aria-hidden /> More technical details
          </summary>
          <div className="stack" style={{ gap: 12, marginTop: 12 }}>
            {fact && (
              <dl className="kv ev-kv">
                <dt>Fact id</dt>
                <dd className="t-mono">{fact.id}</dd>
                <dt>Field</dt>
                <dd className="t-mono">{fact.field}</dd>
                <dt>Value status</dt>
                <dd className="t-mono">{fact.status}</dd>
                <dt>Evidence state</dt>
                <dd className="t-mono">{fact.evidenceState}</dd>
                {fact.verifiedAt && (
                  <>
                    <dt>Verified at</dt>
                    <dd className="t-mono">{fact.verifiedAt}</dd>
                  </>
                )}
                {fact.freshness && (
                  <>
                    <dt>Freshness</dt>
                    <dd className="t-mono">{fact.freshness}</dd>
                  </>
                )}
              </dl>
            )}
            {evidence.map((e) => {
              const s = sourceIndex[e.sourceId];
              return (
                <dl key={e.id} className="kv ev-kv ev-tech-item">
                  <dt>Evidence id</dt>
                  <dd className="t-mono">{e.id}</dd>
                  <dt>Source</dt>
                  <dd>
                    {s?.name ?? e.sourceId} <span className="t-mono t-muted">({e.sourceId})</span>
                  </dd>
                  {s && (
                    <>
                      <dt>Kind · tier</dt>
                      <dd>
                        {SOURCE_KIND_LABEL[s.kind]} · {SOURCE_TIER_LABEL[s.tier]}
                        {s.official ? ' · official' : ''}
                      </dd>
                    </>
                  )}
                  {e.documentTitle && (
                    <>
                      <dt>Document</dt>
                      <dd>
                        {e.documentTitle}
                        {e.page ? ` · p. ${e.page}` : ''}
                      </dd>
                    </>
                  )}
                  <dt>Retrieved</dt>
                  <dd className="t-mono">{e.retrievedAt}</dd>
                  {e.statedValue && (
                    <>
                      <dt>Value stated</dt>
                      <dd className="t-mono">{e.statedValue}</dd>
                    </>
                  )}
                  {e.excerptLanguage && (
                    <>
                      <dt>Language</dt>
                      <dd className="t-mono">{e.excerptLanguage}</dd>
                    </>
                  )}
                  {e.url && (
                    <>
                      <dt>URL</dt>
                      <dd className="t-mono ev-url">{e.url}</dd>
                    </>
                  )}
                </dl>
              );
            })}
          </div>
        </details>
      </div>
    </Drawer>
  );
}

function safeHost(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

function EvidenceItem({ e, source, fact }: { e: Evidence; source?: Source; fact?: Pick<Fact, 'field' | 'unit' | 'currency'> }) {
  const [translated, setTranslated] = useState(false);
  return (
    <li className="ev-item" id={`ev-${e.id}`}>
      <div className="row" style={{ gap: 10, alignItems: 'flex-start' }}>
        <span className="ev-src-icon">{source && <SourceIcon kind={source.kind} />}</span>
        <div className="stack" style={{ gap: 2, minWidth: 0, flex: 1 }}>
          <div className="row-wrap" style={{ gap: 6 }}>
            <strong className="ev-src-name">{source?.name ?? e.sourceId}</strong>
            {source && <span className={cn('pill pill--sm', source.tier === 'primary' && 'pill--ok')}>{SOURCE_TIER_LABEL[source.tier]}</span>}
            {source?.official && <span className="pill pill--sm">Official</span>}
          </div>
          <span className="t-xs t-muted">
            {e.documentTitle ?? source?.originalTitle ?? ''}
            {e.page ? ` · p. ${e.page}` : ''}
            {e.reportingPeriod ? ` · ${e.reportingPeriod}` : ''} · retrieved {formatDate(e.retrievedAt)}
          </span>
        </div>
      </div>
      {e.statedValue && (
        <p className="t-sm" style={{ margin: 0 }}>
          <span className="t-muted">Value stated by this source: </span>
          <strong className="t-num">{fact && /^-?\d+(\.\d+)?$/.test(e.statedValue) ? formatFactValue({ ...fact, value: Number(e.statedValue) }, { exact: true }) : e.statedValue}</strong>
        </p>
      )}
      {e.excerpt && (
        <figure className="ev-excerpt">
          <Quote aria-hidden />
          <blockquote lang={translated ? 'en' : (e.excerptLanguage ?? 'en')}>“…{translated && e.excerptTranslation ? e.excerptTranslation : e.excerpt}…”</blockquote>
          {e.excerptTranslation && (
            <button className="link-btn" onClick={() => setTranslated((t) => !t)} aria-pressed={translated}>
              <Languages aria-hidden /> {translated ? 'Show original (Norwegian)' : 'Show English summary'}
            </button>
          )}
        </figure>
      )}
      {e.url && (
        <a className="link-btn" href={e.url} target="_blank" rel="noopener noreferrer nofollow">
          {source?.kind === 'financial' ? 'Open filing' : source?.kind === 'jobs' ? 'Open job posting' : source?.kind === 'website' ? 'Open page' : 'Open source'}
          <ArrowUpRight aria-hidden />
          <span className="sr-only">(opens external site in a new tab)</span>
        </a>
      )}
    </li>
  );
}

/** Sources disagree: every competing value, its period and source — nothing chosen silently. */
function ConflictBlock({ fact, sourceIndex, evidence }: { fact: Fact; sourceIndex: Record<string, Source>; evidence: Evidence[] }) {
  const c = fact.conflict!;
  const show = (id: string) => {
    const el = document.getElementById(`ev-${id}`);
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.remove('is-highlighted');
    void el.offsetWidth;
    el.classList.add('is-highlighted');
  };
  return (
    <section className="conflict" aria-label="Sources disagree">
      <div className="row" style={{ gap: 8 }}>
        <Scale aria-hidden className="conflict-icon" />
        <strong>Sources disagree</strong>
        <span className="spacer" />
        <span className="t-xs t-muted">{c.candidates.length} values</span>
      </div>
      <div className="conflict-grid">
        {c.candidates.map((cand) => {
          const s = sourceIndex[cand.sourceId];
          const displayed = cand.value === fact.value;
          const ev = evidence.find((e) => e.id === cand.evidenceId);
          return (
            <div key={cand.evidenceId} className={cn('conflict-cand', displayed && 'is-displayed')}>
              <span className="row-wrap" style={{ gap: 6 }}>
                <span className="t-xs" style={{ fontWeight: 500 }}>
                  {s?.name ?? cand.sourceId}
                </span>
                {s && <span className={cn('pill pill--sm', s.tier === 'primary' && 'pill--ok')}>{SOURCE_TIER_LABEL[s.tier]}</span>}
              </span>
              <span className="t-num conflict-v">{cand.displayValue ?? (typeof cand.value === 'number' ? formatFactValue({ ...fact, value: cand.value, displayValue: undefined }, { exact: true }) : String(cand.value))}</span>
              <span className="t-xs t-muted">
                {cand.reportingPeriod ?? 'Period not stated'}
                {ev ? ` · retrieved ${formatDate(ev.retrievedAt)}` : ''}
              </span>
              <span className="row-wrap" style={{ gap: 8 }}>
                {displayed && <span className="pill pill--sm">Shown as headline</span>}
                {ev && (
                  <button className="link-btn" onClick={() => show(ev.id)}>
                    Inspect evidence
                  </button>
                )}
              </span>
            </div>
          );
        })}
      </div>
      <p className="t-sm" style={{ margin: 0 }}>
        <span className="t-muted">Possible reason: </span>
        {c.reason ?? 'The backend has not identified a reason for the difference.'}
      </p>
      <p className="t-xs t-muted" style={{ margin: 0 }}>
        The headline uses the primary source; both values stay visible here until the conflict is resolved by newer evidence.
      </p>
    </section>
  );
}
