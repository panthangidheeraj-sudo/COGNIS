import { describe, expect, it } from 'vitest';
import { compareCells, sheetReducer } from '@/components/sheets/sheetState';
import type { DataSheet } from '@/types';

const sheet: DataSheet = {
  id: 's',
  title: 'T',
  rowCount: 2,
  columnCount: 2,
  updatedAt: '2026-10-03T00:00:00Z',
  columns: [
    { id: 'company', title: 'Company', kind: 'identity', valueType: 'text', width: 200 },
    { id: 'rev', title: 'Revenue', kind: 'standard', valueType: 'currency', width: 120 },
  ],
  rows: [
    { id: 'r1', company: { orgNumber: '1', legalName: 'A AS' }, cells: { rev: { status: 'pending', value: null, evidence: [] } } },
    { id: 'r2', company: { orgNumber: '2', legalName: 'B AS' }, cells: { rev: { status: 'verified', value: 10, evidence: [] } } },
  ],
};

describe('data sheet cells', () => {
  it('updates one cell without replacing untouched rows', () => {
    const next = sheetReducer(sheet, { type: 'cell', rowId: 'r1', columnId: 'rev', cell: { status: 'verified', value: 5, evidence: [] } })!;
    expect(next.rows[0].cells.rev.value).toBe(5);
    expect(next.rows[1]).toBe(sheet.rows[1]); // memoized row keeps identity
  });
  it('adds AI columns as pending for every row', () => {
    const next = sheetReducer(sheet, { type: 'addColumn', column: { id: 'ai', title: 'CEO', kind: 'ai', valueType: 'person', width: 200, instruction: 'Find the CEO' } })!;
    expect(next.rows.every((r) => r.cells.ai.status === 'pending')).toBe(true);
  });
  it('sorts unknown values last in both directions', () => {
    const v = { status: 'verified' as const, value: 1, evidence: [] };
    const na = { status: 'not_available' as const, value: null, evidence: [] };
    expect(compareCells(na, v, 1)).toBeGreaterThan(0);
    expect(compareCells(na, v, -1)).toBeGreaterThan(0);
  });
});
