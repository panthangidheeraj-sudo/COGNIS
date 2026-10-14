/**
 * Live Source Activity and run history.
 * Every state on screen must come from a backend event, and a run that did not complete cleanly must never look completed.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { renderWithProviders } from './utils';
import ResearchPage from '@/pages/Research/ResearchPage';
import ArtifactPage from '@/pages/Artifact/ArtifactPage';
import { RunHistory, focusOf } from '@/components/company/RunHistory';
import { SourceActivity, formatElapsed, stepElapsedMs, stepStateLabel } from '@/components/research/SourceActivity';
import { StepRow } from '@/components/research/ResearchPlan';
import { initialStreamState, reduceResearchEvent } from '@/api/runs';
import { api } from '@/api';
import { mockApi } from '@/data/mock/mockApi';
import { usePreferences } from '@/stores/preferences';
import type { ResearchEvent, ResearchRun, ResearchRunSnapshot, ResearchStep, ResearchStreamState } from '@/types';
import type { StreamHandlers } from '@/api/http';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  usePreferences.setState({ motion: 'system' });
});

/* ------------------------------------------------------------------ helpers -- */
const T0 = Date.parse('2026-10-12T10:00:00Z');
const iso = (secondsFromStart: number) => new Date(T0 + secondsFromStart * 1000).toISOString();

const step = (key: string, label: string, sourceKind: ResearchStep['sourceKind'], over: Partial<ResearchStep> = {}): ResearchStep => ({
  id: `s-${key}`,
  key,
  label,
  sourceKind,
  optional: false,
  status: 'pending',
  ...over,
});

const planSteps = (): ResearchStep[] => [
  step('registry', 'Verify identity', 'registry'),
  step('accounts', 'Annual accounts', 'financial'),
  step('website', 'Company website', 'website', { optional: true }),
  step('jobs', 'Careers and hiring', 'jobs', { optional: true }),
  step('crosscheck', 'Cross-check facts across sources', 'verification', { optional: true }),
];

const baseRun = (over: Partial<ResearchRun> = {}): ResearchRun => ({
  id: 'run-1',
  query: 'Nordvik',
  mode: 'deep',
  status: 'running',
  plan: { steps: planSteps(), requiresConfirmation: false, availableSteps: [] },
  startedAt: iso(0),
  capabilities: { pause: false, cancel: true, retryFailed: false, editPlan: true },
  autoSaved: false,
  ...over,
});

let seq = 0;
const ev = <T extends ResearchEvent['type']>(type: T, at: number, extra: Omit<Extract<ResearchEvent, { type: T }>, 'type' | 'seq' | 'runId' | 'at'>): ResearchEvent =>
  ({ type, seq: ++seq, runId: 'run-1', at: iso(at), ...extra }) as ResearchEvent;

const start = (run: ResearchRun = baseRun()): ResearchStreamState => {
  seq = 0;
  return { ...initialStreamState, run };
};
const apply = (state: ResearchStreamState, ...events: ResearchEvent[]) => events.reduce(reduceResearchEvent, state);
const status = (state: ResearchStreamState, key: string) => state.run!.plan.steps.find((s) => s.key === key)!;
const row = (key: string) => screen.getByTestId(`source-row-${key}`);

