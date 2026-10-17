/**
 * Box-by-box fade-ins across the app: the automatic reveal hook (`useAutoReveal` through `RevealRegion`), its stylesheet contract, and the
 * Home header's pressure-text animation.
 *
 * jsdom does no layout and no animation, and has no IntersectionObserver, so the observer is a controllable fake (the same technique as the
 * About reveal tests) and the stylesheet is checked by reading it from disk. The look and timing were verified in a real browser.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { usePreferences } from '@/stores/preferences';
import { RevealRegion } from '@/components/common/RevealRegion';
import { PressureText, pressureValue } from '@/components/common/PressureText';
import { MAX_BLOCKS, TRIGGER_MARGIN } from '@/hooks/useRevealOnScroll';
// @ts-expect-error -- no @types/node in this project; vitest runs in Node, so the module exists at runtime
import { readFileSync } from 'node:fs';

const read = (path: string): string => readFileSync(new URL(path, import.meta.url), 'utf8') as string;

class FakeIO {
  static instances: FakeIO[] = [];
  observed = new Set<Element>();
  constructor(public cb: (entries: Partial<IntersectionObserverEntry>[]) => void) {
    FakeIO.instances.push(this);
  }
  observe(el: Element) {
    this.observed.add(el);
  }
  unobserve(el: Element) {
    this.observed.delete(el);
  }
  disconnect() {
    this.observed.clear();
  }
  fire(entries: [Element, boolean][]) {
    this.cb(entries.map(([target, isIntersecting]) => ({ target, isIntersecting })));
  }
}
const io = () => FakeIO.instances[FakeIO.instances.length - 1];
const state = (el: Element | null) => el?.getAttribute('data-reveal-auto');

function Page({ cards = 3 }: { cards?: number }) {
  return (
    <div className="page" data-testid="page">
      <header className="page-head" data-testid="head">
        <h1>Title</h1>
      </header>
      <p data-testid="intro">Intro</p>
      <div className="card-grid" data-testid="grid">
        {Array.from({ length: cards }, (_, i) => (
          <article key={i} className="card" data-testid={`card-${i}`}>
            Card {i}
          </article>
        ))}
      </div>
    </div>
  );
}

beforeEach(() => {
  FakeIO.instances = [];
  vi.stubGlobal('IntersectionObserver', FakeIO);
  usePreferences.setState({ motion: 'full' });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('automatic box reveals', () => {
  it('hides each box before first paint and reveals them in document order with a growing stagger', () => {
    render(
      <RevealRegion>
        <Page />
      </RevealRegion>,
    );
    const order = ['head', 'intro', 'card-0', 'card-1', 'card-2'].map((id) => screen.getByTestId(id));
    order.forEach((el) => expect(state(el)).toBe('hidden'));
    expect(state(screen.getByTestId('grid'))).toBeNull(); // the grid itself is a group: its cards are the boxes
    // the browser reports them in any order; the sequence follows the page
    act(() => io().fire([...order].reverse().map((el) => [el, true] as [Element, boolean])));
    order.forEach((el, i) => {
      expect(state(el)).toBe('in');
      expect(el.style.getPropertyValue('--reveal-i')).toBe(String(i));
    });
  });

  it('settles after the transition so later hover styles are the element’s own', () => {
    vi.useFakeTimers();
    render(
      <RevealRegion>
        <Page />
      </RevealRegion>,
    );
    const head = screen.getByTestId('head');
    act(() => io().fire([[head, true]]));
    expect(state(head)).toBe('in');
    act(() => void vi.advanceTimersByTime(2000));
    expect(state(head)).toBe('done');
  });

  it('reveals a box that scrolls in later on its own, once, and never hides it again', () => {
    const { rerender } = render(
      <RevealRegion>
        <Page />
      </RevealRegion>,
    );
    const last = screen.getByTestId('card-2');
    act(() => io().fire([[screen.getByTestId('head'), true]]));
    expect(state(last)).toBe('hidden'); // below the fold: still waiting
    act(() => io().fire([[last, true]]));
    expect(state(last)).toBe('in');
    expect(last.style.getPropertyValue('--reveal-i')).toBe('0'); // alone in its batch: no inherited delay
    expect(io().observed.has(last)).toBe(false);
    act(() => io().fire([[last, false]])); // scrolling away does nothing
    expect(state(last)).toBe('in');
    // an unrelated re-render of the same page does not replay anything
    rerender(
      <RevealRegion>
        <Page />
      </RevealRegion>,
    );
    expect(state(last)).toBe('in');
    expect(state(screen.getByTestId('head'))).toBe('in');
  });

  it('reveals the cards of a grid one by one, and stops tagging at MAX_BLOCKS so a huge page is never one giant batch of hidden boxes', () => {
    render(
      <RevealRegion>
        <Page cards={MAX_BLOCKS + 30} />
      </RevealRegion>,
    );
    expect(state(screen.getByTestId('card-0'))).toBe('hidden'); // each card is its own box, so cards appear in sequence
    expect(document.querySelectorAll('[data-reveal-auto]').length).toBeLessThanOrEqual(MAX_BLOCKS);
    expect(state(screen.getByTestId(`card-${MAX_BLOCKS + 29}`))).toBeNull(); // the far tail is simply there
  });

  it('observes with a trigger line inside the viewport (so a box is revealed as it is really seen), and disconnects on unmount', () => {
    expect(TRIGGER_MARGIN).toMatch(/^0px 0px -\d+% 0px$/);
    const r = render(
      <RevealRegion>
        <Page />
      </RevealRegion>,
    );
    const inst = io() as FakeIO & { options?: IntersectionObserverInit };
    expect(inst.observed.size).toBeGreaterThan(0);
    r.unmount();
    expect(inst.observed.size).toBe(0);
  });

  it('leaves the About story, hand-marked reveals and overlays alone', () => {
    render(
      <RevealRegion>
        <div className="page">
          <section className="story" data-testid="story">
            <p>Chapter</p>
          </section>
          <p data-reveal data-testid="manual">
            Manual
          </p>
          <div role="dialog" data-testid="dialog">
            Dialog
          </div>
          <div data-reveal-skip data-testid="skip">
            Skip
          </div>
          <p data-testid="normal">Normal</p>
        </div>
      </RevealRegion>,
    );
    ['story', 'manual', 'dialog', 'skip'].forEach((id) => expect(state(screen.getByTestId(id))).toBeNull());
    expect(state(screen.getByTestId('normal'))).toBe('hidden');
  });

  it('animates content that arrives after load (data fetched) but not what was already there', async () => {
    function Later() {
      return (
        <RevealRegion>
          <Page />
        </RevealRegion>
      );
    }
    const { container } = render(<Later />);
    const head = screen.getByTestId('head');
    act(() => io().fire([[head, true]]));
    const grid = container.querySelector('[data-testid="grid"]')!;
    const extra = document.createElement('article');
    extra.setAttribute('data-testid', 'late');
    grid.appendChild(extra);
    await waitFor(() => expect(state(extra)).toBe('hidden'));
    expect(state(head)).toBe('in'); // untouched
  });

  it('starts a fresh sequence when the route changes (a new key), and cleans up the old one', () => {
    const { rerender } = render(
      <RevealRegion key="/a">
        <Page />
      </RevealRegion>,
    );
    act(() => io().fire([[screen.getByTestId('head'), true]]));
    rerender(
      <RevealRegion key="/b">
        <Page />
      </RevealRegion>,
    );
    expect(state(screen.getByTestId('head'))).toBe('hidden');
    expect(document.querySelectorAll('[data-reveal-auto="hidden"]').length).toBeGreaterThan(0);
  });

  it('shows everything immediately under reduced motion, and when the setting is switched on live', () => {
    const { unmount } = render(
      <RevealRegion>
        <Page />
      </RevealRegion>,
    );
    expect(document.querySelectorAll('[data-reveal-auto="hidden"]').length).toBeGreaterThan(0);
    act(() => usePreferences.setState({ motion: 'reduced' }));
    expect(document.querySelectorAll('[data-reveal-auto]')).toHaveLength(0); // nothing waiting, nothing animating
    unmount();
    FakeIO.instances = [];
    usePreferences.setState({ motion: 'reduced' });
    render(
      <RevealRegion>
        <Page />
      </RevealRegion>,
    );
    expect(document.querySelectorAll('[data-reveal-auto]')).toHaveLength(0);
    expect(FakeIO.instances).toHaveLength(0);
  });

  it('shows everything when the browser has no IntersectionObserver', () => {
    vi.stubGlobal('IntersectionObserver', undefined);
    render(
      <RevealRegion>
        <Page />
      </RevealRegion>,
    );
    expect(document.querySelectorAll('[data-reveal-auto]')).toHaveLength(0);
  });
});

describe('reveal stylesheet contract', () => {
  const css = read('../styles/reveal.css');
  it('hides only through the JS-set attribute (so no script means no hidden content) and moves with opacity + translate', () => {
    expect(css).toMatch(/\[data-reveal-auto='hidden'\]\s*\{[^}]*opacity:\s*0[^}]*translate:/);
    expect(css).not.toMatch(/display:\s*none|visibility:\s*hidden/);
    expect(css).not.toMatch(/[^-]transform:/); // a box's own transform is never replaced
    expect(css).toMatch(/\[data-reveal-auto='in'\][\s\S]*calc\(var\(--reveal-i, 0\)/); // the stagger
  });
  it('uses a visible, deliberate motion: a 20–28px rise, 550–750ms ease-out, 70–120ms between siblings', () => {
    const num = (n: string) => Number(new RegExp(`--reveal-${n}:\\s*(\\d+)`).exec(css)?.[1]);
    expect(num('distance')).toBeGreaterThanOrEqual(20);
    expect(num('distance')).toBeLessThanOrEqual(28);
    expect(num('duration')).toBeGreaterThanOrEqual(550);
    expect(num('duration')).toBeLessThanOrEqual(750);
    expect(num('step')).toBeGreaterThanOrEqual(70);
    expect(num('step')).toBeLessThanOrEqual(120);
    expect(css).toMatch(/--reveal-ease:\s*cubic-bezier/);
  });
  it('is forced visible for the Motion setting and for prefers-reduced-motion, and for focus inside a waiting box', () => {
    expect(css).toMatch(/:root\[data-motion='reduced'\] \[data-reveal-auto\][\s\S]*?opacity:\s*1 !important/);
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*?:root:not\(\[data-motion='full'\]\) \[data-reveal-auto\][\s\S]*?opacity:\s*1 !important/);
    expect(css).toMatch(/\[data-reveal-auto='hidden'\]:focus-within/);
  });
  it('is loaded by the app, and the old one-off Home card animation no longer doubles it', () => {
    expect(read('../main.tsx')).toMatch(/styles\/reveal\.css/);
    expect(read('../pages/Home/home.css')).not.toMatch(/\.action-card \{[^}]*animation:/);
    expect(read('../pages/Home/HomePage.tsx')).not.toMatch(/animationDelay/);
    expect(read('../app/layout/AppShell.tsx')).toMatch(/<RevealRegion key=\{revealKey\}/);
    expect(read('../app/layout/AppShell.tsx')).toMatch(/const revealKey = loc\.pathname\.startsWith\('\/chat'\) \? '\/chat' : loc\.pathname/); // every other page still re-reveals per path
  });
});

describe('Home header pressure text', () => {
  const segments = [
    { text: 'Find.', className: 't-gradient' },
    { text: 'Understand.', className: 't-gradient' },
    { text: 'Verify.', className: 't-serif', as: 'em' as const, pressure: false },
  ];
  it('maps distance to weight: heavy at the cursor, resting far away, never outside the range', () => {
    expect(pressureValue(0, 300, 450, 800)).toBe(800);
    expect(pressureValue(300, 300, 450, 800)).toBe(450);
    expect(pressureValue(5000, 300, 450, 800)).toBe(450);
    const a = pressureValue(100, 300, 450, 800);
    const b = pressureValue(200, 300, 450, 800);
    expect(a).toBeGreaterThanOrEqual(b);
  });
  it('keeps the heading readable as one phrase and splits only the animated words into letters', () => {
    render(<PressureText as="h1" id="hero-title" segments={segments} />);
    const h1 = screen.getByRole('heading', { level: 1, name: 'Find. Understand. Verify.' });
    expect(h1).toHaveAttribute('data-pressure', 'on');
    expect(h1.querySelectorAll('[data-pressure-char]')).toHaveLength('Find.Understand.'.length); // "Verify." is a static serif run
    expect(h1.querySelector('em')).toHaveTextContent('Verify.');
    expect(h1.querySelectorAll('.t-gradient')).toHaveLength(2);
  });
  it('follows the pointer: letters change weight with distance, and relax when the pointer leaves', async () => {
    render(<PressureText as="h1" segments={segments} />);
    const chars = Array.from(document.querySelectorAll<HTMLElement>('[data-pressure-char]'));
    chars.forEach((c, i) => {
      c.getBoundingClientRect = () => ({ left: i * 20, top: 0, width: 20, height: 40, right: i * 20 + 20, bottom: 40, x: i * 20, y: 0, toJSON: () => ({}) });
    });
    document.querySelector('h1')!.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: 40, right: 400, bottom: 40, x: 0, y: 0, toJSON: () => ({}) });
    fireEvent.mouseMove(window, { clientX: 10, clientY: 20 });
    await waitFor(() => expect(chars[0].style.fontVariationSettings).toContain('800'));
    const far = chars[chars.length - 1].style.fontVariationSettings;
    expect(far).toContain('450'); // far from the pointer: the resting weight
    expect(chars[0].style.fontVariationSettings).not.toBe(far);
  });
  it('is static under reduced motion: no letters move and nothing listens to the pointer', () => {
    usePreferences.setState({ motion: 'reduced' });
    const add = vi.spyOn(window, 'addEventListener');
    render(<PressureText as="h1" segments={segments} />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveAttribute('data-pressure', 'static');
    expect(add.mock.calls.filter(([t]) => t === 'mousemove' || t === 'touchmove')).toHaveLength(0);
    fireEvent.mouseMove(window, { clientX: 10, clientY: 10 });
    document.querySelectorAll<HTMLElement>('[data-pressure-char]').forEach((c) => expect(c.style.fontVariationSettings).toBe(''));
    add.mockRestore();
  });
  it('is what the Home page renders for its heading, with the same words and gradient', () => {
    const home = read('../pages/Home/HomePage.tsx');
    expect(home).toMatch(/<PressureText[\s\S]*as="h1"[\s\S]*id="hero-title"[\s\S]*hero-title t-display/);
    expect(home).toMatch(/'Find\.'[\s\S]*'Understand\.'[\s\S]*'Verify\.'/);
  });
});
