/**
 * The Export dialog offers three things: the Full Research Report (PDF), Research Data (the original structured export, CSV by default) and
 * Evidence & Sources (CSV / JSON). It offers only what the backend can produce, keeps the CSV request exactly as before, and shows the backend's
 * own explanation when an export fails.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { renderWithProviders } from './utils';
import { mockApi } from '@/data/mock/mockApi';
import { ExportModal } from '@/components/common/ExportModal';
import type { ExportRequest, SystemStatus } from '@/types';

const COMPANY: ExportRequest['target'] = { type: 'company', id: '921604337' };

async function liveLikeStatus(over: Partial<SystemStatus['capabilities']> = {}) {
  const base = await mockApi.system.status();
  return {
    ...base,
    mode: 'live' as const,
    capabilities: { ...base.capabilities, exports: ['csv', 'xlsx', 'json', 'pdf'], exportKinds: ['data', 'report', 'evidence'], pdfReports: true, ...over },
  } as SystemStatus;
}

let request: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  request = vi.spyOn(mockApi.exports, 'request').mockResolvedValue({ status: 'ready', filename: 'x.pdf', url: 'blob:test' });
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
});
afterEach(() => {
  vi.restoreAllMocks();
});

async function open(target: ExportRequest['target'] = COMPANY, status?: SystemStatus) {
  if (status) vi.spyOn(mockApi.system, 'status').mockResolvedValue(status);
  renderWithProviders(<ExportModal open onClose={() => undefined} target={target} title="Equinor ASA" />);
  const dialog = await screen.findByRole('dialog');
  await waitFor(() => expect(within(dialog).getByRole('button', { name: /^export$/i })).toBeEnabled());
  return dialog;
}
const exportButton = (dialog: HTMLElement) => within(dialog).getByRole('button', { name: /^export$/i });

describe('Export menu', () => {
  it('offers the three exports for a company, with the Full Research Report first', async () => {
    const dialog = await open(COMPANY, await liveLikeStatus());
    const radios = within(dialog).getAllByRole('radio');
    expect(radios).toHaveLength(3);
    expect(within(dialog).getByRole('radio', { name: /Full Research Report/ })).toBeChecked();
    expect(within(dialog).getByRole('radio', { name: /Research Data/ })).not.toBeChecked();
    expect(within(dialog).getByRole('radio', { name: /Evidence & Sources/ })).not.toBeChecked();
    expect(within(dialog).getByText('PDF')).toBeInTheDocument();
  });

  it('requests the PDF report for the saved research of the company', async () => {
    const dialog = await open(COMPANY, await liveLikeStatus());
    fireEvent.click(exportButton(dialog));
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    expect(request.mock.calls[0][0]).toMatchObject({ target: COMPANY, kind: 'report', format: 'pdf' });
  });

  it('keeps the existing CSV export: Research Data defaults to CSV with every include option on', async () => {
    const dialog = await open(COMPANY, await liveLikeStatus());
    fireEvent.click(within(dialog).getByRole('radio', { name: /Research Data/ }));
    const formats = within(dialog).getByRole('group', { name: /Research Data format/ });
    expect(within(formats).getAllByRole('button').map((b) => b.textContent)).toEqual(['CSV', 'Excel (XLSX)', 'JSON']);
    expect(within(formats).getByRole('button', { name: 'CSV' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(exportButton(dialog));
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    expect(request.mock.calls[0][0]).toEqual({
      target: COMPANY,
      kind: 'data',
      format: 'csv',
      options: { sourceLinks: true, evidence: true, retrievalDates: true, reportingPeriods: true, changes: true },
    });
  });

  it('passes the include options chosen for Research Data', async () => {
    const dialog = await open(COMPANY, await liveLikeStatus());
    fireEvent.click(within(dialog).getByRole('radio', { name: /Research Data/ }));
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Evidence excerpts' }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'JSON' }));
    fireEvent.click(exportButton(dialog));
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    expect(request.mock.calls[0][0]).toMatchObject({ kind: 'data', format: 'json', options: { evidence: false, sourceLinks: true } });
  });

  it('requests Evidence & Sources as CSV or JSON, always in full', async () => {
    const dialog = await open(COMPANY, await liveLikeStatus());
    fireEvent.click(within(dialog).getByRole('radio', { name: /Evidence & Sources/ }));
    const formats = within(dialog).getByRole('group', { name: /Evidence & Sources format/ });
    expect(within(formats).getAllByRole('button').map((b) => b.textContent)).toEqual(['CSV', 'JSON']);
    expect(within(dialog).queryByRole('checkbox')).not.toBeInTheDocument(); // nothing to switch off: the evidence export is always complete
    fireEvent.click(within(formats).getByRole('button', { name: 'JSON' }));
    fireEvent.click(exportButton(dialog));
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    expect(request.mock.calls[0][0]).toMatchObject({ target: COMPANY, kind: 'evidence', format: 'json', options: { evidence: true, sourceLinks: true } });
  });

  it('works for a saved research artifact target too', async () => {
    const dialog = await open({ type: 'artifact', id: 'art-921604337' }, await liveLikeStatus());
    expect(within(dialog).getAllByRole('radio')).toHaveLength(3);
    fireEvent.click(exportButton(dialog));
    await waitFor(() => expect(request.mock.calls[0][0]).toMatchObject({ target: { type: 'artifact', id: 'art-921604337' }, kind: 'report', format: 'pdf' }));
  });
});

describe('Export menu — what the backend cannot do', () => {
  it('disables the report when PDF reports are unavailable, says why, and falls back to Research Data', async () => {
    const dialog = await open(COMPANY, await liveLikeStatus({ exports: ['csv', 'json'], exportKinds: ['data', 'evidence'], pdfReports: false }));
    const report = within(dialog).getByRole('radio', { name: /Full Research Report/ });
    expect(report).toBeDisabled();
    expect(within(dialog).getByText(/PDF reports are not available from this backend yet/)).toBeInTheDocument();
    expect(within(dialog).getByRole('radio', { name: /Research Data/ })).toBeChecked();
    fireEvent.click(exportButton(dialog));
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    expect(request.mock.calls[0][0]).toMatchObject({ kind: 'data', format: 'csv' });
  });

  it('treats an older backend (no exportKinds) as data-only, plus the report when it reports pdfReports', async () => {
    const dialog = await open(COMPANY, await liveLikeStatus({ exportKinds: undefined, pdfReports: false, exports: ['csv', 'xlsx', 'json'] }));
    expect(within(dialog).getByRole('radio', { name: /Full Research Report/ })).toBeDisabled();
    expect(within(dialog).getByRole('radio', { name: /Evidence & Sources/ })).toBeDisabled();
    expect(within(dialog).getByRole('radio', { name: /Research Data/ })).toBeChecked();
  });

  it('offers only Research Data for a data sheet or a comparison', async () => {
    const dialog = await open({ type: 'sheet', id: 'sheet-1' }, await liveLikeStatus());
    expect(within(dialog).getAllByRole('radio')).toHaveLength(1);
    expect(within(dialog).getByRole('radio', { name: /Research Data/ })).toBeChecked();
    expect(within(dialog).queryByRole('radio', { name: /Full Research Report/ })).not.toBeInTheDocument();
  });

  it("shows the backend's own message when an export fails, and does not download anything", async () => {
    request.mockResolvedValue({ status: 'failed', filename: '', message: 'No saved research exists for this company yet, so there is nothing to export.' });
    const dialog = await open(COMPANY, await liveLikeStatus());
    fireEvent.click(exportButton(dialog));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('No saved research exists for this company yet');
    expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
  });

  it('downloads the file the backend prepared', async () => {
    request.mockResolvedValue({ status: 'ready', filename: 'COGNIS-Research-Report-EQUINOR-921604337.pdf', url: '/api/exports/exp-1/download' });
    const dialog = await open(COMPANY, await liveLikeStatus());
    fireEvent.click(exportButton(dialog));
    await waitFor(() => expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1));
  });
});

describe('Demo backend', () => {
  it('explains that the demo backend cannot make a PDF and still serves the evidence export', async () => {
    request.mockRestore(); // use the demo backend's real implementation here
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:demo' }));
    const pdf = await mockApi.exports.request({ target: COMPANY, kind: 'report', format: 'pdf', options: { sourceLinks: true, evidence: true, retrievalDates: true, reportingPeriods: true, changes: true } });
    expect(pdf.status).toBe('failed');
    expect(pdf.message).toMatch(/live backend/);
    const status = await mockApi.system.status();
    expect(status.capabilities.pdfReports).toBe(false);
    expect(status.capabilities.exportKinds).toEqual(['data', 'evidence']);
    const evidence = await mockApi.exports.request({ target: COMPANY, kind: 'evidence', format: 'csv', options: { sourceLinks: true, evidence: true, retrievalDates: true, reportingPeriods: true, changes: true } });
    expect(evidence).toMatchObject({ status: 'ready', filename: 'cognis-evidence-921604337.csv' });
  });
});
