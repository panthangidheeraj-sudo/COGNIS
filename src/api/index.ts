/**
 * Single entry point for backend access.
 *   VITE_API_MODE=mock (default) → in-browser mock backend with fixture data
 *   VITE_API_MODE=live           → typed HTTP client against VITE_API_BASE_URL
 */
import type { CognisApi } from './contract';
import { API_MODE } from './http';
import { liveCompanies, liveSearch } from './companies';
import { liveResearch } from './research';
import { liveLibrary } from './library';
import { liveSheets } from './sheets';
import { liveCompare, liveExports, liveWatchlist } from './compare';
import { liveSystem } from './sources';
import { mockApi } from '@/data/mock/mockApi';

const liveApi: CognisApi = {
  system: liveSystem,
  search: liveSearch,
  companies: liveCompanies,
  research: liveResearch,
  library: liveLibrary,
  sheets: liveSheets,
  compare: liveCompare,
  watchlist: liveWatchlist,
  exports: liveExports,
};

export const api: CognisApi = API_MODE === 'live' ? liveApi : mockApi;
export { API_MODE, ApiError } from './http';
export type { CognisApi } from './contract';
