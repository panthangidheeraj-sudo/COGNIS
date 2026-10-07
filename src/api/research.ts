import type { ResearchApi } from './contract';
import { http, openEventStream } from './http';
import type { ContinueResearchAssessment, ResearchAnswer, ResearchEvent, ResearchRun, StartResearchInput } from '@/types';

/** Live research endpoints. */
export const liveResearch: ResearchApi = {
  // POST /research/runs  body: StartResearchInput → ResearchRun
  start: (input: StartResearchInput) => http.post<ResearchRun>('/research/runs', input),
  // POST /research/runs/:id/confirm  body: { stepKeys } → ResearchRun
  confirm: (runId, stepKeys) => http.post<ResearchRun>(`/research/runs/${runId}/confirm`, { stepKeys }),
  // GET /research/runs/:id → ResearchRun
  get: (runId) => http.get<ResearchRun>(`/research/runs/${runId}`),
  // POST /research/runs/:id/pause|cancel|retry  (only when run.capabilities allow)
  pause: (runId) => http.post<ResearchRun>(`/research/runs/${runId}/pause`),
  cancel: (runId) => http.post<ResearchRun>(`/research/runs/${runId}/cancel`),
  retryFailed: (runId) => http.post<ResearchRun>(`/research/runs/${runId}/retry`),
  // GET /research/runs/:id/events?lastSeq=N  (text/event-stream of ResearchEvent JSON)
  stream: (runId, handlers, opts) =>
    openEventStream<ResearchEvent>(`/research/runs/${runId}/events`, handlers, {
      lastSeq: opts?.lastSeq,
      terminalTypes: ['run.completed', 'run.failed'],
    }),
  // POST /research/ask  body: { orgNumber, artifactId?, question, fresh } → ResearchAnswer
  ask: (input) => http.post<ResearchAnswer>('/research/ask', input),
  // GET /library/:artifactId/assessment → ContinueResearchAssessment
  assess: (artifactId) => http.get<ContinueResearchAssessment>(`/library/${artifactId}/assessment`),
};
