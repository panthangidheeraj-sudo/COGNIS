/**
 * Dark-mode UI polish: ivory surfaces on the dark workspace, a bright sidebar, a clearer run history and one-shot About reveals.
 *
 * jsdom does no layout and loads no stylesheets (the Vitest CSS pipeline returns empty text), so the guarantees are pinned two ways: the
 * components that carry the shared `.on-ivory` scope (and keep their behaviour), and the stylesheet contracts read straight from disk.
 * The pages were also checked in a real browser, in dark and light, at 1440 and 420 px.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useRef } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { renderWithProviders } from './utils';
// @ts-expect-error -- this project has no @types/node; vitest runs in Node, so the module exists at runtime (the Vitest CSS pipeline would hand back empty text for ?raw imports)
import { readFileSync } from 'node:fs';
import { usePreferences } from '@/stores/preferences';
import { Segmented } from '@/components/common/Tabs';
import { Rail } from '@/components/navigation/Rail';
import { RunHistory } from '@/components/company/RunHistory';
import { useRevealOnScroll } from '@/hooks/useRevealOnScroll';
import HomePage from '@/pages/Home/HomePage';
import DiscoverPage from '@/pages/Discover/DiscoverPage';
import ResearchPage from '@/pages/Research/ResearchPage';
import LibraryPage from '@/pages/Library/LibraryPage';
import SettingsPage from '@/pages/Settings/SettingsPage';
import AboutPage from '@/pages/Settings/AboutPage';
import type { ResearchRunSnapshot } from '@/types';

/* ------------------------------------------------------------------ css helpers -- */
const read = (path: string): string => readFileSync(new URL(path, import.meta.url), 'utf8') as string;
const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '');
const tokensCss = read('../styles/tokens.css');
const ivoryCss = read('../styles/ivory.css');
const shellCss = read('../styles/shell.css');
const homeCss = read('../pages/Home/home.css');
const aboutCss = read('../pages/Settings/about.css');
const artifactCss = read('../pages/Artifact/artifact.css');
const libraryCss = read('../pages/Library/library.css');
const mainTsx = read('../main.tsx');