/* ------------------------------------------------------------------ reducer -- */
describe('live progress: the run state changes only when the backend says so', () => {
  it('moves one source at a time through pending → running → succeeded, and nothing else changes', () => {
    let s = start();
    s = apply(s, ev('run.started', 0, {}), ev('step.started', 1, { stepId: 's-registry', sourceName: 'Enhetsregisteret' }));
    expect(status(s, 'registry')).toMatchObject({ status: 'running', startedAt: iso(1), sourceName: 'Enhetsregisteret' });
    expect(['accounts', 'website', 'jobs', 'crosscheck'].map((k) => status(s, k).status)).toEqual(['pending', 'pending', 'pending', 'pending']); // nobody else is "running"

    s = apply(s, ev('step.progress', 2, { stepId: 's-registry', message: 'Looking up the organisation number' }));
    expect(status(s, 'registry').detail).toBe('Looking up the organisation number');

    s = apply(s, ev('step.completed', 3, { stepId: 's-registry', sourceName: 'Enhetsregisteret', factCount: 4, evidenceCount: 4, durationMs: 1800, outcome: 'verified' }));
    expect(status(s, 'registry')).toMatchObject({ status: 'done', durationMs: 1800, factCount: 4, evidenceCount: 4, detail: undefined });
    expect(s.lastSeq).toBe(seq);
    expect(s.events).toHaveLength(4);
  });

  it('shows failures, blocks, skips and cancellations with their reasons', () => {
    let s = start();
    s = apply(
      s,
      ev('step.started', 1, { stepId: 's-accounts', sourceName: 'Regnskapsregisteret' }),
      ev('step.failed', 2, { stepId: 's-accounts', sourceName: 'Regnskapsregisteret', message: 'The source answered with HTTP 503 after 3 attempts.', retryable: false }),
      ev('step.started', 3, { stepId: 's-website', sourceName: 'Official company website' }),
      ev('step.blocked', 4, { stepId: 's-website', sourceName: 'Official company website', message: 'robots.txt does not allow this page to be fetched' }),
      ev('step.skipped', 5, { stepId: 's-jobs', message: 'No verified website, so no company-owned careers sources could be checked.' }),
      ev('step.started', 6, { stepId: 's-crosscheck', sourceName: 'Cross-check' }),
      ev('step.cancelled', 7, { stepId: 's-crosscheck', message: 'Stopped: research was cancelled before this source finished.' }),
    );
    expect(status(s, 'accounts')).toMatchObject({ status: 'failed', message: 'The source answered with HTTP 503 after 3 attempts.' });
    expect(status(s, 'website')).toMatchObject({ status: 'blocked', message: 'robots.txt does not allow this page to be fetched' });
    expect(status(s, 'jobs')).toMatchObject({ status: 'skipped' }); // never started, so no start time and no "ran"
    expect(status(s, 'jobs').startedAt).toBeUndefined();
    expect(status(s, 'crosscheck')).toMatchObject({ status: 'cancelled' });
  });

  it('ignores duplicate and out-of-order events, and a late progress message never revives a finished source', () => {
    let s = start();
    const started = ev('step.started', 1, { stepId: 's-registry', sourceName: 'Enhetsregisteret' });
    const done = ev('step.completed', 2, { stepId: 's-registry', sourceName: 'Enhetsregisteret', factCount: 1, evidenceCount: 1, durationMs: 10, outcome: 'verified' });
    s = apply(s, started, done);
    const before = s;
    expect(apply(s, started, done)).toBe(before); // replays after a reconnect change nothing
    s = apply(s, { type: 'step.progress', seq: 99, runId: 'run-1', at: iso(3), stepId: 's-registry', message: 'late' });
    expect(status(s, 'registry')).toMatchObject({ status: 'done', detail: undefined });
  });

  it('a cancelled run ends as cancelled and a failed one as failed; completion carries the outcome and reasons', () => {
    const cancelled = apply(start(), ev('run.failed', 1, { message: 'Research cancelled.', cancelled: true }));
    expect(cancelled.run!.status).toBe('cancelled');
    expect(apply(start(), ev('run.failed', 1, { message: 'The register did not respond.' })).run!.status).toBe('failed');

    const coverage = { complete: 3, total: 5, areas: [] };
    const done = apply(start(), ev('run.completed', 9, { autoSaved: true, artifactId: 'art-1', coverage, outcome: 'partial', issues: ['1 source could not be reached.'] }));
    expect(done.run).toMatchObject({ status: 'completed', outcome: 'partial', issues: ['1 source could not be reached.'] });
  });
});

