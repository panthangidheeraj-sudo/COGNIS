import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Check, Columns3, Download, Eye, EyeOff, Filter, Info, Pencil, Pin, PinOff, Play, Plus, Rows3, Search, Sparkle, Trash2, X } from 'lucide-react';
import { api } from '@/api';
import type { ColumnPreview, ColumnValueType, DataSheetColumn, ValueStatus } from '@/types';
import { useUi } from '@/stores/ui';
import { useDebounce } from '@/hooks/useDebounce';
import { Modal } from '@/components/common/Overlay';
import { ErrorState } from '@/components/common/ErrorState';
import { Skeleton, LoadingRegion } from '@/components/common/Skeleton';
import { ExportModal } from '@/components/common/ExportModal';
import { useCommand } from '@/hooks/useCommand';
import { Popover } from '@/components/common/Popover';
import { SheetGrid, type DisplayItem } from '@/components/sheets/SheetGrid';
import { AmbientGlobe } from '@/components/globe/AmbientGlobe';
import { compareCells, sheetReducer } from '@/components/sheets/sheetState';
import type { MenuItem } from '@/components/common/Menu';
import { formatDate, formatRelative } from '@/utils/format';
import { VALUE_STATUS } from '@/utils/status';
import './sheets.css';

const AI_EXAMPLES = [
  "Find the company's current CEO",
  'Identify whether the company expanded internationally in the last 12 months.',
  'Who chairs the board?',
  'What is the operating margin?',
  'Is the founder verified?',
  'How many offices does the company have?',
];

export default function SheetPage() {
  const { sheetId = '' } = useParams();
  const q = useQuery({ queryKey: ['sheet', sheetId], queryFn: () => api.sheets.get(sheetId), staleTime: 0 });
  const [sheet, dispatch] = useReducer(sheetReducer, null);
  const [flashed, setFlashed] = useState<Set<string>>(new Set());
  const qc = useQueryClient();
  const toast = useUi((s) => s.toast);

  useEffect(() => {
    if (q.data) dispatch({ type: 'load', sheet: q.data });
  }, [q.data]);

  // Live cell updates from the backend stream
  useEffect(() => {
    if (!sheetId) return;
    return api.sheets.stream(sheetId, {
      onEvent: (e) => {
        if (e.type === 'cell.updated') {
          dispatch({ type: 'cell', rowId: e.rowId, columnId: e.columnId, cell: e.cell });
          if (e.cell.status !== 'researching') {
            const key = `${e.rowId}:${e.columnId}`;
            setFlashed((s) => new Set(s).add(key));
            setTimeout(() => setFlashed((s) => {
              const n = new Set(s);
              n.delete(key);
              return n;
            }), 900);
          }
        } else {
          dispatch({ type: 'batch', batch: e.batch });
          if (e.type === 'batch.completed') {
            toast({ tone: e.batch.failed ? 'warn' : 'ok', text: e.batch.failed ? `Research complete · ${e.batch.failed} cells need a retry` : 'Research complete' });
            qc.invalidateQueries({ queryKey: ['sheets'] });
          }
        }
      },
    });
  }, [sheetId, qc, toast]);

  if (q.isLoading || (!sheet && !q.isError))
    return (
      <div className="page page--wide">
        <LoadingRegion label="Loading data sheet">
          <Skeleton w={320} h={32} style={{ marginBottom: 16 }} />
          <Skeleton h={44} style={{ marginBottom: 12 }} />
          <Skeleton h={480} r={12} />
        </LoadingRegion>
      </div>
    );
  if (q.isError || !sheet)
    return (
      <div className="page">
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      </div>
    );
  return <SheetView sheet={sheet} dispatch={dispatch} flashed={flashed} />;
}

