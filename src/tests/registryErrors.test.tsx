/**
 * "Company search in Enhetsregisteret is unavailable right now" used to hide why. Now the Data Sheets creator shows the real cause, offers Retry only
 * when trying again can help, lets the user continue from companies COGNIS has already verified (their explicit choice, never automatic), and a sheet
 * built that way says so on the sheet itself.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes, useLocation } from 'react-router-dom';
import { renderWithProviders } from './utils';
import { mockApi } from '@/data/mock/mockApi';
import { ApiError } from '@/api/http';
import { failureDetails, failureFacts } from '@/api/errorDetails';
import { liveSheets } from '@/api/sheets';
import { ErrorState } from '@/components/common/ErrorState';
import SheetsIndexPage from '@/pages/DataSheets/SheetsIndexPage';
import SheetPage from '@/pages/DataSheets/SheetPage';

const SLOW = { timeout: 6000 };
const TEXT = 'Logistics companies in Trondheim';

beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function Where() {
  const l = useLocation();
  return <output data-testid="where">{l.pathname + l.search}</output>;
}
const routes = (
  <>
    <Routes>
      <Route path="/sheets" element={<SheetsIndexPage />} />
      <Route path="/sheets/:sheetId" element={<SheetPage />} />
    </Routes>
    <Where />
  </>
);
const where = () => screen.getByTestId('where').textContent;

/** What the backend sends when the register search fails (details are the contract in API_CONTRACT.md). */
function registryError(over: Record<string, unknown> = {}, message = 'Company search in Enhetsregisteret failed. Enhetsregisteret reported a server-side error (HTTP 503) on 4 attempts. This is usually temporary; retry in a moment.') {
  return new ApiError('unavailable', message, 503, {
    source: 'enhetsregisteret',
    reason: 'server_error',
    cause: 'Enhetsregisteret reported a server-side error (HTTP 503) on 4 attempts. This is usually temporary; retry in a moment.',
    httpStatus: 503,
    attempts: 4,
    retryable: true,
    elapsedMs: 2100,
    fallback: { available: false, count: 0, kind: 'verified_companies', note: 'COGNIS has not verified any companies yet, so there is nothing to fall back to.' },
    ...over,
  });
}

async function startCreating() {
  renderWithProviders(routes, { route: '/sheets?new=1' });
  fireEvent.change(await screen.findByLabelText('Sheet description'), { target: { value: TEXT } });
  fireEvent.click(screen.getByRole('button', { name: /Interpret/ }));
  return screen.findByRole('button', { name: /Create sheet/ }, SLOW);
}

