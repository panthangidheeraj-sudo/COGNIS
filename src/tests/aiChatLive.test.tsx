/** The live chat client: progress events reach the UI, a stream that never produces a result is an error (never a silent success), and the panel shows backend follow-ups. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { liveChat } from '@/api/chat';
import { api, ApiError } from '@/api';
import { AskAiPanel } from '@/components/chat/AskAiPanel';
import { renderWithProviders } from './utils';
import type { ChatContext, ChatProgress, ChatReply } from '@/types';

const sse = (blocks: string[]): Response => {
  const enc = new TextEncoder();
  const body = new ReadableStream({
    start(c) {
      for (const b of blocks) c.enqueue(enc.encode(b));
      c.close();
    },
  });
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
};
afterEach(() => vi.restoreAllMocks());

describe('live chat client', () => {
  it('reports progress as it arrives, then resolves the result — even when events are split across chunks', async () => {
    const result = { threadId: 'thread-live-0001', thread: { id: 'thread-live-0001' }, userMessage: { id: 'u' }, assistantMessage: { id: 'a' } };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sse(['event: progress\ndata: {"stage":"identity","la', 'bel":"Confirming"}\n\nevent: progress\ndata: {"stage":"news","label":"News"}\n\n', `event: result\ndata: ${JSON.stringify(result)}\n\n`])));
    const seen: ChatProgress[] = [];
    const out = await liveChat.threads.ask({ threadId: 'thread-live-0001', messageId: 'msg-live-0001', question: 'q', onProgress: (p) => seen.push(p) });
    expect(seen.map((p) => p.label)).toEqual(['Confirming', 'News']);
    expect(out.threadId).toBe('thread-live-0001');
    const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(url)).toContain('/chat/threads/thread-live-0001/ask/stream');
    expect(JSON.parse(init.body)).toMatchObject({ messageId: 'msg-live-0001', question: 'q' });
  });

  it('an error event becomes an ApiError with the server’s code', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sse(['event: error\ndata: {"code":"rate_limited","message":"Slow down."}\n\n'])));
    await expect(liveChat.threads.ask({ threadId: 'thread-live-0001', messageId: 'msg-live-0002', question: 'q' })).rejects.toMatchObject({ code: 'rate_limited', message: 'Slow down.' });
  });

  it('a stream that ends with no result is reported as unfinished — not as an answer', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sse(['event: progress\ndata: {"stage":"a","label":"One"}\n\n'])));
    const err = await liveChat.threads.ask({ threadId: 'thread-live-0001', messageId: 'msg-live-0003', question: 'q' }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toMatch(/did not finish/);
  });

  it('a 404 before the stream opens is a not_found error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 'not_found', message: 'gone' }), { status: 404 })));
    await expect(liveChat.threads.ask({ threadId: 'thread-live-0001', messageId: 'msg-live-0004', question: 'q' })).rejects.toMatchObject({ code: 'not_found' });
  });
});

describe('side panel uses the same answer rendering', () => {
  const ctx: ChatContext = {
    company: { orgNumber: '921604337', legalName: 'Nordvik Helseteknologi AS' },
    suggestions: ['How has its revenue changed?'],
    coverage: [],
    capabilities: { chat: true, aiModel: false, freshResearch: false, maxQuestionChars: 500 },
  };
  const reply: ChatReply = {
    company: ctx.company,
    kind: 'evidence_only',
    answer: 'Revenue was NOK 790.4 million [1][1].',
    citations: [{ n: 1, kind: 'fact', title: 'Annual accounts 2025', url: 'https://data.brreg.no/x', sourceLabel: 'Regnskapsregisteret' }],
    sources: [{ n: 1, kind: 'fact', title: 'Annual accounts 2025', url: 'https://data.brreg.no/x', sourceLabel: 'Regnskapsregisteret' }],
    coverage: [],
    search: { state: 'not_used', note: '' },
    origin: 'saved',
    generatedAt: '2026-10-14T10:00:00Z',
    followUps: ['Compare this with the previous reporting period'],
  };

  it('streams progress into the panel, shows one marker for a repeated citation, and sends a follow-up through the same pipeline', async () => {
    vi.spyOn(api.chat, 'context').mockResolvedValue(ctx);
    const ask = vi.spyOn(api.chat, 'ask').mockImplementation(async (_i, onProgress) => {
      onProgress?.({ stage: 'financials', label: 'Reading the filed accounts' });
      await new Promise((r) => setTimeout(r, 30));
      return reply;
    });
    renderWithProviders(<AskAiPanel orgNumber="921604337" legalName="Nordvik Helseteknologi AS" onClose={() => undefined} />);
    await screen.findByRole('group', { name: 'Suggested questions' });
    fireEvent.change(screen.getByLabelText(/Your question about/), { target: { value: 'Revenue?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send question' }));
    expect(await screen.findByText('Reading the filed accounts')).toBeInTheDocument();
    await screen.findByText(/Revenue was NOK 790.4 million/);
    expect(screen.getAllByRole('button', { name: 'Source 1' })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Compare this with the previous reporting period' }));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0].question).toBe('Compare this with the previous reporting period');
    expect(ask.mock.calls[1][0].orgNumber).toBe('921604337'); // still the same verified company
  });
});
