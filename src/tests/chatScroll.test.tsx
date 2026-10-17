/**
 * AI Chat scrolling. The conversation log is the ONLY thing that scrolls on the chat page: a fixed-height page (not a flex share that grows with the
 * conversation, which let the window scroll instead and cut long answers off under the footer), the log as a min-height:0 flex child with its own
 * overflow, and the composer pinned under it. New content is followed only while the reader is at the bottom; someone reading older messages is left
 * where they are. The intro's wheel handler is gone once the intro is.
 *
 * jsdom does no layout, so the stylesheet contract is read from disk, and the log's scroll metrics are supplied per test.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
// @ts-expect-error -- this project has no @types/node; vitest runs in Node, so the module exists at runtime
import { readFileSync } from 'node:fs';
import ChatPage from '@/pages/Chat/ChatPage';
import { isNearBottom, nextScrollTop, NEAR_BOTTOM_PX } from '@/pages/Chat/followScroll';
import { LaunchGate, LEAVE_MS } from '@/components/intro/LaunchGate';
import { resetMockThreads } from '@/data/mock/chatThreads';
import { api } from '@/api';
import { usePreferences } from '@/stores/preferences';
import type { ThreadAskInput } from '@/types';

const css = readFileSync('src/pages/Chat/chat.css', 'utf8') as string;
const rule = (sel: string) => {
  const i = css.indexOf(`\n${sel} {`);
  return i < 0 ? '' : css.slice(i, css.indexOf('}', i));
};
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '');

describe('the layout makes the conversation log the scroll container', () => {
  it('the page has a fixed height (not a flex share that grows with the conversation)', () => {
    const r = strip(rule('.chat-page'));
    expect(r).toMatch(/height:\s*var\(--chat-h\)/);
    expect(r).toMatch(/flex:\s*none/);
    expect(r).not.toMatch(/flex:\s*1\b/);
    expect(r).toMatch(/overflow:\s*hidden/);
  });

  it('the log scrolls on its own and the composer stays under it', () => {
    const main = strip(rule('.chat-main'));
    expect(main).toMatch(/display:\s*flex/);
    expect(main).toMatch(/flex-direction:\s*column/);
    expect(main).toMatch(/min-height:\s*0/);
    const log = strip(rule('.chat-log'));
    expect(log).toMatch(/flex:\s*1/);
    expect(log).toMatch(/min-height:\s*0/);
    expect(log).toMatch(/overflow-y:\s*auto/);
    expect(log).toMatch(/overscroll-behavior:\s*contain/); // reaching the end of the log does not scroll the page behind it
    expect(strip(rule('.chat-dock'))).toMatch(/flex:\s*none/);
  });
});

describe('following new content', () => {
  const log = (scrollTop: number, scrollHeight = 3000, clientHeight = 500) => ({ scrollTop, scrollHeight, clientHeight });

  it('"at the bottom" means within a small margin of it', () => {
    expect(isNearBottom(log(2500))).toBe(true);
    expect(isNearBottom(log(2500 - NEAR_BOTTOM_PX))).toBe(true);
    expect(isNearBottom(log(2500 - NEAR_BOTTOM_PX - 1))).toBe(false);
    expect(isNearBottom(log(0))).toBe(false);
  });

  it('a reader who scrolled up is left where they are', () => {
    expect(nextScrollTop(log(300), { follow: false })).toBeNull();
    expect(nextScrollTop(log(300), { follow: false, newAnswer: { offsetTop: 2000, offsetHeight: 900 } })).toBeNull();
  });

  it('at the bottom: short content is followed to the end, a long new answer is shown from its first line', () => {
    expect(nextScrollTop(log(2500), { follow: true })).toBe(2500);
    expect(nextScrollTop(log(2500), { follow: true, newAnswer: { offsetTop: 2700, offsetHeight: 200 } })).toBe(2500);
    expect(nextScrollTop(log(2500), { follow: true, newAnswer: { offsetTop: 1800, offsetHeight: 1100 } })).toBe(1788);
  });
});

// ------------------------------------------------------------------------------------------ on the page --
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
  fireEvent.change(screen.getByLabelText(/Your question|Ask/), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: 'Send question' }));
}
const idle = () => waitFor(() => expect(screen.queryByTestId('chat-progress')).not.toBeInTheDocument(), { timeout: 8000 });

/** jsdom has no layout: give the conversation log a fixed viewport and a tall content height. */
function fakeLayout(height = { value: 3000 }) {
  const isLog = (el: HTMLElement) => el.dataset?.testid === 'chat-log';
  const sh = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollHeight')!;
  const ch = Object.getOwnPropertyDescriptor(Element.prototype, 'clientHeight')!;
  vi.spyOn(Element.prototype, 'scrollHeight', 'get').mockImplementation(function (this: HTMLElement) {
    return isLog(this) ? height.value : (sh.get!.call(this) as number);
  });
  vi.spyOn(Element.prototype, 'clientHeight', 'get').mockImplementation(function (this: HTMLElement) {
    return isLog(this) ? 500 : (ch.get!.call(this) as number);
  });
  return height;
}