const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\>:'=]/g, '\\$&');
/** Declarations of the first rule whose selector (or selector list entry) is exactly `selector`. */
function rule(css: string, selector: string): Record<string, string> {
  const re = new RegExp(`(?:^|[}\\s,])${esc(selector)}\\s*(?:,[^{}]*)?\\{([^}]*)\\}`);
  const m = re.exec(strip(css));
  if (!m) throw new Error(`rule not found: ${selector}`);
  const out: Record<string, string> = {};
  for (const d of m[1].split(';')) {
    const i = d.indexOf(':');
    if (i > 0) out[d.slice(0, i).trim()] = d.slice(i + 1).trim().replace(/\s+/g, ' ');
  }
  return out;
}
const hasRule = (css: string, selector: string) => {
  try {
    rule(css, selector);
    return true;
  } catch {
    return false;
  }
};
/** A `--name: #hex` value declared in tokens.css (first occurrence, or within the block that starts at `from`). */
const hex = (name: string, from = 0): string => {
  const m = new RegExp(`${esc(name)}:\\s*(#[0-9a-fA-F]{6})`).exec(tokensCss.slice(from));
  if (!m) throw new Error(`token not found: ${name}`);
  return m[1];
};
const luminance = (h: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

afterEach(() => {
  usePreferences.getState().set({ motion: 'system', theme: 'dark', researchMode: 'quick' });
});

/* ---------------------------------------------------------------- ivory tokens -- */
describe('ivory surface tokens', () => {
  const surfaces = ['--ivory-field', '--ivory-panel'].map((n) => hex(n));
  it('keeps navy ink readable on the ivory fields and panels (WCAG AA for text)', () => {
    for (const ink of ['--ivory-ink', '--ivory-ink-2', '--ivory-ink-3', '--ivory-ink-4'])
      for (const bg of surfaces) expect(contrast(hex(ink), bg), `${ink} on ${bg}`).toBeGreaterThanOrEqual(4.5);
  });
  it('draws the keyboard focus ring with enough contrast on ivory and on the dark navy page (WCAG 1.4.11: 3:1)', () => {
    const dark = tokensCss.indexOf("--ivory-ring: #3f7be0");
    expect(dark).toBeGreaterThan(0);
    for (const bg of [...surfaces, '#0f1725', '#06111c']) expect(contrast('#3f7be0', bg), `ring on ${bg}`).toBeGreaterThanOrEqual(3);
    const lightBlock = tokensCss.indexOf(":root[data-theme='light']");
    for (const bg of [...surfaces, hex('--c-ivory')]) expect(contrast(hex('--ivory-ring', lightBlock), bg)).toBeGreaterThanOrEqual(3);
  });
  it('remaps the semantic tokens inside the .on-ivory scope, so everything within reads dark-on-light', () => {
    const scope = rule(ivoryCss, '.on-ivory');
    for (const t of ['--text-1', '--text-2', '--text-3', '--text-4', '--line', '--line-strong', '--line-focus', '--surface-1', '--surface-2', '--surface-3', '--primary-bg', '--ok', '--warn', '--err'])
      expect(scope[t], t).toBeTruthy();
    expect(scope['--text-1']).toBe('var(--ivory-ink)');
    expect(scope['--surface-2']).toBe('var(--ivory-field)');
    expect(scope['color-scheme']).toBe('light');
    expect(scope['--primary-bg']).toBe('#0f1b2a'); // the primary button is navy on ivory
  });
  it('is loaded by the app', () => {
    expect(mainTsx).toContain("import './styles/ivory.css'");
  });
  it('gives fields, chips and toggles hover, focus, selected and disabled states', () => {
    expect(hasRule(ivoryCss, ':is(.input, .textarea, .select).on-ivory:focus-visible')).toBe(true);
    expect(rule(ivoryCss, '.chip.on-ivory:hover:not(:disabled):not([aria-disabled=\'true\'])')['border-color']).toBeTruthy();
    expect(rule(ivoryCss, ".chip.on-ivory[aria-pressed='true']")['background']).toBe('var(--ivory-ink)');
    expect(rule(ivoryCss, '.chip.on-ivory:disabled')['cursor']).toBe('not-allowed');
    expect(rule(ivoryCss, '.chip.on-ivory:focus-visible')['border-radius']).toBe('var(--r-pill)'); // a pill stays a pill when focused
    expect(rule(ivoryCss, ".segmented.on-ivory button[aria-pressed='true']")['background']).toBe('var(--ivory-ink)');
    expect(hasRule(ivoryCss, '.segmented.on-ivory button:focus-visible')).toBe(true);
    // placeholders are fully opaque ink-4, never the faded dark-theme grey
    expect(strip(ivoryCss)).toMatch(/::placeholder\s*\{\s*color:\s*var\(--ivory-ink-4\);\s*opacity:\s*1;/);
  });
});

/* ------------------------------------------------------------------ Segmented -- */
describe('Segmented', () => {
  it('stays dark by default and draws on ivory only when asked, with the same behaviour', () => {
    const onChange = vi.fn();
    const opts = [
      { value: 'a', label: 'Alpha' },
      { value: 'b', label: 'Beta' },
    ];
    const { rerender } = render(<Segmented label="Pick" value="a" onChange={onChange} options={opts} />);
    expect(screen.getByRole('group', { name: 'Pick' })).not.toHaveClass('on-ivory');
    rerender(<Segmented label="Pick" value="a" onChange={onChange} options={opts} tone="ivory" />);
    const group = screen.getByRole('group', { name: 'Pick' });
    expect(group).toHaveClass('segmented', 'on-ivory');
    expect(screen.getByRole('button', { name: 'Alpha' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Beta' })).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(screen.getByRole('button', { name: 'Beta' }));
    expect(onChange).toHaveBeenCalledWith('b');
  });
});

/* ------------------------------------------------------------------------ Home -- */
describe('Home', () => {
  it('draws the four action cards on ivory, with dark text', () => {
    const { container } = renderWithProviders(<HomePage />);
    const cards = Array.from(container.querySelectorAll('.action-card'));
    expect(cards.map((c) => c.textContent)).toEqual([
      expect.stringContaining('Research a company'),
      expect.stringContaining('Find companies'),
      expect.stringContaining('Create a data sheet'),
      expect.stringContaining('Explore the library'),
    ]);
    cards.forEach((c) => expect(c).toHaveClass('on-ivory'));
    // the card title reads from the remapped ink token, not a hard-coded colour
    expect(rule(homeCss, '.action-title')['color']).toBe('var(--text-1)');
    expect(rule(homeCss, '.action-card')['background']).toBe('var(--surface-1)');
  });
  it('has no bottom band on the hero (it ended on a hard horizontal line behind the cards)', () => {
    expect(strip(homeCss)).not.toMatch(/\.hero::after/);
    expect(strip(homeCss)).not.toMatch(/linear-gradient\(180deg, transparent, var\(--bg-canvas\)\)/);
  });
});

/* --------------------------------------------------------------------- Discover -- */
describe('Discover', () => {
  it('draws the search bar and the query suggestions on ivory, and the suggestions still search', async () => {
    const { container } = renderWithProviders(<DiscoverPage />, { route: '/discover' });
    const form = container.querySelector('form[role="search"]')!;
    expect(form).toHaveClass('disc-search', 'on-ivory', 'is-bar');
    const chips = await screen.findAllByRole('button', { name: /Norwegian SaaS companies with over 100 employees/ });
    chips.forEach((c) => expect(c).toHaveClass('chip', 'on-ivory'));
    fireEvent.click(chips[0]);
    expect(await screen.findByDisplayValue('Norwegian SaaS companies with over 100 employees')).toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------------- Research -- */
describe('Research', () => {
  it('draws the company field, the question box and the "How research works" panel on ivory, and keeps them working', () => {
    const { container } = renderWithProviders(<ResearchPage />, { route: '/research' });
    const company = screen.getByLabelText('Company');
    expect(company.closest('.input-wrap')).toHaveClass('on-ivory');
    const question = screen.getByLabelText('Or ask your own question');
    expect(question).toHaveClass('on-ivory');
    expect(container.querySelector('.composer-explain')).toHaveClass('on-ivory');
    expect(screen.getByRole('heading', { name: 'How research works' }).closest('.composer-explain')).toBe(container.querySelector('.composer-explain'));
    // typing and focus options still work; the Quick/Deep control and Start research are untouched
    fireEvent.change(question, { target: { value: 'Has it opened offices abroad?' } });
    expect(question).toHaveValue('Has it opened offices abroad?');
    expect(screen.getByRole('group', { name: 'Research depth' })).not.toHaveClass('on-ivory');
    expect(screen.getByRole('button', { name: /Start research/ })).toBeDisabled(); // nothing typed in the company field yet
  });
});

/* ------------------------------------------------------------------------ Library -- */
describe('Library', () => {
  it('draws the search bar on ivory', () => {
    const { container } = renderWithProviders(<LibraryPage />, { route: '/library' });
    expect(container.querySelector('.lib-search')).toHaveClass('input-wrap', 'on-ivory');
    expect(screen.getByLabelText('Search your research')).toBeInTheDocument();
  });
  it('shows when each item was researched as a real <time> element, set off by a separator', async () => {
    const { container } = renderWithProviders(<LibraryPage />, { route: '/library' });
    await waitFor(() => expect(container.querySelectorAll('.lib-foot time').length).toBeGreaterThan(0), { timeout: 4000 });
    const t = container.querySelector('.lib-foot time')!;
    expect(t.getAttribute('dateTime')).toMatch(/^\d{4}-\d{2}-\d{2}/);
    expect(container.querySelector('.lib-foot .lib-when-label')?.textContent).toMatch(/^(Researched|Updated)$/);
    expect(rule(libraryCss, '.lib-foot')['border-top']).toContain('var(--line)');
  });
});

/* ------------------------------------------------------------------ Run history -- */
const snap = (over: Partial<ResearchRunSnapshot>): ResearchRunSnapshot => ({
  id: 'run-x',
  mode: 'quick',
  prompt: null,
  status: 'completed',
  startedAt: '2026-10-12T10:00:00Z',
  finishedAt: '2026-10-12T10:00:40Z',
  versionId: 'v3',
  versionNumber: 3,
  hasReport: true,
  isLatestReport: false,
  evidenceChanged: true,
  summary: { coverage: { complete: 5, total: 5, areas: [] }, factsVerified: 41, sourcesVerified: 6 },
  effort: null,
  steps: [],
  issues: [],
  ...over,
});
describe('Library run history', () => {
  const runs = [
    snap({ id: 'run-4', isLatestReport: true }),
    snap({ id: 'run-3', status: 'partial', issues: ['2 of 5 areas verified.'] }),
    snap({ id: 'run-2', status: 'failed', hasReport: false, versionId: null, versionNumber: null, summary: null, issues: ['The company register did not respond.'] }),
    snap({ id: 'run-1', status: 'cancelled', hasReport: false, versionId: null, versionNumber: null, summary: null, issues: ['Research cancelled.'] }),
  ];
  const renderRuns = () =>
    render(
      <MemoryRouter>
        <RunHistory runs={runs} artifactId="a1" />
      </MemoryRouter>,
    );
  it('tells completed, partial, failed, cancelled and current runs apart by text and by a status mark', () => {
    renderRuns();
    for (const [id, status, label] of [
      ['run-run-4', 'completed', 'Completed'],
      ['run-run-3', 'partial', 'Partial'],
      ['run-run-2', 'failed', 'Failed'],
      ['run-run-1', 'cancelled', 'Cancelled'],
    ] as const) {
      const row = screen.getByTestId(id);
      expect(row).toHaveAttribute('data-status', status);
      expect(within(row).getByText(label)).toHaveClass('run-status'); // the outcome is words first
      expect(row.querySelector('.run-dot')).not.toBeNull(); // and a mark
    }
    expect(screen.getByTestId('run-run-4')).toHaveClass('is-latest');
    expect(screen.getAllByText('Latest report')).toHaveLength(1);
  });
  it('shows each run\'s time as a <time> element and keeps the reasons for runs that did not complete', () => {
    renderRuns();
    const t = within(screen.getByTestId('run-run-3')).getByText(/Oct 2026/);
    expect(t.tagName).toBe('TIME');
    expect(t).toHaveAttribute('dateTime', '2026-10-12T10:00:00Z');
    expect(screen.getByTestId('run-issues-run-2')).toHaveTextContent('The company register did not respond.');
  });
  it('uses muted tones from the theme tokens (no hard-coded bright colours) and distinguishes outcomes by shape too', () => {
    const css = strip(artifactCss);
    expect(css).toMatch(/\.run\[data-status='completed'\]\s*\{\s*--run-tone:\s*var\(--ok\);/);
    expect(css).toMatch(/\.run\[data-status='partial'\]\s*\{\s*--run-tone:\s*var\(--warn\);/);
    expect(css).toMatch(/\.run\[data-status='failed'\]\s*\{\s*--run-tone:\s*var\(--err\);/);
    expect(css).toMatch(/\.run\[data-status='cancelled'\] \.run-dot\s*\{[^}]*background:\s*transparent;/); // hollow
    const runBlock = css.slice(css.indexOf('.runs {'));
    expect(runBlock).not.toMatch(/#[0-9a-fA-F]{3,8}\b/); // every colour comes from a token
  });
});

/* ------------------------------------------------------------------------ Settings -- */
describe('Settings', () => {
  it('draws the Theme, Motion, Data density and research-mode toggles on ivory, and they still change the settings', () => {
    renderWithProviders(<SettingsPage />, { route: '/settings' });
    for (const label of ['Theme', 'Motion', 'Data density', 'Default research mode']) expect(screen.getByRole('group', { name: label })).toHaveClass('segmented', 'on-ivory');
    const mode = screen.getByRole('group', { name: 'Default research mode' });
    expect(within(mode).getByRole('button', { name: 'Quick' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(within(mode).getByRole('button', { name: 'Deep' }));
    expect(usePreferences.getState().researchMode).toBe('deep');
    expect(within(mode).getByRole('button', { name: 'Deep' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(mode).getByRole('button', { name: 'Quick' })).toHaveAttribute('aria-pressed', 'false');
    const motion = screen.getByRole('group', { name: 'Motion' });
    fireEvent.click(within(motion).getByRole('button', { name: 'Reduced' }));
    expect(usePreferences.getState().motion).toBe('reduced');
  });
});

/* ------------------------------------------------------------------------ Sidebar -- */
describe('Sidebar', () => {
  it('keeps the same links, and marks the current page', () => {
    renderWithProviders(<Rail />, { route: '/library' });
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    expect(within(nav).getAllByRole('link').map((a) => a.textContent?.replace(/\d+$/, ''))).toEqual(['', 'Home', 'Discover', 'Research', 'Library', 'Data Sheets', 'Compare', 'Watchlist', 'Settings', 'About']);
    const library = within(nav).getByRole('link', { name: 'Library' });
    expect(library).toHaveClass('rail-link', 'active');
    expect(within(nav).getByRole('link', { name: 'Home' })).not.toHaveClass('active');
  });
  it('colours icons and labels bright whether or not an item is selected, and sets the selected one apart by more than colour', () => {
    const link = rule(shellCss, '.rail-link');
    expect(link['color']).toBe('var(--nav-fg)'); // not the dimmed --text-3 it used to be
    expect(strip(shellCss)).not.toMatch(/\.rail-link\s*\{[^}]*var\(--text-3\)/);
    const active = rule(shellCss, '.rail-link.active');
    expect(active['background']).toBe('var(--nav-active-bg)');
    expect(active['box-shadow']).toContain('var(--nav-active-line)'); // a border
    expect(rule(shellCss, '.rail-link.active::before')['background']).toBe('var(--nav-indicator)'); // a bar
    expect(rule(shellCss, '.rail-link.active .rail-label')['font-weight']).toBe('650'); // and weight
    expect(rule(shellCss, '.rail-link:hover')['background']).toBe('var(--nav-hover-bg)');
    expect(rule(shellCss, '.rail-link:focus-visible')['outline']).toContain('var(--nav-fg-strong)');
    expect(rule(shellCss, '.rail-link:focus-visible')['border-radius']).toBe('var(--r-md)');
  });
  it('is bright ivory on the dark rail and navy ink on the ivory light rail, both with AA contrast', () => {
    const dark = tokensCss.indexOf("--nav-fg: #f6f4ee");
    expect(dark).toBeGreaterThan(0);
    expect(contrast('#f6f4ee', hex('--c-navy-900'))).toBeGreaterThanOrEqual(7);
    const lightBlock = tokensCss.indexOf(":root[data-theme='light']");
    expect(hex('--nav-fg', lightBlock)).toBe('#0f1b2a');
    expect(contrast('#0f1b2a', '#fbf9f4')).toBeGreaterThanOrEqual(7); // the light rail is --chrome-bg #fbf9f4
  });
});

/* ------------------------------------------------------------- useRevealOnScroll -- */
type IOCallback = (entries: Partial<IntersectionObserverEntry>[]) => void;
class FakeIO {
  static instances: FakeIO[] = [];
  observed = new Set<Element>();
  unobserved: Element[] = [];
  disconnected = false;
  constructor(public cb: IOCallback) {
    FakeIO.instances.push(this);
  }
  observe(el: Element) {
    this.observed.add(el);
  }
  unobserve(el: Element) {
    this.observed.delete(el);
    this.unobserved.push(el);
  }
  disconnect() {
    this.disconnected = true;
    this.observed.clear();
  }
  /** Report a change of visibility for some elements, as the browser would. */
  fire(entries: [Element, boolean][]) {
    this.cb(entries.map(([target, isIntersecting]) => ({ target, isIntersecting })));
  }
}

function Probe({ enabled }: { enabled: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useRevealOnScroll(ref, enabled);
  return (
    <div ref={ref}>
      <section data-reveal-group>
        <h2 data-reveal>Heading</h2>
        <p data-reveal>Body</p>
        <p data-reveal>Third</p>
      </section>
      <section data-reveal-group>
        <p data-reveal>Other group</p>
      </section>
      <footer data-reveal>Ungrouped</footer>
    </div>
  );
}

describe('useRevealOnScroll', () => {
  beforeEach(() => {
    FakeIO.instances = [];
    vi.stubGlobal('IntersectionObserver', FakeIO);
  });
  afterEach(() => vi.unstubAllGlobals());

  it('reveals an item the first time it is seen, and never hides or animates it again', () => {
    const { container } = render(<Probe enabled />);
    const io = FakeIO.instances[0];
    const [heading, body] = [container.querySelector('h2')!, container.querySelectorAll('p')[0]];
    expect(container.querySelectorAll('[data-revealed]')).toHaveLength(0); // nothing is shown before it is seen
    act(() => io.fire([[heading, true]]));
    expect(heading).toHaveAttribute('data-revealed', 'true');
    expect(body).not.toHaveAttribute('data-revealed');
    expect(io.unobserved).toContain(heading); // observation ends: this is the only time it can change
    expect(io.observed.has(heading)).toBe(false);
    // scrolling away reports "not intersecting" for it — nothing happens; and it is not observed any more
    act(() => io.fire([[heading, false]]));
    expect(heading).toHaveAttribute('data-revealed', 'true');
    // a second report for the same element never re-triggers anything
    act(() => io.fire([[heading, true]]));
    expect(io.unobserved.filter((e) => e === heading)).toHaveLength(2); // harmless repeat, still revealed
    expect(heading).toHaveAttribute('data-revealed', 'true');
  });
  it('ignores items that are reported as not visible', () => {
    const { container } = render(<Probe enabled />);
    const io = FakeIO.instances[0];
    act(() => io.fire([[container.querySelector('footer')!, false]]));
    expect(container.querySelector('footer')).not.toHaveAttribute('data-revealed');
  });
  it('staggers related items: each gets its order within its group', () => {
    const { container } = render(<Probe enabled />);
    const idx = (el: Element) => (el as HTMLElement).style.getPropertyValue('--reveal-i');
    const ps = container.querySelectorAll('p');
    expect([container.querySelector('h2')!, ps[0], ps[1]].map(idx)).toEqual(['0', '1', '2']);
    expect(idx(ps[2])).toBe('0'); // the other group starts again from zero
    expect(idx(container.querySelector('footer')!)).toBe('0');
  });
  it('shows everything immediately when motion is reduced, and observes nothing', () => {
    const { container } = render(<Probe enabled={false} />);
    expect(FakeIO.instances).toHaveLength(0);
    const items = container.querySelectorAll('[data-reveal]');
    expect(items.length).toBe(5);
    items.forEach((el) => expect(el).toHaveAttribute('data-revealed', 'true'));
  });
  it('shows everything when the browser has no IntersectionObserver', () => {
    vi.stubGlobal('IntersectionObserver', undefined);
    const { container } = render(<Probe enabled />);
    container.querySelectorAll('[data-reveal]').forEach((el) => expect(el).toHaveAttribute('data-revealed', 'true'));
  });
  it('stops observing when the page unmounts', () => {
    const { unmount } = render(<Probe enabled />);
    const io = FakeIO.instances[0];
    unmount();
    expect(io.disconnected).toBe(true);
  });
});

/* ------------------------------------------------------------------------- About -- */
describe('About scroll reveals', () => {
  beforeEach(() => {
    FakeIO.instances = [];
    vi.stubGlobal('IntersectionObserver', FakeIO);
  });
  afterEach(() => vi.unstubAllGlobals());

  it('marks headings, copy and illustration items for a one-shot reveal, and shows them as they are seen', () => {
    usePreferences.getState().set({ motion: 'full' });
    const { container } = renderWithProviders(<AboutPage />);
    expect(container.querySelector('.story')).not.toHaveClass('story--static');
    const reveal = container.querySelectorAll('[data-reveal]');
    expect(reveal.length).toBeGreaterThan(40);
    // every chapter's heading, kicker and copy takes part; so do the dossier layers, labels, tiers, flow steps and the closing section
    for (const sel of ['.copy-kicker', '.copy-title', '.copy-body', '.dossier-layer', '.label', '.tier', '.flow-dot', '.flow-text', '.final-title', '.final-notes']) {
      const els = container.querySelectorAll(sel);
      expect(els.length, sel).toBeGreaterThan(0);
      els.forEach((e) => expect(e, sel).toHaveAttribute('data-reveal'));
    }
    expect(container.querySelectorAll('[data-revealed]')).toHaveLength(0);
    const io = FakeIO.instances[0];
    const title = container.querySelector('#h-understand')!;
    act(() => io.fire([[title, true]]));
    expect(title).toHaveAttribute('data-revealed', 'true');
    expect(container.querySelector('#h-verify')).not.toHaveAttribute('data-revealed'); // still below the fold
    // the layers of the dossier are staggered in order
    const layers = Array.from(container.querySelectorAll<HTMLElement>('.dossier-layer')).map((l) => l.style.getPropertyValue('--reveal-i'));
    expect(layers).toEqual(['0', '1', '2', '3', '4', '5']);
  });
  it('shows every chapter at once under reduced motion — the Motion setting …', () => {
    usePreferences.getState().set({ motion: 'reduced' });
    const { container } = renderWithProviders(<AboutPage />);
    expect(container.querySelector('.story')).toHaveClass('story--static');
    expect(FakeIO.instances).toHaveLength(0);
    const reveal = container.querySelectorAll('[data-reveal]');
    expect(reveal.length).toBeGreaterThan(40);
    reveal.forEach((el) => expect(el).toHaveAttribute('data-revealed', 'true'));
  });
  it('… and the operating system preference (when the Motion setting is "System")', () => {
    const mm = vi.spyOn(window, 'matchMedia').mockImplementation(
      (query: string) => ({ matches: /prefers-reduced-motion: reduce/.test(query), media: query, onchange: null, addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false }) as unknown as MediaQueryList,
    );
    usePreferences.getState().set({ motion: 'system' });
    const { container } = renderWithProviders(<AboutPage />);
    expect(container.querySelector('.story')).toHaveClass('story--static');
    container.querySelectorAll('[data-reveal]').forEach((el) => expect(el).toHaveAttribute('data-revealed', 'true'));
    mm.mockRestore();
  });
  it('an explicit "Full" motion choice still animates, even when the OS prefers reduced motion', () => {
    const mm = vi.spyOn(window, 'matchMedia').mockImplementation(
      (query: string) => ({ matches: /prefers-reduced-motion: reduce/.test(query), media: query, onchange: null, addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false }) as unknown as MediaQueryList,
    );
    usePreferences.getState().set({ motion: 'full' });
    const { container } = renderWithProviders(<AboutPage />);
    expect(container.querySelector('.story')).not.toHaveClass('story--static');
    expect(container.querySelectorAll('[data-revealed]')).toHaveLength(0);
    mm.mockRestore();
  });

  it('hides nothing unless motion is on: the hidden state is scoped to the animated story, and the OS preference is honoured in CSS too', () => {
    const css = strip(aboutCss);
    // the hidden start state applies only inside `.story:not(.story--static)`
    expect(css).toMatch(/\.story:not\(\.story--static\) \[data-reveal\]\s*\{[^}]*opacity:\s*0;[^}]*translate3d\(0, 18px, 0\)/);
    expect(css).toMatch(/\.story:not\(\.story--static\) \[data-reveal\]\[data-revealed='true'\]\s*\{[^}]*opacity:\s*1;[^}]*transform:\s*none;/);
    expect(css).not.toMatch(/^\[data-reveal\]/m);
    // a restrained motion: a short rise and a gentle ease, staggered by --reveal-i
    expect(rule(aboutCss, ".story:not(.story--static) [data-reveal]")['transition']).toContain('var(--reveal-i, 0)');
    // belt and braces for the OS preference unless the viewer picked Full motion
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)\s*\{\s*:root:not\(\[data-motion='full'\]\) \.story \[data-reveal\]\s*\{[^}]*opacity:\s*1;[^}]*transition:\s*none;/);
  });
  it('no longer scrubs entrances with scroll position (they would replay when scrolling back); only the hand-over and progress effects are scroll-linked', () => {
    const css = strip(aboutCss);
    expect(css).not.toMatch(/--in\b/);
    expect(css).not.toMatch(/\.dossier-layer\s*\{[^}]*--lp/);
    expect(css).not.toMatch(/\.story:not\(\.story--static\) \.tier\s*\{/);
    expect(css).not.toMatch(/\.story:not\(\.story--static\) \.label\s*\{/);
    expect(css).toContain('--out: clamp(0, calc((var(--p) - 0.88) * 8.3), 1)'); // the hand-over between acts is kept
    expect(css).toContain('.story:not(.story--static) .flow'); // and so is the workflow progress fill
  });
});
