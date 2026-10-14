/**
 * Discover: missing card figures are looked up (and said to be missing for a reason), and the company landscape never draws a blank chart.
 *
 * "Not available" used to mean only "the search pipeline did not verify this" while reading as "this does not exist". Cards now show a verified
 * value, "Checking…", or why there is none — never an invented number and never "0 openings" from missing results.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { renderWithProviders } from './utils';
import DiscoverPage from '@/pages/Discover/DiscoverPage';
import { api } from '@/api';
import { usePreferences } from '@/stores/preferences';
import { clearEnrichmentCache, ENRICH_BATCH, missingFigures, withVerifiedFigures } from '@/hooks/useDiscoverEnrichment';
import { figureView } from '@/components/company/CompanyFigure';
import { landscapeData } from '@/components/charts/landscapeData';
import type { CompanyEnrichment, CompanySummary, DiscoverResult, EnrichedFigure, EnrichmentResult } from '@/types';

const SLOW = { timeout: 6000 };

function company(org: string, name: string, over: Partial<CompanySummary> = {}): CompanySummary {
  return {
    orgNumber: org,
    legalName: name,
    municipality: 'Oslo',
    country: 'Norway',
    status: 'active',
    employees: null,
    revenue: null,
    openPositions: null,
    coverage: { complete: 1, total: 5, areas: [] },
    researchState: 'not_researched',
    ...over,
  };
}
const verified = (value: number, extra: Partial<EnrichedFigure> = {}): EnrichedFigure => ({ state: 'verified', note: 'Verified.', sources: [{ name: 'Regnskapsregisteret', state: 'checked' }], value, ...extra });
const said = (state: EnrichedFigure['state'], note: string): EnrichedFigure => ({ state, note, sources: [] });

const A = company('810359862', 'AUTOBJØRN A/S');
const B = company('810034882', 'SANDNES ELEKTRISKE AS', { employees: 11 });
const R = company('923609016', 'RESEARCHED ASA', { researchState: 'researched', revenue: { value: 5e9, currency: 'NOK', period: 'FY2025' }, employees: 900, openPositions: 0, openPositionsStatus: 'none_found' });

const LOOKUPS: Record<string, CompanyEnrichment['fields']> = {
  [A.orgNumber]: {
    revenue: verified(21_789_260, { currency: 'NOK', period: 'FY2025' }),
    employees: verified(12, { sources: [{ name: 'Enhetsregisteret', state: 'checked' }] }),
    openPositions: verified(2, { lowerBound: true, note: '2 verified current openings (Company careers page). Not every job source could be checked, so there may be more.' }),
  },
  [B.orgNumber]: {
    revenue: said('not_reported', 'No annual accounts are filed for this company. This is not a revenue of zero.'),
    openPositions: said('none_found', 'No verified openings in NAV Arbeidsplassen. This does not mean the company is not hiring.'),
  },
};

function answer(orgs: string[], fields?: string[]): EnrichmentResult {
  return {
    enabled: true,
    checkedAt: '2026-10-14T12:00:00Z',
    items: orgs.map((org) => ({
      orgNumber: org,
      checkedAt: '2026-10-14T12:00:00Z',
      fields: Object.fromEntries(Object.entries(LOOKUPS[org] ?? {}).filter(([f]) => !fields || fields.includes(f))),
    })),
  };
}

function discoverReturns(items: CompanySummary[]) {
  return vi.spyOn(api.companies, 'discover').mockResolvedValue({ items, total: items.length, page: 1, pageSize: 24, appliedFilters: {} } as DiscoverResult);
}
function renderDiscover() {
  return renderWithProviders(
    <Routes>
      <Route path="/discover" element={<DiscoverPage />} />
    </Routes>,
    { route: '/discover' },
  );
}

beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null); // no globe drawing in jsdom
  clearEnrichmentCache();
  usePreferences.setState({ discoverView: 'cards' });
});
afterEach(() => vi.restoreAllMocks());

/* --------------------------------------------------------------------------------------------------- what a figure shows -- */
describe('a figure without a verified value says why', () => {
  it('shows verified looked-up values, with the period and a lower bound marked', () => {
    const e = { orgNumber: A.orgNumber, checkedAt: '', fields: LOOKUPS[A.orgNumber] };
    expect(figureView('revenue', A, e)).toMatchObject({ value: 'NOK 21.8M', detail: 'FY2025' });
    expect(figureView('employees', A, e).value).toBe('12');
    expect(figureView('openPositions', A, e).value).toBe('2+'); // "at least two": not every job source could be checked
  });

  it('never shows a bare "Not available"', () => {
    const e = { orgNumber: B.orgNumber, checkedAt: '', fields: LOOKUPS[B.orgNumber] };
    expect(figureView('revenue', B, e)).toMatchObject({ label: 'Not reported', note: expect.stringContaining('not a revenue of zero') });
    expect(figureView('openPositions', B, e)).toMatchObject({ label: 'None verified', note: expect.stringContaining('does not mean the company is not hiring') });
    expect(figureView('openPositions', B, undefined, true)).toMatchObject({ label: 'Checking…', checking: true });
    expect(figureView('openPositions', B).label).toBe('Not checked');
    expect(figureView('revenue', company('1', 'X', { researchState: 'researched' })).label).toBe('Not verified');
    expect(figureView('employees', A, { orgNumber: A.orgNumber, checkedAt: '', fields: { employees: said('not_reported', 'No count registered.') } }).label).toBe('Not registered');
    expect(figureView('revenue', B, { orgNumber: B.orgNumber, checkedAt: '', fields: { revenue: said('unavailable', 'Regnskapsregisteret could not be read.') } }).label).toBe('Source unavailable');
  });

  it('a researched company whose hiring research found nothing shows "None verified", not "0"', () => {
    expect(figureView('openPositions', R)).toMatchObject({ label: 'None verified' });
    expect(figureView('openPositions', { ...R, openPositions: 3, openPositionsStatus: 'verified' }).value).toBe('3');
  });

  it('asks only for the figures a card is missing, and never for researched companies', () => {
    expect(missingFigures(A)).toEqual(['revenue', 'employees', 'openPositions']);
    expect(missingFigures(B)).toEqual(['revenue', 'openPositions']);
    expect(missingFigures(R)).toEqual([]);
  });

  it('fills only verified values into a summary; everything else stays empty', () => {
    const merged = withVerifiedFigures(B, { orgNumber: B.orgNumber, checkedAt: '', fields: LOOKUPS[B.orgNumber] });
    expect(merged.revenue).toBeNull();
    expect(merged.openPositions).toBeNull();
  });
});

