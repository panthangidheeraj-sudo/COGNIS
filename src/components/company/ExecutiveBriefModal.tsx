import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, LoaderCircle, Printer, Telescope } from 'lucide-react';
import { api } from '@/api';
import type { BriefItem, ExecutiveBrief } from '@/types';
import { Modal } from '@/components/common/Overlay';
import { ErrorState } from '@/components/common/ErrorState';
import { Skeleton } from '@/components/common/Skeleton';
import { CoverageMeter } from './Coverage';
import { useOpenEvidence } from '@/components/evidence/useEvidence';
import { formatDate, formatDateLong, formatOrgNumber } from '@/utils/format';

/**
 * Executive brief — a one-screen factual summary on the ivory knowledge layer.
 * Compiled by the backend from saved evidence; every line carries numbered
 * source references. No scores, rankings, opinions or advice.
 */
export function ExecutiveBriefModal({ orgNumber, companyName, open, onClose }: { orgNumber: string; companyName: string; open: boolean; onClose: () => void }) {
  const q = useQuery({ queryKey: ['brief', orgNumber], queryFn: () => api.companies.brief(orgNumber), enabled: open, staleTime: 60_000 });
  const b = q.data;
  const print = () => {
    document.documentElement.classList.add('print-brief');
    window.print();
    setTimeout(() => document.documentElement.classList.remove('print-brief'), 200);
  };
  return (
    <Modal
      open={open}
      onClose={onClose}
      className="paper modal--paper brief-modal"
      labelledBy="brief-title"
      eyebrow={<span className="eyebrow">Executive brief</span>}
      title={companyName}
      footer={
        <>
          <span className="t-xs t-muted brief-disclaimer">Factual summary compiled from saved evidence. No assessment, score or advice.</span>
          <span className="spacer" />
          <button className="btn btn--ghost btn--sm" onClick={print} disabled={!b}>
            <Printer aria-hidden /> Print
          </button>
          {b?.artifactId ? (
            <Link to={`/library/${b.artifactId}`} className="btn btn--primary btn--sm" onClick={onClose}>
              View full research <ArrowRight aria-hidden />
            </Link>
          ) : (
            <Link to={`/research?org=${orgNumber}&autostart=1`} className="btn btn--primary btn--sm" onClick={onClose}>
              <Telescope aria-hidden /> Research this company
            </Link>
          )}
        </>
      }
    >
      {q.isLoading ? (
        <div className="stack" style={{ gap: 12 }} role="status" aria-live="polite">
          <span className="row t-sm t-muted" style={{ gap: 8 }}>
            <LoaderCircle className="spin" width={15} height={15} aria-hidden /> Compiling the brief from saved evidence…
          </span>
          <Skeleton h={40} w="60%" />
          <div className="brief-grid">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} h={96} r={10} />
            ))}
          </div>
        </div>
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} compact />
      ) : b ? (
        <BriefBody brief={b} />
      ) : null}
    </Modal>
  );
}

function BriefBody({ brief }: { brief: ExecutiveBrief }) {
  const open = useOpenEvidence(brief.sourceIndex, brief.companyName);
  // Numbered references: one number per distinct source, in order of first use.
  const refs = useMemo(() => {
    const order: string[] = [];
    for (const s of brief.sections) for (const it of s.items) for (const e of it.evidence) if (!order.includes(e.sourceId)) order.push(e.sourceId);
    return order;
  }, [brief]);
  const refNums = (it: BriefItem) => [...new Set(it.evidence.map((e) => refs.indexOf(e.sourceId) + 1))].sort((a, b) => a - b);
  const main = brief.sections.filter((s) => s.id !== 'changes');
  const changes = brief.sections.find((s) => s.id === 'changes');

  return (
    <article className="brief" aria-label={`Executive brief: ${brief.companyName}`}>
      <header className="stack" style={{ gap: 10 }}>
        <div className="note-mast">
          <strong>Cognis</strong>
          <span>Research note</span>
          <span className="spacer" />
          <span>{brief.researchedAt ? `Based on research of ${formatDate(brief.researchedAt)}` : 'Registry data only'}</span>
        </div>
        <div className="note-sub">
          <span>{brief.statusLabel}</span>
          {brief.location && <span>{brief.location}</span>}
          <span>
            Org. no. <span className="t-mono">{formatOrgNumber(brief.orgNumber)}</span>
          </span>
          <CoverageMeter coverage={brief.coverage} size="sm" interactive={false} />
        </div>
      </header>

      <div className="brief-grid">
        {main.map((s, si) => (
          <section key={s.id} className="brief-sec" aria-labelledby={`bs-${s.id}`}>
            <h3 id={`bs-${s.id}`} className="note-sec-title">
              <span className="note-sec-num">{String(si + 1).padStart(2, '0')}</span> {s.title}
            </h3>
            {s.items.length ? (
              <ul>
                {s.items.map((it) => (
                  <li key={it.id}>
                    {it.text}
                    {refNums(it).map((n) => (
                      <button key={n} className="note-ref" onClick={() => open({ title: it.label ?? s.title, value: it.value, evidence: it.evidence })} aria-label={`Source ${n}: view evidence`}>
                        {n}
                      </button>
                    ))}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="brief-empty">{s.emptyText ?? 'Not available.'}</p>
            )}
          </section>
        ))}
      </div>

      {changes && (
        <section className="brief-sec brief-changes" aria-labelledby="bs-changes">
          <h3 id="bs-changes" className="note-sec-title">
            <span className="note-sec-num">{String(main.length + 1).padStart(2, '0')}</span> {changes.title}
          </h3>
          {changes.items.length ? (
            <ul>
              {changes.items.map((it) => (
                <li key={it.id}>
                  {it.text}
                  {refNums(it).map((n) => (
                    <button key={n} className="note-ref" onClick={() => open({ title: it.label ?? changes.title, evidence: it.evidence })} aria-label={`Source ${n}: view evidence`}>
                      {n}
                    </button>
                  ))}
                </li>
              ))}
            </ul>
          ) : (
            <p className="brief-empty">{changes.emptyText}</p>
          )}
        </section>
      )}

      <footer className="brief-foot">
        {brief.gaps.length > 0 && (
          <div>
            <h4 className="t-micro" style={{ marginBottom: 6 }}>
              Not established by the evidence
            </h4>
            <ul className="brief-gaps">
              {brief.gaps.slice(0, 5).map((g) => (
                <li key={g}>{g}</li>
              ))}
            </ul>
          </div>
        )}
        <div>
          <h4 className="t-micro" style={{ marginBottom: 6 }}>
            Sources
          </h4>
          <ol className="note-footnotes">
            {refs.map((id, i) => (
              <li key={id}>
                <span className="t-mono">[{i + 1}]</span>
                <span>
                  {brief.sourceIndex[id]?.name ?? id}
                  {brief.sourceIndex[id]?.tier ? ` · ${brief.sourceIndex[id].tier}` : ''}
                </span>
              </li>
            ))}
          </ol>
          <p className="t-xs t-muted" style={{ marginTop: 8 }}>
            Compiled {formatDateLong(brief.generatedAt)}. Each figure keeps its reporting period; click a number for the evidence.
          </p>
        </div>
      </footer>
    </article>
  );
}
