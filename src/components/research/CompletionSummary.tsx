import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, BookmarkCheck, BookmarkPlus, CircleAlert, CircleCheck, FileText, LoaderCircle, Timer } from 'lucide-react';
import { api } from '@/api';
import type { ResearchRun } from '@/types';
import { CoverageMeter } from '@/components/company/Coverage';
import { useUi } from '@/stores/ui';
import { cn } from '@/utils/cn';

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

function elapsed(ms: number) {
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
}

/**
 * Research-completion summary. Every number is a real value from the
 * backend's run.completed summary; anything the backend did not send is
 * left out rather than estimated.
 */
export function CompletionSummary({ run, onSaved }: { run: ResearchRun; onSaved?: (artifactId: string) => void }) {
  const s = run.summary;
  const company = run.company;
  const nav = useNavigate();
  const toast = useUi((x) => x.toast);
  const [saving, setSaving] = useState(false);
  const [savedId, setSavedId] = useState<string | undefined>(run.autoSaved ? run.artifactId : undefined);
  const coverage = s?.coverage ?? run.coverage;

  const save = async () => {
    setSaving(true);
    try {
      const a = await api.library.saveRun(run.id);
      setSavedId(a.id);
      onSaved?.(a.id);
      toast({ tone: 'ok', text: 'Saved to Library', action: { label: 'Open', href: `/library/${a.id}` } });
    } catch {
      toast({ tone: 'err', text: 'Could not save to Library. Try again.' });
    } finally {
      setSaving(false);
    }
  };

  const stats: { key: string; label: string; value: string; sub?: string; tone?: 'ok' | 'warn' }[] = [];
  if (s?.sourcesVerified != null)
    stats.push({
      key: 'src',
      label: 'Sources verified',
      value: String(s.sourcesVerified),
      sub: s.primarySources != null && s.secondarySources != null ? `${s.primarySources} primary · ${s.secondarySources} secondary` : undefined,
    });
  if (s?.factsVerified != null) stats.push({ key: 'facts', label: 'Facts verified', value: String(s.factsVerified) });
  if (s?.identityConflicts != null)
    stats.push({
      key: 'id',
      label: 'Identity conflicts',
      value: s.identityConflicts ? String(s.identityConflicts) : 'None',
      sub: s.identityConflicts ? 'Unresolved — review before relying on this research' : 'Company identity confirmed',
      tone: s.identityConflicts ? 'warn' : 'ok',
    });
  if (s?.conflicts != null)
    stats.push({ key: 'cf', label: 'Value conflicts', value: s.conflicts ? String(s.conflicts) : 'None', sub: s.conflicts ? 'Sources disagree; both values are kept' : undefined, tone: s.conflicts ? 'warn' : undefined });
  if (s?.changesDetected != null)
    stats.push({ key: 'ch', label: 'Changes detected', value: String(s.changesDetected), sub: s.changesDetected ? 'Material changes since the previous research' : 'No verified material changes' });
  const unreachable = (s?.blockedSources ?? 0) + (s?.failedSources ?? 0);
  if (unreachable) stats.push({ key: 'bl', label: 'Not reachable', value: plural(unreachable, 'source'), sub: [s?.blockedSources ? `${s.blockedSources} blocked` : '', s?.failedSources ? `${s.failedSources} failed` : ''].filter(Boolean).join(' · '), tone: 'warn' });

  return (
    <section className="rs-complete" aria-labelledby="rs-complete-h">
      <div className="rs-complete-head">
        <CircleCheck aria-hidden className="rs-complete-ico" />
        <div className="stack" style={{ gap: 2, minWidth: 0 }}>
          <h2 id="rs-complete-h">Research complete{company ? ` · ${company.legalName}` : ''}</h2>
          <span className="t-xs t-muted row" style={{ gap: 6 }}>
            {s?.elapsedMs != null && (
              <>
                <Timer aria-hidden width={13} height={13} /> Finished in {elapsed(s.elapsedMs)} <span aria-hidden>·</span>
              </>
            )}
            {savedId ? 'Saved to your Library' : 'Not saved yet'}
          </span>
        </div>
        <span className="spacer" />
        <div className="row-wrap" style={{ gap: 8 }}>
          {company && (
            <Link to={`/company/${company.orgNumber}`} className="btn btn--primary">
              Open company <ArrowRight aria-hidden />
            </Link>
          )}
          {savedId ? (
            <button className="btn" onClick={() => nav(`/library/${savedId}`)}>
              <BookmarkCheck aria-hidden /> Saved · Open in Library
            </button>
          ) : (
            <button className="btn" onClick={save} disabled={saving}>
              {saving ? <LoaderCircle className="spin" aria-hidden /> : <BookmarkPlus aria-hidden />} Save to Library
            </button>
          )}
          {company && (
            <Link to={`/company/${company.orgNumber}?brief=1`} className="btn btn--ghost">
              <FileText aria-hidden /> Executive brief
            </Link>
          )}
        </div>
      </div>
      <dl className="rs-complete-stats">
        {coverage && (
          <div className="rs-stat rs-stat--cov">
            <dt>Coverage</dt>
            <dd>
              <CoverageMeter coverage={coverage} />
            </dd>
          </div>
        )}
        {stats.map((x) => (
          <div key={x.key} className={cn('rs-stat', x.tone && `rs-stat--${x.tone}`)}>
            <dt>{x.label}</dt>
            <dd>
              <span className="rs-stat-v t-num">
                {x.tone === 'warn' && <CircleAlert aria-hidden />}
                {x.value}
              </span>
              {x.sub && <span className="rs-stat-sub">{x.sub}</span>}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
