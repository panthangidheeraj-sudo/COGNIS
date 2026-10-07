import { useState } from 'react';
import { FileText } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '@/api';
import type { ReportKind, ReportSection } from '@/types';
import { useUi } from '@/stores/ui';
import { Modal } from '@/components/common/Overlay';

const SECTIONS: { id: ReportSection; label: string }[] = [
  { id: 'summary', label: 'Executive summary' },
  { id: 'financials', label: 'Financials' },
  { id: 'people', label: 'People' },
  { id: 'locations', label: 'Locations' },
  { id: 'hiring', label: 'Hiring' },
  { id: 'activity', label: 'Recent activity' },
  { id: 'sources', label: 'Sources' },
];

export function ReportModal({ open, onClose, orgNumber, name }: { open: boolean; onClose: () => void; orgNumber: string; name: string }) {
  const [kind, setKind] = useState<ReportKind>('company_brief');
  const [sections, setSections] = useState<ReportSection[]>(SECTIONS.map((s) => s.id));
  const [busy, setBusy] = useState(false);
  const toast = useUi((s) => s.toast);
  const qc = useQueryClient();
  const run = async () => {
    setBusy(true);
    try {
      const a = await api.library.generateReport({ orgNumber, kind, sections });
      qc.invalidateQueries({ queryKey: ['library'] });
      toast({ tone: 'ok', text: 'Report generated', action: { label: 'Open', href: `/library/${a.id}` } });
      onClose();
    } catch (e) {
      toast({ tone: 'err', text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Company report · ${name}`}
      footer={
        <>
          <button className="btn btn--ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn--primary" onClick={run} disabled={busy || !sections.length}>
            <FileText aria-hidden /> {busy ? 'Generating…' : 'Generate report'}
          </button>
        </>
      }
    >
      <div className="stack" style={{ gap: 18 }}>
        <div className="row-wrap" role="group" aria-label="Report type">
          <button className="chip" aria-pressed={kind === 'company_brief'} onClick={() => setKind('company_brief')}>
            Company brief
          </button>
          <button className="chip" aria-pressed={kind === 'deep_report'} onClick={() => setKind('deep_report')}>
            Deep research report
          </button>
        </div>
        <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="field-label" style={{ marginBottom: 8 }}>
            Sections
          </legend>
          {SECTIONS.map((s) => (
            <label key={s.id} className="checkbox" style={{ width: '100%' }}>
              <input type="checkbox" checked={sections.includes(s.id)} onChange={(e) => setSections((xs) => (e.target.checked ? [...xs, s.id] : xs.filter((x) => x !== s.id)))} />
              {s.label}
            </label>
          ))}
        </fieldset>
        <p className="t-xs t-muted">Reports are built from the saved research and its evidence. They are added to your Library.</p>
      </div>
    </Modal>
  );
}
