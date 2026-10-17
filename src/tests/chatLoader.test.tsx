/**
 * The chat answer loader: a rotating COGNIS orbit (CSS transforms only) and a few plain-language stages that follow what the server really reports.
 * A stage is never shown as done before the server has moved past it; per-source detail stays in a collapsed section; the loader goes away when the
 * request ends, whether it succeeded or failed.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import loaderSource from '@/components/chat/ChatLoader.tsx?raw';
// @ts-expect-error -- this project has no @types/node; vitest runs in Node, so the module exists at runtime
import { readFileSync } from 'node:fs';
import { ChatLoader, chatSources, chatStages } from '@/components/chat/ChatLoader';
import ChatPage from '@/pages/Chat/ChatPage';
import { resetMockThreads } from '@/data/mock/chatThreads';
import { api, ApiError } from '@/api';
import type { ChatProgress, ThreadAskInput } from '@/types';

// jsdom loads no stylesheets, so the CSS contract is read from disk (vitest runs from the project root)
const css = readFileSync('src/components/chat/ask-ai.css', 'utf8') as string;
const states = (steps: ChatProgress[]) => Object.fromEntries(chatStages(steps).map((r) => [r.phase, r.state]));

describe('stages follow the server, never ahead of it', () => {
  it('before any event: understanding is in progress, nothing is done, no research row is invented', () => {
    expect(states([])).toEqual({ understand: 'active', evidence: 'waiting', answer: 'waiting' });
  });

  it('moves on only as the server does, in its own order', () => {
    const s1: ChatProgress[] = [{ stage: 'understand', label: 'Understanding your question' }, { stage: 'identity', label: 'Checking company register' }];
    expect(states(s1)).toEqual({ understand: 'active', evidence: 'waiting', answer: 'waiting' });
    const s2 = [...s1, { stage: 'evidence', label: 'Checking the saved evidence' }, { stage: 'research', label: 'Checking current sources for this question' }];
    expect(states(s2)).toEqual({ understand: 'done', evidence: 'done', research: 'active', answer: 'waiting' });
    const s3 = [...s2, { stage: 'evidence', label: 'Selecting the relevant evidence' }, { stage: 'answer', label: 'Writing the answer' }];
    expect(states(s3)).toEqual({ understand: 'done', evidence: 'done', research: 'done', answer: 'active' });
  });

  it('a stage that never started is never shown as done', () => {
    expect(states([{ stage: 'identity', label: 'x' }, { stage: 'answer', label: 'y' }])).toEqual({ understand: 'done', evidence: 'waiting', answer: 'active' });
  });

  it('going back to check current sources after a first draft puts the answer back to waiting', () => {
    const steps: ChatProgress[] = ['understand', 'evidence', 'answer', 'research'].map((stage) => ({ stage, label: stage }));
    expect(states(steps)).toEqual({ understand: 'done', evidence: 'done', research: 'active', answer: 'waiting' });
  });

  it('the active stage carries what the server is doing right now; source events are details, not stages', () => {
    const steps: ChatProgress[] = [
      { stage: 'research', label: 'Checking current sources for this question' },
      { stage: 'source', label: 'e24.no', source: { name: 'e24.no', url: 'https://e24.no/a', state: 'checking' } },
      { stage: 'research', label: 'Reading 2 pages that may answer it' },
      { stage: 'source', label: 'e24.no', source: { name: 'e24.no', url: 'https://e24.no/a', state: 'used', reason: 'names the company' } },
      { stage: 'source', label: 'example.com', source: { name: 'example.com', url: 'https://example.com/x', state: 'skipped', reason: 'not permitted' } },
    ];
    const rows = chatStages(steps);
    expect(rows.find((r) => r.state === 'active')).toMatchObject({ phase: 'research', detail: 'Reading 2 pages that may answer it' });
    expect(rows).toHaveLength(4);
    expect(chatSources(steps)).toEqual([
      { name: 'e24.no', url: 'https://e24.no/a', state: 'used', reason: 'names the company' },
      { name: 'example.com', url: 'https://example.com/x', state: 'skipped', reason: 'not permitted' },
    ]);
  });
});

describe('the loader', () => {
  it('shows the orbit, the stages, and source details collapsed until asked for', () => {
    render(
      <ChatLoader
        steps={[
          { stage: 'evidence', label: 'Checking the saved evidence' },
          { stage: 'research', label: 'Searching permitted sources for this question' },
          { stage: 'source', label: 'Web search (Tavily)', source: { name: 'Web search (Tavily)', state: 'used', reason: '3 result(s)' } },
        ]}
      />,
    );
    const box = screen.getByTestId('chat-progress');
    expect(box).toHaveAttribute('role', 'status');
    expect(screen.getByTestId('chat-orbit')).toHaveAttribute('aria-hidden', 'true');
    expect(screen.getByRole('list', { name: 'Progress' }).children).toHaveLength(4);
    expect(box).toHaveTextContent('Checking current sources');
    const details = box.querySelector('details')!;
    expect(details.open).toBe(false);
    expect(details).toHaveTextContent('Sources checked (1)');
    fireEvent.click(details.querySelector('summary')!);
    expect(details.open).toBe(true);
  });

  it('motion is CSS transforms only: no blur or filters, no canvas, no JavaScript animation loop, and it stops under reduced motion', () => {
    expect(loaderSource).not.toMatch(/requestAnimationFrame|setInterval|setTimeout|<canvas|getContext/);
    const block = css.slice(css.indexOf('/* ---- answer loader'), css.indexOf('/* ---- composer')).replace(/\/\*[\s\S]*?\*\//g, '');
    expect(block).toMatch(/@keyframes cg-orbit-spin\s*{\s*to\s*{\s*transform:\s*rotate\(360deg\)/);
    expect(block).not.toMatch(/filter|blur|will-change/);
    expect(block).toMatch(/:root\[data-motion='reduced'\] \.cg-orbit \*/);
    expect(block).toMatch(/@media \(prefers-reduced-motion: reduce\)\s*{\s*:root:not\(\[data-motion='full'\]\) \.cg-orbit \*/);
  });
});

