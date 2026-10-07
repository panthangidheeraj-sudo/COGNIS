/**
 * Data-sheet client state. Cell updates replace only the affected row object
 * so memoized rows that did not change skip re-rendering.
 */
import type { BatchStatus, DataSheet, DataSheetCell, DataSheetColumn } from '@/types';

export type SheetAction =
  | { type: 'load'; sheet: DataSheet }
  | { type: 'cell'; rowId: string; columnId: string; cell: DataSheetCell }
  | { type: 'batch'; batch: BatchStatus }
  | { type: 'addColumn'; column: DataSheetColumn }
  | { type: 'removeColumn'; columnId: string }
  | { type: 'updateColumn'; columnId: string; patch: Partial<DataSheetColumn> }
  | { type: 'reorder'; columnIds: string[] }
  | { type: 'rename'; title: string };

export function sheetReducer(s: DataSheet | null, a: SheetAction): DataSheet | null {
  if (a.type === 'load') return a.sheet;
  if (!s) return s;
  switch (a.type) {
    case 'cell': {
      const i = s.rows.findIndex((r) => r.id === a.rowId);
      if (i < 0) return s;
      const rows = s.rows.slice();
      rows[i] = { ...rows[i], cells: { ...rows[i].cells, [a.columnId]: a.cell } };
      return { ...s, rows };
    }
    case 'batch':
      return { ...s, batch: a.batch };
    case 'addColumn':
      return {
        ...s,
        columns: [...s.columns, a.column],
        columnCount: s.columnCount + 1,
        rows: s.rows.map((r) => ({ ...r, cells: { ...r.cells, [a.column.id]: { status: 'pending', value: null, evidence: [] } } })),
      };
    case 'removeColumn':
      return { ...s, columns: s.columns.filter((c) => c.id !== a.columnId), columnCount: s.columnCount - 1 };
    case 'updateColumn':
      return { ...s, columns: s.columns.map((c) => (c.id === a.columnId ? { ...c, ...a.patch } : c)) };
    case 'reorder':
      return { ...s, columns: a.columnIds.map((id) => s.columns.find((c) => c.id === id)!).filter(Boolean) };
    case 'rename':
      return { ...s, title: a.title };
  }
}

/** Sort key for a cell: numbers numerically, everything else as text; unknowns last. */
export function cellSortValue(cell: DataSheetCell | undefined): number | string | null {
  if (!cell || cell.status !== 'verified' || cell.value == null) return null;
  if (typeof cell.value === 'number') return cell.value;
  if (typeof cell.value === 'boolean') return cell.value ? 1 : 0;
  return (cell.display ?? String(cell.value)).toLowerCase();
}

export function compareCells(a: DataSheetCell | undefined, b: DataSheetCell | undefined, dir: 1 | -1) {
  const x = cellSortValue(a);
  const y = cellSortValue(b);
  if (x === null && y === null) return 0;
  if (x === null) return 1;
  if (y === null) return -1;
  if (typeof x === 'number' && typeof y === 'number') return (x - y) * dir;
  return String(x).localeCompare(String(y), 'nb') * dir;
}