beforeEach(() => resetMockThreads());
afterEach(() => vi.restoreAllMocks());

describe('the conversation on the chat page', () => {
  it('follows a new message to the bottom, but never pulls back a reader who scrolled up', async () => {
    const height = fakeLayout();
    mount();
    await screen.findByTestId('chat-landing');
    await send('How has Nordvik Helseteknologi AS revenue changed?');
    await idle();
    const logEl = screen.getByTestId('chat-log');
    expect(logEl.scrollTop).toBe(2500); // at the end of the conversation

    // the reader scrolls up to read; a slow answer to a new question then streams in and lands
    const real = api.chat.threads.ask;
    let release: () => void = () => undefined;
    const gate = new Promise<void>((r) => (release = r));
    vi.spyOn(api.chat.threads, 'ask').mockImplementation(async (input: ThreadAskInput) => {
      await gate;
      input.onProgress?.({ stage: 'evidence', label: 'Checking the saved evidence' });
      return real({ ...input, onProgress: undefined });
    });
    await send('Who runs it?'); // sending follows: the question is shown
    await screen.findByTestId('chat-progress');
    expect(logEl.scrollTop).toBe(2500);
    logEl.scrollTop = 300;
    fireEvent.scroll(logEl);
    height.value = 4200; // more content arrives
    await act(async () => release());
    await idle();
    expect(logEl.scrollTop).toBe(300); // left where the reader was

    // back at the bottom: the next answer is followed again
    logEl.scrollTop = 3700 - NEAR_BOTTOM_PX + 10;
    fireEvent.scroll(logEl);
    height.value = 5000;
    vi.mocked(api.chat.threads.ask).mockImplementation(async (input: ThreadAskInput) => real({ ...input, onProgress: undefined }));
    // a follow-up chip or "Check for new information" is not needed: any new content while at the bottom is followed
    await send('What about hiring?');
    await idle();
    expect(logEl.scrollTop).toBe(4500);
  });

  it('long answers keep their sources and follow-up controls inside the scrolling log, with the composer outside it', async () => {
    mount();
    await screen.findByTestId('chat-landing');
    await send('How has Nordvik Helseteknologi AS revenue changed?');
    await idle();
    const logEl = screen.getByTestId('chat-log');
    expect(logEl.querySelector('.askai-sources')).not.toBeNull();
    expect(logEl.querySelector('[aria-label="Suggested follow-up questions"]')).not.toBeNull();
    const composer = screen.getByRole('button', { name: 'Send question' });
    expect(logEl.contains(composer)).toBe(false); // the composer is docked under the log, not scrolled away with it
    expect(composer.closest('.chat-dock')).not.toBeNull();
  });
});

describe('the intro never captures the wheel outside itself', () => {
  beforeEach(() => usePreferences.setState({ motion: 'full' }));

  it('once the intro is dismissed, wheel events on the page are not cancelled', () => {
    vi.useFakeTimers();
    render(
      <MemoryRouter>
        <LaunchGate>
          <div data-testid="app-scroll" style={{ overflowY: 'auto', height: 200 }}>
            content
          </div>
        </LaunchGate>
      </MemoryRouter>,
    );
    const intro = screen.getByTestId('launch-intro');
    const inside = new WheelEvent('wheel', { deltaY: 120, bubbles: true, cancelable: true });
    intro.querySelector('.li-tourbox')!.dispatchEvent(inside);
    expect(inside.defaultPrevented).toBe(true); // while it is up, the intro uses the wheel for its own cards
    fireEvent.click(screen.getByRole('button', { name: /Enter COGNIS/ }));
    act(() => void vi.advanceTimersByTime(LEAVE_MS + 50));
    expect(screen.queryByTestId('launch-intro')).not.toBeInTheDocument();
    for (const target of [screen.getByTestId('app-scroll'), document.body, document]) {
      const ev = new WheelEvent('wheel', { deltaY: 120, bubbles: true, cancelable: true });
      target.dispatchEvent(ev);
      expect(ev.defaultPrevented).toBe(false);
    }
    expect(document.documentElement).not.toHaveClass('cg-intro-lock'); // the page itself is scrollable again
    vi.useRealTimers();
  });
});