/* ------------------------------------------------------------------------------------------------------ the cards view -- */
describe('Discover cards look up their missing figures', () => {
  it('shows "Checking…" at once, then the verified values and the reasons', async () => {
    discoverReturns([A, B, R]);
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const enrich = vi.spyOn(api.companies, 'enrich').mockImplementation(async (orgs, opts) => {
      await gate;
      return answer(orgs, opts?.fields);
    });
    renderDiscover();
    expect((await screen.findAllByText('Checking…', {}, SLOW)).length).toBeGreaterThan(0);
    expect(screen.getByTestId('discover-lookups')).toHaveTextContent(/Looking up missing figures for 2 results/);
    release();
    const card = (name: string) => screen.getByRole('heading', { name }).closest('article')!;
    await waitFor(() => expect(within(card('AUTOBJØRN A/S')).getByText('NOK 21.8M')).toBeInTheDocument(), SLOW);
    expect(within(card('AUTOBJØRN A/S')).getByText('2+')).toBeInTheDocument();
    expect(within(card('SANDNES ELEKTRISKE AS')).getByText('Not reported')).toBeInTheDocument();
    expect(within(card('SANDNES ELEKTRISKE AS')).getByText('None verified')).toBeInTheDocument();
    expect(within(card('RESEARCHED ASA')).getByText('None verified')).toBeInTheDocument(); // research found none: not "0"
    expect(screen.queryByText('Not available')).not.toBeInTheDocument();
    expect(screen.getByTestId('discover-lookups')).toHaveTextContent(/were looked up/);
    // one request, only the two unresearched companies, only the figures they miss
    expect(enrich).toHaveBeenCalledTimes(1);
    expect(enrich.mock.calls[0][0]).toEqual([A.orgNumber, B.orgNumber]);
    expect(enrich.mock.calls[0][1]?.fields?.sort()).toEqual(['employees', 'openPositions', 'revenue']);
  });

  it('a failed lookup is shown as "Source unavailable", never as a value', async () => {
    discoverReturns([A]);
    vi.spyOn(api.companies, 'enrich').mockRejectedValue(new Error('The COGNIS backend could not be reached.'));
    renderDiscover();
    const card = await screen.findByRole('heading', { name: 'AUTOBJØRN A/S' }, SLOW);
    await waitFor(() => expect(within(card.closest('article')!).getAllByText('Source unavailable')).toHaveLength(3), SLOW);
    expect(within(card.closest('article')!).getAllByText(/could not be run/)[0]).toBeInTheDocument();
  });

  it('looks up in small batches, two at a time', async () => {
    const many = Array.from({ length: 14 }, (_, i) => company(String(910000000 + i), `Company ${i}`));
    discoverReturns(many);
    let active = 0;
    let peak = 0;
    const enrich = vi.spyOn(api.companies, 'enrich').mockImplementation(async (orgs, opts) => {
      active++;
      peak = Math.max(peak, active);
      await new Promise((r) => setTimeout(r, 30));
      active--;
      return answer(orgs, opts?.fields);
    });
    renderDiscover();
    await waitFor(() => expect(screen.getByTestId('discover-lookups')).toHaveTextContent(/were looked up/), SLOW);
    expect(enrich).toHaveBeenCalledTimes(Math.ceil(14 / ENRICH_BATCH));
    expect(enrich.mock.calls.every(([orgs]) => orgs.length <= ENRICH_BATCH)).toBe(true);
    expect(peak).toBe(2);
  });

  it('reuses what it already looked up instead of asking again', async () => {
    discoverReturns([A]);
    const enrich = vi.spyOn(api.companies, 'enrich').mockImplementation(async (orgs, opts) => answer(orgs, opts?.fields));
    const first = renderDiscover();
    await screen.findByText('NOK 21.8M', {}, SLOW);
    first.unmount();
    renderDiscover();
    await screen.findByText('NOK 21.8M', {}, SLOW);
    expect(enrich).toHaveBeenCalledTimes(1);
  });
});