/* -------------------------------------------------------------- source panel -- */
describe('Source activity panel', () => {
  const view = (s: ResearchStreamState, props: { now?: number; connection?: ResearchStreamState['connection'] } = {}) => (
    <SourceActivity run={s.run!} connection={props.connection ?? 'open'} error={s.error} now={props.now ?? T0 + 12_000} />
  );

  it('updates in place as events arrive, with names, states, counts and elapsed time from the backend', () => {
    let s = start();
    const { rerender } = render(view(s));
    expect(screen.getAllByText('Pending')).toHaveLength(5);
    expect(screen.getByTestId('source-activity-counts')).toHaveTextContent('5 pending');
    expect(screen.queryByText('Running')).not.toBeInTheDocument(); // nothing is animated or marked active before the backend starts it

    s = apply(s, ev('step.started', 2, { stepId: 's-registry', sourceName: 'Brønnøysundregistrene — Enhetsregisteret' }), ev('step.progress', 3, { stepId: 's-registry', message: 'Looking up 921 604 337' }));
    rerender(view(s, { now: T0 + 12_000 }));
    expect(within(row('registry')).getByText('Running')).toBeInTheDocument();
    expect(within(row('registry')).getByText('Brønnøysundregistrene — Enhetsregisteret')).toBeInTheDocument();
    expect(within(row('registry')).getByText('Looking up 921 604 337')).toBeInTheDocument();
    expect(screen.getByTestId('elapsed-registry')).toHaveTextContent('running 10 s'); // 12 s clock − start at 2 s
    expect(screen.getByTestId('source-activity-counts')).toHaveTextContent('1 running · 4 pending');

    s = apply(s, ev('step.completed', 5, { stepId: 's-registry', sourceName: 'Brønnøysundregistrene — Enhetsregisteret', factCount: 4, evidenceCount: 4, durationMs: 2300, outcome: 'verified' }));
    rerender(view(s, { now: T0 + 14_000 }));
    expect(within(row('registry')).getByText('Succeeded')).toBeInTheDocument();
    expect(within(row('registry')).getByText('4 facts · 4 evidence')).toBeInTheDocument();
    expect(screen.getByTestId('elapsed-registry')).toHaveTextContent('2.3 s'); // the backend's own duration, not the page's clock
    expect(screen.queryByText('Looking up 921 604 337')).not.toBeInTheDocument();
    expect(screen.getByTestId('source-activity-counts')).toHaveTextContent('1 succeeded · 4 pending');
    expect(screen.getByTestId('source-activity-state')).toHaveTextContent('Researching — 1 of 5 sources reported.');
  });

  it('explains a failed, blocked, skipped and empty source in the source\'s own row', () => {
    const s = apply(
      start(),
      ev('step.started', 1, { stepId: 's-accounts', sourceName: 'Regnskapsregisteret' }),
      ev('step.failed', 2, { stepId: 's-accounts', sourceName: 'Regnskapsregisteret', message: 'The source did not respond (timeout).', retryable: false }),
      ev('step.started', 2, { stepId: 's-website', sourceName: 'Official company website' }),
      ev('step.blocked', 3, { stepId: 's-website', sourceName: 'Official company website', message: 'robots.txt does not allow this page to be fetched' }),
      ev('step.skipped', 3, { stepId: 's-jobs', message: 'No verified website, so no careers sources could be checked.' }),
      ev('step.started', 4, { stepId: 's-registry', sourceName: 'Enhetsregisteret' }),
      ev('step.completed', 5, { stepId: 's-registry', sourceName: 'Enhetsregisteret', factCount: 0, evidenceCount: 0, durationMs: 400, outcome: 'not_available', message: 'The register lists no website.' }),
    );
    render(view(s));
    expect(within(row('accounts')).getByText('Failed')).toBeInTheDocument();
    expect(within(row('accounts')).getByText('The source did not respond (timeout).')).toHaveClass('t-err');
    expect(within(row('website')).getByText('Blocked')).toBeInTheDocument();
    expect(within(row('website')).getByText('robots.txt does not allow this page to be fetched')).toBeInTheDocument();
    expect(within(row('jobs')).getByText('Skipped')).toBeInTheDocument();
    expect(within(row('jobs')).getByText('No verified website, so no careers sources could be checked.')).toBeInTheDocument();
    expect(screen.queryByTestId('elapsed-jobs')).not.toBeInTheDocument(); // a skipped source has no elapsed time to invent
    expect(within(row('registry')).getByText('Succeeded · no data')).toBeInTheDocument(); // it answered, and held nothing verifiable
    expect(screen.getByTestId('source-activity-counts')).toHaveTextContent('1 succeeded · 1 failed · 1 blocked · 1 skipped · 1 pending');
  });

  it('describes how the run ended: cancelled, time limit, partial, complete, connection lost', () => {
    const at = (r: Partial<ResearchRun>, connection: ResearchStreamState['connection'] = 'closed') => {
      const { unmount } = render(<SourceActivity run={baseRun(r)} connection={connection} now={T0} />);
      const text = screen.getByTestId('source-activity-state').textContent;
      unmount();
      return text;
    };
    const coverage = { complete: 5, total: 5, areas: [] };
    expect(at({ status: 'cancelled' })).toMatch(/Cancelled — running sources were stopped/);
    expect(at({ status: 'failed' })).toMatch(/run failed/);
    expect(at({ status: 'completed', coverage, summary: { coverage, effort: { mode: 'deep', requests: 1, llmCalls: 0, pagesRead: 0, timedOut: true, workflows: [] } } })).toMatch(/Time limit reached/);
    expect(at({ status: 'completed', coverage, outcome: 'partial', plan: { steps: planSteps().map((x) => ({ ...x, status: x.key === 'jobs' ? 'failed' : 'done' })), requiresConfirmation: false, availableSteps: [] } })).toMatch(
      /Finished with gaps — 1 source could not be read/,
    );
    expect(at({ status: 'completed', coverage, outcome: 'completed', plan: { steps: planSteps().map((x) => ({ ...x, status: 'done' })), requiresConfirmation: false, availableSteps: [] } })).toMatch(/Finished — every planned source reported/);
    expect(at({}, 'reconnecting')).toMatch(/interrupted — reconnecting/);
  });

  it('formats elapsed time and labels states from backend values only', () => {
    expect(formatElapsed(2300)).toBe('2.3 s');
    expect(formatElapsed(42_000)).toBe('42 s');
    expect(formatElapsed(125_000)).toBe('2 min 5 s');
    const running = step('website', 'Website', 'website', { status: 'running', startedAt: iso(1) });
    expect(stepElapsedMs(running, T0 + 5000)).toBe(4000);
    expect(stepElapsedMs({ ...running, startedAt: undefined }, T0)).toBeUndefined();
    expect(stepElapsedMs(step('jobs', 'Jobs', 'jobs'), T0)).toBeUndefined(); // pending: nothing to show
    expect(stepStateLabel(step('jobs', 'Jobs', 'jobs', { status: 'cancelled' }))).toBe('Stopped');
  });

  it('respects reduced motion: a running source is marked but not spun, and pending sources never animate', () => {
    const s = apply(start(), ev('step.started', 1, { stepId: 's-registry', sourceName: 'Enhetsregisteret' }));
    const { unmount } = render(view(s));
    expect(row('registry').querySelector('.sact-icon')).toHaveClass('is-spinning');
    expect(row('accounts').querySelector('.sact-icon')).not.toHaveClass('is-spinning');
    unmount();
    usePreferences.setState({ motion: 'reduced' });
    render(view(s));
    expect(within(row('registry')).getByText('Running')).toBeInTheDocument(); // still shown in words
    expect(row('registry').querySelector('.sact-icon')).not.toHaveClass('is-spinning');
  });

  it('plan rows show what a running step is doing and the reason for skipped or stopped steps', () => {
    render(
      <ol>
        <StepRow step={step('website', 'Company website', 'website', { status: 'running', detail: 'Reading autobjorn.no' })} />
        <StepRow step={step('jobs', 'Careers', 'jobs', { status: 'skipped', message: 'Not reached: the research time limit was reached.' })} />
        <StepRow step={step('extract', 'Read pages', 'website', { status: 'cancelled', message: 'Stopped: research was cancelled before this source finished.' })} />
      </ol>,
    );
    expect(screen.getByText('Reading autobjorn.no')).toBeInTheDocument();
    expect(screen.getByText('Not reached: the research time limit was reached.')).toBeInTheDocument();
    expect(screen.getByText('Stopped: research was cancelled before this source finished.')).toBeInTheDocument();
  });
});

