/** AI Chat workspace: landing, history, persistence, isolation, company switching, answer rendering, and the CSS contracts (panel width, ivory composer, readable selection). */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
// @ts-expect-error node builtin, tests run under Node
import { readFileSync } from 'node:fs';
import ChatPage, { STARTERS } from '@/pages/Chat/ChatPage';
import { groupThreads } from '@/pages/Chat/ChatHistory';
import { Answer, ComparisonTable, dedupeAdjacent, FollowUps, Progress, splitCitations } from '@/components/chat/ChatParts';
import { PRIMARY_NAV } from '@/components/navigation/navItems';
import { createMockThreads, makeTitle, resetMockThreads } from '@/data/mock/chatThreads';
import { parseSse } from '@/api/http';
import { api } from '@/api';
import type { ChatReply, ChatSource, ChatThreadSummary } from '@/types';

const read = (rel: string): string => readFileSync(new URL('../' + rel, import.meta.url), 'utf8') as string;

function Where() {
  const l = useLocation();
  return <output data-testid="where">{l.pathname}</output>;
}
function mount(route = '/chat') {
  // a desktop-width window: the history sidebar is open
  window.matchMedia = ((query: string) => ({ matches: /min-width:\s*861px/.test(query), media: query, onchange: null, addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false })) as unknown as typeof window.matchMedia;
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/chat/:threadId?" element={<ChatPage />} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return view;
}
const composer = () => screen.getByLabelText('Your question') as HTMLTextAreaElement;
async function ask(text: string) {
  fireEvent.change(composer(), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: 'Send question' }));
}
const history = () => screen.getByRole('complementary', { name: 'Chat history' });

beforeEach(() => resetMockThreads());
afterEach(() => vi.restoreAllMocks());

describe('navigation and landing', () => {
  it('has AI Chat in the main navigation next to Research', () => {
    const labels = PRIMARY_NAV.map((n) => n.label);
    expect(labels.slice(0, 4)).toEqual(['Home', 'Discover', 'Research', 'AI Chat']);
    expect(PRIMARY_NAV.find((n) => n.label === 'AI Chat')?.to).toBe('/chat');
  });

  it('shows the Atlas logo, the heading, a large composer and starter prompts', async () => {
    mount();
    const landing = await screen.findByTestId('chat-landing');
    expect(within(landing).getByRole('heading', { level: 1, name: 'Ask COGNIS' })).toBeInTheDocument();
    expect(landing.querySelector('img[data-logo]')).toHaveAttribute('src', expect.stringMatching(/cognis-atlas-(ivory|navy)/));
    expect(composer().closest('form')).toHaveClass('chat-composer--large');
    expect(within(landing).getByRole('group', { name: 'Starter prompts' }).querySelectorAll('button')).toHaveLength(STARTERS.length);
  });

  it('a starter prompt fills the composer for the person to finish — it sends nothing and names no company', async () => {
    const spy = vi.spyOn(api.chat.threads, 'ask');
    mount();
    fireEvent.click(await screen.findByRole('button', { name: /Compare results year on year/ }));
    expect(composer().value).toBe('Compare the latest annual results of ');
    expect(spy).not.toHaveBeenCalled();
  });

  it('shows the empty history state', async () => {
    mount();
    expect(await screen.findByTestId('history-empty')).toHaveTextContent('No conversations yet');
  });
});

