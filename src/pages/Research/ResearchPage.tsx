import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Building2, CircleAlert, LoaderCircle, RotateCcw, Square, Telescope, X } from 'lucide-react';
import { api, ApiError } from '@/api';
import type { CompanySummary, ResearchMode, ResearchRun } from '@/types';
import { useResearchStream } from '@/hooks/useResearchStream';
import { useDebounce } from '@/hooks/useDebounce';
import { usePreferences } from '@/stores/preferences';
import { useUi } from '@/stores/ui';
import { Segmented } from '@/components/common/Tabs';
import { BrandMark } from '@/components/common/BrandMark';
import { ErrorState } from '@/components/common/ErrorState';
import { StageTrack } from '@/components/research/StageTrack';
import { PlanEditor, ResearchPlanView } from '@/components/research/ResearchPlan';
import { SourceStack } from '@/components/research/SourceStack';
import { CompletionSummary } from '@/components/research/CompletionSummary';
import { EventTimeline } from '@/components/research/EventTimeline';
import { AnswerView } from '@/components/research/AnswerView';
import { AmbiguousCandidates } from '@/components/research/AmbiguousCandidates';
import { FactValue } from '@/components/evidence/FactValue';
import { formatOrgNumber } from '@/utils/format';
import '@/styles/sections.css';
import './research.css';

const PROMPTS = ['Company brief', 'Latest financials', 'Who runs it?', 'Where does it operate?', 'Is it hiring?', 'Recent activity', 'What changed recently?'];