/* ------------------------------------------------- the research screen, live -- */
describe('Research screen: the panel follows the stream', () => {
  it('updates source by source as events arrive and shows the cancelled state without leaving anything running', async () => {
    let handlers: StreamHandlers<ResearchEvent> | undefined;
    vi.spyOn(api.research, 'stream').mockImplementation((_id, h) => {
      handlers = h;
      return () => undefined;
    });
    const startSpy = vi.spyOn(api.research, 'start');
    renderWithProviders(<ResearchPage />, { route: '/research' });
    fireEvent.change(screen.getByLabelText('Company'), { target: { value: 'Nordvik' } });
    fireEvent.click(await screen.findByRole('option', { name: /Nordvik Helseteknologi AS/ }));
    fireEvent.click(screen.getByRole('button', { name: /Start research/ }));
    await waitFor(() => expect(startSpy).toHaveBeenCalledTimes(1));
    const run = await startSpy.mock.results[0].value;
    const ids = run.plan.steps.map((x: ResearchStep) => x.id as string);
    await screen.findByTestId('source-activity');
    await waitFor(() => expect(handlers).toBeDefined());

    const panel = () => screen.getByTestId('source-activity');
    const send = (e: ResearchEvent) => act(() => handlers!.onEvent(e));
    const mk = (n: number, type: ResearchEvent['type'], extra: object): ResearchEvent => ({ type, seq: n, runId: run.id, at: new Date(Date.now() + n * 1000).toISOString(), ...extra }) as ResearchEvent;

    expect(within(panel()).getAllByText('Pending')).toHaveLength(ids.length); // no events yet: nothing is "active"
    expect(within(panel()).queryByText('Running')).not.toBeInTheDocument();

    send(mk(1, 'run.started', {}));
    send(mk(2, 'step.started', { stepId: ids[0], sourceName: 'Enhetsregisteret' }));
    send(mk(3, 'step.progress', { stepId: ids[0], message: 'Looking up the organisation number' }));
    expect(within(panel()).getByText('Running')).toBeInTheDocument();
    expect(within(panel()).getAllByText('Looking up the organisation number').length).toBeGreaterThan(0);
    expect(within(panel()).getAllByText('Pending')).toHaveLength(ids.length - 1);

    send(mk(4, 'step.completed', { stepId: ids[0], sourceName: 'Enhetsregisteret', factCount: 3, evidenceCount: 3, durationMs: 1200, outcome: 'verified' }));
    send(mk(5, 'step.started', { stepId: ids[1], sourceName: 'Regnskapsregisteret' }));
    send(mk(6, 'step.failed', { stepId: ids[1], sourceName: 'Regnskapsregisteret', message: 'The source did not respond (timeout).', retryable: false }));
    expect(within(panel()).getByText('Succeeded')).toBeInTheDocument();
    expect(within(panel()).getByText('Failed')).toBeInTheDocument();
    expect(within(panel()).getByText('The source did not respond (timeout).')).toBeInTheDocument();
    expect(within(panel()).queryByText('Running')).not.toBeInTheDocument();

    send(mk(7, 'step.started', { stepId: ids[2], sourceName: 'Official company website' }));
    expect(within(panel()).getByText('Running')).toBeInTheDocument();
    // The run is cancelled: the running source is stopped, the rest are never started — the backend says so, and the panel shows exactly that.
    send(mk(8, 'step.cancelled', { stepId: ids[2], message: 'Stopped: research was cancelled before this source finished.' }));
    for (const id of ids.slice(3)) send(mk(9 + ids.indexOf(id), 'step.skipped', { stepId: id, message: 'Not started: research was cancelled.' }));
    send(mk(30, 'run.failed', { message: 'Research cancelled. Nothing from this run was saved.', cancelled: true }));

    expect(within(panel()).queryByText('Running')).not.toBeInTheDocument();
    expect(within(panel()).queryByText('Pending')).not.toBeInTheDocument();
    expect(within(panel()).getByText('Stopped')).toBeInTheDocument();
    expect(screen.getByTestId('source-activity-state')).toHaveTextContent('Cancelled — running sources were stopped');
    expect(screen.getByText('Research cancelled', { selector: '.eyebrow' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /Research complete/ })).not.toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------ history -- */
const snap = (over: Partial<ResearchRunSnapshot>): ResearchRunSnapshot => ({
  id: 'run-x',
  mode: 'quick',
  prompt: null,
  status: 'completed',
  startedAt: '2026-10-12T10:00:00Z',
  finishedAt: '2026-10-12T10:00:40Z',
  versionId: 'v3',
  versionNumber: 3,
  hasReport: true,
  isLatestReport: false,
  evidenceChanged: true,
  summary: { coverage: { complete: 5, total: 5, areas: [] }, factsVerified: 41, sourcesVerified: 6 },
  effort: null,
  steps: [],
  issues: [],
  ...over,
});

const runs: ResearchRunSnapshot[] = [
  snap({ id: 'run-5', mode: 'quick', isLatestReport: true, versionId: 'v5', versionNumber: 5, evidenceChanged: false, startedAt: '2026-10-12T12:00:00Z' }),
  snap({ id: 'run-4', mode: 'deep', prompt: 'Which contracts were announced recently?', status: 'partial', versionId: 'v4', versionNumber: 4, issues: ['2 of 5 areas verified — not verified: Company website, Hiring & public activity.', '1 source could not be reached.'], summary: { coverage: { complete: 2, total: 5, areas: [] }, factsVerified: 20, sourcesVerified: 3 }, startedAt: '2026-10-12T11:00:00Z', effort: { mode: 'deep', requests: 31, llmCalls: 3, pagesRead: 8, workflows: [{ key: 'filings', label: 'Filed annual reports', status: 'ran', detail: '4 filed annual reports listed.' }, { key: 'press', label: 'Press coverage search', status: 'skipped', detail: 'News coverage search is not configured (TAVILY_API_KEY missing).' }], crosscheck: { checked: 20, corroborated: 6, singleSource: 13, conflicts: 1, conflictFacts: [{ field: 'employees', label: 'Employees', candidates: [{ source: 'Enhetsregisteret', value: '120' }, { source: 'Company website', value: '150' }] }] } } }),
  snap({ id: 'run-3', mode: 'deep', status: 'failed', hasReport: false, versionId: null, versionNumber: null, evidenceChanged: null, summary: null, issues: ['The company register did not respond.'], startedAt: '2026-10-12T10:30:00Z' }),
  snap({ id: 'run-2', mode: 'quick', status: 'cancelled', hasReport: false, versionId: null, versionNumber: null, evidenceChanged: null, summary: null, issues: ['Research cancelled. Nothing from this run was saved.'], startedAt: '2026-10-12T10:15:00Z' }),
  snap({ id: 'run-1', mode: 'quick', versionId: 'v1', versionNumber: 1, startedAt: '2026-10-11T09:00:00Z' }),
];

const renderHistory = (viewing?: string) =>
  render(
    <MemoryRouter>
      <RunHistory runs={runs} artifactId="art-1" viewingVersionId={viewing} />
    </MemoryRouter>,
  );

describe('Library run history', () => {
  it('lists every run with mode, focus, time and status, and marks exactly one as the latest report', () => {
    renderHistory();
    expect(screen.getAllByRole('listitem').filter((li) => li.getAttribute('data-testid')?.startsWith('run-')).map((li) => li.getAttribute('data-testid'))).toEqual(['run-run-5', 'run-run-4', 'run-run-3', 'run-run-2', 'run-run-1']);
    expect(screen.getAllByText('Latest report')).toHaveLength(1);
    const latest = screen.getByTestId('run-run-5');
    expect(within(latest).getByText('Latest report')).toBeInTheDocument();
    expect(within(latest).getByText('Quick research')).toBeInTheDocument();
    expect(within(latest).getByText(/Company brief/)).toBeInTheDocument();
    expect(within(latest).getByText('Found the same facts as the run before it.')).toBeInTheDocument();
    const deep = screen.getByTestId('run-run-4');
    expect(within(deep).getByText('Deep research')).toBeInTheDocument();
    expect(within(deep).getByText('Which contracts were announced recently?')).toBeInTheDocument();
    expect(within(deep).getByText('Earlier run')).toBeInTheDocument();
    expect(within(deep).getByText(/2 of 5 areas verified · 20 facts · 3 sources/)).toBeInTheDocument();
    expect(focusOf({ prompt: 'research this company' })).toBe('Company brief');
  });

  it('never labels a partial, failed or cancelled run as completed, and says why', () => {
    renderHistory();
    const partial = screen.getByTestId('run-run-4');
    expect(within(partial).getByText('Partial')).toBeInTheDocument();
    expect(within(partial).queryByText('Completed')).not.toBeInTheDocument();
    expect(screen.getByTestId('run-issues-run-4')).toHaveTextContent('not verified: Company website, Hiring & public activity');
    expect(screen.getByTestId('run-issues-run-4')).toHaveTextContent('1 source could not be reached.');
    const failed = screen.getByTestId('run-run-3');
    expect(within(failed).getByText('Failed')).toBeInTheDocument();
    expect(within(failed).getByText('No report saved')).toBeInTheDocument();
    expect(within(failed).queryByRole('link')).not.toBeInTheDocument(); // there is no report to open
    expect(screen.getByTestId('run-issues-run-3')).toHaveTextContent('The company register did not respond.');
    const cancelled = screen.getByTestId('run-run-2');
    expect(within(cancelled).getByText('Cancelled')).toBeInTheDocument();
    expect(within(cancelled).getByText('No report saved')).toBeInTheDocument();
    expect(within(screen.getByTestId('run-run-1')).getByText('Completed')).toBeInTheDocument();
    expect(screen.getAllByText('Completed')).toHaveLength(2); // only the two clean runs
  });

  it('lets an earlier run\'s report be opened without replacing the latest one', () => {
    renderHistory('v4');
    expect(within(screen.getByTestId('run-run-5')).getByRole('link', { name: 'Open latest report' })).toHaveAttribute('href', '/library/art-1');
    const earlier = within(screen.getByTestId('run-run-1')).getByRole('link', { name: /View this run’s report \(v1\)/ });
    expect(earlier).toHaveAttribute('href', '/library/art-1?version=v1');
    const viewing = within(screen.getByTestId('run-run-4')).getByRole('link', { name: 'Viewing this report' });
    expect(viewing).toHaveAttribute('aria-current', 'true');
    expect(screen.getByText(/This page shows the latest report/)).toBeInTheDocument();
  });

  it('shows what a Deep run did and what it skipped, without implying it found more', () => {
    renderHistory();
    const effort = within(screen.getByTestId('run-run-4')).getByTestId('effort-summary');
    expect(effort).toHaveTextContent('Deep · 8 website pages read · 31 requests · 3 AI calls');
    expect(within(effort).getByTestId('effort-filings')).toHaveAttribute('data-status', 'ran');
    expect(within(effort).getByTestId('effort-press')).toHaveTextContent('TAVILY_API_KEY missing');
    expect(within(effort).getByTestId('effort-press')).toHaveAttribute('data-status', 'skipped');
    expect(within(effort).getByTestId('effort-crosscheck')).toHaveTextContent('6 of 20 published facts are confirmed by two or more independent sources · 13 rest on a single source · 1 disagreement');
    expect(effort).toHaveTextContent('Employees: 120 (Enhetsregisteret) vs 150 (Company website)');
    expect(effort).toHaveTextContent('A deeper run is not guaranteed to find more facts');
  });

  it('explains itself when a company has no recorded runs yet', () => {
    render(
      <MemoryRouter>
        <RunHistory runs={[]} artifactId="art-1" />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Run history starts with the next research run/)).toBeInTheDocument();
  });

  it('appears on the company dossier next to the version history', async () => {
    // jsdom has no IntersectionObserver (the dossier uses one for its section nav).
    vi.stubGlobal('IntersectionObserver', class { observe() {} unobserve() {} disconnect() {} takeRecords() { return []; } });
    const art = await mockApi.library.get('art-921604337');
    vi.spyOn(api.library, 'get').mockResolvedValue({ ...(art as object), runs } as never);
    renderWithProviders(
      <Routes>
        <Route path="/library/:artifactId" element={<ArtifactPage />} />
      </Routes>,
      { route: '/library/art-921604337' },
    );
    const history = await screen.findByTestId('run-history', undefined, { timeout: 5000 });
    expect(within(history).getByText('Research runs')).toBeInTheDocument();
    expect(within(history).getAllByRole('listitem').filter((li) => li.getAttribute('data-testid')?.startsWith('run-'))).toHaveLength(5);
    expect(screen.getByText('Research history')).toBeInTheDocument(); // the version list is still there
  });
});
