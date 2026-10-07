import { memo, useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useVirtualizer } from '@tanstack/react-virtual';
import { ArrowDown, ArrowUp, Ban, ChevronDown, CircleAlert, CircleCheck, CircleDashed, CircleX, Ellipsis, LoaderCircle, Sparkle } from 'lucide-react';
import type { DataSheetCell, DataSheetColumn, DataSheetRow, Source } from '@/types';
import { Popover } from '@/components/common/Popover';
import { VerificationBadge, evidenceAsFact } from '@/components/evidence/SourceBadge';
import { Menu, type MenuItem } from '@/components/common/Menu';
import { useUi } from '@/stores/ui';
import { useCompact } from '@/stores/preferences';
import { formatDate, formatInteger, formatMoneyCompact, formatOrgNumber } from '@/utils/format';
import { VALUE_STATUS } from '@/utils/status';
import { cn } from '@/utils/cn';

export type DisplayItem = { kind: 'group'; key: string; label: string; count: number } | { kind: 'row'; row: DataSheetRow; index: number };

const STATUS_ICON = { verified: CircleCheck, researching: LoaderCircle, pending: CircleDashed, not_available: CircleDashed, ambiguous: CircleAlert, blocked: Ban, failed: CircleX, stale: CircleAlert };

function cellText(cell: DataSheetCell, col: DataSheetColumn): string {
  if (cell.status !== 'verified' && cell.status !== 'blocked') return VALUE_STATUS[cell.status].label;
  if (cell.display) return cell.display;
  if (cell.value == null) return '—';
  if (typeof cell.value === 'number') return col.valueType === 'currency' ? formatMoneyCompact(cell.value, cell.currency) : formatInteger(cell.value);
  if (typeof cell.value === 'boolean') return cell.value ? 'Yes' : 'No';
  return String(cell.value);
}

interface GridProps {
  items: DisplayItem[];
  columns: DataSheetColumn[];
  sort: { columnId: string; dir: 1 | -1 } | null;
  onSort: (columnId: string, dir: 1 | -1) => void;
  columnMenu: (c: DataSheetColumn) => MenuItem[];
  onResize: (columnId: string, width: number, commit: boolean) => void;
  flashed: Set<string>;
  rowCount: number;
  sourceIndex: Record<string, Source>;
}

/** Virtualized research grid: sticky header, frozen columns, resizable, keyboard navigable. */
export function SheetGrid({ items, columns, sort, onSort, columnMenu, onResize, flashed, rowCount, sourceIndex }: GridProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  // Row height follows the density preference (Comfortable 44px / Compact 34px; matches --row-h).
  const rowH = useCompact() ? 34 : 44;
  const virt = useVirtualizer({ count: items.length, getScrollElement: () => scrollRef.current, estimateSize: () => rowH, overscan: 12 });
  useEffect(() => {
    virt.measure();
  }, [rowH, virt]);
  const frozen = columns.filter((c) => c.frozen);
  const free = columns.filter((c) => !c.frozen);
  const ordered = [...frozen, ...free];
  const left: Record<string, number> = {};
  let acc = 48;
  for (const c of frozen) {
    left[c.id] = acc;
    acc += c.width;
  }
  const template = `48px ${ordered.map((c) => `${c.width}px`).join(' ')}`;
  const total = 48 + ordered.reduce((n, c) => n + c.width, 0);
  const [cellPop, setCellPop] = useState<{ el: HTMLElement; row: DataSheetRow; col: DataSheetColumn } | null>(null);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const t = e.target as HTMLElement;
      const r = Number(t.dataset.r);
      const c = Number(t.dataset.c);
      if (Number.isNaN(r) || Number.isNaN(c)) return;
      let nr = r;
      let nc = c;
      if (e.key === 'ArrowDown') nr = r + 1;
      else if (e.key === 'ArrowUp') nr = r - 1;
      else if (e.key === 'ArrowRight') nc = c + 1;
      else if (e.key === 'ArrowLeft') nc = c - 1;
      else return;
      e.preventDefault();
      nr = Math.max(0, Math.min(items.length - 1, nr));
      nc = Math.max(0, Math.min(ordered.length - 1, nc));
      virt.scrollToIndex(nr, { align: 'auto' });
      requestAnimationFrame(() => scrollRef.current?.querySelector<HTMLElement>(`[data-r="${nr}"][data-c="${nc}"]`)?.focus());
    },
    [items.length, ordered.length, virt],
  );

  return (
    <div className="sg-scroll" ref={scrollRef} role="grid" aria-rowcount={rowCount + 1} aria-colcount={ordered.length + 1} aria-label="Data sheet" onKeyDown={onKeyDown}>
      <div className="sg-inner" style={{ width: total, height: virt.getTotalSize() + rowH }}>
        <div className="sg-row sg-head" role="row" style={{ gridTemplateColumns: template, width: total }}>
          <div className="sg-cell sg-num sg-frozen" role="columnheader" style={{ left: 0 }}>
            #
          </div>
          {ordered.map((c) => (
            <HeaderCell key={c.id} c={c} left={c.frozen ? left[c.id] : undefined} sort={sort?.columnId === c.id ? sort.dir : null} onSort={onSort} menu={columnMenu(c)} onResize={onResize} />
          ))}
        </div>
        {virt.getVirtualItems().map((v) => {
          const it = items[v.index];
          if (it.kind === 'group')
            return (
              <div key={`g-${it.key}`} className="sg-group" role="row" style={{ transform: `translateY(${v.start + rowH}px)`, width: total }}>
                <span className="sg-group-label" role="gridcell">
                  {it.label} <span className="t-muted t-num">· {it.count}</span>
                </span>
              </div>
            );
          return <Row key={it.row.id} row={it.row} r={v.index} n={it.index + 1} top={v.start + rowH} columns={ordered} template={template} total={total} left={left} flashed={flashed} onCell={(el, col) => setCellPop({ el, row: it.row, col })} />;
        })}
      </div>
      {cellPop && <CellEvidence anchor={cellPop.el} row={cellPop.row} col={cellPop.col} sourceIndex={sourceIndex} onClose={() => setCellPop(null)} />}
    </div>
  );
}

