import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { LoaderCircle, Plus, Sparkle, Table2, X } from 'lucide-react';
import { api } from '@/api';
import type { InterpretedFilter, QueryInterpretation } from '@/types';
import { Skeleton } from '@/components/common/Skeleton';
import { EmptyState } from '@/components/common/EmptyState';
import { ErrorState } from '@/components/common/ErrorState';
import { ArtifactThumb } from '@/components/library/ArtifactThumb';
import { formatRelative } from '@/utils/format';
import '../Library/library.css';
import './sheets.css';

const EXAMPLES = [
  'Build a sheet of Norwegian technology companies in Oslo with over 100 employees and current hiring.',
  'Healthcare companies with revenue above 50M NOK',
  'Logistics companies in Trondheim',
];

export default function SheetsIndexPage() {
  const [params, setParams] = useSearchParams();
  const creating = params.get('new') === '1';
  const list = useQuery({ queryKey: ['sheets'], queryFn: api.sheets.list });
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Data Sheets</h1>
          <p>Multi-company research tables with AI columns. Every cell carries its own source and evidence.</p>
        </div>
        <div className="page-actions">
          {!creating && (
            <button className="btn btn--primary" onClick={() => setParams({ new: '1' })}>
              <Plus aria-hidden /> New sheet
            </button>
          )}
        </div>
      </div>
      {creating && <SheetCreator onClose={() => setParams({})} />}
      {list.isError ? (
        <ErrorState error={list.error} onRetry={() => list.refetch()} />
      ) : list.isLoading ? (
        <div className="lib-grid">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} h={220} r={12} />
          ))}
        </div>
      ) : !list.data?.length ? (
        <EmptyState title="No data sheets yet." text="Describe the companies you want and Cognis builds the sheet." />
      ) : (
        <div className="lib-grid">
          {list.data.map((s) => (
            <article key={s.id} className="lib-card">
              <Link to={`/sheets/${s.id}`} className="co-card-link" aria-label={`Open ${s.title}`} />
              <ArtifactThumb a={{ id: s.id, type: 'data_sheet', title: s.title, updatedAt: s.updatedAt, tags: [], pinned: false, archived: false }} />
              <div className="lib-body">
                <span className="row" style={{ gap: 8 }}>
                  <Table2 width={16} height={16} className="t-accent" aria-hidden />
                  <span className="t-micro">Data sheet</span>
                </span>
                <h3 className="lib-title truncate">{s.title}</h3>
                <span className="t-xs t-muted">
                  {s.rowCount} companies · {s.columnCount} columns · updated {formatRelative(s.updatedAt)}
                </span>
                {s.criteria && s.criteria.length > 0 && (
                  <div className="row-wrap" style={{ gap: 4 }}>
                    {s.criteria.map((c) => (
                      <span key={c.key} className="pill pill--sm">
                        {c.display}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function SheetCreator({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState('');
  const [interp, setInterp] = useState<QueryInterpretation | null>(null);
  const [criteria, setCriteria] = useState<InterpretedFilter[]>([]);
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState<false | 'interpret' | 'create'>(false);
  const [error, setError] = useState<unknown>(null);
  const nav = useNavigate();
  const qc = useQueryClient();
  const interpret = async (t = text) => {
    if (!t.trim()) return;
    setBusy('interpret');
    setError(null);
    try {
      const r = await api.sheets.interpret(t);
      setInterp(r);
      setCriteria(r.filters);
      setTitle(
        t
          .replace(/^build (a|me a) sheet of\s*/i, '')
          .replace(/\.$/, '')
          .replace(/^\w/, (c) => c.toUpperCase())
          .slice(0, 60),
      );
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const create = async () => {
    setBusy('create');
    try {
      const s = await api.sheets.create({ title: title.trim() || 'Untitled sheet', criteria, text });
      qc.invalidateQueries({ queryKey: ['sheets'] });
      qc.invalidateQueries({ queryKey: ['library'] });
      nav(`/sheets/${s.id}`);
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };
  return (
    <section className="creator surface" aria-labelledby="creator-h">
      <div className="row">
        <h2 id="creator-h" className="t-h3">
          <Sparkle width={16} height={16} className="t-accent" aria-hidden style={{ display: 'inline', marginRight: 8 }} />
          Describe the sheet you need
        </h2>
        <span className="spacer" />
        <button className="btn btn--ghost btn--icon btn--sm" onClick={onClose} aria-label="Close">
          <X aria-hidden />
        </button>
      </div>
      <textarea className="textarea" rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder="Build a sheet of Norwegian technology companies in Oslo with over 100 employees and current hiring." aria-label="Sheet description" autoFocus />
      <div className="row-wrap" style={{ gap: 6 }}>
        {EXAMPLES.map((e) => (
          <button key={e} className="chip" style={{ height: 28, fontSize: 12.5 }} onClick={() => (setText(e), void interpret(e))}>
            {e}
          </button>
        ))}
      </div>
      {!interp && (
        <div>
          <button className="btn btn--primary" onClick={() => void interpret()} disabled={!text.trim() || !!busy}>
            {busy === 'interpret' ? <LoaderCircle className="spin" aria-hidden /> : <Sparkle aria-hidden />} Interpret
          </button>
        </div>
      )}
      {interp && (
        <div className="creator-interp anim-fade-up">
          <span className="t-micro">Interpreted criteria</span>
          {criteria.length === 0 ? (
            <p className="t-sm t-muted">No structured criteria found. The sheet will start from a keyword match — consider adding a location or industry.</p>
          ) : (
            <dl className="creator-criteria">
              {criteria.map((c) => (
                <div key={c.key}>
                  <dt>{c.label}</dt>
                  <dd>
                    {c.display}
                    <button className="chip-x" onClick={() => setCriteria((cs) => cs.filter((x) => x.key !== c.key))} aria-label={`Remove ${c.label}`}>
                      <X width={12} height={12} aria-hidden />
                    </button>
                  </dd>
                </div>
              ))}
            </dl>
          )}
          {interp.notes?.map((n) => (
            <p key={n} className="t-xs t-muted">
              {n}
            </p>
          ))}
          <div className="field">
            <label htmlFor="sheet-title">Sheet title</label>
            <input id="sheet-title" className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="row-wrap">
            <button className="btn" onClick={() => setInterp(null)}>
              Edit description
            </button>
            <button className="btn btn--primary" onClick={() => void create()} disabled={busy === 'create'}>
              {busy === 'create' ? <LoaderCircle className="spin" aria-hidden /> : <Table2 aria-hidden />} Create sheet
            </button>
          </div>
          <p className="t-xs t-muted">The backend selects matching companies. Columns that need research start as “Pending” until you run research.</p>
        </div>
      )}
      {error != null && <ErrorState error={error} compact />}
    </section>
  );
}