export default function ResearchPage() {
  const [params, setParams] = useSearchParams();
  const defaultMode = usePreferences((s) => s.researchMode);
  const [mode, setMode] = useState<ResearchMode>(defaultMode);
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [startError, setStartError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [planKeys, setPlanKeys] = useState<string[]>([]);
  const orgParam = params.get('org');
  const autostarted = useRef(false);

  const start = useCallback(
    async (input: { orgNumber?: string; query: string; prompt?: string }) => {
      setBusy(true);
      setStartError(null);
      try {
        const r = await api.research.start({ ...input, mode });
        setRun(r);
        setPlanKeys(r.plan.steps.map((s) => s.key));
      } catch (e) {
        setStartError(e);
      } finally {
        setBusy(false);
      }
    },
    [mode],
  );

  useEffect(() => {
    if (autostarted.current || params.get('autostart') !== '1') return;
    const q = params.get('q');
    if (!orgParam && !q) return;
    autostarted.current = true;
    void start({ orgNumber: orgParam ?? undefined, query: q ?? orgParam ?? '', prompt: params.get('prompt') ?? undefined });
    const p = new URLSearchParams(params);
    p.delete('autostart');
    setParams(p, { replace: true });
  }, [params, orgParam, start, setParams]);

  const reset = () => {
    setRun(null);
    setStartError(null);
  };

  if (!run)
    return (
      <div className="page">
        <Composer orgParam={orgParam} initialQuery={params.get('q') ?? ''} initialPrompt={params.get('prompt') ?? ''} mode={mode} setMode={setMode} onStart={start} busy={busy} error={startError} />
      </div>
    );

  if (run.status === 'ambiguous' && run.ambiguity)
    return (
      <div className="page">
        <div className="page-head">
          <div>
            <h1>Which company?</h1>
          </div>
          <div className="page-actions">
            <button className="btn btn--ghost" onClick={reset}>
              <X aria-hidden /> New research
            </button>
          </div>
        </div>
        <AmbiguousCandidates match={run.ambiguity} onPick={(org) => void start({ orgNumber: org, query: run.query, prompt: run.prompt })} />
      </div>
    );

  if (run.status === 'awaiting_confirmation')
    return (
      <div className="page">
        <div className="page-head">
          <div>
            <span className="eyebrow">Deep research · plan</span>
            <h1 style={{ marginTop: 10 }}>Research plan for {run.company?.legalName}</h1>
            <p>Review the steps before starting. Required steps verify identity, filings and leadership.</p>
          </div>
          <div className="page-actions">
            <button className="btn btn--ghost" onClick={reset}>
              Cancel
            </button>
          </div>
        </div>
        <div className="research-plan-edit card">
          <PlanEditor
            plan={run.plan}
            keys={planKeys}
            setKeys={setPlanKeys}
            busy={busy}
            onStart={async () => {
              setBusy(true);
              try {
                setRun(await api.research.confirm(run.id, planKeys));
              } finally {
                setBusy(false);
              }
            }}
          />
        </div>
      </div>
    );

  return <Workspace run={run} setRun={setRun} onNew={reset} />;
}

/* ------------------------------------------------------------------ */

function Composer({ orgParam, initialQuery, initialPrompt, mode, setMode, onStart, busy, error }: { orgParam: string | null; initialQuery: string; initialPrompt: string; mode: ResearchMode; setMode: (m: ResearchMode) => void; onStart: (i: { orgNumber?: string; query: string; prompt?: string }) => void; busy: boolean; error: unknown }) {
  const [company, setCompany] = useState<Pick<CompanySummary, 'orgNumber' | 'legalName' | 'municipality'> | null>(null);
  const [q, setQ] = useState(initialQuery);
  const [prompt, setPrompt] = useState(initialPrompt || 'Company brief');
  const [question, setQuestion] = useState('');
  const dq = useDebounce(q.trim(), 200);
  const preset = useQuery({ queryKey: ['company', orgParam], queryFn: () => api.companies.get(orgParam!), enabled: !!orgParam });
  useEffect(() => {
    if (preset.data) setCompany(preset.data.company);
  }, [preset.data]);
  const sugg = useQuery({ queryKey: ['research-suggest', dq], queryFn: ({ signal }) => api.search.global(dq, signal), enabled: !company && dq.length >= 2 });
  const finalPrompt = question.trim() || prompt;
  const submit = () => {
    if (company) onStart({ orgNumber: company.orgNumber, query: company.legalName, prompt: finalPrompt });
    else if (q.trim()) onStart({ query: q.trim(), prompt: finalPrompt });
  };
  return (
    <div className="composer">
      <div className="composer-head">
        <span className="eyebrow">AI research workspace</span>
        <h1 className="t-display composer-title">
          What do you want to <em className="t-serif">research?</em>
        </h1>
        <p className="t-soft">Every step is checked against public sources. Progress you see comes from the backend as each source completes.</p>
      </div>

      <div className="composer-card surface">
        <label className="field-label" htmlFor="rc-company">
          Company
        </label>
        {company ? (
          <div className="composer-company">
            <BrandMark name={company.legalName} org={company.orgNumber} size={36} />
            <span className="stack" style={{ gap: 0, flex: 1, minWidth: 0 }}>
              <strong style={{ fontWeight: 500 }}>{company.legalName}</strong>
              <span className="t-xs t-muted">
                {company.municipality} · Org <span className="t-mono">{formatOrgNumber(company.orgNumber)}</span>
              </span>
            </span>
            <button className="btn btn--ghost btn--icon btn--sm" onClick={() => setCompany(null)} aria-label="Change company">
              <X aria-hidden />
            </button>
          </div>
        ) : (
          <div className="composer-search">
            <div className="input-wrap">
              <Building2 aria-hidden />
              <input id="rc-company" className="input" style={{ height: 46, fontSize: 15 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Company name or 9-digit organization number" autoComplete="off" onKeyDown={(e) => e.key === 'Enter' && submit()} />
            </div>
            {sugg.data && sugg.data.companies.length > 0 && dq.length >= 2 && (
              <ul className="composer-sugg" role="listbox" aria-label="Matching companies">
                {sugg.data.companies.slice(0, 5).map((c) => (
                  <li key={c.orgNumber}>
                    <button role="option" aria-selected={false} className="palette-item" onClick={() => setCompany(c)}>
                      <Building2 aria-hidden />
                      <span className="stack" style={{ gap: 0, flex: 1, minWidth: 0 }}>
                        <span className="truncate">{c.legalName}</span>
                        <span className="palette-sub">
                          {c.municipality} · {formatOrgNumber(c.orgNumber)} · {c.researchState === 'not_researched' ? 'Not researched yet' : `${c.coverage.complete}/5 areas`}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <span className="field-label" style={{ marginTop: 16 }}>
          Focus
        </span>
        <div className="row-wrap" role="group" aria-label="Suggested prompts">
          {PROMPTS.map((p) => (
            <button key={p} className="chip" aria-pressed={!question && prompt === p} onClick={() => (setPrompt(p), setQuestion(''))}>
              {p}
            </button>
          ))}
        </div>
        <label className="field-label" htmlFor="rc-q" style={{ marginTop: 16 }}>
          Or ask your own question
        </label>
        <textarea id="rc-q" className="textarea" rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="e.g. Has the company opened offices outside Norway in the last year?" />
        <div className="composer-foot">
          <Segmented
            label="Research depth"
            value={mode}
            onChange={setMode}
            options={[
              { value: 'quick', label: 'Quick', title: 'Core sources, starts immediately' },
              { value: 'deep', label: 'Deep', title: 'All source families, plan shown first' },
            ]}
          />
          <span className="t-xs t-muted">{mode === 'deep' ? 'Deep research shows the plan for review before it starts.' : 'Quick research starts immediately with the core sources.'}</span>
          <span className="spacer" />
          <button className="btn btn--primary btn--lg" onClick={submit} disabled={busy || (!company && !q.trim())}>
            {busy ? <LoaderCircle className="spin" aria-hidden /> : <Telescope aria-hidden />} Start research
          </button>
        </div>
        {error != null && (
          <div style={{ marginTop: 14 }}>
            <ErrorState error={error} title={error instanceof ApiError && error.code === 'not_found' ? 'No matching company' : undefined} compact />
          </div>
        )}
      </div>

      <div className="composer-explain">
        <SourceStack steps={null} compact />
        <div className="stack" style={{ gap: 10 }}>
          <h2 className="t-h3">How research works</h2>
          <ol className="how">
            <li>
              <strong>Identify</strong> — the company is matched to one organization number. Ambiguous names stop and ask.
            </li>
            <li>
              <strong>Gather</strong> — registry, filed accounts, website, roles, jobs and public activity are checked.
            </li>
            <li>
              <strong>Verify & reconcile</strong> — facts are tied to evidence; disagreements are shown, not hidden.
            </li>
            <li>
              <strong>Synthesize & save</strong> — a cited summary is written and the research is saved to your Library.
            </li>
          </ol>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function Workspace({ run, setRun, onNew }: { run: ResearchRun; setRun: (r: ResearchRun) => void; onNew: () => void }) {
  const { state, setRun: setStreamRun } = useResearchStream(run);
  const live = state.run ?? run;
  const qc = useQueryClient();
  const nav = useNavigate();
  const toast = useUi((s) => s.toast);
  const company = live.company;
  const profileQ = useQuery({ queryKey: ['company', company?.orgNumber], queryFn: () => api.companies.get(company!.orgNumber), enabled: !!company });
  const sourceIndex = profileQ.data?.sourceIndex ?? sourceIndexFromFacts(state.facts);
  const stepLabels = useMemo(() => Object.fromEntries(live.plan.steps.map((s) => [s.id, s.label])), [live.plan.steps]);
  const running = live.status === 'running';
  const failedSteps = live.plan.steps.filter((s) => s.status === 'failed');
  const notified = useRef<number>(0);

  useEffect(() => {
    if (live.status === 'completed' && company && notified.current !== state.lastSeq) {
      notified.current = state.lastSeq;
      qc.invalidateQueries({ queryKey: ['company', company.orgNumber] });
      qc.invalidateQueries({ queryKey: ['companies'] });
      qc.invalidateQueries({ queryKey: ['library'] });
      qc.invalidateQueries({ queryKey: ['assess'] });
      toast({ tone: 'ok', text: `Research complete · ${company.legalName}`, action: live.artifactId ? { label: 'Open', href: `/library/${live.artifactId}` } : undefined });
    }
  }, [live.status, live.artifactId, company, qc, toast, state.lastSeq]);

  const cancel = async () => {
    const r = await api.research.cancel(live.id);
    setStreamRun({ ...live, status: r.status });
  };
  const retry = async () => {
    const r = await api.research.retryFailed(live.id);
    setStreamRun({ ...live, status: 'running' });
    setRun({ ...r, plan: live.plan });
  };

  const facts = state.facts;
  const failed = live.status === 'failed' || live.status === 'cancelled' || state.connection === 'error';

  return (
    <div className="page page--wide rs">
      <header className="rs-head">
        <div className="row" style={{ gap: 14, minWidth: 0 }}>
          {company && <BrandMark name={company.legalName} org={company.orgNumber} size={46} />}
          <div className="stack" style={{ gap: 4, minWidth: 0 }}>
            <span className="eyebrow">{live.status === 'completed' ? 'Research complete' : live.status === 'cancelled' ? 'Research cancelled' : failed ? 'Research paused' : 'Researching'}</span>
            <h1 className="rs-title truncate">{company?.legalName ?? live.query}</h1>
            <span className="t-xs t-muted">
              {live.mode === 'deep' ? 'Deep research' : 'Quick research'} · Focus: {live.prompt ?? 'Company brief'}
              {company && (
                <>
                  {' '}
                  · Org <span className="t-mono">{formatOrgNumber(company.orgNumber)}</span>
                </>
              )}
            </span>
          </div>
        </div>
        <div className="row-wrap" style={{ gap: 8 }}>
          {running && live.capabilities.cancel && (
            <button className="btn" onClick={cancel}>
              <Square aria-hidden /> Cancel
            </button>
          )}
          {!running && failedSteps.length > 0 && live.capabilities.retryFailed && (
            <button className="btn" onClick={retry}>
              <RotateCcw aria-hidden /> Retry failed sources
            </button>
          )}
          <button className="btn btn--ghost" onClick={onNew}>
            New research
          </button>
        </div>
      </header>

      <StageTrack stage={live.stage} done={live.status === 'completed'} />

      {live.status === 'completed' && <CompletionSummary run={live} />}

      {failed && (
        <div className="notice notice--warn" role="alert" style={{ marginTop: 16 }}>
          <CircleAlert aria-hidden />
          <div className="stack" style={{ gap: 4 }}>
            <strong>{live.status === 'cancelled' ? 'Research cancelled' : 'Research paused'}</strong>
            <span>{state.error ?? 'A source did not respond.'} Your verified company data is still available.</span>
            {live.status !== 'cancelled' && (
              <div>
                <button className="btn btn--sm" onClick={() => company && nav(`/research?org=${company.orgNumber}&autostart=1`)}>
                  <RotateCcw aria-hidden /> Retry research
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="rs-grid">
        <aside className="rs-col" aria-labelledby="rs-plan">
          <div className="rs-panel">
            <h2 id="rs-plan" className="rs-panel-title">
              Research plan
            </h2>
            <ResearchPlanView plan={live.plan} />
          </div>
        </aside>

        <section className="rs-col rs-center" aria-labelledby="rs-syn">
          <div className="rs-panel rs-synth">
            <h2 id="rs-syn" className="rs-panel-title">
              Synthesis
            </h2>
            {state.answer ? (
              <AnswerView answer={state.answer} sourceIndex={sourceIndex} context={company?.legalName} />
            ) : state.synthesisText ? (
              <p className="rs-stream" aria-live="polite">
                {state.synthesisText}
                <span className="rs-caret" aria-hidden />
              </p>
            ) : (
              <p className="t-sm t-muted">{running ? 'The synthesis is written after sources are gathered and verified.' : 'No synthesis yet.'}</p>
            )}
          </div>
          <div className="rs-panel">
            <h2 className="rs-panel-title">
              Facts confirmed <span className="t-num t-muted">{facts.length}</span>
            </h2>
            {facts.length === 0 ? (
              <p className="t-sm t-muted">Facts appear here only after the backend confirms them with evidence.</p>
            ) : (
              <ul className="rs-facts">
                {facts.map((f) => (
                  <li key={f.id} className="anim-fade-up">
                    <span className="t-sm t-muted">{f.label}</span>
                    <FactValue fact={f} sourceIndex={sourceIndex} context={company?.legalName} showFreshness />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        <aside className="rs-col" aria-labelledby="rs-src">
          <div className="rs-panel">
            <h2 id="rs-src" className="rs-panel-title">
              Source activity
            </h2>
            <SourceStack steps={live.plan.steps} running={running} />
          </div>
          <div className="rs-panel">
            <h2 className="rs-panel-title">Event timeline</h2>
            <EventTimeline events={state.events} stepLabels={stepLabels} />
            {state.connection === 'reconnecting' && <p className="t-xs t-warn">Reconnecting to the research stream…</p>}
          </div>
        </aside>
      </div>
    </div>
  );
}

/** Before the profile loads, cite sources by id; the drawer still shows the evidence. */
function sourceIndexFromFacts(facts: { evidence: { sourceId: string }[] }[]) {
  const idx: Record<string, { id: string; name: string; kind: 'web'; tier: 'primary'; official: boolean }> = {};
  for (const f of facts) for (const e of f.evidence) idx[e.sourceId] ??= { id: e.sourceId, name: e.sourceId, kind: 'web', tier: 'primary', official: false };
  return idx;
}
