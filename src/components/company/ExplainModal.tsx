import { useQuery } from '@tanstack/react-query';
import { CircleHelp, Eye, LoaderCircle, Quote, Sparkles, Telescope } from 'lucide-react';
import { useState } from 'react';
import { api } from '@/api';
import type { Evidence, ExplainSubject, Source } from '@/types';
import { Modal } from '@/components/common/Overlay';
import { ErrorState } from '@/components/common/ErrorState';
import { Skeleton } from '@/components/common/Skeleton';
import { useOpenEvidence } from '@/components/evidence/useEvidence';
import { formatDateTime } from '@/utils/format';

/**
 * "Explain this change". The backend researches the explanation; the UI keeps
 * observed facts, explanations reported by sources and AI synthesis visibly
 * separate so causal inference is never presented as established fact.
 */
export function ExplainModal({ orgNumber, companyName, subject, title, sourceIndex, onClose }: { orgNumber: string; companyName: string; subject: ExplainSubject; title: string; sourceIndex: Record<string, Source>; onClose: () => void }) {
  const [fresh, setFresh] = useState(false);
  const key = subject.kind === 'change' ? subject.changeId : `${subject.metric}:${subject.fromPeriod}:${subject.toPeriod}`;
  const q = useQuery({ queryKey: ['explain', orgNumber, key, fresh], queryFn: () => api.companies.explain(orgNumber, subject, { fresh }), staleTime: 5 * 60_000 });
  const openEv = useOpenEvidence(sourceIndex, companyName);
  const evBtn = (label: string, evidence: Evidence[]) =>
    evidence.length ? (
      <button className="btn btn--ghost btn--sm" onClick={() => openEv({ title: label, evidence })} aria-label={`Evidence: ${label}`}>
        <Eye aria-hidden /> Evidence
      </button>
    ) : null;
  const x = q.data;

  return (
    <Modal open onClose={onClose} className="paper modal--paper" title={x?.question ?? title} eyebrow={<span className="eyebrow">Explain this change · {companyName}</span>} labelledBy="explain-title">
      {q.isLoading ? (
        <div className="stack" style={{ gap: 12 }} role="status" aria-live="polite">
          <span className="row t-sm t-muted" style={{ gap: 8 }}>
            <LoaderCircle className="spin" width={15} height={15} aria-hidden /> {fresh ? 'Researching live sources for an explanation…' : 'Checking saved evidence for an explanation…'}
          </span>
          <Skeleton h={90} r={12} />
          <Skeleton h={90} r={12} />
        </div>
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} compact />
      ) : x ? (
        <div className="stack" style={{ gap: 14 }}>
          <section className="layer layer--observed" aria-labelledby="ly-obs">
            <div className="layer-head">
              <Eye aria-hidden width={16} height={16} />
              <h3 id="ly-obs">Observed facts</h3>
              <span className="spacer" />
              <span className="layer-kind">Verified data</span>
            </div>
            {x.observed.length ? (
              <ul>
                {x.observed.map((o) => (
                  <li key={o.id}>
                    <span>{o.text}</span>
                    {evBtn(o.text, o.evidence)}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="t-sm t-muted">No verified facts are available for this change.</p>
            )}
          </section>

          <section className="layer layer--reported" aria-labelledby="ly-rep">
            <div className="layer-head">
              <Quote aria-hidden width={16} height={16} />
              <h3 id="ly-rep">Reported by sources</h3>
              <span className="spacer" />
              <span className="layer-kind">Attributed statements</span>
            </div>
            {x.reported.length ? (
              <ul>
                {x.reported.map((r) => (
                  <li key={r.id}>
                    <span>
                      <span className="t-muted">{sourceIndex[r.sourceId]?.name ?? r.sourceId}: </span>
                      {r.text}
                      {r.quote && <blockquote>“{r.quote}”</blockquote>}
                    </span>
                    {evBtn(r.text, r.evidence)}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="t-sm t-muted">No source in the evidence states a reason for this change.</p>
            )}
          </section>

          <section className="layer layer--synthesis" aria-labelledby="ly-syn">
            <div className="layer-head">
              <Sparkles aria-hidden width={16} height={16} />
              <h3 id="ly-syn">AI synthesis</h3>
              <span className="spacer" />
              <span className="layer-kind">Not established fact</span>
            </div>
            {x.synthesis ? (
              <>
                <p className="t-sm" style={{ margin: 0, lineHeight: 1.6 }}>
                  {x.synthesis.text}
                </p>
                <p className="layer-caveat">{x.synthesis.caveat}</p>
              </>
            ) : (
              <p className="t-sm t-muted">No synthesis — the evidence is not sufficient to connect facts and reasons.</p>
            )}
          </section>

          {x.gaps.length > 0 && (
            <section aria-labelledby="ly-gaps" className="stack" style={{ gap: 6 }}>
              <h3 id="ly-gaps" className="t-micro row" style={{ gap: 6 }}>
                <CircleHelp width={13} height={13} aria-hidden /> What the evidence does not show
              </h3>
              <ul className="stack" style={{ gap: 4 }}>
                {x.gaps.map((g) => (
                  <li key={g} className="t-sm t-soft">
                    {g}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <div className="row-wrap" style={{ gap: 10, paddingTop: 6, borderTop: '1px solid var(--paper-rule-soft)' }}>
            <span className="t-xs t-muted">
              {x.origin === 'saved_evidence' ? 'From saved evidence' : 'Includes live source research'} · {formatDateTime(x.generatedAt)}
            </span>
            <span className="spacer" />
            {x.origin === 'saved_evidence' && (
              <button className="btn btn--sm" onClick={() => setFresh(true)}>
                <Telescope aria-hidden /> Research more (live sources)
              </button>
            )}
          </div>
        </div>
      ) : null}
    </Modal>
  );
}
