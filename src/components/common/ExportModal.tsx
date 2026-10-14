import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Download, FileSpreadsheet, FileText, ScrollText } from 'lucide-react';
import { api } from '@/api';
import type { ExportFormat, ExportKind, ExportOptions, ExportRequest } from '@/types';
import { useUi } from '@/stores/ui';
import { cn } from '@/utils/cn';
import { Modal } from './Overlay';

const FORMAT_LABEL: Record<ExportFormat, string> = { csv: 'CSV', xlsx: 'Excel (XLSX)', json: 'JSON', pdf: 'PDF' };
const ALL_ON: ExportOptions = { sourceLinks: true, evidence: true, retrievalDates: true, reportingPeriods: true, changes: true };

const KINDS: Record<ExportKind, { title: string; badge: string; Icon: typeof FileText; blurb: string; detail: string }> = {
  report: {
    title: 'Full Research Report',
    badge: 'PDF',
    Icon: FileText,
    blurb: 'A polished, multi-page report: identity, executive summary, financials, people, locations, digital presence, hiring, activity, changes, coverage and every source.',
    detail: 'Includes a cover page, table of contents, page numbers and the full evidence register. Built from the saved research only — gaps are stated, never filled.',
  },
  data: {
    title: 'Research Data',
    badge: 'CSV',
    Icon: FileSpreadsheet,
    blurb: 'The structured facts as a spreadsheet: one row per fact, with its value, status and period.',
    detail: 'Choose what each row carries.',
  },
  evidence: {
    title: 'Evidence & Sources',
    badge: 'CSV / JSON',
    Icon: ScrollText,
    blurb: 'Every fact with its source URL, evidence excerpt, verification status, retrieval timestamps and reporting period.',
    detail: 'Always complete; also lists the information that could not be established.',
  },
};

/** A target that is one company's saved research (the report and the evidence export need exactly that). */
function isSingleCompany(target: ExportRequest['target']) {
  return target.type === 'company' || (target.type === 'artifact' && !target.id.startsWith('sheet-'));
}

/**
 * Export UI for backend-provided exports. Offers only what the backend can produce:
 * Full Research Report (PDF) · Research Data (CSV / XLSX / JSON) · Evidence & Sources (CSV / JSON).
 * Sheets and comparisons offer Research Data only — the report and the evidence export belong to one company.
 */
export function ExportModal({ open, onClose, target, title }: { open: boolean; onClose: () => void; target: ExportRequest['target']; title: string }) {
  const { data: status } = useQuery({ queryKey: ['status'], queryFn: api.system.status });
  const caps = status?.capabilities;
  const dataFormats: ExportFormat[] = (caps?.exports ?? []).filter((f) => f !== 'pdf');
  const single = isSingleCompany(target);
  const kinds: ExportKind[] = single ? ['report', 'data', 'evidence'] : ['data'];

  const supported: Record<ExportKind, boolean> = {
    report: !!(caps?.exportKinds ? caps.exportKinds.includes('report') : caps?.pdfReports),
    data: dataFormats.length > 0,
    evidence: !!caps?.exportKinds?.includes('evidence'),
  };
  const unsupportedNote: Record<ExportKind, string> = {
    report: caps?.pdfReportsNote ?? 'PDF reports are not available from this backend yet.',
    data: 'No data formats are available from this backend.',
    evidence: 'The evidence export is not available from this backend yet.',
  };

  const [picked, setPicked] = useState<ExportKind | null>(null);
  const kind: ExportKind = picked && kinds.includes(picked) && supported[picked] ? picked : (kinds.find((k) => supported[k]) ?? kinds[0]);
  const [dataFormat, setDataFormat] = useState<ExportFormat>('csv');
  const [evidenceFormat, setEvidenceFormat] = useState<'csv' | 'json'>('csv');
  const [opts, setOpts] = useState<ExportOptions>(ALL_ON);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useUi((s) => s.toast);

  const effectiveDataFormat: ExportFormat = dataFormats.includes(dataFormat) ? dataFormat : (dataFormats[0] ?? 'csv');
  const format: ExportFormat = kind === 'report' ? 'pdf' : kind === 'evidence' ? evidenceFormat : effectiveDataFormat;

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.exports.request({ target, kind, format, options: kind === 'data' ? opts : ALL_ON });
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
  const formatChips = (list: ExportFormat[], current: ExportFormat, set: (f: ExportFormat) => void, label: string) => (
    <div className="row-wrap" role="group" aria-label={label}>
      {list.map((f) => (
        <button key={f} type="button" className="chip" aria-pressed={current === f} onClick={() => set(f)}>
          {FORMAT_LABEL[f]}
        </button>
      ))}
    </div>
  );

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Export · ${title}`}
      wide
      footer={
        <>
          <button className="btn btn--ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn--primary" onClick={run} disabled={busy || !status || !supported[kind]}>
            <Download aria-hidden /> {busy ? 'Preparing…' : 'Export'}
          </button>
        </>
      }
    >
      <div className="stack" style={{ gap: 16 }}>
        <div className="export-options" role="radiogroup" aria-label="What to export">
          {kinds.map((k) => {
            const meta = KINDS[k];
            const selected = kind === k;
            const disabled = !!status && !supported[k];
            return (
              <label key={k} className={cn('export-option', selected && 'is-selected', disabled && 'is-disabled')}>
                <input type="radio" name="export-kind" value={k} checked={selected} disabled={disabled} onChange={() => setPicked(k)} />
                <span className="export-option__body">
                  <span className="export-option__head">
                    <meta.Icon aria-hidden width={16} height={16} />
                    <span>{meta.title}</span>
                    <span className="export-option__badge">{meta.badge}</span>
                  </span>
                  <span className="t-sm t-muted">{meta.blurb}</span>
                  {disabled && <span className="t-xs t-muted">{unsupportedNote[k]}</span>}
                </span>
              </label>
            );
          })}
        </div>

        {kind === 'report' && <p className="t-xs t-muted">{KINDS.report.detail}</p>}

        {kind === 'data' && (
          <>
            <fieldset className="stack" style={{ gap: 8, border: 0, padding: 0, margin: 0 }}>
              <legend className="field-label" style={{ marginBottom: 8 }}>
                Format
              </legend>
              {formatChips(dataFormats, effectiveDataFormat, setDataFormat, 'Research Data format')}
              {status && !dataFormats.includes('xlsx') && <span className="t-xs t-muted">XLSX is offered when the backend supports it.</span>}
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
          </>
        )}

        {kind === 'evidence' && (
          <fieldset className="stack" style={{ gap: 8, border: 0, padding: 0, margin: 0 }}>
            <legend className="field-label" style={{ marginBottom: 8 }}>
              Format
            </legend>
            {formatChips(['csv', 'json'], evidenceFormat, (f) => setEvidenceFormat(f === 'json' ? 'json' : 'csv'), 'Evidence & Sources format')}
            <span className="t-xs t-muted">{KINDS.evidence.detail}</span>
          </fieldset>
        )}

        <p className="t-xs t-muted">The backend generates every export from saved evidence. Nothing is added by the browser.</p>
        {error && (
          <div className="notice notice--err" role="alert">
            {error}
          </div>
        )}
      </div>
    </Modal>
  );
}