function HeaderCell({ c, left, sort, onSort, menu, onResize }: { c: DataSheetColumn; left?: number; sort: 1 | -1 | null; onSort: (id: string, dir: 1 | -1) => void; menu: MenuItem[]; onResize: GridProps['onResize'] }) {
  const startX = useRef(0);
  const startW = useRef(0);
  const onDown = (e: React.PointerEvent) => {
    e.preventDefault();
    startX.current = e.clientX;
    startW.current = c.width;
    const move = (ev: PointerEvent) => onResize(c.id, Math.max(90, startW.current + ev.clientX - startX.current), false);
    const up = (ev: PointerEvent) => {
      onResize(c.id, Math.max(90, startW.current + ev.clientX - startX.current), true);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return (
    <div className={cn('sg-cell sg-hcell', c.frozen && 'sg-frozen')} role="columnheader" aria-sort={sort === 1 ? 'ascending' : sort === -1 ? 'descending' : 'none'} style={c.frozen ? { left } : undefined} title={c.instruction}>
      <button className="sg-hbtn" onClick={() => onSort(c.id, sort === 1 ? -1 : 1)}>
        {c.kind === 'ai' && <Sparkle aria-hidden className="sg-ai" />}
        <span className="truncate">{c.title}</span>
        {sort === 1 && <ArrowUp aria-hidden className="sg-sort" />}
        {sort === -1 && <ArrowDown aria-hidden className="sg-sort" />}
        <span className="sr-only">, sort</span>
      </button>
      {menu.length > 0 && <Menu label={`Column options: ${c.title}`} trigger={<ChevronDown aria-hidden />} items={menu} />}
      <span className="sg-resize" onPointerDown={onDown} role="separator" aria-orientation="vertical" aria-label={`Resize ${c.title}`} />
    </div>
  );
}

const Row = memo(function Row({ row, r, n, top, columns, template, total, left, flashed, onCell }: { row: DataSheetRow; r: number; n: number; top: number; columns: DataSheetColumn[]; template: string; total: number; left: Record<string, number>; flashed: Set<string>; onCell: (el: HTMLElement, col: DataSheetColumn) => void }) {
  return (
    <div className="sg-row" role="row" aria-rowindex={n + 1} style={{ gridTemplateColumns: template, transform: `translateY(${top}px)`, width: total }}>
      <div className="sg-cell sg-num sg-frozen t-num" role="rowheader" style={{ left: 0 }}>
        {n}
      </div>
      {columns.map((c, ci) => {
        if (c.kind === 'identity')
          return (
            <div key={c.id} className={cn('sg-cell sg-company', c.frozen && 'sg-frozen')} role="gridcell" style={c.frozen ? { left: left[c.id] } : undefined}>
              <Link to={`/company/${row.company.orgNumber}`} className="sg-company-link" data-r={r} data-c={ci} tabIndex={r === 0 && ci === 0 ? 0 : -1}>
                <span className="truncate">{row.company.legalName}</span>
                <span className="t-xs t-muted t-mono">{formatOrgNumber(row.company.orgNumber)}</span>
              </Link>
            </div>
          );
        const cell = row.cells[c.id] ?? { status: 'pending', value: null, evidence: [] };
        const Icon = STATUS_ICON[cell.status];
        const key = `${row.id}:${c.id}`;
        return (
          <div key={c.id} className={cn('sg-cell', c.frozen && 'sg-frozen', flashed.has(key) && 'sg-flash')} role="gridcell" style={c.frozen ? { left: left[c.id] } : undefined}>
            <button className={cn('sg-cbtn', `sg-cbtn--${cell.status}`, (c.valueType === 'number' || c.valueType === 'currency') && 'sg-num-v')} data-r={r} data-c={ci} tabIndex={-1} onClick={(e) => onCell(e.currentTarget, c)} aria-label={`${c.title}: ${cellText(cell, c)}${cell.status === 'verified' ? '' : ` (${VALUE_STATUS[cell.status].label})`}`}>
              <span className="truncate">{cellText(cell, c)}</span>
              {cell.status === 'verified' ? <span className="sg-src" aria-hidden title={cell.sourceName} /> : <Icon aria-hidden className="sg-icon" />}
            </button>
          </div>
        );
      })}
    </div>
  );
});

/** Compact evidence for one cell: value, verification, source, date, period and the supporting excerpt. */
function CellEvidence({ anchor, row, col, sourceIndex, onClose }: { anchor: HTMLElement; row: DataSheetRow; col: DataSheetColumn; sourceIndex: Record<string, Source>; onClose: () => void }) {
  const cell = row.cells[col.id] ?? { status: 'pending', value: null, evidence: [] };
  const openEvidence = useUi((s) => s.openEvidence);
  const first = cell.evidence[0];
  const sources = [...new Set(cell.evidence.map((e) => sourceIndex[e.sourceId]?.name ?? e.sourceId))];
  const excerpt = first?.excerptTranslation ?? first?.excerpt;
  return (
    <Popover anchor={anchor} open onClose={onClose} label={`Evidence for ${col.title}, ${row.company.legalName}`} width={320}>
      <div className="stack cellev" style={{ gap: 10 }}>
        <div className="stack" style={{ gap: 2 }}>
          <span className="t-micro">{col.title}</span>
          <span className="t-xs t-muted truncate">{row.company.legalName}</span>
        </div>
        <div className={cn('cellev-value', cell.status !== 'verified' && 'is-muted')}>{cell.status === 'verified' ? cellText(cell, col) : VALUE_STATUS[cell.status].label}</div>
        {cell.status !== 'pending' && <VerificationBadge fact={evidenceAsFact(cell.evidence, cell.evidenceState, cell.status)} sourceIndex={sourceIndex} small />}
        {cell.note && <p className="t-xs t-soft">{cell.note}</p>}
        {cell.evidence.length > 0 && (
          <dl className="kv" style={{ gridTemplateColumns: '74px 1fr', fontSize: 12.5 }}>
            <dt>Source</dt>
            <dd>{cell.sourceName ?? sources.join(', ')}</dd>
            <dt>Date</dt>
            <dd>{first ? formatDate(first.retrievedAt) : cell.updatedAt ? formatDate(cell.updatedAt) : '—'}</dd>
            {first?.reportingPeriod && (
              <>
                <dt>Period</dt>
                <dd>{first.reportingPeriod}</dd>
              </>
            )}
            {first?.statedValue && (
              <>
                <dt>As stated</dt>
                <dd className="t-mono">{first.statedValue}</dd>
              </>
            )}
          </dl>
        )}
        {excerpt && (
          <blockquote className="cellev-quote">
            “{excerpt}”{first?.documentTitle && <cite>{first.documentTitle}</cite>}
          </blockquote>
        )}
        {col.instruction && <p className="t-xs t-muted">Column instruction: “{col.instruction}”</p>}
        {cell.evidence.length > 0 ? (
          <button
            className="btn btn--sm"
            onClick={() => {
              onClose();
              openEvidence({ title: col.title, value: cellText(cell, col), evidence: cell.evidence, sourceIndex, context: row.company.legalName });
            }}
          >
            View full evidence{cell.evidence.length > 1 ? ` (${cell.evidence.length})` : ''}
          </button>
        ) : (
          <span className="t-xs t-muted">{cell.status === 'researching' || cell.status === 'pending' ? 'Evidence appears when the backend verifies this cell.' : 'No verified evidence for this cell.'}</span>
        )}
      </div>
    </Popover>
  );
}

export { Ellipsis };
