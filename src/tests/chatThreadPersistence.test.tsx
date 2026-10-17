/** One conversation = one thread. Several messages in a row create exactly one thread, share its id, and are restored after a reload. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import ChatPage from '@/pages/Chat/ChatPage';
import { resetMockThreads } from '@/data/mock/chatThreads';
import { api } from '@/api';

function Where() {
  const l = useLocation();
  return <output data-testid="where">{l.pathname}</output>;
}
function mount(route = '/chat') {
  window.matchMedia = ((query: string) => ({ matches: /min-width:\s*861px/.test(query), media: query, onchange: null, addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false })) as typeof window.matchMedia;
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/chat/:threadId?" element={<ChatPage />} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
const composer = () => screen.getByLabelText('Your question') as HTMLTextAreaElement;
async function send(text: string) {
  fireEvent.change(composer(), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: 'Send question' }));
}
const idle = () => waitFor(() => expect(screen.queryByTestId('chat-progress')).not.toBeInTheDocument(), { timeout: 8000 });
const history = () => screen.getByRole('complementary', { name: 'Chat history' });

beforeEach(() => resetMockThreads());
afterEach(() => vi.restoreAllMocks());

const Q1 = 'How has Nordvik Helseteknologi AS revenue changed?';
const Q2 = 'And who runs it?';
const Q3 = 'What about its hiring?';

describe('thread persistence', () => {
  it('three messages in a row use ONE thread: one create, one id on every ask, one row in History', async () => {
    const create = vi.spyOn(api.chat.threads, 'create');
    const ask = vi.spyOn(api.chat.threads, 'ask');
    mount();
    await screen.findByTestId('chat-landing');
    await send(Q1);
    await waitFor(() => expect(screen.getByTestId('where').textContent).toMatch(/^\/chat\/.+/));
    const path = screen.getByTestId('where').textContent!;
    await idle();
    await send(Q2);
    await idle();
    await send(Q3);
    await idle();

    expect(create).toHaveBeenCalledTimes(1);
    expect(ask).toHaveBeenCalledTimes(3);
    const ids = new Set(ask.mock.calls.map((c) => c[0].threadId));
    expect(ids.size).toBe(1);
    expect(`/chat/${[...ids][0]}`).toBe(path); // the URL never left this thread
    expect(screen.getByTestId('where').textContent).toBe(path);

    const threads = await api.chat.threads.list();
    expect(threads).toHaveLength(1); // not one conversation per message
    expect(threads[0].messageCount).toBe(6);
    await waitFor(() => expect(within(history()).getAllByRole('link')).toHaveLength(1));

    // the follow-ups kept the company and the history on the server
    const stored = await api.chat.threads.get(threads[0].id);
    expect(stored.messages.filter((m) => m.role === 'user').map((m) => m.content)).toEqual([Q1, Q2, Q3]);
    expect(new Set(stored.messages.map((m) => m.role))).toEqual(new Set(['user', 'assistant']));
    expect(stored.company?.orgNumber).toBeTruthy();
  });

  it('the conversation is restored after a reload (new page load, same URL)', async () => {
    const first = mount();
    await screen.findByTestId('chat-landing');
    await send(Q1);
    await waitFor(() => expect(screen.getByTestId('where').textContent).toMatch(/^\/chat\/.+/));
    await idle();
    await send(Q2);
    await idle();
    await send(Q3);
    await idle();
    const path = screen.getByTestId('where').textContent!;
    first.unmount();

    const create = vi.spyOn(api.chat.threads, 'create');
    mount(path); // reload: empty query cache, the thread id comes from the URL
    const log = await screen.findByTestId('chat-log');
    for (const q of [Q1, Q2, Q3]) expect(await within(log).findByText(q)).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
    expect(await api.chat.threads.list()).toHaveLength(1);

    // a message after the reload continues the same thread
    const ask = vi.spyOn(api.chat.threads, 'ask');
    await send('Who is the chair?');
    await idle();
    expect(ask.mock.calls[0][0].threadId).toBe(path.replace('/chat/', ''));
    expect(create).not.toHaveBeenCalled();
    expect(await api.chat.threads.list()).toHaveLength(1);
  });

  it('a failed first answer and its retry do not create a second thread', async () => {
    const create = vi.spyOn(api.chat.threads, 'create');
    const real = api.chat.threads.ask.bind(api.chat.threads);
    const ask = vi.spyOn(api.chat.threads, 'ask').mockRejectedValueOnce(new Error('network down')).mockImplementation(real);
    mount();
    await screen.findByTestId('chat-landing');
    await send(Q1);
    fireEvent.click(await screen.findByRole('button', { name: /Retry/ }));
    await idle();
    await send(Q2);
    await idle();
    expect(ask.mock.calls.length).toBe(3);
    expect(new Set(ask.mock.calls.map((c) => c[0].threadId)).size).toBe(1);
    expect(create.mock.calls.length).toBe(1); // the thread is created once, not on every attempt
    expect(await api.chat.threads.list()).toHaveLength(1);
  });

  it('only New chat starts another conversation, and it creates nothing until a message is sent', async () => {
    const create = vi.spyOn(api.chat.threads, 'create');
    mount();
    await screen.findByTestId('chat-landing');
    await send(Q1);
    await waitFor(() => expect(screen.getByTestId('where').textContent).toMatch(/^\/chat\/.+/));
    await idle();
    const firstPath = screen.getByTestId('where').textContent!;
    fireEvent.click(within(history()).getByRole('button', { name: /New chat/ }));
    await screen.findByTestId('chat-landing');
    expect(screen.getByTestId('where').textContent).toBe('/chat');
    expect(create).toHaveBeenCalledTimes(1); // opening New chat is not a conversation yet
    await send('Who runs Tindra Software AS?');
    await waitFor(() => expect(screen.getByTestId('where').textContent).toMatch(/^\/chat\/.+/));
    await idle();
    expect(screen.getByTestId('where').textContent).not.toBe(firstPath);
    expect(create).toHaveBeenCalledTimes(2);
    expect(await api.chat.threads.list()).toHaveLength(2);
  });

  it('"Check for new information" re-asks the SAME question in the SAME thread with live sources, and keeps the question where it was', async () => {
    const create = vi.spyOn(api.chat.threads, 'create');
    const ask = vi.spyOn(api.chat.threads, 'ask');
    mount();
    await screen.findByTestId('chat-landing');
    await send(Q1);
    await waitFor(() => expect(screen.getByTestId('where').textContent).toMatch(/^\/chat\/.+/));
    await idle();
    const more = await screen.findByRole('button', { name: /Check for new information/ });
    fireEvent.click(more);
    await idle();
    expect(ask).toHaveBeenCalledTimes(2);
    const [first, second] = ask.mock.calls.map((c) => c[0]);
    expect(second.fresh).toBe(true);
    expect(second.retryOf).toBe(first.messageId); // answers that question again: no second copy of it
    expect(second.threadId).toBe(first.threadId);
    expect(create).toHaveBeenCalledTimes(1);
    const threads = await api.chat.threads.list();
    expect(threads).toHaveLength(1);
    const stored = await api.chat.threads.get(threads[0].id);
    expect(stored.messages.filter((m) => m.role === 'user')).toHaveLength(1);
    expect(stored.messages[0].role).toBe('user'); // the question is still first
    const log = screen.getByTestId('chat-log');
    expect(within(log).getAllByText(Q1)).toHaveLength(1);
  });
});
