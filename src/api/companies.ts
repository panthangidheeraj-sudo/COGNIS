import type { CompaniesApi, SearchApi } from './contract';
import { http } from './http';
import type { ChangeExplanation, CompanyProfile, CompanySummary, DiscoverQuery, DiscoverResult, ExecutiveBrief, QueryInterpretation, SearchResult } from '@/types';

/** Live company endpoints. */
export const liveCompanies: CompaniesApi = {
  // POST /companies/discover  body: DiscoverQuery → DiscoverResult
  discover: (query: DiscoverQuery, signal?: AbortSignal) => http.post<DiscoverResult>('/companies/discover', query, signal),
  // POST /companies/interpret body: { text } → QueryInterpretation
  interpret: (text: string, signal?: AbortSignal) => http.post<QueryInterpretation>('/companies/interpret', { text }, signal),
  // GET /companies/:orgNumber → CompanyProfile   (409 + AmbiguousMatch details when ambiguous)
  get: (orgNumber: string) => http.get<CompanyProfile>(`/companies/${encodeURIComponent(orgNumber)}`),
  // GET /companies/recent → CompanySummary[]
  recent: () => http.get<CompanySummary[]>('/companies/recent'),
  // GET /companies/:orgNumber/brief → ExecutiveBrief (compiled from saved evidence)
  brief: (orgNumber: string) => http.get<ExecutiveBrief>(`/companies/${encodeURIComponent(orgNumber)}/brief`),
  // POST /companies/:orgNumber/explain  body: { subject, fresh? } → ChangeExplanation
  explain: (orgNumber, subject, opts) => http.post<ChangeExplanation>(`/companies/${encodeURIComponent(orgNumber)}/explain`, { subject, fresh: !!opts?.fresh }),
};

/** Live global search. */
export const liveSearch: SearchApi = {
  // GET /search?q= → SearchResult (grouped results + routing intent)
  global: (query: string, signal?: AbortSignal) => http.get<SearchResult>('/search', { q: query }, signal),
};
