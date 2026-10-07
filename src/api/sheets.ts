import type { SheetsApi } from './contract';
import { http, openEventStream } from './http';
import type { BatchStatus, ColumnPreview, DataSheet, DataSheetColumn, DataSheetSummary, QueryInterpretation, SheetEvent } from '@/types';

/** Live Data Sheet endpoints. */
export const liveSheets: SheetsApi = {
  // GET /sheets → DataSheetSummary[]
  list: () => http.get<DataSheetSummary[]>('/sheets'),
  // GET /sheets/:id → DataSheet
  get: (id) => http.get<DataSheet>(`/sheets/${id}`),
  // POST /sheets/interpret body: { text } → QueryInterpretation
  interpret: (text) => http.post<QueryInterpretation>('/sheets/interpret', { text }),
  // POST /sheets body: { title, criteria, text? } → DataSheetSummary
  create: (input) => http.post<DataSheetSummary>('/sheets', input),
  // PATCH /sheets/:id body: { title }
  rename: (id, title) => http.patch<DataSheetSummary>(`/sheets/${id}`, { title }),
  // POST /sheets/:id/columns/preview body: AddColumnInput → ColumnPreview (nothing is added)
  previewColumn: (id, input) => http.post<ColumnPreview>(`/sheets/${id}/columns/preview`, input),
  // POST /sheets/:id/columns body: AddColumnInput → DataSheetColumn (cells start 'pending')
  addColumn: (id, input) => http.post<DataSheetColumn>(`/sheets/${id}/columns`, input),
  // PATCH /sheets/:id/columns/:columnId
  updateColumn: (id, columnId, patch) => http.patch<DataSheetColumn>(`/sheets/${id}/columns/${columnId}`, patch),
  // DELETE /sheets/:id/columns/:columnId
  removeColumn: (id, columnId) => http.del<void>(`/sheets/${id}/columns/${columnId}`),
  // PUT /sheets/:id/columns/order body: { columnIds }
  reorderColumns: (id, columnIds) => http.put<void>(`/sheets/${id}/columns/order`, { columnIds }),
  // POST /sheets/:id/research body: { columnIds? } → BatchStatus
  researchAll: (id, opts) => http.post<BatchStatus>(`/sheets/${id}/research`, opts ?? {}),
  // GET /sheets/:id/events  (text/event-stream of SheetEvent JSON)
  stream: (id, handlers) => openEventStream<SheetEvent>(`/sheets/${id}/events`, handlers, { terminalTypes: ['batch.completed'] }),
};