// ------------------------------------------------------------------------------------- on the page --
function mount() {
  window.matchMedia = ((query: string) => ({ matches: /min-width:\s*861px/.test(query), media: query, onchange: null, addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false })) as typeof window.matchMedia;
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/chat']}>
        <Routes>
          <Route path="/chat/:threadId?" element={<ChatPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
async function send(text: string) {
  fireEvent.change(screen.getByLabelText('Your question'), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: 'Send question' }));
}

beforeEach(() => resetMockThreads());
afterEach(() => vi.restoreAllMocks());

describe('the loader on the chat page', () => {
  it('follows a slow streamed answer and disappears when it arrives', async () => {
    const real = api.chat.threads.ask;
    let release: () => void = () => undefined;
    const gate = new Promise<void>((r) => (release = r));
    vi.spyOn(api.chat.threads, 'ask').mockImplementation(async (input: ThreadAskInput) => {
      input.onProgress?.({ stage: 'understand', label: 'Understanding your question' });
      input.onProgress?.({ stage: 'evidence', label: 'Checking the saved evidence' });
      await gate;
      return real({ ...input, onProgress: undefined });
    });
    mount();
    await screen.findByTestId('chat-landing');
    await send('How has Nordvik Helseteknologi AS revenue changed?');
    const box = await screen.findByTestId('chat-progress');
    await waitFor(() => expect(box.querySelector('[data-state="active"]')).toHaveTextContent('Checking relevant evidence'));
    expect(box.querySelector('[data-state="done"]')).toHaveTextContent('Understanding your question');
    expect(box).not.toHaveTextContent('Preparing your sourced answer (done)');
    await act(async () => release());
    await waitFor(() => expect(screen.queryByTestId('chat-progress')).not.toBeInTheDocument(), { timeout: 8000 });
  });

  it('disappears on an error, leaving the error and a retry instead', async () => {
    vi.spyOn(api.chat.threads, 'ask').mockImplementation(async (input: ThreadAskInput) => {
      input.onProgress?.({ stage: 'understand', label: 'Understanding your question' });
      throw new ApiError('unavailable', 'The AI service did not respond.', 503);
    });
    mount();
    await screen.findByTestId('chat-landing');
    await send('How has Nordvik Helseteknologi AS revenue changed?');
    await waitFor(() => expect(screen.queryByTestId('chat-progress')).not.toBeInTheDocument());
    expect(await screen.findByRole('button', { name: /retry|try again/i })).toBeInTheDocument();
  });
});
