import type { CompareApi, ExportsApi, WatchlistApi } from './contract';
import { http } from './http';
import type { Comparison, ExportResult, SignalFeedGroup, Watchlist } from '@/types';

/** Live comparison endpoint. */
export const liveCompare: CompareApi = {
  // GET /compare?orgs=a,b,c → Comparison (2–5 companies)
  get: (orgNumbers) => http.get<Comparison>('/compare', { orgs: orgNumbers.join(',') }),
};

/** Live watchlist + signal feed endpoints. */
export const liveWatchlist: WatchlistApi = {
  // GET /watchlist → Watchlist
  get: () => http.get<Watchlist>('/watchlist'),
  // POST /watchlist/items body: { orgNumber }
  add: (orgNumber) => http.post<Watchlist>('/watchlist/items', { orgNumber }),
  // DELETE /watchlist/items/:orgNumber
  remove: (orgNumber) => http.del<Watchlist>(`/watchlist/items/${orgNumber}`),
  // POST /watchlist/checked → marks signals as seen
  markChecked: () => http.post<Watchlist>('/watchlist/checked'),
  // GET /signals → SignalFeedGroup[]
  feed: () => http.get<SignalFeedGroup[]>('/signals'),
};

/** Live export endpoint — the backend builds every export file. */
export const liveExports: ExportsApi = {
  // POST /exports body: ExportRequest → ExportResult { url }
  request: (req) => http.post<ExportResult>('/exports', req),
};
