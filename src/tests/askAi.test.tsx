/** Company "Ask AI" panel: identity, grounded citations, honest statuses, failure and retry, no silent company switching. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { renderWithProviders } from './utils';
import { AskAiPanel, COVERAGE_LABEL, historyOf, splitCitations } from '@/components/chat/AskAiPanel';
import { api, ApiError } from '@/api';
import chatClient from '@/api/chat.ts?raw';
import panelSource from '@/components/chat/AskAiPanel.tsx?raw';
import mockChat from '@/data/mock/chat.ts?raw';
import type { ChatContext, ChatReply, ChatSource } from '@/types';

const ORG = '921604337';
const NAME = 'Nordvik Helseteknologi AS';

const src = (n: number, extra: Partial<ChatSource> = {}): ChatSource => ({ n, kind: 'fact', title: `Source ${n} title`, url: `https://example.org/${n}`, sourceLabel: 'Regnskapsregisteret', ...extra });
const context = (over: Partial<ChatContext> = {}): ChatContext => ({
  company: { orgNumber: ORG, legalName: NAME },
  suggestions: ['How has its revenue changed?', 'Who runs this company?', 'Does it have patents or regulatory issues?'],
  coverage: [
    { area: 'financials', label: 'Financial statements', status: 'verified', note: 'Filed accounts read.' },
    { area: 'ip', label: 'Patents, trademarks and designs', status: 'unavailable', note: 'Needs a registered key; not used.' },
    { area: 'news', label: 'News', status: 'no_public_results_found', note: 'Nothing found.' },
  ],
  capabilities: { chat: true, aiModel: true, freshResearch: true, maxQuestionChars: 200 },
  ...over,
});
const reply = (over: Partial<ChatReply> = {}): ChatReply => ({
  company: { orgNumber: ORG, legalName: NAME },
  kind: 'model',
  answer: 'Revenue was NOK 10.0 million in 2024 [1]. Invented marker [9].',
  citations: [src(1, { excerpt: 'Driftsinntekter 10 000 000' })],
  sources: [src(1, { excerpt: 'Driftsinntekter 10 000 000' })],
  coverage: context().coverage,
  search: { state: 'not_used', note: 'Answered from saved, verified research.' },
  origin: 'saved',
  generatedAt: '2026-10-14T10:00:00Z',
  ...over,
});

afterEach(() => vi.restoreAllMocks());

function open(ctx: ChatContext = context()) {
  vi.spyOn(api.chat, 'context').mockResolvedValue(ctx);
  const onClose = vi.fn();
  renderWithProviders(<AskAiPanel orgNumber={ORG} legalName={NAME} onClose={onClose} />);
  return onClose;
}
const box = () => screen.getByLabelText(new RegExp(`Your question about ${NAME}`));
const ask = (q: string) => {
  fireEvent.change(box(), { target: { value: q } });
  fireEvent.click(screen.getByRole('button', { name: 'Send question' }));
};

describe('citation helpers', () => {
  it('turns only known [n] markers into citations', () => {
    const parts = splitCitations('A [1] and B [2][9].', [src(1), src(2)]);
    expect(parts.filter((p) => 'n' in p)).toEqual([{ n: 1 }, { n: 2 }]);
    expect(parts.map((p) => ('text' in p ? p.text : '')).join('')).toContain('[9]'); // an unknown marker stays visible as plain text
  });
  it('sends only completed turns as history', () => {
    const h = historyOf([
      { id: 1, question: 'q1', status: 'done', reply: reply({ answer: 'a1' }) },
      { id: 2, question: 'q2', status: 'error' },
      { id: 3, question: 'q3', status: 'pending' },
    ]);
    expect(h).toEqual([
      { role: 'user', content: 'q1' },
      { role: 'assistant', content: 'a1' },
    ]);
  });
  it('words the five statuses exactly', () => {
    expect(Object.values(COVERAGE_LABEL)).toEqual(['Verified', 'No public results found in checked sources', 'Not reported', 'Not checked', 'Unavailable']);
  });
});

describe('Ask AI panel', () => {
  it('shows the company identity, a welcome with suggested questions, and what was checked', async () => {
    open();
    const panel = await screen.findByRole('complementary', { name: `Ask AI about ${NAME}` });
    expect(within(panel).getByText(NAME)).toBeInTheDocument();
    expect(await within(panel).findByRole('group', { name: 'Suggested questions' })).toBeInTheDocument();
    fireEvent.click(within(panel).getByText('What was checked'));
    expect(within(panel).getByText('Unavailable')).toBeInTheDocument();
    expect(within(panel).getByText('No public results found in checked sources')).toBeInTheDocument();
  });

  it('sends the question with the company, renders clickable citations and a source list', async () => {
    open();
    const spy = vi.spyOn(api.chat, 'ask').mockResolvedValue(reply());
    await screen.findByRole('group', { name: 'Suggested questions' });
    ask('How has its revenue changed?');
    expect(await screen.findByText(/Revenue was NOK 10.0 million/)).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith({ orgNumber: ORG, question: 'How has its revenue changed?', messages: [], expectedName: NAME, fresh: false }, expect.any(Function)); // the 2nd argument reports real progress
    const cite = screen.getByRole('button', { name: 'Source 1' });
    fireEvent.click(cite);
    const list = screen.getByRole('region', { name: 'Sources' });
    expect(within(list).getByRole('link', { name: /Source 1 title/ })).toHaveAttribute('href', 'https://example.org/1');
    expect(within(list).getByText('Driftsinntekter 10 000 000')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Source 9' })).not.toBeInTheDocument(); // a marker with no source is not made clickable
  });

  it('carries earlier turns into a follow-up', async () => {
    open();
    const spy = vi.spyOn(api.chat, 'ask').mockResolvedValue(reply({ answer: 'First answer [1].' }));
    await screen.findByRole('group', { name: 'Suggested questions' });
    ask('First?');
    await screen.findByText(/First answer/);
    spy.mockResolvedValue(reply({ answer: 'Second answer [1].' }));
    ask('And the year before?');
    await screen.findByText(/Second answer/);
    expect(spy.mock.calls[1][0].messages).toEqual([
      { role: 'user', content: 'First?' },
      { role: 'assistant', content: 'First answer [1].' },
    ]);
  });

  it('shows a retry on failure and recovers without inventing an answer', async () => {
    open();
    const spy = vi.spyOn(api.chat, 'ask').mockRejectedValueOnce(new ApiError('unavailable', 'The answer service is down.', 503)).mockResolvedValueOnce(reply({ answer: 'Recovered [1].' }));
    await screen.findByRole('group', { name: 'Suggested questions' });
    ask('Anything?');
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('The answer service is down.');
    fireEvent.click(within(alert).getByRole('button', { name: /Retry/ }));
    expect(await screen.findByText(/Recovered/)).toBeInTheDocument();
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it('says plainly when web search is unavailable, and offers no paid fallback', async () => {
    open();
    vi.spyOn(api.chat, 'ask').mockResolvedValue(reply({ search: { state: 'unavailable', note: 'Web search is temporarily unavailable (free allowance used up) — no paid fallback is used.' } }));
    await screen.findByRole('group', { name: 'Suggested questions' });
    ask('Any news this week?');
    expect(await screen.findByText(/no paid fallback is used/)).toBeInTheDocument();
  });

  it('a question about another company gets a clarification, not an answer about the other company', async () => {
    open();
    vi.spyOn(api.chat, 'ask').mockResolvedValue(reply({ kind: 'clarification', answer: `This chat is about ${NAME}. Your question mentions “Equinor ASA”, which is a different company.`, citations: [], sources: [] }));
    await screen.findByRole('group', { name: 'Suggested questions' });
    ask('How is Equinor ASA doing?');
    expect(await screen.findByText(/different company/)).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Sources' })).not.toBeInTheDocument();
  });

  it('new chat clears the conversation; Escape closes the panel', async () => {
    const onClose = open();
    vi.spyOn(api.chat, 'ask').mockResolvedValue(reply());
    await screen.findByRole('group', { name: 'Suggested questions' });
    ask('Hello?');
    await screen.findByText(/Revenue was/);
    fireEvent.click(screen.getByRole('button', { name: 'Start a new chat' }));
    expect(screen.queryByText(/Revenue was/)).not.toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Suggested questions' })).toBeInTheDocument();
    fireEvent.keyDown(box(), { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('rejects an over-long question before it is sent', async () => {
    open();
    const spy = vi.spyOn(api.chat, 'ask');
    await screen.findByRole('group', { name: 'Suggested questions' });
    fireEvent.change(box(), { target: { value: 'x'.repeat(201) } });
    expect(screen.getByText(/Too long: 201\/200/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send question' })).toBeDisabled();
    expect(spy).not.toHaveBeenCalled();
  });

  it('shows an unavailable state when chat is switched off, and an error with retry when the context fails', async () => {
    open(context({ capabilities: { chat: false, aiModel: false, freshResearch: false, maxQuestionChars: 200 } }));
    expect(await screen.findByText('Ask AI is unavailable')).toBeInTheDocument();
    expect(box()).toBeDisabled();
  });

  it('shows an error state with Retry when the context cannot be loaded', async () => {
    vi.spyOn(api.chat, 'context').mockRejectedValue(new ApiError('network', 'Backend unreachable', 0));
    renderWithProviders(<AskAiPanel orgNumber={ORG} legalName={NAME} onClose={() => undefined} />);
    expect(await screen.findByText('Ask AI could not be loaded')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Retry/ })).toBeInTheDocument();
  });

  it('offers a fresh check only on the latest answer and only when the server allows it', async () => {
    open();
    const spy = vi.spyOn(api.chat, 'ask').mockResolvedValue(reply());
    await screen.findByRole('group', { name: 'Suggested questions' });
    ask('News?');
    fireEvent.click(await screen.findByRole('button', { name: /Check for new information/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(spy.mock.calls[1][0].fresh).toBe(true);
  });
});

describe('mock backend chat', () => {
  it('answers only from the profile, with numbered sources, and refuses a wrong expected name', async () => {
    const ctx = await api.chat.context(ORG);
    expect(ctx.company.legalName).toBe(NAME);
    expect(ctx.coverage.find((c) => c.area === 'ip')?.status).toBe('unavailable');
    const r = await api.chat.ask({ orgNumber: ORG, question: 'How has revenue changed?', messages: [], expectedName: NAME });
    const marks = [...r.answer.matchAll(/\[(\d+)\]/g)].map((m) => Number(m[1]));
    for (const n of marks) expect(r.sources.some((s) => s.n === n)).toBe(true);
    await expect(api.chat.ask({ orgNumber: ORG, question: 'x', messages: [], expectedName: 'Other AS' })).rejects.toMatchObject({ code: 'ambiguous' });
  });
});

describe('secrets', () => {
  it('the chat client and panel source never reference an API key', () => {
    for (const text of [chatClient, panelSource, mockChat]) expect(text).not.toMatch(/GROQ|TAVILY|api[_-]?key|Authorization|VITE_[A-Z_]*KEY/i);
  });
});
