/**
 * Quick vs Deep in the browser: the depth the user picks is the mode the API is asked to run, Deep shows its plan before anything starts,
 * and the run report says plainly which optional workflows a Quick run left out (and why). The backend side is proved in backend/tests/test_mode_policies.py.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { renderWithProviders } from './utils';
import ResearchPage from '@/pages/Research/ResearchPage';
import { EffortSummary } from '@/components/research/EffortSummary';
import { api } from '@/api';
import { mockApi } from '@/data/mock/mockApi';
import type { ResearchEffort, ResearchMode, ResearchRun } from '@/types';

afterEach(() => vi.restoreAllMocks());

const depth = () => within(screen.getByRole('group', { name: 'Research depth' }));

async function startResearch(mode: ResearchMode) {
  vi.spyOn(api.research, 'stream').mockImplementation(() => () => undefined); // no live stream is needed to see what was requested
  const start = vi.spyOn(api.research, 'start');
  renderWithProviders(<ResearchPage />, { route: '/research' });
  fireEvent.change(screen.getByLabelText('Company'), { target: { value: 'Nordvik' } });
  fireEvent.click(await screen.findByRole('option', { name: /Nordvik Helseteknologi AS/ }));
  if (mode === 'deep') fireEvent.click(depth().getByRole('button', { name: 'Deep' }));
  fireEvent.click(screen.getByRole('button', { name: /Start research/ }));
  await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
  return { start, run: (await start.mock.results[0].value) as ResearchRun };
}

describe('the depth control reaches the API', () => {
  it('starts in Quick, says Quick starts immediately, and asks the API for a Quick run', async () => {
    renderWithProviders(<ResearchPage />, { route: '/research' });
    expect(depth().getByRole('button', { name: 'Quick' })).toHaveAttribute('aria-pressed', 'true');
    expect(depth().getByRole('button', { name: 'Deep' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByText('Quick research starts immediately with the core sources.')).toBeInTheDocument();
  });

  it('a Quick run is requested with mode "quick" and starts at once', async () => {
    const { start, run } = await startResearch('quick');
    expect(start).toHaveBeenCalledWith(expect.objectContaining({ mode: 'quick' }));
    expect(run.mode).toBe('quick');
    expect(run.plan.requiresConfirmation).toBe(false);
  });

  it('choosing Deep changes the request, the explanation and the plan: Deep shows its plan for review first', async () => {
    const { start, run } = await startResearch('deep');
    expect(start).toHaveBeenCalledWith(expect.objectContaining({ mode: 'deep' }));
    expect(run.mode).toBe('deep');
    expect(run.status).toBe('awaiting_confirmation');
    expect(run.plan.requiresConfirmation).toBe(true);
  });

  it('the mode switch is not just a label: the two plans list different work', async () => {
    const input = { orgNumber: '921604337', query: 'Nordvik Helseteknologi AS' };
    const quick = await mockApi.research.start({ ...input, mode: 'quick' });
    const deep = await mockApi.research.start({ ...input, mode: 'deep' });
    const keys = (r: ResearchRun) => r.plan.steps.map((s) => s.key);
    expect(keys(deep).length).toBeGreaterThan(keys(quick).length);
    expect(keys(quick).every((k) => keys(deep).includes(k))).toBe(true); // Deep does everything Quick does, and more
  });

  it('the hint under the control follows the choice', () => {
    renderWithProviders(<ResearchPage />, { route: '/research' });
    fireEvent.click(depth().getByRole('button', { name: 'Deep' }));
    expect(depth().getByRole('button', { name: 'Deep' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('Deep research shows the plan for review before it starts.')).toBeInTheDocument();
    fireEvent.click(depth().getByRole('button', { name: 'Quick' }));
    expect(screen.getByText('Quick research starts immediately with the core sources.')).toBeInTheDocument();
  });
});

describe('the run report says what Quick left out', () => {
  const budget = { maxRequests: 20, maxSeconds: 60, maxSearches: 1, maxLlmCalls: 1, maxSitePages: 3, followUpRounds: 1, jobPageSearch: false };
  const quick: ResearchEffort = {
    mode: 'quick',
    requests: 11,
    llmCalls: 1,
    pagesRead: 5,
    budget,
    workflows: [
      { key: 'filings', label: 'Filed annual reports', status: 'skipped', detail: 'Quick research reads the latest filed accounts only; the multi-year filing history is a Deep step.' },
      {
        key: 'job_search',
        label: 'Web search for job pages',
        status: 'skipped',
        detail: "Quick research does not search the web for job pages unless the focus is about hiring; the company's own careers pages and NAV were still checked.",
      },
    ],
  };
  const deep: ResearchEffort = {
    ...quick,
    mode: 'deep',
    requests: 16,
    llmCalls: 4,
    pagesRead: 9,
    budget: { ...budget, maxRequests: 30, maxSeconds: 120, maxSearches: 3, maxLlmCalls: 4, maxSitePages: 8, followUpRounds: 3, jobPageSearch: true },
    workflows: [
      { key: 'filings', label: 'Filed annual reports', status: 'ran', detail: 'Filing history listed.' },
      { key: 'job_search', label: 'Web search for job pages', status: 'ran', detail: "0 posting(s) verified as this company's; 0 search result(s) considered." },
    ],
  };

  it('names the mode and lists each skipped workflow as "Not run" with its reason', () => {
    renderWithProviders(<EffortSummary effort={quick} open />);
    expect(screen.getByTestId('effort-summary')).toHaveTextContent(/Quick · 5 website pages read · 11 requests · 1 AI call/);
    const row = screen.getByTestId('effort-job_search');
    expect(row).toHaveAttribute('data-status', 'skipped');
    expect(row).toHaveTextContent('Not run');
    expect(row).toHaveTextContent(/unless the focus is about hiring/);
    expect(screen.getByTestId('effort-filings')).toHaveAttribute('data-status', 'skipped');
  });

  it('a Deep run reports the same workflows as run, and a deeper run is not promised to find more', () => {
    renderWithProviders(<EffortSummary effort={deep} open />);
    expect(screen.getByTestId('effort-summary')).toHaveTextContent(/Deep · 9 website pages read · 16 requests · 4 AI calls/);
    expect(screen.getByTestId('effort-job_search')).toHaveAttribute('data-status', 'ran');
    expect(screen.getByTestId('effort-filings')).toHaveAttribute('data-status', 'ran');
    expect(screen.getByText(/not guaranteed to find more facts/)).toBeInTheDocument();
  });

  it('the budget of a run is part of the report contract and Deep is allowed more of every kind than Quick', () => {
    const b = quick.budget!;
    const d = deep.budget!;
    for (const key of ['maxRequests', 'maxSeconds', 'maxSearches', 'maxLlmCalls', 'maxSitePages', 'followUpRounds'] as const) expect(b[key]).toBeLessThan(d[key]);
    expect([b.jobPageSearch, d.jobPageSearch]).toEqual([false, true]);
  });
});