describe('a conversation end to end (demo data)', () => {
  it('asks from the landing page, shows progress, answers with citations, and appears in History', async () => {
    mount();
    await screen.findByTestId('chat-landing');
    await ask('How has Nordvik Helseteknologi AS revenue changed?');
    await waitFor(() => expect(screen.getByTestId('where').textContent).toMatch(/^\/chat\/.+/));
    expect(await screen.findByTestId('chat-progress')).toBeInTheDocument(); // real steps, not a fake spinner
    const log = await screen.findByTestId('chat-log');
    await waitFor(() => expect(within(log).getAllByText(/Nordvik/).length).toBeGreaterThan(0), { timeout: 6000 });
    await waitFor(() => expect(screen.queryByTestId('chat-progress')).not.toBeInTheDocument());
    expect(within(log).getAllByRole('button', { name: /^Source \d/ }).length).toBeGreaterThan(0);
    const list = within(history());
    expect(await list.findByRole('link', { name: /revenue changed/i })).toHaveAttribute('aria-current', 'page'); // title from the first message, active row marked
  });

  it('survives a reload and reopens from History without mixing threads', async () => {
    const first = mount();
    await screen.findByTestId('chat-landing');
    await ask('Who runs Nordvik Helseteknologi AS?');
    await waitFor(() => expect(screen.getByTestId('where').textContent).toMatch(/^\/chat\/.+/));
    await waitFor(() => expect(screen.queryByTestId('chat-progress')).not.toBeInTheDocument(), { timeout: 6000 });
    await within(history()).findByRole('link', { name: /Who runs/ });
    first.unmount();

    // a second, different company in its own conversation
    mount();
    await screen.findByTestId('chat-landing');
    await ask('What is the latest news at Tindra Software AS?');
    await waitFor(() => expect(screen.queryByTestId('chat-progress')).not.toBeInTheDocument(), { timeout: 6000 });
    await waitFor(() => expect(within(history()).getAllByRole('link').length).toBe(2));
    expect(within(screen.getByTestId('chat-log')).queryByText('Who runs Nordvik Helseteknologi AS?')).not.toBeInTheDocument(); // the other thread's question is not in this conversation
    fireEvent.click(within(history()).getByRole('link', { name: /Who runs/ }));
    expect(await within(screen.getByTestId('chat-log')).findByText('Who runs Nordvik Helseteknologi AS?')).toBeInTheDocument();
    expect(within(screen.getByTestId('chat-log')).queryByText(/news at Tindra/)).not.toBeInTheDocument();
  });

  it('asks which company when none is named, and answers once one is picked — without duplicating the question', async () => {
    mount();
    await screen.findByTestId('chat-landing');
    await ask('What was the revenue last year?');
    expect(await screen.findByText(/Which company do you mean/, undefined, { timeout: 6000 })).toBeInTheDocument();
    const t = await api.chat.threads.list();
    expect(t).toHaveLength(1);
    expect(t[0].company).toBeNull();
  });

  it('a question about another company continues in a NEW thread, with a notice in the old one', async () => {
    mount();
    await screen.findByTestId('chat-landing');
    await ask('Who runs Nordvik Helseteknologi AS?');
    await waitFor(() => expect(screen.queryByTestId('chat-progress')).not.toBeInTheDocument(), { timeout: 6000 });
    await within(history()).findByRole('link', { name: /Who runs/ });
    const oldPath = screen.getByTestId('where').textContent;
    await ask('And what about Tindra Software AS?');
    await waitFor(() => expect(screen.getByTestId('where').textContent).not.toBe(oldPath), { timeout: 6000 });
    expect(await screen.findByTestId('context-switch', undefined, { timeout: 6000 })).toHaveTextContent(/Tindra Software AS/);
    const threads = await api.chat.threads.list();
    expect(threads).toHaveLength(2);
    const old = await api.chat.threads.get(oldPath!.split('/').pop()!);
    expect(old.messages.at(-1)?.kind).toBe('context_notice'); // the old thread kept a notice and nothing from the other company
    expect(old.messages.some((m) => /Tindra/.test(JSON.stringify(m.payload?.citations ?? [])))).toBe(false);
  });

  it('renames and deletes from the history menu', async () => {
    await api.chat.threads.create({ id: 'thread-aaaa-1111', title: 'Alpha chat' });
    await api.chat.threads.create({ id: 'thread-bbbb-2222', title: 'Beta chat' });
    mount('/chat/thread-aaaa-1111');
    const h = within(await screen.findByRole('complementary', { name: 'Chat history' }));
    fireEvent.click(await h.findByRole('button', { name: 'Actions for Alpha chat' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: /Rename/ }));
    const field = await screen.findByLabelText('Title');
    fireEvent.change(field, { target: { value: 'Renamed chat' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await h.findByRole('link', { name: /Renamed chat/ })).toBeInTheDocument();

    fireEvent.click(h.getByRole('button', { name: 'Actions for Beta chat' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: /Delete/ }));
    expect(screen.getByText(/permanently removed/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(h.queryByRole('link', { name: /Beta chat/ })).not.toBeInTheDocument());
    await expect(api.chat.threads.get('thread-bbbb-2222')).rejects.toMatchObject({ code: 'not_found' });
  });

  it('says so when a conversation was deleted, instead of showing someone else’s', async () => {
    mount('/chat/gone-thread-0001');
    expect(await screen.findByText('This conversation is not available')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Start a new chat/ })).toHaveAttribute('href', '/chat');
  });
});

describe('mock thread store', () => {
  const deps = () => {
    let n = 0;
    return {
      companies: () => [
        { orgNumber: '921604337', legalName: 'Nordvik Helseteknologi AS' },
        { orgNumber: '810034882', legalName: 'Sandnes Elektriske AS' },
      ],
      reply: (org: string): ChatReply => ({ company: { orgNumber: org, legalName: org }, kind: 'evidence_only', answer: `answer ${++n}`, citations: [], sources: [], coverage: [], search: { state: 'not_used', note: '' }, origin: 'saved', generatedAt: '2026-10-14T10:00:00Z' }),
      wait: async () => undefined,
      now: () => new Date().toISOString(),
    };
  };
  it('the same message id never creates a second message or a second answer', async () => {
    const s = createMockThreads(deps());
    await s.create({ id: 'thread-idem-0001' });
    const a = await s.ask({ threadId: 'thread-idem-0001', messageId: 'msg-idem-0001', question: 'Revenue of Nordvik Helseteknologi AS?' });
    const b = await s.ask({ threadId: 'thread-idem-0001', messageId: 'msg-idem-0001', question: 'Revenue of Nordvik Helseteknologi AS?' });
    expect(b.assistantMessage.id).toBe(a.assistantMessage.id);
    expect((await s.get('thread-idem-0001')).messages).toHaveLength(2);
    expect(await s.list()).toHaveLength(1);
  });
  it('titles come from the first meaningful message and survive a rename', async () => {
    const s = createMockThreads(deps());
    await s.create({ id: 'thread-title-001' });
    await s.ask({ threadId: 'thread-title-001', messageId: 'msg-title-0001', question: 'Compare the latest results of Nordvik Helseteknologi AS with the previous year' });
    expect((await s.get('thread-title-001')).title).toMatch(/^Compare the latest results of Nordvik/);
    await s.rename('thread-title-001', 'My title');
    await s.ask({ threadId: 'thread-title-001', messageId: 'msg-title-0002', question: 'And equity?' });
    expect((await s.get('thread-title-001')).title).toBe('My title');
    expect(makeTitle('hi')).toBe('New chat');
    expect(makeTitle('x'.repeat(200)).length).toBeLessThanOrEqual(56);
  });
  it('delete removes the thread and its messages', async () => {
    const s = createMockThreads(deps());
    await s.create({ id: 'thread-del-00001' });
    await s.remove('thread-del-00001');
    await expect(s.get('thread-del-00001')).rejects.toMatchObject({ code: 'not_found' });
    expect(await s.list()).toHaveLength(0);
  });
});

describe('history grouping', () => {
  const th = (id: string, iso: string): ChatThreadSummary => ({ id, title: id, titleEdited: false, createdAt: iso, updatedAt: iso, company: null, messageCount: 1, preview: '' });
  it('groups into Today / Previous 7 days / Earlier, newest first', () => {
    const now = new Date('2026-10-14T15:00:00');
    const g = groupThreads([th('old', '2026-08-01T10:00:00'), th('week', '2026-10-10T10:00:00'), th('today-a', '2026-10-14T09:00:00'), th('today-b', '2026-10-14T12:00:00')], now);
    expect(g.map((x) => x.label)).toEqual(['Today', 'Previous 7 days', 'Earlier']);
    expect(g[0].items.map((i) => i.id)).toEqual(['today-b', 'today-a']);
  });
  it('omits empty groups', () => {
    expect(groupThreads([], new Date()).length).toBe(0);
  });
});

describe('answer rendering', () => {
  const src = (n: number, extra: Partial<ChatSource> = {}): ChatSource => ({ n, kind: 'fact', title: `Filing ${n}`, url: `https://data.example.no/${n}`, sourceLabel: 'Regnskapsregisteret', ...extra });
  const base = (over: Partial<ChatReply> = {}): ChatReply => ({
    company: { orgNumber: '921604337', legalName: 'Nordvik Helseteknologi AS' },
    kind: 'comparison',
    answer: 'Revenue fell [1][1] and profit rose [2].',
    citations: [src(1, { reportingPeriod: 'FY2025', retrievedAt: '2026-10-14T08:00:00Z', publishedAt: '2026-06-30T00:00:00Z', accountingScope: 'group', origin: 'fresh' }), src(2)],
    sources: [src(1), src(2), src(3)],
    coverage: [{ area: 'news', label: 'News', status: 'not_checked', note: 'Not checked.' }],
    search: { state: 'timeout', note: 'The news check timed out, so no news is claimed.' },
    origin: 'fresh',
    generatedAt: '2026-10-14T10:00:00Z',
    ...over,
  });

  it('collapses a repeated adjacent marker and keeps only real sources', () => {
    const parts = dedupeAdjacent(splitCitations('A [1][1] B [2] C [9]', [src(1), src(2)]));
    expect(parts.filter((p) => 'n' in p)).toEqual([{ n: 1 }, { n: 2 }]);
  });

  it('lists exactly the cited sources, separates published / retrieved / period, and names the domains', () => {
    render(<Answer reply={base()} turnId="t1" />);
    const list = screen.getByRole('region', { name: 'Sources' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(2); // source 3 was considered but not cited
    expect(list).toHaveTextContent('period FY2025');
    expect(list).toHaveTextContent('published 2026-06-30');
    expect(list).toHaveTextContent('retrieved 2026-10-14');
    expect(list).toHaveTextContent('consolidated');
    expect(list).toHaveTextContent('found just now');
    expect(list).toHaveTextContent('Domains used: data.example.no');
    expect(screen.getAllByRole('button', { name: 'Source 1' })).toHaveLength(1);
  });

  it('a timed-out check is stated as a timeout, never as success, and cached vs fresh is labelled', () => {
    render(<Answer reply={base()} turnId="t2" />);
    expect(screen.getByText(/timed out, so no news is claimed/)).toBeInTheDocument();
    expect(screen.getByText(/Includes information checked just now/)).toBeInTheDocument();
    render(<Answer reply={base({ origin: 'saved', search: { state: 'not_used', note: '' } })} turnId="t3" />);
    expect(screen.getByText(/From saved research \(not re-checked/)).toBeInTheDocument();
  });

  it('shows the comparison with both periods, the ranking criterion and every formula', () => {
    render(
      <ComparisonTable
        data={{
          periods: ['FY2024', 'FY2025'],
          rankedBy: 'percent',
          omitted: ['Equity: only 1 reporting period has a filed value.'],
          rows: [{ metric: 'revenue', label: 'Revenue', scope: 'company', currency: 'USD', previous: { period: 'FY2024', value: 72_540_000_000 }, latest: { period: 'FY2025', value: 67_960_000_000 }, absoluteChange: -4_580_000_000, percentChange: -6.31, formula: 'USD 67.96B − USD 72.54B = −USD 4.58B; (−USD 4.58B ÷ USD 72.54B) × 100 = −6.31%' }],
        }}
      />,
    );
    const region = screen.getByRole('region', { name: 'Period comparison' });
    expect(region).toHaveTextContent('Ranked by percentage change');
    expect(region).toHaveTextContent('FY2024');
    expect(region).toHaveTextContent('−6.31%');
    expect(region).toHaveTextContent('−4,580,000,000');
    expect(region).toHaveTextContent('USD 67.96B − USD 72.54B = −USD 4.58B');
    expect(region).toHaveTextContent('Left out of the comparison (1)');
  });

  it('follow-ups are compact, send through the callback, and can be dismissed', () => {
    const pick = vi.fn();
    render(<FollowUps items={['Show the original filing', 'Which claims could not be verified?']} onPick={pick} />);
    fireEvent.click(screen.getByRole('button', { name: 'Show the original filing' }));
    expect(pick).toHaveBeenCalledWith('Show the original filing');
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss follow-up suggestions' }));
    expect(screen.queryByRole('group', { name: 'Suggested follow-up questions' })).not.toBeInTheDocument();
  });

  it('progress shows a few plain stages that follow what really started', () => {
    render(<Progress steps={[{ stage: 'identity', label: 'Confirming the company' }, { stage: 'news', label: 'Checking announcements' }]} label="x" />);
    const p = screen.getByTestId('chat-progress');
    expect(p.querySelector('[data-state="done"]')).toHaveTextContent('Understanding your question');
    expect(p.querySelector('[data-state="active"]')).toHaveTextContent('Checking current sources');
    expect(p.querySelector('[data-state="active"]')).toHaveTextContent('Checking announcements'); // what it is doing right now
  });

  it('a clarification offers the matching companies to pick', () => {
    const pick = vi.fn();
    render(<Answer reply={base({ kind: 'clarification', answer: 'More than one company matches.', citations: [], sources: [], candidates: [{ orgNumber: '921604337', legalName: 'Nordvik Helseteknologi AS' }] })} turnId="t4" onPick={pick} />);
    fireEvent.click(screen.getByRole('button', { name: /Nordvik Helseteknologi AS/ }));
    expect(pick).toHaveBeenCalledWith(expect.objectContaining({ orgNumber: '921604337' }));
  });
});

describe('server-sent events', () => {
  it('parses progress and result blocks and keeps a partial block for later', () => {
    const { events, rest } = parseSse('event: progress\ndata: {"stage":"a","label":"One"}\n\nevent: result\ndata: {"ok":true}\n\nevent: progr');
    expect(events).toEqual([{ event: 'progress', data: { stage: 'a', label: 'One' } }, { event: 'result', data: { ok: true } }]);
    expect(rest).toBe('event: progr');
  });
  it('skips a malformed block instead of showing it', () => {
    expect(parseSse('event: result\ndata: {oops\n\n').events).toEqual([]);
  });
});

describe('styling contracts (jsdom loads no CSS, so the stylesheets are pinned)', () => {
  const panel = read('components/chat/ask-ai.css');
  const page = read('pages/Chat/chat.css');
  const base = read('styles/base.css');
  const tokens = read('styles/tokens.css');

  it('the side panel is 520–650 px wide on desktop, wider on large screens, and a full-width sheet on a phone', () => {
    expect(panel).toMatch(/width:\s*min\(clamp\(520px,\s*40vw,\s*650px\),\s*100vw\)/);
    expect(panel).toMatch(/@media \(min-width: 1920px\)\s*\{\s*\.askai\s*\{\s*width:\s*720px/);
    expect(panel).toMatch(/@media \(max-width: 640px\)\s*\{\s*\.askai\s*\{[^}]*width:\s*100vw/);
  });
  it('the message area scrolls on its own and long URLs cannot overflow it', () => {
    expect(panel).toMatch(/\.askai-log\s*\{[^}]*overflow-y:\s*auto;[^}]*overflow-x:\s*hidden/s);
    expect(panel).toMatch(/\.askai-msg\s*\{[^}]*overflow-wrap:\s*anywhere/s);
    expect(panel).toMatch(/\.askai-msg a\s*\{[^}]*word-break:\s*break-word/s);
  });
  it('the composer and prompt cards use ivory with navy ink — explicit tokens, so both themes match', () => {
    const rule = (css: string, sel: string) => css.match(new RegExp(`${sel.replace(/[.[\]]/g, '\\$&')}[^{]*\\{([^}]*)\\}`))?.[1] ?? '';
    expect(rule(panel, '.chat-composer__input,')).toMatch(/background:\s*var\(--ivory-field\)/);
    expect(rule(panel, '.chat-composer__input,')).toMatch(/color:\s*var\(--ivory-ink\)/);
    expect(rule(panel, '.askai-prompt')).toMatch(/background:\s*var\(--ivory-field\)/);
    expect(rule(panel, '.askai-prompt')).toMatch(/color:\s*var\(--ivory-ink\)/);
    expect(panel).not.toMatch(/\.chat-composer[^{]*\{[^}]*var\(--surface-/); // never the page's surface tokens
    // the ivory tokens are defined once at :root, so they are identical in dark and light
    expect(tokens).toMatch(/--ivory-field:\s*#fffdf8/);
    expect(tokens).toMatch(/--ivory-ink:\s*#0f1b2a/);
  });
  it('the send button has clear focus, disabled and loading styles', () => {
    expect(panel).toMatch(/\.chat-composer__send:focus-visible/);
    expect(panel).toMatch(/\.chat-composer__send:disabled/);
    expect(panel).toMatch(/\.chat-composer__spin/);
  });

  const lum = (hex: string) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const contrast = (a: string, b: string) => {
    const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
  };
  it('selected text is readable on ivory, white and navy surfaces, and every chat surface uses it', () => {
    const bg = tokens.match(/--selection-bg:\s*(#[0-9a-f]{6})/i)![1];
    const fg = tokens.match(/--selection-fg:\s*(#[0-9a-f]{6})/i)![1];
    expect(contrast(bg, fg)).toBeGreaterThanOrEqual(4.5); // selected text against its own highlight
    for (const surface of ['#fbf8f1', '#fffdf8', '#ffffff', '#0b1626']) expect(contrast(bg, surface)).toBeGreaterThanOrEqual(3); // the highlight stands out from the surface
    expect(base).toMatch(/::selection\s*\{[^}]*var\(--selection-bg\)[^}]*var\(--selection-fg\)/s);
    for (const sel of ['textarea::selection', '.askai-msg ::selection', '.askai-cite::selection', '.askai-sources ::selection', '.askai-prompt ::selection', '.chat-history ::selection']) expect(base).toContain(sel);
    expect(base).not.toMatch(/::selection\s*\{[^}]*accent-wash/); // the old translucent wash (invisible on the ivory bubble) is gone
  });

  it('history collapses to a slide-over on narrow screens, and motion respects reduced-motion', () => {
    expect(page).toMatch(/@media \(max-width: 860px\)[\s\S]*\.chat-history-wrap\s*\{[^}]*position:\s*absolute/);
    expect(page).toMatch(/data-motion='reduced'\] \.chat-landing/);
    expect(page).toMatch(/prefers-reduced-motion: reduce/);
    expect(panel).toMatch(/prefers-reduced-motion: reduce\)\s*\{\s*:root:not\(\[data-motion='full'\]\) \.chat-composer__spin/);
  });
});

describe('keyboard', () => {
  it('Enter sends, Shift+Enter does not, and the composer is labelled', async () => {
    const spy = vi.spyOn(api.chat.threads, 'ask');
    mount();
    await screen.findByTestId('chat-landing');
    fireEvent.change(composer(), { target: { value: 'Revenue of Nordvik Helseteknologi AS?' } });
    fireEvent.keyDown(composer(), { key: 'Enter', shiftKey: true });
    expect(spy).not.toHaveBeenCalled();
    expect(screen.getByTestId('where').textContent).toBe('/chat');
    fireEvent.keyDown(composer(), { key: 'Enter' });
    await waitFor(() => expect(screen.getByTestId('where').textContent).toMatch(/^\/chat\/.+/));
  });
});
