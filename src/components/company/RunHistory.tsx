import { Link } from 'react-router-dom';
import { Pill } from '@/components/common/StatusPill';
import { EffortSummary } from '@/components/research/EffortSummary';
import type { ResearchRunSnapshot } from '@/types';
import { formatDateTime } from '@/utils/format';
import { RUN_STATUS } from '@/utils/status';
import { cn } from '@/utils/cn';

const GENERIC_FOCUS = new Set(['', 'company brief', 'research this company']);

export const focusOf = (run: Pick<ResearchRunSnapshot, 'prompt'>): string => (GENERIC_FOCUS.has((run.prompt ?? '').trim().toLowerCase()) ? 'Company brief' : (run.prompt ?? '').trim());

/** Why a run does not carry the plain "Completed" label, in the run's own words. */
function whyNotCompleted(run: ResearchRunSnapshot): string[] {
  if (run.status === 'completed') return [];
  return run.issues.length ? run.issues : [run.status === 'failed' ? 'The run failed before it finished.' : run.status === 'cancelled' ? 'The run was cancelled.' : 'Not everything could be verified.'];
}

function RunRow({ run, artifactId, viewingVersionId }: { run: ResearchRunSnapshot; artifactId: string; viewingVersionId?: string }) {
  const st = RUN_STATUS[run.status];
  const coverage = run.summary?.coverage;
  const viewing = !!run.versionId && run.versionId === viewingVersionId;
  const reasons = whyNotCompleted(run);
  const answer = run.answer?.blocks?.[0]?.text;
  return (
    <li className={cn('run', run.isLatestReport && 'is-latest', viewing && 'is-viewing')} data-testid={`run-${run.id}`} data-status={run.status}>
      <span className="run-dot" aria-hidden />
      <div className="run-top">
        <span className="t-sm run-mode">{run.mode === 'deep' ? 'Deep research' : 'Quick research'}</span>
        <Pill tone={st.tone} small className="run-status">
          {st.label}
        </Pill>
        <time className="t-xs run-time" dateTime={run.startedAt} title={run.startedAt}>
          {formatDateTime(run.startedAt)}
        </time>
      </div>
      <div className="run-kinds">
        {run.isLatestReport ? (
          <Pill tone="info" small className="run-kind">
            Latest report
          </Pill>
        ) : run.hasReport ? (
          <Pill tone="neutral" small className="run-kind">
            Earlier run
          </Pill>
        ) : (
          <Pill tone="neutral" small className="run-kind">
            No report saved
          </Pill>
        )}
      </div>
      <span className="t-xs run-focus">
        <span className="t-muted">Focus:</span> {focusOf(run)}
      </span>
      {answer && focusOf(run) !== 'Company brief' && <span className="t-xs t-muted run-answer">Answer: {answer.length > 180 ? `${answer.slice(0, 180)}…` : answer}</span>}
      {run.summary && (
        <span className="t-xs t-muted t-num">
          {coverage ? `${coverage.complete} of ${coverage.total} areas verified` : 'Coverage not reported'}
          {run.summary.factsVerified != null ? ` · ${run.summary.factsVerified} facts` : ''}
          {run.summary.sourcesVerified != null ? ` · ${run.summary.sourcesVerified} sources` : ''}
        </span>
      )}
      {reasons.length > 0 && (
        <ul className={cn('run-issues', run.status === 'failed' && 'is-failed')} data-testid={`run-issues-${run.id}`}>
          {reasons.map((r) => (
            <li key={r} className="t-xs">
              {r}
            </li>
          ))}
        </ul>
      )}
      {run.hasReport && run.evidenceChanged === false && <span className="t-xs t-muted">Found the same facts as the run before it.</span>}
      <div className="row-wrap run-actions">
        {run.hasReport && run.versionId && (
          <Link to={run.isLatestReport ? `/library/${artifactId}` : `/library/${artifactId}?version=${run.versionId}`} className="link-btn t-xs" aria-current={viewing ? 'true' : undefined}>
            {viewing ? 'Viewing this report' : run.isLatestReport ? 'Open latest report' : `View this run’s report${run.versionNumber ? ` (v${run.versionNumber})` : ''}`}
          </Link>
        )}
      </div>
      {run.effort && <EffortSummary effort={run.effort} title="What this run did" />}
    </li>
  );
}

/**
 * Every research run of the company. The dossier shows one report — the latest — but earlier runs are never discarded: each keeps its own mode, focus,
 * outcome and report version, and runs that failed, were cancelled or finished with gaps say so instead of looking completed.
 */
export function RunHistory({ runs, artifactId, viewingVersionId }: { runs: ResearchRunSnapshot[]; artifactId: string; viewingVersionId?: string }) {
  return (
    <section className="card" aria-labelledby="runs-h" data-testid="run-history">
      <h2 id="runs-h" className="t-micro" style={{ marginBottom: 6 }}>
        Research runs {runs.length > 0 && <span className="t-num t-muted">· {runs.length}</span>}
      </h2>
      {runs.length === 0 ? (
        <p className="t-xs t-muted">Run history starts with the next research run. Earlier research is available as report versions under Research history.</p>
      ) : (
        <>
          <p className="t-xs t-muted" style={{ marginBottom: 10 }}>
            This page shows the latest report. Each run is kept here; an earlier run’s report stays available under its own version.
          </p>
          <ol className="runs">
            {runs.map((r) => (
              <RunRow key={r.id} run={r} artifactId={artifactId} viewingVersionId={viewingVersionId} />
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
