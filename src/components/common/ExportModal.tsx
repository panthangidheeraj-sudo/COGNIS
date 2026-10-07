import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import { api } from '@/api';
import type { ExportFormat, ExportOptions, ExportRequest } from '@/types';
import { useUi } from '@/stores/ui';
import { Modal } from './Overlay';

const LABEL: Record<ExportFormat, string> = { csv: 'CSV', xlsx: 'Excel (XLSX)', json: 'JSON', pdf: 'PDF report' };

/** Export UI for backend-provided exports. Only formats the backend supports are offered. */
export function ExportModal({ open, onClose, target, title }: { open: boolean; onClose: () => void; target: ExportRequest['target']; title: string }) {
  const { data: status } = useQuery({ queryKey: ['status'], queryFn: api.system.status });
  const formats = status?.capabilities.exports ?? [];
  const [format, setFormat] = useState<ExportFormat>('csv');
  const [opts, setOpts] = useState<ExportOptions>({ sourceLinks: true, evidence: true, retrievalDates: true, reportingPeriods: true, changes: true });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useUi((s) => s.toast);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.exports.request({ target, format, options: opts });
      if (res.status !== 'ready' || !res.url) {
        setError(res.message ?? 'The export could not be created.');
        return;
      }
      const a = document.createElement('a');
      a.href = res.url;
      a.download = res.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      toast({ tone: 'ok', text: `Export ready · ${res.filename}` });
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const opt = (k: keyof ExportOptions, label: string) => (
    <label className="checkbox">
      <input type="checkbox" checked={opts[k]} onChange={(e) => setOpts((o) => ({ ...o, [k]: e.target.checked }))} />
      {label}
    </label>
  );
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Export · ${title}`}
      footer={
        <>
          <button className="btn btn--ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn--primary" onClick={run} disabled={busy || !formats.length}>
            <Download aria-hidden /> {busy ? 'Preparing…' : 'Export'}
          </button>
        </>
      }
    >
      <div className="stack" style={{ gap: 18 }}>
        <fieldset className="stack" style={{ gap: 8, border: 0, padding: 0, margin: 0 }}>
          <legend className="field-label" style={{ marginBottom: 8 }}>
            Format
          </legend>
          <div className="row-wrap">
            {formats.map((f) => (
              <button key={f} className="chip" aria-pressed={format === f} onClick={() => setFormat(f)}>
                {LABEL[f]}
              </button>
            ))}
          </div>
          {status && !formats.includes('pdf') && <span className="t-xs t-muted">PDF and XLSX are offered when the backend supports them.</span>}
        </fieldset>
        <fieldset className="stack" style={{ gap: 2, border: 0, padding: 0, margin: 0 }}>
          <legend className="field-label" style={{ marginBottom: 8 }}>
            Include
          </legend>
          {opt('sourceLinks', 'Source links')}
          {opt('evidence', 'Evidence excerpts')}
          {opt('retrievalDates', 'Retrieval dates')}
          {opt('reportingPeriods', 'Reporting periods')}
          {opt('changes', 'Changes')}
        </fieldset>
        <p className="t-xs t-muted">The backend generates every export from saved evidence. Nothing is added by the browser.</p>
        {error && <div className="notice notice--err">{error}</div>}
      </div>
    </Modal>
  );
}
