import type { ChatApi } from './contract';
import { http } from './http';
import type { ChatContext, ChatProgress, ChatReply, ChatThread, ChatThreadSummary, ThreadAskResult } from '@/types';

/** Live company chat. Secrets stay on the server: the browser only sends the question and earlier turns. */
export const liveChat: ChatApi = {
  // GET /companies/:org/chat/context → ChatContext
  context: (orgNumber) => http.get<ChatContext>(`/companies/${orgNumber}/chat/context`),
  // POST /companies/:org/chat/stream (SSE: progress… result) → ChatReply
  ask: ({ orgNumber, question, messages, expectedName, fresh }, onProgress) =>
    http.stream<ChatReply>(`/companies/${orgNumber}/chat/stream`, { question, messages, expectedName, fresh: !!fresh }, onProgress as ((p: never) => void) | undefined),
  threads: {
    // GET /chat/threads → { threads }
    list: async () => (await http.get<{ threads: ChatThreadSummary[] }>('/chat/threads')).threads,
    // GET /chat/threads/:id → ChatThread (with messages)
    get: (id) => http.get<ChatThread>(`/chat/threads/${encodeURIComponent(id)}`),
    // POST /chat/threads  body: { id, orgNumber?, title? } — idempotent by id
    create: (input) => http.post<ChatThreadSummary>('/chat/threads', input),
    // PATCH /chat/threads/:id  body: { title }
    rename: (id, title) => http.patch<ChatThreadSummary>(`/chat/threads/${encodeURIComponent(id)}`, { title }),
    // DELETE /chat/threads/:id — removes the conversation and every stored message
    remove: async (id) => {
      await http.del(`/chat/threads/${encodeURIComponent(id)}`);
    },
    // POST /chat/threads/:id/ask/stream  body: { messageId, question, orgNumber?, fresh?, retryOf? } (SSE: progress… result)
    ask: ({ threadId, messageId, question, orgNumber, fresh, retryOf, onProgress, signal }) =>
      http.stream<ThreadAskResult>(`/chat/threads/${encodeURIComponent(threadId)}/ask/stream`, { messageId, question, orgNumber, fresh: !!fresh, retryOf }, onProgress as ((p: ChatProgress) => void) | undefined as never, signal),
  },
};
