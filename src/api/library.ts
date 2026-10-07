import type { LibraryApi } from './contract';
import { http } from './http';
import type { Artifact, ArtifactCapabilities, ArtifactSummary, CompanyArtifact, LibraryPage, VersionComparison } from '@/types';

/** Live Library (saved research artifacts) endpoints. */
export const liveLibrary: LibraryApi = {
  // GET /library?q=&type=&sort=&page=&pageSize=&tag=&includeArchived= → LibraryPage (Paged<ArtifactSummary> + facets)
  list: (q, signal) => http.get<LibraryPage>('/library', { ...q }, signal),
  // GET /library/recent → ArtifactSummary[]
  recent: () => http.get<ArtifactSummary[]>('/library/recent'),
  // GET /library/:id → Artifact
  get: (id) => http.get<Artifact>(`/library/${id}`),
  // GET /library/:id/versions/:versionId → CompanyArtifact
  getVersion: (id, versionId) => http.get<CompanyArtifact>(`/library/${id}/versions/${versionId}`),
  // GET /library/:id/versions/compare?from=&to= → VersionComparison
  compareVersions: (id, from, to) => http.get<VersionComparison>(`/library/${id}/versions/compare`, { from, to }),
  // PATCH /library/:id  body: { title?, tags?, pinned?, archived? }
  update: (id, patch) => http.patch<ArtifactSummary>(`/library/${id}`, patch),
  // POST /library/:id/duplicate
  duplicate: (id) => http.post<ArtifactSummary>(`/library/${id}/duplicate`),
  // GET /library/capabilities → which artifact actions the backend supports
  capabilities: () => http.get<ArtifactCapabilities>('/library/capabilities'),
  // POST /library/from-run/:runId → saved artifact
  saveRun: (runId) => http.post<ArtifactSummary>(`/library/from-run/${runId}`),
  // POST /reports body: { orgNumber, kind, sections } → report artifact
  generateReport: (input) => http.post<ArtifactSummary>('/reports', input),
  // GET /library/by-org/:orgNumber → ArtifactSummary | null
  findByOrg: (orgNumber) => http.get<ArtifactSummary | null>(`/library/by-org/${orgNumber}`),
};
