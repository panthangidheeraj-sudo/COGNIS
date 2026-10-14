/**
 * Online/offline status: "Backend offline" only when the backend really cannot be reached.
 *
 * Regression: a missing optional Python package (ReportLab) made GET /status answer 500, and the app showed "Backend offline" although the backend
 * was running. A failed status report is now checked against the liveness endpoint first, and a PDF export that is turned off says why.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from './utils';
import { StatusCenter } from '@/components/navigation/StatusCenter';
import { ExportModal } from '@/components/common/ExportModal';
import { api } from '@/api';
import { ApiError } from '@/api/http';
import { mockApi } from '@/data/mock/mockApi';

const SLOW = { timeout: 6000 }; // the status query retries once before it reports an error
const PDF_NOTE =
  "PDF reports are turned off: the Python package 'reportlab' is not installed in this backend environment. Run `python -m pip install -r requirements.txt` in the backend folder (with its virtual environment active) and restart the backend.";

afterEach(() => vi.restoreAllMocks());

describe('the status indicator', () => {
  it('says the backend is running when only its status report fails', async () => {
    vi.spyOn(api.system, 'status').mockRejectedValue(new ApiError('unavailable', 'Something went wrong on the server. Please try again.', 500));
    const health = vi.spyOn(api.system, 'health').mockResolvedValue({ status: 'ok', version: '1.0.0' });
    renderWithProviders(<StatusCenter />);
    const button = await screen.findByRole('button', { name: 'System status: Status check failed' }, SLOW);
    expect(health).toHaveBeenCalled();
    expect(screen.queryByText('Backend offline')).not.toBeInTheDocument();
    fireEvent.click(button);
    expect(await screen.findByTestId('status-check-failed')).toHaveTextContent(/The backend is running \(version 1\.0\.0\), but its status report failed/);
  });

  it('says offline only when the backend cannot be reached at all', async () => {
    vi.spyOn(api.system, 'status').mockRejectedValue(new ApiError('network', 'The COGNIS backend could not be reached.'));
    vi.spyOn(api.system, 'health').mockRejectedValue(new ApiError('network', 'The COGNIS backend could not be reached.'));
    renderWithProviders(<StatusCenter />);
    expect(await screen.findByRole('button', { name: 'System status: Backend offline' }, SLOW)).toBeInTheDocument();
  });

  it('a healthy backend is "Connected" even with PDF reports turned off, and the reason is shown', async () => {
    const status = await mockApi.system.status();
    vi.spyOn(api.system, 'status').mockResolvedValue({ ...status, mode: 'live', backend: 'connected', capabilities: { ...status.capabilities, pdfReports: false, pdfReportsNote: PDF_NOTE } });
    const health = vi.spyOn(api.system, 'health');
    renderWithProviders(<StatusCenter />);
    fireEvent.click(await screen.findByRole('button', { name: 'System status: Connected' }, SLOW));
    expect(await screen.findByText(PDF_NOTE)).toBeInTheDocument();
    expect(health).not.toHaveBeenCalled(); // nothing failed: no liveness probe
  });
});

describe('the export menu', () => {
  it('tells why the Full Research Report is unavailable instead of a generic message', async () => {
    const status = await mockApi.system.status();
    vi.spyOn(api.system, 'status').mockResolvedValue({ ...status, capabilities: { ...status.capabilities, pdfReports: false, exportKinds: ['data', 'evidence'], pdfReportsNote: PDF_NOTE } });
    renderWithProviders(<ExportModal open onClose={() => undefined} target={{ type: 'company', id: '810359862' }} title="AUTOBJØRN A/S" />);
    await waitFor(() => expect(screen.getByText(PDF_NOTE)).toBeInTheDocument(), SLOW);
  });
});