describe('the error panel', () => {
  it('shows the cause, the register status and the attempts instead of a generic message', () => {
    renderWithProviders(<ErrorState error={registryError()} onRetry={() => undefined} />);
    const alert = screen.getByRole('alert');
    expect(within(alert).getByText('Company search in Enhetsregisteret failed')).toBeInTheDocument();
    expect(within(alert).getByText(/reported a server-side error \(HTTP 503\) on 4 attempts/)).toBeInTheDocument();
    expect(screen.getByTestId('error-facts')).toHaveTextContent('Server error · HTTP 503 · 4 attempts');
    expect(within(alert).queryByText(/unavailable right now/i)).not.toBeInTheDocument();
    expect(within(alert).getByRole('button', { name: /Retry/ })).toBeInTheDocument();
  });

  it('offers no Retry when the same request cannot succeed, and says what to change', () => {
    const rejected = registryError(
      { reason: 'client_error', httpStatus: 400, attempts: 1, retryable: false, detail: 'Invalid value for parameter fraAntallAnsatte', cause: 'Enhetsregisteret rejected the search request (HTTP 400).' },
      'Company search in Enhetsregisteret failed. Enhetsregisteret rejected the search request (HTTP 400).',
    );
    renderWithProviders(<ErrorState error={rejected} onRetry={() => undefined} />);
    expect(screen.queryByRole('button', { name: /Retry/ })).not.toBeInTheDocument();
    expect(screen.getByText(/adjust the filters/i)).toBeInTheDocument();
    expect(screen.getByTestId('error-facts')).toHaveTextContent('Request rejected · HTTP 400 · 1 attempt · Invalid value for parameter fraAntallAnsatte');
  });

  it('leaves every other error exactly as before', () => {
    const onRetry = vi.fn();
    renderWithProviders(<ErrorState error={new ApiError('unavailable', 'The company register did not respond.', 503)} onRetry={onRetry} />);
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    expect(screen.getByText('The company register did not respond.')).toBeInTheDocument();
    expect(screen.queryByTestId('error-facts')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Retry/ }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('reads failure details only from an ApiError that carries them', () => {
    expect(failureDetails(new Error('boom'))).toBeNull();
    expect(failureDetails(new ApiError('unavailable', 'x', 503))).toBeNull();
    expect(failureDetails(new ApiError('unavailable', 'x', 503, { unrelated: true }))).toBeNull();
    expect(failureDetails(registryError())?.reason).toBe('server_error');
    expect(failureFacts({ reason: 'timeout', attempts: 4 })).toBe('Timed out · 4 attempts');
    expect(failureFacts({ reason: 'something_new' })).toBe('something_new');
  });
});

describe('creating a sheet while the register search is down', () => {
  it('shows the underlying cause with a Retry that repeats the create and, on success, opens the sheet', async () => {
    const create = vi.spyOn(mockApi.sheets, 'create').mockRejectedValueOnce(registryError());
    fireEvent.click(await startCreating());
    const alert = await screen.findByRole('alert', undefined, SLOW);
    expect(within(alert).getByText(/HTTP 503\) on 4 attempts/)).toBeInTheDocument();
    expect(where()).toBe('/sheets?new=1'); // nothing was created, nothing navigated
    fireEvent.click(within(alert).getByRole('button', { name: /Retry/ }));
    await waitFor(() => expect(where()).toMatch(/^\/sheets\/sheet-new-/), SLOW);
    expect(create).toHaveBeenCalledTimes(2);
    expect(create.mock.calls[1][0]).not.toHaveProperty('fallback'); // Retry asks the register again; it never silently switches source
  });

  it('never uses the verified companies unasked: the first request carries no fallback and the offer waits for a click', async () => {
    const offer = { available: true, count: 3, kind: 'verified_companies', note: '3 companies COGNIS has already verified match the selected filters.' };
    const create = vi.spyOn(mockApi.sheets, 'create').mockRejectedValueOnce(registryError({ fallback: offer }));
    fireEvent.click(await startCreating());
    const panel = await screen.findByTestId('verified-fallback', undefined, SLOW);
    expect(create).toHaveBeenCalledTimes(1);
    expect(create.mock.calls[0][0]).not.toHaveProperty('fallback');
    expect(within(panel).getByText(/3 companies COGNIS has already verified match/)).toBeInTheDocument();
    expect(within(panel).getByText(/not a full register search/)).toBeInTheDocument();
    expect(where()).toBe('/sheets?new=1');
  });

  it('continues from the verified companies only when the user chooses to', async () => {
    const offer = { available: true, count: 3, kind: 'verified_companies', note: '3 companies COGNIS has already verified match the selected filters.' };
    const create = vi.spyOn(mockApi.sheets, 'create').mockRejectedValueOnce(registryError({ fallback: offer }));
    fireEvent.click(await startCreating());
    fireEvent.click(await screen.findByRole('button', { name: 'Use 3 verified companies instead' }, SLOW));
    await waitFor(() => expect(where()).toMatch(/^\/sheets\/sheet-new-/), SLOW);
    expect(create).toHaveBeenCalledTimes(2);
    expect(create.mock.calls[1][0]).toMatchObject({ fallback: 'verified' });
  });

  it('offers nothing to fall back to when nothing is stored, and says so', async () => {
    vi.spyOn(mockApi.sheets, 'create').mockRejectedValueOnce(registryError());
    fireEvent.click(await startCreating());
    await screen.findByRole('alert', undefined, SLOW);
    expect(screen.queryByRole('button', { name: /verified (company|companies) instead/ })).not.toBeInTheDocument();
    expect(screen.getByText(/has not verified any companies yet/)).toBeInTheDocument();
  });

  it('retries the interpretation, not the create, when the interpretation is what failed', async () => {
    const interpret = vi.spyOn(mockApi.sheets, 'interpret').mockRejectedValueOnce(new ApiError('network', 'The COGNIS backend could not be reached.'));
    const create = vi.spyOn(mockApi.sheets, 'create');
    renderWithProviders(routes, { route: '/sheets?new=1' });
    fireEvent.change(await screen.findByLabelText('Sheet description'), { target: { value: TEXT } });
    fireEvent.click(screen.getByRole('button', { name: /Interpret/ }));
    fireEvent.click(await screen.findByRole('button', { name: /Retry/ }, SLOW));
    await screen.findByRole('button', { name: /Create sheet/ }, SLOW);
    expect(interpret).toHaveBeenCalledTimes(2);
    expect(create).not.toHaveBeenCalled();
  });
});

describe('a sheet built from verified companies says so', () => {
  const discovery = {
    kind: 'verified_companies' as const,
    registryAvailable: false as const,
    reason: 'server_error',
    cause: 'Enhetsregisteret reported a server-side error (HTTP 503) on 4 attempts.',
    at: '2026-10-12T08:15:00Z',
    count: 2,
    note: 'The Enhetsregisteret search was unavailable, so this list contains only the 2 companies COGNIS had already verified that match the selected filters. It is not a full register search.',
  };

  it('shows a note with the cause on the sheet page', async () => {
    const [first] = await mockApi.sheets.list();
    const real = await mockApi.sheets.get(first.id);
    vi.spyOn(mockApi.sheets, 'get').mockResolvedValue({ ...real, discovery });
    renderWithProviders(routes, { route: `/sheets/${first.id}` });
    const note = await screen.findByTestId('sheet-discovery-note', undefined, SLOW);
    expect(note).toHaveTextContent('Built from companies COGNIS had already verified');
    expect(note).toHaveTextContent('It is not a full register search.');
    expect(note).toHaveTextContent('HTTP 503');
  });

  it('shows no note on an ordinary sheet', async () => {
    const [first] = await mockApi.sheets.list();
    renderWithProviders(routes, { route: `/sheets/${first.id}` });
    await screen.findByRole('toolbar', { name: 'Sheet tools' }, SLOW);
    expect(screen.queryByTestId('sheet-discovery-note')).not.toBeInTheDocument();
  });

  it('marks the sheet in the listing', async () => {
    const list = await mockApi.sheets.list();
    vi.spyOn(mockApi.sheets, 'list').mockResolvedValue(list.map((s, i) => (i === 0 ? { ...s, discovery } : s)));
    renderWithProviders(routes, { route: '/sheets' });
    await screen.findAllByRole('link', { name: /^Open /i }, SLOW);
    expect(screen.getAllByText('Verified companies only')).toHaveLength(1);
  });
});

describe('the live API client', () => {
  it('sends the explicit fallback choice and keeps the backend’s failure details on the error', async () => {
    const body = { code: 'unavailable', message: 'Company search in Enhetsregisteret failed. x', details: { source: 'enhetsregisteret', reason: 'timeout', cause: 'x', attempts: 4, retryable: true } };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 503, headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    const err = await liveSheets.create({ title: 'T', criteria: [], text: 'x', fallback: 'verified' }).catch((e: unknown) => e);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toMatchObject({ fallback: 'verified', title: 'T' });
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(503);
    expect(failureDetails(err)).toMatchObject({ reason: 'timeout', attempts: 4, retryable: true });
  });
});