function SheetView({ sheet, dispatch, flashed }: { sheet: NonNullable<ReturnType<typeof sheetReducer>>; dispatch: React.Dispatch<Parameters<typeof sheetReducer>[1]>; flashed: Set<string> }) {
  const toast = useUi((s) => s.toast);
  const qc = useQueryClient();
  const [search, setSearch] = useState('');
  const dsearch = useDebounce(search, 150);
  const [statusFilter, setStatusFilter] = useState<ValueStatus | 'all'>('all');
  const [sort, setSort] = useState<{ columnId: string; dir: 1 | -1 } | null>(null);
  const [groupBy, setGroupBy] = useState<'none' | 'municipality' | 'industry'>('none');
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [modal, setModal] = useState<null | 'ai' | 'export' | 'columns' | 'rename' | { remove: DataSheetColumn } | { renameCol: DataSheetColumn }>(null);
  useCommand('export', () => setModal('export'));
  const [propsOpen, setPropsOpen] = useState(false);
  const propsRef = useRef<HTMLButtonElement>(null);
  const [filterOpen, setFilterOpen] = useState(false);
  const filterRef = useRef<HTMLButtonElement>(null);
  const batch = sheet.batch;
  const running = batch?.state === 'running';

  const visibleCols = sheet.columns.filter((c) => !hidden.has(c.id));
  const items = useMemo<DisplayItem[]>(() => {
    const t = dsearch.trim().toLowerCase();
    let rows = sheet.rows.filter((r) => {
      if (t && !(r.company.legalName.toLowerCase().includes(t) || r.company.orgNumber.includes(t) || Object.values(r.cells).some((c) => (c.display ?? String(c.value ?? '')).toLowerCase().includes(t)))) return false;
      if (statusFilter !== 'all' && !visibleCols.some((c) => c.kind !== 'identity' && (r.cells[c.id]?.status ?? 'pending') === statusFilter)) return false;
      return true;
    });
    if (sort) rows = [...rows].sort((a, b) => (sort.columnId === 'company' ? a.company.legalName.localeCompare(b.company.legalName, 'nb') * sort.dir : compareCells(a.cells[sort.columnId], b.cells[sort.columnId], sort.dir)));
    if (groupBy === 'none') return rows.map((row, index) => ({ kind: 'row' as const, row, index }));
    const groups = new Map<string, typeof rows>();
    for (const r of rows) {
      const k = groupBy === 'municipality' ? (r.company.municipality ?? 'Unknown') : (r.company.industry?.description ?? 'Unknown');
      groups.set(k, [...(groups.get(k) ?? []), r]);
    }
    const out: DisplayItem[] = [];
    let i = 0;
    for (const [k, rs] of [...groups.entries()].sort((a, b) => b[1].length - a[1].length)) {
      out.push({ kind: 'group', key: k, label: k, count: rs.length });
      for (const row of rs) out.push({ kind: 'row', row, index: i++ });
    }
    return out;
  }, [sheet.rows, dsearch, statusFilter, sort, groupBy, visibleCols]);
  const shownRows = items.filter((i) => i.kind === 'row').length;

  const researchAll = useCallback(async () => {
    const b = await api.sheets.researchAll(sheet.id);
    dispatch({ type: 'batch', batch: b });
    if (b.total === 0) toast({ tone: 'info', text: 'Nothing to research — every cell already has a result.' });
  }, [sheet.id, dispatch, toast]);

  const moveCol = async (c: DataSheetColumn, delta: number) => {
    const ids = sheet.columns.map((x) => x.id);
    const i = ids.indexOf(c.id);
    const j = i + delta;
    if (j < 1 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    dispatch({ type: 'reorder', columnIds: ids });
    await api.sheets.reorderColumns(sheet.id, ids);
  };
  const columnMenu = (c: DataSheetColumn): MenuItem[] => {
    const items: MenuItem[] = [
      { label: 'Sort ascending', icon: <ArrowUp aria-hidden />, onSelect: () => setSort({ columnId: c.id, dir: 1 }) },
      { label: 'Sort descending', icon: <ArrowDown aria-hidden />, onSelect: () => setSort({ columnId: c.id, dir: -1 }) },
    ];
    if (c.kind === 'identity') return items;
    items.push(
      { label: c.frozen ? 'Unfreeze column' : 'Freeze column', icon: c.frozen ? <PinOff aria-hidden /> : <Pin aria-hidden />, onSelect: () => (dispatch({ type: 'updateColumn', columnId: c.id, patch: { frozen: !c.frozen } }), void api.sheets.updateColumn(sheet.id, c.id, { frozen: !c.frozen })) },
      { label: 'Move left', icon: <ArrowLeft aria-hidden />, onSelect: () => void moveCol(c, -1) },
      { label: 'Move right', icon: <ArrowRight aria-hidden />, onSelect: () => void moveCol(c, 1) },
      { label: 'Hide column', icon: <EyeOff aria-hidden />, onSelect: () => setHidden((h) => new Set(h).add(c.id)) },
    );
    if (c.kind === 'ai') items.push({ label: 'Rename column', icon: <Pencil aria-hidden />, onSelect: () => setModal({ renameCol: c }) });
    items.push({ label: 'Remove column', icon: <Trash2 aria-hidden />, danger: true, separatorBefore: true, onSelect: () => setModal({ remove: c }) });
    return items;
  };
  const onResize = (id: string, width: number, commit: boolean) => {
    dispatch({ type: 'updateColumn', columnId: id, patch: { width } });
    if (commit) void api.sheets.updateColumn(sheet.id, id, { width });
  };

  const pendingCount = sheet.rows.reduce((n, r) => n + sheet.columns.filter((c) => c.kind !== 'identity' && ['pending', 'failed'].includes(r.cells[c.id]?.status ?? 'pending')).length, 0);

  return (
    <div className="page page--wide sheet-page">
      <div className="sheet-head">
        <AmbientGlobe className="sheet-ambient" />
        <div className="stack" style={{ gap: 6, minWidth: 0 }}>
          <Link to="/sheets" className="link-btn">
            <ArrowLeft aria-hidden /> Data Sheets
          </Link>
          <div className="row" style={{ gap: 8 }}>
            <h1 className="sheet-title truncate">{sheet.title}</h1>
            <button className="btn btn--ghost btn--icon btn--sm" onClick={() => setModal('rename')} aria-label="Rename sheet">
              <Pencil aria-hidden />
            </button>
          </div>
          {sheet.criteria && sheet.criteria.length > 0 && (
            <div className="row-wrap" style={{ gap: 6 }}>
              {sheet.criteria.map((c) => (
                <span key={c.key} className="pill pill--sm">
                  {c.label}: {c.display}
                </span>
              ))}
            </div>
          )}
        </div>
        <span className="t-xs t-muted sheet-saved">
          <Check width={13} height={13} aria-hidden /> Saved · updated {formatRelative(sheet.updatedAt)}
        </span>
      </div>

      <div className="sheet-toolbar" role="toolbar" aria-label="Sheet tools">
        <Link to="/sheets?new=1" className="btn btn--sm">
          <Plus aria-hidden /> New
        </Link>
        <button className="btn btn--sm" onClick={() => setModal('ai')}>
          <Sparkle aria-hidden /> Add AI column
        </button>
        <button className="btn btn--primary btn--sm" onClick={researchAll} disabled={running || pendingCount === 0} title={pendingCount === 0 ? 'Every cell already has a result' : undefined}>
          <Play aria-hidden /> {running ? 'Researching…' : `Research all${pendingCount ? ` (${pendingCount})` : ''}`}
        </button>
        <span className="tb-sep" aria-hidden />
        <button ref={filterRef} className={`btn btn--sm ${statusFilter !== 'all' ? 'is-selected' : ''}`} onClick={() => setFilterOpen((o) => !o)} aria-haspopup="dialog">
          <Filter aria-hidden /> Filter{statusFilter !== 'all' ? `: ${VALUE_STATUS[statusFilter].label}` : ''}
        </button>
        <label className="row t-xs t-muted" style={{ gap: 6 }}>
          <Rows3 width={14} height={14} aria-hidden />
          <span className="sr-only">Group by</span>
          <select className="select" style={{ height: 30, width: 150, fontSize: 12.5 }} value={groupBy} onChange={(e) => setGroupBy(e.target.value as typeof groupBy)} aria-label="Group rows">
            <option value="none">No grouping</option>
            <option value="municipality">Group: Location</option>
            <option value="industry">Group: Industry</option>
          </select>
        </label>
        <button className="btn btn--sm" onClick={() => setModal('columns')}>
          <Columns3 aria-hidden /> Columns{hidden.size ? ` (${hidden.size} hidden)` : ''}
        </button>
        <button className="btn btn--sm" onClick={() => setModal('export')}>
          <Download aria-hidden /> Export
        </button>
        <span className="spacer" />
        <div className="input-wrap sheet-search">
          <Search aria-hidden />
          <input className="input" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search sheet" aria-label="Search this sheet" style={{ height: 32 }} />
        </div>
        <button ref={propsRef} className="btn btn--ghost btn--icon btn--sm" onClick={() => setPropsOpen((o) => !o)} aria-label="Sheet properties">
          <Info aria-hidden />
        </button>
      </div>

      {batch && batch.state !== 'idle' && batch.total > 0 && <BatchBar batch={batch} />}

      <SheetGrid items={items} columns={visibleCols} sort={sort} onSort={(columnId, dir) => setSort({ columnId, dir })} columnMenu={columnMenu} onResize={onResize} flashed={flashed} rowCount={shownRows} sourceIndex={sheet.sourceIndex ?? {}} />

      <div className="sheet-foot t-xs t-muted" role="status">
        Showing {shownRows} of {sheet.rows.length} rows · {visibleCols.length} columns · rows are virtualized for large sheets
        {sort && (
          <button className="link-btn" style={{ marginLeft: 12, fontSize: 12 }} onClick={() => setSort(null)}>
            Clear sort
          </button>
        )}
      </div>

      <Popover anchor={filterRef.current} open={filterOpen} onClose={() => setFilterOpen(false)} label="Filter by cell status" width={250}>
        <div className="stack" style={{ gap: 4 }}>
          <span className="t-micro" style={{ marginBottom: 4 }}>
            Rows with a cell that is…
          </span>
          {(['all', 'verified', 'pending', 'not_available', 'blocked', 'failed', 'ambiguous'] as const).map((s) => (
            <button key={s} className="menu-item" aria-pressed={statusFilter === s} onClick={() => (setStatusFilter(s), setFilterOpen(false))}>
              {statusFilter === s ? <Check aria-hidden /> : <span style={{ width: 15 }} />}
              {s === 'all' ? 'Any status' : VALUE_STATUS[s].label}
            </button>
          ))}
        </div>
      </Popover>
      <Popover anchor={propsRef.current} open={propsOpen} onClose={() => setPropsOpen(false)} label="Sheet properties" width={300}>
        <dl className="kv" style={{ gridTemplateColumns: '100px 1fr', fontSize: 12.5 }}>
          <dt>Rows</dt>
          <dd>{sheet.rows.length}</dd>
          <dt>Columns</dt>
          <dd>
            {sheet.columns.length} ({sheet.columns.filter((c) => c.kind === 'ai').length} AI)
          </dd>
          <dt>Updated</dt>
          <dd>{formatDate(sheet.updatedAt)}</dd>
          {sheet.description && (
            <>
              <dt>About</dt>
              <dd>{sheet.description}</dd>
            </>
          )}
        </dl>
      </Popover>

      <AddColumnModal
        open={modal === 'ai'}
        onClose={() => setModal(null)}
        sheetId={sheet.id}
        sampleRows={sheet.rows.map((r) => r.company.legalName)}
        onAdd={async (input) => {
          const col = await api.sheets.addColumn(sheet.id, input);
          dispatch({ type: 'addColumn', column: col });
          setModal(null);
          toast({ tone: 'info', text: `Researching “${col.title}” for ${sheet.rows.length} companies` });
          const b = await api.sheets.researchAll(sheet.id, { columnIds: [col.id] });
          dispatch({ type: 'batch', batch: b });
        }}
      />
      <ExportModal open={modal === 'export'} onClose={() => setModal(null)} target={{ type: 'sheet', id: sheet.id }} title={sheet.title} />
      <Modal open={modal === 'columns'} onClose={() => setModal(null)} title="Columns">
        <ul className="stack" style={{ gap: 4 }}>
          {sheet.columns.map((c) => (
            <li key={c.id} className="row" style={{ justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--line)' }}>
              <span className="row" style={{ gap: 8 }}>
                {c.kind === 'ai' && <Sparkle width={14} height={14} className="t-accent" aria-hidden />}
                {c.title}
                {c.frozen && <span className="pill pill--sm">Frozen</span>}
              </span>
              {c.kind !== 'identity' && (
                <button className="btn btn--ghost btn--sm" aria-pressed={!hidden.has(c.id)} onClick={() => setHidden((h) => {
                  const n = new Set(h);
                  if (n.has(c.id)) n.delete(c.id);
                  else n.add(c.id);
                  return n;
                })}>
                  {hidden.has(c.id) ? <EyeOff aria-hidden /> : <Eye aria-hidden />} {hidden.has(c.id) ? 'Hidden' : 'Visible'}
                </button>
              )}
            </li>
          ))}
        </ul>
      </Modal>
      {modal && typeof modal === 'object' && 'remove' in modal && (
        <Modal
          open
          onClose={() => setModal(null)}
          title={`Remove “${modal.remove.title}”?`}
          footer={
            <>
              <button className="btn btn--ghost" onClick={() => setModal(null)}>
                Cancel
              </button>
              <button
                className="btn btn--danger"
                onClick={async () => {
                  await api.sheets.removeColumn(sheet.id, modal.remove.id);
                  dispatch({ type: 'removeColumn', columnId: modal.remove.id });
                  setModal(null);
                }}
              >
                Remove column
              </button>
            </>
          }
        >
          <p className="t-sm t-soft">The column and its researched values will be removed from this sheet. Evidence in company research is not affected.</p>
        </Modal>
      )}
      {(modal === 'rename' || (modal && typeof modal === 'object' && 'renameCol' in modal)) && (
        <RenameModal
          initial={modal === 'rename' ? sheet.title : (modal as { renameCol: DataSheetColumn }).renameCol.title}
          title={modal === 'rename' ? 'Rename sheet' : 'Rename column'}
          onClose={() => setModal(null)}
          onSave={async (t) => {
            if (modal === 'rename') {
              await api.sheets.rename(sheet.id, t);
              dispatch({ type: 'rename', title: t });
              qc.invalidateQueries({ queryKey: ['sheets'] });
            } else {
              const c = (modal as { renameCol: DataSheetColumn }).renameCol;
              await api.sheets.updateColumn(sheet.id, c.id, { title: t });
              dispatch({ type: 'updateColumn', columnId: c.id, patch: { title: t } });
            }
            setModal(null);
          }}
        />
      )}
    </div>
  );
}

function BatchBar({ batch }: { batch: NonNullable<ReturnType<typeof sheetReducer>>['batch'] & object }) {
  const [showErr, setShowErr] = useState(false);
  const pct = batch.total ? Math.round(((batch.done + batch.failed) / batch.total) * 100) : 0;
  return (
    <div className="batch" role="status" aria-live="polite">
      <div className="row-wrap" style={{ gap: 14 }}>
        <strong className="t-num">
          {batch.done + batch.failed} / {batch.total} complete
        </strong>
        <span className="batch-stat t-ok">✓ {batch.done}</span>
        <span className="batch-stat t-accent">⟳ {batch.running}</span>
        <span className="batch-stat t-muted">○ {batch.pending}</span>
        <span className={`batch-stat ${batch.failed ? 't-warn' : 't-muted'}`}>⚠ {batch.failed}</span>
        <span className="spacer" />
        {batch.state === 'running' && batch.etaSeconds != null && <span className="t-xs t-muted">About {batch.etaSeconds}s remaining (backend estimate)</span>}
        {batch.state === 'completed' && <span className="t-xs t-ok">Batch complete</span>}
        {batch.errors.length > 0 && (
          <button className="link-btn" onClick={() => setShowErr((s) => !s)}>
            {showErr ? 'Hide' : 'Show'} {batch.errors.length} error{batch.errors.length === 1 ? '' : 's'}
          </button>
        )}
      </div>
      <div className="batch-track" aria-hidden>
        <span style={{ width: `${pct}%` }} />
      </div>
      {batch.sourceUsage && batch.sourceUsage.length > 0 && (
        <p className="t-xs t-muted">
          Source usage: {batch.sourceUsage.slice(0, 5).map((s) => `${s.sourceName} (${s.calls})`).join(' · ')}
        </p>
      )}
      {showErr && (
        <ul className="batch-errors">
          {batch.errors.slice(0, 20).map((e) => (
            <li key={`${e.rowId}${e.columnId}`} className="t-xs">
              <X width={12} height={12} aria-hidden className="t-err" /> {e.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const TYPE_LABEL: Record<ColumnValueType, string> = { text: 'Text', person: 'Person', number: 'Number', currency: 'Currency (as filed)', date: 'Date', boolean: 'Yes / No', url: 'URL' };

/**
 * AI research column, in two steps: write the instruction → the backend
 * interprets it and the user previews the intended column (title, value type,
 * what each cell will contain, planned sources) → add and research.
 */
function AddColumnModal({ open, onClose, sheetId, sampleRows, onAdd }: { open: boolean; onClose: () => void; sheetId: string; sampleRows: string[]; onAdd: (i: { instruction: string; title?: string; valueType?: ColumnValueType }) => Promise<void> }) {
  const [instruction, setInstruction] = useState('');
  const [title, setTitle] = useState('');
  const [type, setType] = useState<ColumnValueType | ''>('');
  const [busy, setBusy] = useState<null | 'preview' | 'add'>(null);
  const [preview, setPreview] = useState<ColumnPreview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const reset = () => {
    setPreview(null);
    setErr(null);
  };
  const close = () => {
    reset();
    onClose();
  };
  const runPreview = async () => {
    setBusy('preview');
    setErr(null);
    try {
      setPreview(await api.sheets.previewColumn(sheetId, { instruction: instruction.trim(), title: title.trim() || undefined, valueType: type || undefined }));
    } catch {
      setErr('The backend could not interpret this instruction. Try rephrasing it.');
    } finally {
      setBusy(null);
    }
  };
  const add = async () => {
    if (!preview) return;
    setBusy('add');
    try {
      await onAdd({ instruction: preview.instruction, title: preview.title, valueType: preview.valueType });
      setInstruction('');
      setTitle('');
      setType('');
      reset();
    } finally {
      setBusy(null);
    }
  };
  return (
    <Modal
      open={open}
      onClose={close}
      wide
      eyebrow={<span className="eyebrow">{preview ? 'Step 2 of 2 · Preview' : 'Step 1 of 2 · Instruction'}</span>}
      title={preview ? 'Preview the research column' : 'Add a research column'}
      footer={
        preview ? (
          <>
            <button className="btn btn--ghost" onClick={reset}>
              <ArrowLeft aria-hidden /> Edit instruction
            </button>
            <span className="spacer" />
            <button className="btn btn--primary" disabled={!preview.supported || !!busy} onClick={add}>
              <Sparkle aria-hidden /> {busy === 'add' ? 'Adding…' : `Add & research ${preview.rowCount} companies`}
            </button>
          </>
        ) : (
          <>
            <button className="btn btn--ghost" onClick={close}>
              Cancel
            </button>
            <button className="btn btn--primary" disabled={instruction.trim().length < 4 || !!busy} onClick={runPreview}>
              {busy === 'preview' ? 'Interpreting…' : 'Preview column'} <ArrowRight aria-hidden />
            </button>
          </>
        )
      }
    >
      {!preview ? (
        <div className="stack" style={{ gap: 16 }}>
          <div className="field">
            <label htmlFor="ai-instr">What should this column find for each company?</label>
            <textarea
              id="ai-instr"
              className="textarea"
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && (e.metaKey || e.ctrlKey) && instruction.trim().length >= 4 && void runPreview()}
              placeholder="Find the company's current CEO"
              data-autofocus
            />
          </div>
          <div className="row-wrap" style={{ gap: 6 }}>
            {AI_EXAMPLES.map((e) => (
              <button key={e} className="chip chip--sm" onClick={() => setInstruction(e)}>
                {e}
              </button>
            ))}
          </div>
          <div className="row-wrap" style={{ gap: 12 }}>
            <div className="field" style={{ flex: 1, minWidth: 200 }}>
              <label htmlFor="ai-title">Column title (optional)</label>
              <input id="ai-title" className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Suggested by the backend if empty" />
            </div>
            <div className="field" style={{ width: 180 }}>
              <label htmlFor="ai-type">Value type</label>
              <select id="ai-type" className="select" value={type} onChange={(e) => setType(e.target.value as ColumnValueType | '')}>
                <option value="">Let the backend decide</option>
                {(Object.keys(TYPE_LABEL) as ColumnValueType[]).map((k) => (
                  <option key={k} value={k}>
                    {TYPE_LABEL[k]}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {err && (
            <p className="t-sm t-warn" role="alert">
              {err}
            </p>
          )}
          <p className="t-xs t-muted">Nothing is researched until you confirm the preview.</p>
        </div>
      ) : (
        <div className="colprev">
          <div className="colprev-spec">
            <dl className="kv">
              <dt>Instruction</dt>
              <dd>“{preview.instruction}”</dd>
              <dt>Column</dt>
              <dd>
                <strong style={{ fontWeight: 500 }}>{preview.title}</strong>
              </dd>
              <dt>Value type</dt>
              <dd>{TYPE_LABEL[preview.valueType]}</dd>
              <dt>Each cell</dt>
              <dd>{preview.cellDescription}</dd>
              <dt>Sources</dt>
              <dd>
                <ul className="colprev-src">
                  {preview.plannedSources.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              </dd>
            </dl>
            {preview.notes.length > 0 && (
              <ul className="colprev-notes">
                {preview.notes.map((n) => (
                  <li key={n}>
                    <Info aria-hidden width={13} height={13} /> {n}
                  </li>
                ))}
              </ul>
            )}
            {!preview.supported && (
              <p className="t-sm t-warn" role="alert">
                The backend cannot research this instruction as written. Edit it and preview again.
              </p>
            )}
          </div>
          <figure className="colprev-table" aria-label="How the column will look">
            <figcaption className="t-micro">How it will look</figcaption>
            <div className="colprev-grid" role="table">
              <div className="colprev-row colprev-head" role="row">
                <span role="columnheader">Company</span>
                <span role="columnheader">
                  <Sparkle aria-hidden width={12} height={12} /> {preview.title}
                </span>
              </div>
              {sampleRows.slice(0, 4).map((name) => (
                <div key={name} className="colprev-row" role="row">
                  <span role="cell" className="truncate">
                    {name}
                  </span>
                  <span role="cell" className="t-muted">
                    <span className="colprev-dot" aria-hidden /> Queued
                  </span>
                </div>
              ))}
              {preview.rowCount > 4 && <div className="colprev-more">+ {preview.rowCount - 4} more companies</div>}
            </div>
            <p className="t-xs t-muted">Each cell shows Researching → a verified value with its source and date, or Not available / Ambiguous / Source blocked.</p>
          </figure>
        </div>
      )}
    </Modal>
  );
}

function RenameModal({ initial, title, onClose, onSave }: { initial: string; title: string; onClose: () => void; onSave: (t: string) => Promise<void> }) {
  const [t, setT] = useState(initial);
  return (
    <Modal
      open
      onClose={onClose}
      title={title}
      footer={
        <>
          <button className="btn btn--ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn--primary" disabled={!t.trim()} onClick={() => void onSave(t.trim())}>
            Save
          </button>
        </>
      }
    >
      <input className="input" value={t} onChange={(e) => setT(e.target.value)} aria-label="Title" data-autofocus />
    </Modal>
  );
}
