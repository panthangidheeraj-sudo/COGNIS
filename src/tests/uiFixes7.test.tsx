/**
 * Seven UI fixes: the enlarged intro, the dot cursor over the intro, Home offsets, Compare auto-enrichment, the layer scale,
 * the Research metrics + "Ask AI about this company", and the compare tray rule.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, Link, Outlet, RouterProvider } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
// @ts-expect-error -- this project has no @types/node; vitest runs in Node, so the module exists at runtime
import { readFileSync } from 'node:fs';
import { renderWithProviders } from './utils';
import { api } from '@/api';
import { DotCursor } from '@/components/common/DotCursor';
import { LaunchGate } from '@/components/intro/LaunchGate';
import { CompareTray } from '@/components/navigation/CompareTray';
import { routes } from '@/app/router';
import ComparePage from '@/pages/Compare/ComparePage';
import { CompletionSummary } from '@/components/research/CompletionSummary';
import { AskAiHost, useAskAiHost } from '@/components/chat/AskAiHost';
import { clearEnrichmentCache } from '@/hooks/useDiscoverEnrichment';
import { neededFields, useCompareEnrichment } from '@/hooks/useCompareEnrichment';
import { useCompare } from '@/stores/ui';
import { usePreferences } from '@/stores/preferences';
import type { ChatContext, ChatReply, CompanyEnrichment, CompanySummary, Comparison, EnrichedFigure, EnrichmentResult, Fact, ResearchRun } from '@/types';

const css = (p: string): string => readFileSync(new URL(p, import.meta.url), 'utf8') as string;
const introCss = css('../components/intro/intro.css');
const homeCss = css('../pages/Home/home.css');
const shellCss = css('../styles/shell.css');
const tokensCss = css('../styles/tokens.css');
const researchCss = css('../pages/Research/research.css');
const compareCss = css('../pages/Compare/compare.css');
const askCss = css('../components/chat/ask-ai.css');
const rule = (src: string, sel: string): string => {
  const i = src.indexOf(`${sel} {`);
  if (i < 0) throw new Error(`no rule ${sel}`);
  return src.slice(i, src.indexOf('}', i));
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  cleanup();
  document.documentElement.className = '';
  useCompare.getState().clear();
  clearEnrichmentCache();
});

/* ===================================================================== 1. intro */
describe('1 · intro carousel is the centrepiece', () => {
  it('the tour is one card at a time inside a fixed stage: cards are stacked in place and the stage fills the tour area', () => {
    expect(rule(introCss, '.li-card')).toMatch(/position:\s*absolute/);
    expect(rule(introCss, '.li-tourbox')).toMatch(/position:\s*absolute/);
    expect(introCss).toMatch(/\n\.li-cards\s*{[^}]*overflow:\s*hidden/);
    expect(rule(introCss, '.li-card img')).toMatch(/max-width:\s*100%/);
    expect(rule(introCss, '.li-card img')).toMatch(/max-height:\s*100%/);
  });

  it('is an asymmetrical two-column grid (hero + actions left, carousel right) with a control band, and no CSS scale()', () => {
    expect(introCss).not.toMatch(/scale\(\s*2/);
    expect(rule(introCss, '.li-inner')).toMatch(/grid-template-columns:\s*minmax\(\d+px,\s*0?\.\d+fr\)\s*minmax\(0,\s*1\.\d+fr\)/);
    expect(rule(introCss, '.li-inner')).toMatch(/grid-template-areas:\s*'hero tour'\s*'actions tour'/);
    expect(rule(introCss, '.li-caption')).toBeTruthy();
    expect(introCss).toMatch(/--li-band:/);
    expect(introCss).toMatch(/li-logo-in/); // the logo keeps its entrance animation
  });

  it('stacks cleanly on small screens (hero, tour, actions) and hides the long copy on very short windows', () => {
    expect(introCss).toMatch(/@media \(max-width: 860px\)\s*{[\s\S]*grid-template-areas:\s*'hero'\s*'tour'\s*'actions'/);
    expect(introCss).toMatch(/@media \(max-height: 640px\) and \(min-width: 861px\)\s*{[\s\S]*\.li-desc,\s*\.li-steps\s*{\s*display:\s*none/);
  });
});

/* ===================================================================== 2. cursor */
describe('2 · dot cursor above the intro', () => {
  const media = () =>
    vi.spyOn(window, 'matchMedia').mockImplementation(
      (q: string) => ({ matches: q.includes('pointer: fine') || q.includes('hover: hover'), media: q, addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false, onchange: null }) as unknown as MediaQueryList,
    );

  it('is portalled to <body>, outside the app root and therefore outside its stacking context', () => {
    media();
    usePreferences.setState({ motion: 'reduced' });
    render(
      <div id="root">
        <DotCursor />
      </div>,
    );
    const dot = screen.getByTestId('dot-cursor');
    expect(dot.parentElement).toBe(document.body);
    expect(dot.closest('#root')).toBeNull();
  });

  it('sits above the intro (z-index) and never takes pointer events', () => {
    const cursor = css('../styles/cursor.css');
    const z = Number(/\.cg-dot-cursor\s*{[^}]*z-index:\s*(\d+)/s.exec(cursor)?.[1]);
    const intro = Number(/\.launch-intro\s*{[^}]*z-index:\s*(\d+)/s.exec(introCss)?.[1]);
    expect(z).toBeGreaterThan(intro);
    expect(cursor).toMatch(/\.cg-dot-cursor\s*{[^}]*pointer-events:\s*none/s);
  });

  it('re-evaluates what is under a stationary pointer when the page scrolls, and cleans up on unmount', () => {
    media();
    usePreferences.setState({ motion: 'reduced' });
    const remove = vi.spyOn(window, 'removeEventListener');
    const r = render(
      <>
        <DotCursor />
        <button>btn</button>
      </>,
    );
    const dot = screen.getByTestId('dot-cursor');
    fireEvent(window, new MouseEvent('pointermove', { clientX: 30, clientY: 30, bubbles: true }));
    expect(dot).not.toHaveAttribute('data-active');
    const btn = screen.getByRole('button');
    (document as unknown as { elementFromPoint: () => Element }).elementFromPoint = () => btn;
    vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame'] });
    fireEvent.scroll(window);
    act(() => void vi.advanceTimersByTime(50));
    expect(dot).toHaveAttribute('data-active');
    r.unmount();
    expect(remove.mock.calls.some(([t]) => t === 'scroll')).toBe(true);
    expect(document.querySelector('.cg-dot-cursor')).toBeNull();
    delete (document as unknown as { elementFromPoint?: unknown }).elementFromPoint;
  });

  it('is mounted at the shell, outside the gated app tree (main.tsx)', () => {
    const main = css('../main.tsx');
    expect(main.indexOf('<DotCursor')).toBeGreaterThan(-1);
    expect(main.indexOf('<DotCursor')).toBeLessThan(main.indexOf('<LaunchGate'));
    expect(LaunchGate).toBeDefined();
  });
});

/* ===================================================================== 3. home */
describe('3 · Home offsets and clipping', () => {
  it('the rail scrolls instead of clipping its last items on a short window', () => {
    expect(rule(shellCss, '.rail')).toMatch(/overflow-y:\s*auto/);
    expect(shellCss).toMatch(/@media \(max-height: 700px\)\s*{\s*\.rail/);
  });

  it('list tracks cannot grow past the card (no sideways overflow at 420 px)', () => {
    expect(homeCss).toMatch(/\.artifact-mini-list,\s*\.signal-mini-list\s*{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s);
    expect(rule(homeCss, '.recent-list')).toMatch(/minmax\(0,\s*1fr\)/);
  });

  it('the hero is tall for the enlarged Earth but still leaves the top of the first card row in view, and short laptop screens keep their own rules', () => {
    // (was 190px / 760px before the globe was enlarged: the hero now takes more of the first viewport, with 100px left for the cards to peek in)
    expect(rule(homeCss, '.hero')).toMatch(/--hero-h:\s*clamp\(460px,\s*calc\(100dvh - var\(--topbar-h\) - 100px\),\s*920px\)/);
    expect(rule(homeCss, '.hero')).toMatch(/min-height:\s*var\(--hero-h\)/);
    expect(homeCss).toMatch(/@media \(min-width: 641px\) and \(max-height: 760px\)/);
  });

  it('the page scroll position is reset on navigation, and sticky bars offset by the top bar', () => {
    const shell = css('../app/layout/AppShell.tsx');
    expect(shell).toMatch(/window\.scrollTo\(\{ top: 0 \}\)/);
    expect(rule(css('../pages/Company/company.css'), '.co-tabs')).toMatch(/top:\s*var\(--topbar-h\)/);
    expect(rule(compareCss, '.cmp-anchors')).toMatch(/top:\s*var\(--topbar-h\)/);
  });
});

/* ===================================================================== 4. compare enrichment */
const A = '810359862';
const B = '923609016';
const C = '914778271';
const co = (org: string, name: string, over: Partial<CompanySummary> = {}): CompanySummary => ({
  orgNumber: org,
  legalName: name,
  municipality: 'Oslo',
  country: 'Norway',
  status: 'active',
  employees: null,
  revenue: null,
  openPositions: null,
  coverage: { complete: 1, total: 5, areas: [] },
  researchState: 'not_researched',
  ...over,
});
const fact = (org: string, field: string, value: number, extra: Partial<Fact> = {}): Fact => ({
  id: `${org}:${field}`,
  field,
  label: field,
  status: 'verified',
  value,
  evidenceState: 'primary',
  evidence: [],
  freshness: 'current',
  ...extra,
});
function comparison(orgs: string[], researched: Record<string, boolean> = {}): Comparison {
  const companies = orgs.map((o, i) => co(o, `Company ${String.fromCharCode(65 + i)}`, { researchState: researched[o] ? 'researched' : 'not_researched' }));
  // only the first company has a verified revenue in its saved profile; everything else is empty
  const vals = (key: string): (Fact | null)[] => orgs.map((o, i) => (i === 0 && key === 'revenue' ? fact(o, 'financials.revenue', 5_000_000, { currency: 'NOK', reportingPeriod: 'FY2025', displayValue: 'NOK 5.0M' }) : null));
  return {
    companies,
    summary: ['revenue', 'employees', 'hiring'].map((k) => ({ key: k, label: k, values: vals(k) })),
    sections: [],
    series: [],
    generatedAt: '2026-10-14T00:00:00Z',
    sourceIndex: {},
  };
}
const verified = (value: number, extra: Partial<EnrichedFigure> = {}): EnrichedFigure => ({ state: 'verified', note: 'Verified.', sources: [{ name: 'Regnskapsregisteret', state: 'checked', url: 'https://regnskapsregisteret.no' }], value, ...extra });
const said = (state: EnrichedFigure['state'], note: string): EnrichedFigure => ({ state, note, sources: [] });
const answer = (orgs: string[], byOrg: (o: string) => CompanyEnrichment['fields']): EnrichmentResult => ({ enabled: true, checkedAt: '2026-10-14T12:00:00Z', items: orgs.map((o) => ({ orgNumber: o, checkedAt: '2026-10-14T12:00:00Z', fields: byOrg(o) })) });
const GOOD = (o: string): CompanyEnrichment['fields'] => ({
  revenue: o === A ? undefined : verified(21_789_260, { currency: 'NOK', period: 'FY2024' }),
  employees: o === A ? verified(12) : said('not_reported', 'No count registered.'),
  openPositions: said('none_found', 'No verified openings in NAV Arbeidsplassen. This does not mean the company is not hiring.'),
});

function renderCompare(orgs: string[], cmp = comparison(orgs)) {
  vi.spyOn(api.compare, 'get').mockResolvedValue(cmp);
  return renderWithProviders(<ComparePage />, { route: `/compare?orgs=${orgs.join(',')}` });
}
const SLOW = { timeout: 6000 };

describe('4 · Compare auto-enrichment', () => {
  it('asks only for what the saved profiles leave empty, per company', () => {
    const n = neededFields(comparison([A, B]));
    expect(n.find((x) => x.org === A)?.fields.sort()).toEqual(['employees', 'openPositions']); // A already has a verified revenue
    expect(n.find((x) => x.org === B)?.fields.sort()).toEqual(['employees', 'openPositions', 'revenue']);
    // a researched company's hiring conclusion ("none verified") is shown as research left it, not looked up again
    const c = comparison([A, B]);
    c.companies[1] = { ...c.companies[1], researchState: 'researched', openPositionsStatus: 'none_found' };
    expect(neededFields(c).find((x) => x.org === B)?.fields).not.toContain('openPositions');
  });

  it('shows a skeleton per cell while fetching, then fills cells with values, sources and reasons — never a bare "Not available"', async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const enrich = vi.spyOn(api.companies, 'enrich').mockImplementation(async (orgs) => {
      await gate;
      return answer(orgs, GOOD);
    });
    renderCompare([A, B]);
    expect((await screen.findAllByTestId('cmp-cell-fetching', {}, SLOW)).length).toBeGreaterThanOrEqual(5);
    release();
    await waitFor(() => expect(screen.queryAllByTestId('cmp-cell-fetching')).toHaveLength(0), SLOW);
    expect(screen.getAllByText('NOK 21.8M').length).toBeGreaterThan(0); // B's looked-up revenue
    expect(screen.getAllByText(/Regnskapsregisteret/).length).toBeGreaterThan(0); // its citation travels with it
    expect(screen.getAllByText('None verified').length).toBeGreaterThan(0); // confirmed absence (hiring)
    expect(screen.getAllByText('Not registered').length).toBeGreaterThan(0); // the register holds none: not a zero
    expect(screen.queryByText('Not available')).not.toBeInTheDocument();
    expect(screen.getByText('NOK 5.0M')).toBeInTheDocument(); // the saved verified fact keeps its own rendering
    expect(enrich).toHaveBeenCalledTimes(1);
    expect(enrich.mock.calls[0][0]).toEqual([A, B]);
  });

  it('keeps each result on the exact organisation number it was requested for', async () => {
    vi.spyOn(api.companies, 'enrich').mockResolvedValue(answer(['999999999'], () => ({ revenue: verified(1), employees: verified(1), openPositions: verified(1) }))); // a stranger
    renderCompare([A, B]);
    await waitFor(() => expect(screen.getAllByText('Lookup failed').length).toBeGreaterThan(0), SLOW);
    expect(screen.queryByText('NOK 1')).not.toBeInTheDocument();
    for (const cell of document.querySelectorAll('.cmp-lookup')) expect([A, B]).toContain(cell.getAttribute('data-org'));
  });

  it('a failed request is "Lookup failed" with Retry (not "Not available"), and Retry fetches again', async () => {
    const enrich = vi.spyOn(api.companies, 'enrich').mockRejectedValueOnce(new Error('offline')).mockImplementation(async (orgs) => answer(orgs, GOOD));
    renderCompare([A, B]);
    const retry = (await screen.findAllByRole('button', { name: /Retry/ }, SLOW))[0];
    expect(screen.queryByText('Not available')).not.toBeInTheDocument();
    fireEvent.click(retry);
    await waitFor(() => expect(screen.getAllByText('Not registered').length).toBeGreaterThan(0), SLOW);
    expect(enrich.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it('an unreachable source is "Source unavailable" (not "none"), distinct from a confirmed absence', async () => {
    vi.spyOn(api.companies, 'enrich').mockImplementation(async (orgs) => answer(orgs, () => ({ revenue: said('unavailable', 'Regnskapsregisteret could not be read.'), employees: said('not_reported', 'None registered.'), openPositions: said('none_found', 'Nothing verified.') })));
    renderCompare([A, B]);
    await waitFor(() => expect(screen.getAllByText('Source unavailable').length).toBeGreaterThan(0), SLOW);
    expect(screen.getAllByText('Not registered').length).toBeGreaterThan(0);
  });

  it('reuses the cache: reopening the comparison does not fetch again', async () => {
    const enrich = vi.spyOn(api.companies, 'enrich').mockImplementation(async (orgs) => answer(orgs, GOOD));
    const first = renderCompare([A, B]);
    await waitFor(() => expect(screen.queryAllByTestId('cmp-cell-fetching')).toHaveLength(0), SLOW);
    await waitFor(() => expect(screen.getAllByText('NOK 21.8M').length).toBeGreaterThan(0), SLOW);
    first.unmount();
    renderCompare([A, B]);
    await waitFor(() => expect(screen.getAllByText('NOK 21.8M').length).toBeGreaterThan(0), SLOW);
    expect(screen.queryAllByTestId('cmp-cell-fetching')).toHaveLength(0);
    expect(enrich).toHaveBeenCalledTimes(1);
  });

  it('adding a company fetches only that company', async () => {
    const enrich = vi.spyOn(api.companies, 'enrich').mockImplementation(async (orgs) => answer(orgs, GOOD));
    const { result, rerender } = renderHook(({ cmp }) => useCompareEnrichment(cmp), { initialProps: { cmp: comparison([A, B]) } });
    await waitFor(() => expect(result.current.progress.running).toBe(false));
    await waitFor(() => expect(result.current.cell('employees', co(B, 'B'))?.state).toBe('none_found'));
    expect(enrich).toHaveBeenCalledTimes(1);
    rerender({ cmp: comparison([A, B, C]) });
    await waitFor(() => expect(result.current.cell('employees', co(C, 'C'))?.state).toBe('none_found'));
    expect(enrich).toHaveBeenCalledTimes(2);
    expect(enrich.mock.calls[1][0]).toEqual([C]);
  });

  it('bounds concurrency and batch size', async () => {
    const orgs = Array.from({ length: 5 }, (_, i) => `81000000${i}`);
    let live = 0;
    let peak = 0;
    vi.spyOn(api.companies, 'enrich').mockImplementation(async (list) => {
      live++;
      peak = Math.max(peak, live);
      await new Promise((r) => setTimeout(r, 20));
      live--;
      return answer(list, GOOD);
    });
    const cmp = comparison(orgs);
    renderHook(() => useCompareEnrichment(cmp));
    await waitFor(() => expect(api.companies.enrich).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 120));
    expect(peak).toBeLessThanOrEqual(2);
  });

  it('is not a second engine: it calls the one enrich endpoint and writes nothing', () => {
    const src = css('../hooks/useCompareEnrichment.ts');
    expect(src).toMatch(/api\.companies\.enrich\(/);
    expect(src).not.toMatch(/api\.research|api\.library|fetch\(/);
  });
});

/* ===================================================================== 5. layers */
describe('5 · one layer scale', () => {
  const z = (name: string) => Number(new RegExp(`--z-${name}:\\s*(\\d+)`).exec(tokensCss)?.[1]);
  it('orders in-page, sticky, floating, top bar, rail, tray, panel, dialogs, palette and toasts', () => {
    const order = ['raised', 'sticky', 'float', 'nav', 'tray', 'panel', 'modal', 'drawer', 'palette', 'toast'].map(z);
    expect(order.every(Number.isFinite)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(z('nav') - 1).toBeGreaterThan(z('float')); // the top bar (nav − 1) is above page sticky bars and floats
    expect(shellCss).toMatch(/\.topbar\s*{[^}]*z-index:\s*calc\(var\(--z-nav\) - 1\)/s);
  });
  it('page bars and the Ask AI panel take their layer from the scale', () => {
    expect(rule(compareCss, '.cmp-anchors')).toMatch(/z-index:\s*var\(--z-sticky\)/);
    expect(rule(askCss, '.askai')).toMatch(/z-index:\s*var\(--z-panel\)/);
    expect(rule(css('../pages/Company/company.css'), '.co-tabs')).toMatch(/z-index:\s*var\(--z-sticky\)/);
  });
  it('the Compare anchors are a flush band under the top bar, not a floating chip bar', () => {
    const r = rule(compareCss, '.cmp-anchors');
    expect(r).toMatch(/top:\s*var\(--topbar-h\)/);
    expect(r).not.toMatch(/box-shadow/);
    expect(r).toMatch(/calc\(var\(--page-px/);
  });
  it('every layer of the stack has its own tone, in both themes', () => {
    expect(researchCss).toMatch(/\.sstack-tile:is\(\.sstack-tile--idle, \.sstack-tile--queued\)\s*{[^}]*calc\(var\(--i\) \* 5%/s);
    expect(researchCss).toMatch(/:root\[data-theme='light'\] \.sstack-tile:is\(/);
    expect(researchCss).toMatch(/:root:not\(\[data-theme='light'\]\) \.on-inverse \.sstack-tile:is\(/);
  });
});

/* ===================================================================== 6. research results */
const RUN = (over: Partial<ResearchRun> = {}): ResearchRun =>
  ({
    id: 'run-1',
    status: 'completed',
    company: co(A, 'Nordvik Helseteknologi AS'),
    coverage: { complete: 4, total: 5, areas: [] },
    summary: { sourcesVerified: 9, primarySources: 5, secondarySources: 4, factsVerified: 31, identityConflicts: 0, conflicts: 2, changesDetected: 3, elapsedMs: 42_000, coverage: { complete: 4, total: 5, areas: [] } },
    ...over,
  }) as unknown as ResearchRun;

describe('6 · research results', () => {
  it('shows every metric, each in its own tile', () => {
    renderWithProviders(<CompletionSummary run={RUN()} />);
    for (const label of ['Coverage', 'Sources verified', 'Facts verified', 'Identity conflicts', 'Value conflicts', 'Changes detected']) expect(screen.getByText(label)).toBeInTheDocument();
    expect(document.querySelectorAll('.rs-stat')).toHaveLength(6);
  });
  it('lays the tiles out as a wrapping grid with no overlapping left-border hacks', () => {
    expect(rule(researchCss, '.rs-complete-stats')).toMatch(/repeat\(auto-fill,\s*minmax\(min\(100%,\s*156px\),\s*1fr\)\)/);
    expect(rule(researchCss, '.rs-stat')).toMatch(/min-width:\s*0/);
    expect(researchCss).not.toMatch(/\.rs-stat:first-child/);
    expect(researchCss).toMatch(/\.rs-stat--cov \.cov\s*{[^}]*white-space:\s*normal/s); // the coverage meter wraps inside its tile
    expect(researchCss).toMatch(/@media \(max-width: 380px\)/);
  });
  it('offers "Ask AI about this company" in the completed panel, as a labelled toggle for the panel', () => {
    const onAsk = vi.fn();
    renderWithProviders(<CompletionSummary run={RUN()} onAsk={onAsk} />);
    const btn = screen.getByRole('button', { name: /Ask AI about this company/ });
    expect(btn).toHaveAttribute('aria-controls', 'ask-ai');
    expect(btn).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(btn);
    expect(onAsk).toHaveBeenCalledTimes(1);
  });
  it('has no Ask AI button when the page does not wire it', () => {
    renderWithProviders(<CompletionSummary run={RUN()} />);
    expect(screen.queryByRole('button', { name: /Ask AI/ })).not.toBeInTheDocument();
  });
});

const CTX: ChatContext = {
  company: { orgNumber: A, legalName: 'Nordvik Helseteknologi AS' },
  suggestions: ['Who runs this company?'],
  coverage: [],
  capabilities: { chat: true, aiModel: true, freshResearch: true, maxQuestionChars: 500 },
};
const REPLY: ChatReply = { company: CTX.company, kind: 'model', answer: 'Two value conflicts were found [1].', citations: [], sources: [], coverage: [], search: { state: 'not_used', note: '' }, origin: 'saved', generatedAt: '2026-10-14T10:00:00Z' };

function Harness({ org = A, name = 'Nordvik Helseteknologi AS' }: { org?: string; name?: string }) {
  const host = useAskAiHost();
  return (
    <>
      <button onClick={host.toggle}>open ask</button>
      <AskAiHost host={host} orgNumber={org} legalName={name} origin="the research run that just finished" suggestions={['What is missing or could not be checked, and why?']} />
    </>
  );
}

describe('6 · Ask AI from the research result', () => {
  it('opens with the exact org number and the run-specific starter questions, and asks about that company only', async () => {
    const context = vi.spyOn(api.chat, 'context').mockResolvedValue(CTX);
    const askSpy = vi.spyOn(api.chat, 'ask').mockResolvedValue(REPLY);
    renderWithProviders(<Harness />);
    expect(screen.queryByTestId('ask-ai-panel')).not.toBeInTheDocument(); // nothing is loaded until it is opened
    fireEvent.click(screen.getByText('open ask'));
    const panel = await screen.findByTestId('ask-ai-panel');
    expect(context).toHaveBeenCalledWith(A);
    expect(await within(panel).findByText(/Opened from the research run that just finished/)).toBeInTheDocument();
    fireEvent.click(await within(panel).findByRole('button', { name: 'What is missing or could not be checked, and why?' }));
    await waitFor(() => expect(askSpy).toHaveBeenCalled());
    expect(askSpy.mock.calls[0][0]).toMatchObject({ orgNumber: A, expectedName: 'Nordvik Helseteknologi AS' }); // identity validation travels with every question
  });

  it('keeps the conversation when the panel is closed and opened again', async () => {
    vi.spyOn(api.chat, 'context').mockResolvedValue(CTX);
    vi.spyOn(api.chat, 'ask').mockResolvedValue(REPLY);
    renderWithProviders(<Harness />);
    fireEvent.click(screen.getByText('open ask'));
    const panel = await screen.findByTestId('ask-ai-panel');
    fireEvent.click(await within(panel).findByRole('button', { name: 'Who runs this company?' }));
    expect(await within(panel).findByText(/Two value conflicts were found/)).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole('button', { name: 'Close Ask AI' }));
    expect(screen.getByTestId('ask-ai-host')).toHaveAttribute('hidden');
    fireEvent.click(screen.getByText('open ask'));
    expect(screen.getByTestId('ask-ai-host')).not.toHaveAttribute('hidden');
    expect(screen.getByText(/Two value conflicts were found/)).toBeInTheDocument(); // same chat
  });

  it('a different company starts a different conversation', async () => {
    vi.spyOn(api.chat, 'context').mockImplementation(async (o) => ({ ...CTX, company: { orgNumber: o, legalName: 'X' } }));
    vi.spyOn(api.chat, 'ask').mockResolvedValue(REPLY);
    const r = renderWithProviders(<Harness />);
    fireEvent.click(screen.getByText('open ask'));
    fireEvent.click(await screen.findByRole('button', { name: 'Who runs this company?' }));
    await screen.findByText(/Two value conflicts were found/);
    r.rerender(
      <QueryClientProvider client={new QueryClient()}>
        <Harness org={B} name="Other AS" />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.queryByText(/Two value conflicts were found/)).not.toBeInTheDocument());
  });
});

/* ===================================================================== 7. tray */
function Routed({ initial, children }: { initial: string; children?: never }) {
  void children;
  const router = createMemoryRouter(
    [
      {
        element: (
          <>
            <Link to="/">home</Link>
            <Link to="/discover">discover</Link>
            <Link to="/compare">compare</Link>
            <Outlet />
            <CompareTray />
          </>
        ),
        children: [
          { path: '/', element: <p>Home</p> },
          { path: '/discover', element: <p>Discover</p> },
          { path: '/research', element: <p>Research</p> },
          { path: '/compare', element: <p>Compare</p>, handle: routes[0].children!.find((r) => r.path === '/compare')!.handle },
        ],
      },
    ],
    { initialEntries: [initial] },
  );
  return (
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}

describe('7 · compare tray', () => {
  beforeEach(() => {
    useCompare.getState().setAll([
      { orgNumber: A, legalName: 'Alpha AS' },
      { orgNumber: B, legalName: 'Beta AS' },
    ]);
  });
  it('is declared by route metadata: only /compare opts in', () => {
    const kids = routes[0].children!;
    expect(kids.filter((r) => (r.handle as { compareTray?: boolean } | undefined)?.compareTray).map((r) => r.path)).toEqual(['/compare']);
  });
  it('does not render on Home, Discover or Research, even with a selection', () => {
    for (const p of ['/', '/discover', '/research']) {
      const r = render(<Routed initial={p} />);
      expect(screen.queryByRole('region', { name: /selected for comparison/ })).not.toBeInTheDocument();
      r.unmount();
    }
  });
  it('shows on the compare route, hides at once when leaving, and returns to the same selection', async () => {
    render(<Routed initial="/compare" />);
    expect(screen.getByRole('region', { name: /selected for comparison/ })).toBeInTheDocument();
    fireEvent.click(screen.getByText('home'));
    await waitFor(() => expect(screen.getByText('Home')).toBeInTheDocument());
    expect(screen.queryByRole('region', { name: /selected for comparison/ })).not.toBeInTheDocument();
    expect(useCompare.getState().selected).toHaveLength(2); // the selection is preserved
    fireEvent.click(screen.getByText('compare'));
    const tray = await screen.findByRole('region', { name: /selected for comparison/ });
    expect(within(tray).getByText('Alpha AS')).toBeInTheDocument();
  });
  it('is absent without a selection, and without a data router (no route can opt in)', () => {
    useCompare.getState().clear();
    render(<Routed initial="/compare" />);
    expect(screen.queryByRole('region', { name: /selected for comparison/ })).not.toBeInTheDocument();
  });
  it('clears the floor for the tray, above the mobile nav, and the Ask AI panel sits above it', () => {
    expect(shellCss).toMatch(/\.shell\[data-tray\] \.shell-main\s*{\s*padding-bottom:\s*84px/);
    expect(shellCss).toMatch(/\.compare-tray\s*{[^}]*bottom:\s*calc\(var\(--mobile-nav-h\)/s);
    expect(Number(/--z-panel:\s*(\d+)/.exec(tokensCss)![1])).toBeGreaterThan(Number(/--z-tray:\s*(\d+)/.exec(tokensCss)![1]));
  });
});

/* ===================================================================== themes / a11y */
describe('both themes and reduced motion', () => {
  it('the new skeleton stops animating under reduced motion', () => {
    expect(compareCss).toMatch(/prefers-reduced-motion: reduce\)\s*{[^}]*\.cmp-skel\s*{\s*animation:\s*none/s);
  });
  it('the new rules use theme tokens, not raw theme-specific colours (apart from the stack tones, which have both themes)', () => {
    const added = compareCss.slice(compareCss.indexOf('looked-up cells'));
    expect(added).not.toMatch(/#[0-9a-f]{3,6}\b/i);
  });
  it('the Ask AI button and the retry control are real buttons reachable by keyboard', () => {
    renderWithProviders(<CompletionSummary run={RUN()} onAsk={() => undefined} />);
    expect(screen.getByRole('button', { name: /Ask AI about this company/ }).tagName).toBe('BUTTON');
  });
});