/* -------------------------------------------------------------------------------------------------------- the landscape -- */
describe('Company landscape', () => {
  it('plots only verified values above zero: a research "none found" and other currencies are left out', () => {
    const rows = [
      company('1', 'One', { employees: 10, revenue: { value: 1e7, currency: 'NOK', period: 'FY2025' }, openPositions: 3, openPositionsStatus: 'verified' }),
      company('2', 'Two', { employees: 20, revenue: { value: 2e7, currency: 'NOK', period: 'FY2025' }, openPositions: 0, openPositionsStatus: 'none_found' }),
      company('3', 'Three', { employees: 30, revenue: { value: 3e7, currency: 'USD', period: 'FY2025' }, openPositions: 4 }),
    ];
    const d = landscapeData(rows, 'openPositions', 'revenue');
    expect(d.points.map((p) => p.org)).toEqual(['1']);
    expect([d.withX, d.withY, d.otherCurrency, d.currency]).toEqual([2, 2, 1, 'NOK']);
  });

  it('explains what is missing instead of drawing a blank chart, and looks figures up only when asked', async () => {
    usePreferences.setState({ discoverView: 'landscape' });
    const C = company('810324562', 'SERVI AS', { employees: 4 });
    LOOKUPS[C.orgNumber] = { revenue: verified(5_000_000, { currency: 'NOK', period: 'FY2025' }), openPositions: verified(1) };
    discoverReturns([A, B, C]);
    const enrich = vi.spyOn(api.companies, 'enrich').mockImplementation(async (orgs, opts) => answer(orgs, opts?.fields));
    renderDiscover();
    fireEvent.change(await screen.findByRole('combobox', { name: 'X' }, SLOW), { target: { value: 'openPositions' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Y' }), { target: { value: 'revenue' } });
    const empty = await screen.findByTestId('landscape-empty', {}, SLOW);
    expect(empty).toHaveTextContent('Not enough verified values to plot Open positions against Revenue');
    expect(empty).toHaveTextContent('Open positions: verified for 0 of 3 companies');
    expect(empty).toHaveTextContent('Revenue: verified for 0 of 3 companies');
    expect(empty).toHaveTextContent(/Nothing is estimated/);
    expect(enrich).not.toHaveBeenCalled(); // up to 100 companies: the landscape asks first
    fireEvent.click(within(empty).getByRole('button', { name: 'Look up verified figures for 3 companies' }));
    await waitFor(() => expect(screen.queryByTestId('landscape-empty')).not.toBeInTheDocument(), SLOW);
    expect(await screen.findByText(/2 of 3 companies plotted/, {}, SLOW)).toBeInTheDocument(); // A and C now have both verified values; B has none
    expect(enrich).toHaveBeenCalledTimes(1);
  });

  it('says so when the lookups found nothing more', async () => {
    usePreferences.setState({ discoverView: 'landscape' });
    discoverReturns([B]);
    vi.spyOn(api.companies, 'enrich').mockImplementation(async (orgs, opts) => answer(orgs, opts?.fields));
    renderDiscover();
    fireEvent.change(await screen.findByRole('combobox', { name: 'X' }, SLOW), { target: { value: 'openPositions' } });
    const empty = await screen.findByTestId('landscape-empty', {}, SLOW);
    fireEvent.click(within(empty).getByRole('button', { name: /Look up verified figures/ }));
    expect(await screen.findByText('The lookups found no further verified values for these companies.', {}, SLOW)).toBeInTheDocument();
    expect(screen.getByTestId('landscape-empty')).toBeInTheDocument();
  });
});
