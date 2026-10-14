/** Company selection: typed text is only a search term. Research starts for a company the user selected or confirmed — never for a guess. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { renderWithProviders } from './utils';
import ResearchPage from '@/pages/Research/ResearchPage';
import { CompletionSummary } from '@/components/research/CompletionSummary';
import { api } from '@/api';
import { mockApi } from '@/data/mock/mockApi';
import { classifyCompanyInput } from '@/utils/format';
import { researchOutcome } from '@/utils/status';
import type { Coverage, ResearchRun } from '@/types';

const NORDVIK = { orgNumber: '921604337', legalName: 'Nordvik Helseteknologi AS' };
const POLARLYS = { orgNumber: '925116702', legalName: 'Polarlys Medtech AS' };

afterEach(() => vi.restoreAllMocks());

const startSpy = () => vi.spyOn(api.research, 'start');
const field = () => screen.getByLabelText('Company') as HTMLInputElement;
const startButton = () => screen.getByRole('button', { name: /Start research/ });
const type = (text: string) => fireEvent.change(field(), { target: { value: text } });
const suggestion = (name: RegExp) => screen.findByRole('option', { name });

describe('typing a company name without choosing a suggestion', () => {
  it('does not research anything for "abc" — it asks for a registry company instead', async () => {
    const start = startSpy();
    renderWithProviders(<ResearchPage />, { route: '/research' });
    type('abc');
    fireEvent.click(startButton());
    expect(await screen.findByRole('alert')).toHaveTextContent(/No registered company matched “abc”/);
    expect(start).not.toHaveBeenCalled();
    expect(screen.queryByText('Confirmed company', { exact: false })).not.toBeInTheDocument();
  });

  it('does not pick the only match either: a company is researched only after it is selected', async () => {
    const start = startSpy();
    renderWithProviders(<ResearchPage />, { route: '/research' });
    type('Nordvik Helseteknologi AS'); // an exact, unique name is still just text
    await suggestion(/Nordvik Helseteknologi AS/);
    fireEvent.click(startButton());
    expect(await screen.findByRole('alert')).toHaveTextContent(/Select the company you mean from the list/);
    expect(start).not.toHaveBeenCalled();
    fireEvent.keyDown(field(), { key: 'Enter' });
    await screen.findByRole('alert');
    expect(start).not.toHaveBeenCalled();
  });

  it('the backend contract matches: a typed name returns candidates to confirm, never a started run', async () => {
    const run = await mockApi.research.start({ query: NORDVIK.legalName, mode: 'quick' });
    expect(run.status).toBe('ambiguous');
    expect(run.company).toBeUndefined();
    expect(run.ambiguity?.candidates.map((c) => c.orgNumber)).toEqual([NORDVIK.orgNumber]);
  });
});

describe('selecting a suggestion', () => {
  it('shows the confirmed legal name and organization number, then starts research for exactly that company', async () => {
    const start = startSpy();
    renderWithProviders(<ResearchPage />, { route: '/research' });
    type('Nordvik');
    fireEvent.click(await suggestion(/Nordvik Helseteknologi AS/));
    expect(screen.getByText(NORDVIK.legalName)).toBeInTheDocument();
    expect(screen.getByText('921 604 337')).toBeInTheDocument();
    expect(screen.getByText(/Confirmed company/)).toBeInTheDocument();
    expect(start).not.toHaveBeenCalled(); // choosing is not starting
    fireEvent.click(startButton());
    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
    expect(start.mock.calls[0][0]).toMatchObject({ orgNumber: NORDVIK.orgNumber, expectedName: NORDVIK.legalName });
  });

  it('keeps keyboard selection working: arrow down from the field reaches the list, arrows move, Escape returns', async () => {
    renderWithProviders(<ResearchPage />, { route: '/research' });
    type('a');
    type('as');
    await screen.findAllByRole('option');
    fireEvent.keyDown(field(), { key: 'ArrowDown' });
    const options = screen.getAllByRole('option');
    expect(options[0]).toHaveFocus();
    if (options.length > 1) {
      fireEvent.keyDown(options[0], { key: 'ArrowDown' });
      expect(options[1]).toHaveFocus();
    }
    fireEvent.keyDown(options[0], { key: 'Escape' });
    expect(field()).toHaveFocus();
  });
});

describe('changing the field after a selection', () => {
  it('drops the earlier selection: the wrong company can no longer be researched once the text is edited', async () => {
    const start = startSpy();
    renderWithProviders(<ResearchPage />, { route: '/research' });
    type('Nordvik');
    fireEvent.click(await suggestion(/Nordvik Helseteknologi AS/)); // wrong company picked
    fireEvent.click(screen.getByRole('button', { name: 'Change company' }));
    expect(screen.queryByText(/Confirmed company/)).not.toBeInTheDocument(); // the earlier selection is gone
    expect(field()).toHaveFocus();
    type('Polarlys'); // edit the field
    fireEvent.click(startButton()); // not selected yet
    expect(await screen.findByRole('alert')).toHaveTextContent(/Select the company you mean/);
    expect(start).not.toHaveBeenCalled();

    fireEvent.click(await suggestion(/Polarlys Medtech AS/));
    expect(screen.getByText(POLARLYS.legalName)).toBeInTheDocument();
    fireEvent.click(startButton());
    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
    expect(start.mock.calls[0][0]).toMatchObject({ orgNumber: POLARLYS.orgNumber, expectedName: POLARLYS.legalName });
  });
});

describe('entering an organization number directly', () => {
  it('looks the number up, shows the registered name and waits for confirmation before researching', async () => {
    const start = startSpy();
    renderWithProviders(<ResearchPage />, { route: '/research' });
    type('921 604 337');
    fireEvent.click(startButton());
    expect(await screen.findByText(NORDVIK.legalName)).toBeInTheDocument();
    expect(screen.getByText('921 604 337')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(/then press Start research to confirm/);
    expect(start).not.toHaveBeenCalled();
    fireEvent.click(startButton());
    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
    expect(start.mock.calls[0][0]).toMatchObject({ orgNumber: NORDVIK.orgNumber, expectedName: NORDVIK.legalName });
  });

  it('rejects a malformed number without contacting the registry or starting research', async () => {
    const start = startSpy();
    const lookup = vi.spyOn(api.search, 'global');
    renderWithProviders(<ResearchPage />, { route: '/research' });
    type('12345');
    lookup.mockClear();
    fireEvent.click(startButton());
    expect(await screen.findByRole('alert')).toHaveTextContent(/9 digits/);
    expect(lookup).not.toHaveBeenCalled();
    expect(start).not.toHaveBeenCalled();
  });

  it('says so when the registry has no company with that number', async () => {
    const start = startSpy();
    renderWithProviders(<ResearchPage />, { route: '/research' });
    type('999 999 999');
    fireEvent.click(startButton());
    expect(await screen.findByRole('alert')).toHaveTextContent(/No company with organization number 999 999 999/);
    expect(start).not.toHaveBeenCalled();
  });

  it('classifies field text: names are search terms, digits are an organization number that must have 9 digits', () => {
    expect(classifyCompanyInput('  ')).toEqual({ kind: 'empty' });
    expect(classifyCompanyInput('abc')).toEqual({ kind: 'name', text: 'abc' });
    expect(classifyCompanyInput('916 664 974')).toEqual({ kind: 'org', digits: '916664974', valid: true });
    expect(classifyCompanyInput('9166')).toEqual({ kind: 'org', digits: '9166', valid: false });
  });
});

describe('the identity check on a selected company', () => {
  it('refuses to start when the registered name is not the name that was confirmed', async () => {
    await expect(mockApi.research.start({ orgNumber: NORDVIK.orgNumber, expectedName: POLARLYS.legalName, query: POLARLYS.legalName, mode: 'quick' })).rejects.toMatchObject({ code: 'ambiguous' });
    const ok = await mockApi.research.start({ orgNumber: NORDVIK.orgNumber, expectedName: NORDVIK.legalName, query: NORDVIK.legalName, mode: 'quick' });
    expect(ok.company?.orgNumber).toBe(NORDVIK.orgNumber);
  });
});

describe('completion messaging', () => {
  const area = (a: Coverage['areas'][number]['area'], status: Coverage['areas'][number]['status'], note?: string) => ({ area: a, status, factCount: status === 'complete' ? 3 : 0, note });
  const run = (coverage: Coverage, summary: Partial<NonNullable<ResearchRun['summary']>> = {}): ResearchRun => ({
    id: 'r1',
    query: 'x',
    mode: 'quick',
    status: 'completed',
    company: { ...NORDVIK, country: 'Norway', status: 'active', coverage, researchState: 'researched' },
    plan: { steps: [], requiresConfirmation: false } as unknown as ResearchRun['plan'],
    startedAt: '2026-10-12T10:00:00Z',
    capabilities: { pause: false, cancel: false, retryFailed: false, editPlan: false },
    autoSaved: false,
    coverage,
    summary: { coverage, ...summary },
  });

  it('says "Research complete" only when every area was verified and no source was unreachable', () => {
    const full: Coverage = { complete: 5, total: 5, areas: (['company_record', 'financials', 'people_locations', 'website', 'hiring_activity'] as const).map((a) => area(a, 'complete')) };
    renderWithProviders(<CompletionSummary run={run(full)} />);
    expect(screen.getByRole('heading', { name: /Research complete/ })).toBeInTheDocument();
    expect(screen.queryByTestId('coverage-gaps')).not.toBeInTheDocument();
    expect(researchOutcome(run(full)).complete).toBe(true);
  });

  it('shows coverage and every unavailable area instead of "complete" when something could not be verified', () => {
    const partial: Coverage = {
      complete: 3,
      total: 5,
      areas: [area('company_record', 'complete'), area('financials', 'complete'), area('people_locations', 'complete'), area('website', 'blocked', 'robots.txt does not allow access'), area('hiring_activity', 'unavailable', 'Hiring data unavailable')],
    };
    renderWithProviders(<CompletionSummary run={run(partial, { blockedSources: 1, failedSources: 1 })} />);
    expect(screen.getByRole('heading', { name: /Research finished/ })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /Research complete/ })).not.toBeInTheDocument();
    const gaps = screen.getByTestId('coverage-gaps');
    expect(gaps).toHaveTextContent('3 of 5 areas verified');
    expect(within(gaps).getByText(/Company website: Blocked — robots.txt does not allow access/)).toBeInTheDocument();
    expect(within(gaps).getByText(/Hiring & public activity: Unavailable — Hiring data unavailable/)).toBeInTheDocument();
    expect(gaps).toHaveTextContent('2 sources could not be reached');
  });

  it('does not claim completeness when the backend reported no coverage', () => {
    const r = run({ complete: 0, total: 0, areas: [] });
    delete r.coverage;
    delete r.summary;
    renderWithProviders(<CompletionSummary run={r} />);
    expect(screen.getByRole('heading', { name: /Research finished/ })).toBeInTheDocument();
    expect(screen.getByTestId('coverage-gaps')).toHaveTextContent('Coverage was not reported');
  });
});
