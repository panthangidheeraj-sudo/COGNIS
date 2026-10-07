import type { SystemApi } from './contract';
import { API_BASE_URL, http } from './http';
import type { SystemStatus } from '@/types';

/** Live system / source-availability endpoint. */
export const liveSystem: SystemApi = {
  // GET /status → SystemStatus (backend + research health, source availability, capabilities)
  status: async () => ({ ...(await http.get<SystemStatus>('/status')), mode: 'live', baseUrl: API_BASE_URL }),
};
