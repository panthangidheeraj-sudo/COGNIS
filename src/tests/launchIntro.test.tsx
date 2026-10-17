/** Launch intro, tour slides and the minimal dot cursor. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import introTourSource from '@/components/intro/IntroTour.tsx?raw';
import { LaunchGate, LEAVE_MS } from '@/components/intro/LaunchGate';
import { TOUR_SLIDES } from '@/components/intro/slides';
import { DotCursor } from '@/components/common/DotCursor';
import { usePreferences } from '@/stores/preferences';
// @ts-expect-error -- this project has no @types/node; vitest runs in Node, so the module exists at runtime
import { readFileSync } from 'node:fs';
import gateSource from '@/components/intro/wheelGate.ts?raw';

// jsdom loads no stylesheets (the CSS pipeline returns empty text), so CSS rules are pinned by reading the files from disk
const css = (p: string): string => readFileSync(new URL(p, import.meta.url), 'utf8') as string;
const cursorCss = css('../styles/cursor.css');
const pkg = JSON.parse(css('../../package.json')) as { dependencies: Record<string, string> };
const introCss = css('../components/intro/intro.css');
const svgs = import.meta.glob('../../public/intro/*.svg', { eager: true, query: '?raw', import: 'default' }) as Record<string, string>;

function App() {
  return (
    <MemoryRouter initialEntries={['/']}>
      <LaunchGate>
        <nav>
          <Link to="/discover">go discover</Link>
          <Link to="/">go home</Link>
        </nav>
        <Routes>
          <Route path="/" element={<h1>Dashboard</h1>} />
          <Route path="/discover" element={<h1>Discover page</h1>} />
        </Routes>
      </LaunchGate>
    </MemoryRouter>
  );
}

beforeEach(() => {
  usePreferences.setState({ theme: 'dark', motion: 'full' });
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  cleanup();
  document.documentElement.className = '';
});

const leave = () => act(() => void vi.advanceTimersByTime(LEAVE_MS + 50));

describe('launch intro', () => {
  it('shows a full-screen dialog first, with Enter and Skip, and does not mount the application behind it', () => {
    render(<App />);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(screen.getByRole('heading', { name: 'COGNIS' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Enter COGNIS/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Skip intro' })).toBeInTheDocument();
    expect(screen.queryByText('Dashboard')).not.toBeInTheDocument(); // no flash of the dashboard
  });

  it('Enter COGNIS reveals the application and removes the intro', () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: /Enter COGNIS/ }));
    expect(screen.getByText('Dashboard')).toBeInTheDocument();
    leave();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('Skip intro and Escape dismiss it too', () => {
    const first = render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Skip intro' }));
    leave();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    first.unmount();
    render(<App />);
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    leave();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByText('Dashboard')).toBeInTheDocument();
  });

  it('does not come back during SPA navigation', () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: /Enter COGNIS/ }));
    leave();
    fireEvent.click(screen.getByText('go discover'));
    expect(screen.getByText('Discover page')).toBeInTheDocument();
    fireEvent.click(screen.getByText('go home'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('shows again on the next fresh launch, and remembers nothing in storage', () => {
    const local = vi.spyOn(Storage.prototype, 'setItem');
    const a = render(<App />);
    fireEvent.click(screen.getByRole('button', { name: /Enter COGNIS/ }));
    leave();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(local.mock.calls.filter(([k]) => /intro|launch|enter|dismiss/i.test(String(k)))).toHaveLength(0);
    a.unmount();
    render(<App />); // a fresh launch
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('locks background scrolling while it is up and restores it when dismissed or unmounted', () => {
    const a = render(<App />);
    expect(document.documentElement).toHaveClass('cg-intro-lock');
    fireEvent.click(screen.getByRole('button', { name: /Enter COGNIS/ }));
    leave();
    expect(document.documentElement).not.toHaveClass('cg-intro-lock');
    a.unmount();
    render(<App />);
    expect(document.documentElement).toHaveClass('cg-intro-lock');
    cleanup();
    expect(document.documentElement).not.toHaveClass('cg-intro-lock');
  });

  it('keeps keyboard focus inside the dialog (Tab wraps) and starts on the primary action', () => {
    render(<App />);
    const enter = screen.getByRole('button', { name: /Enter COGNIS/ });
    expect(enter).toHaveFocus();
    const skip = screen.getByRole('button', { name: 'Skip intro' });
    skip.focus();
    fireEvent.keyDown(skip, { key: 'Tab' });
    expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true);
  });

  it('uses the genuine navy Atlas mark on the ivory surface in both themes', () => {
    for (const theme of ['dark', 'light'] as const) {
      usePreferences.setState({ theme });
      const r = render(<App />);
      const img = document.querySelector('.li-logo img') as HTMLImageElement;
      expect(img.dataset.logo).toBe('navy');
      expect(img.getAttribute('src')).toMatch(/brand\/cognis-atlas-navy\.png$/);
      r.unmount();
    }
  });

  describe('tour (five cards, one gesture = one card)', () => {
    const tourbox = () => screen.getByTestId('tour-carousel');
    const caption = () => screen.getByTestId('tour-caption');
    const activeId = () => TOUR_SLIDES.find((s) => screen.getByTestId(`tour-card-${s.id}`).dataset.state === 'active')?.id;
    /** A wheel event with a controlled timestamp (jsdom's own is wall-clock). */
    const wheel = (el: Element, deltaY: number, t: number, extra: Partial<WheelEventInit> = {}) => {
      const ev = new WheelEvent('wheel', { deltaY, bubbles: true, cancelable: true, ...extra });
      Object.defineProperty(ev, 'timeStamp', { value: t });
      act(() => void el.dispatchEvent(ev));
      return ev;
    };
    const matchWide = (wide: boolean) =>
      vi.spyOn(window, 'matchMedia').mockImplementation(
        (q: string) =>
          ({ matches: wide && q.includes('min-width: 861px'), media: q, addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false, onchange: null }) as unknown as MediaQueryList,
      );

    it('shows the five local cards at once (no delay, no lazy chunk), the first active, with alt text on the visible one', () => {
      render(<App />);
      const tour = tourbox();
      const cards = TOUR_SLIDES.map((s) => screen.getByTestId(`tour-card-${s.id}`));
      expect(cards).toHaveLength(5);
      expect(cards.map((c) => c.dataset.state)).toEqual(['active', 'after', 'after', 'after', 'after']);
      cards.forEach((c, i) => {
        const img = c.querySelector('img')!;
        expect(img.getAttribute('src')).toMatch(/\/intro\/[a-z-]+\.svg$/);
        if (i === 0) expect(img.getAttribute('alt')!.length).toBeGreaterThan(15);
        else expect(c).toHaveAttribute('aria-hidden', 'true'); // only the current card is exposed to assistive tech
      });
      expect(tour.querySelector('.depth-carousel')).toBeNull();
      expect(caption()).toHaveTextContent('01 / 05');
      expect(caption()).toHaveTextContent(TOUR_SLIDES[0].title);
    });

    it('one wheel gesture advances exactly one card, and the next gesture the next one', () => {
      render(<App />);
      wheel(tourbox(), 100, 1000);
      expect(activeId()).toBe(TOUR_SLIDES[1].id);
      expect(caption()).toHaveTextContent('02 / 05');
      wheel(tourbox(), 100, 2000); // a separate gesture, well after the lock
      expect(activeId()).toBe(TOUR_SLIDES[2].id);
    });

    it('a trackpad swipe (dozens of events, inertia tail) moves one card only', () => {
      render(<App />);
      let t = 1000;
      for (let i = 0; i < 60; i++) {
        wheel(tourbox(), Math.max(6, 120 - i * 2), t); // ~1 s of decaying deltas, every 16 ms
        t += 16;
      }
      expect(activeId()).toBe(TOUR_SLIDES[1].id);
      wheel(tourbox(), 120, t + 400); // after it settles, a new swipe moves one more
      expect(activeId()).toBe(TOUR_SLIDES[2].id);
    });

    it('scrolling up goes back one card; it stops at both ends instead of wrapping', () => {
      render(<App />);
      wheel(tourbox(), -100, 1000);
      expect(activeId()).toBe(TOUR_SLIDES[0].id); // first card: nothing before it
      wheel(tourbox(), 100, 2000);
      wheel(tourbox(), -100, 3000);
      expect(activeId()).toBe(TOUR_SLIDES[0].id);
      for (let i = 0; i < 8; i++) wheel(tourbox(), 100, 4000 + i * 1000);
      expect(activeId()).toBe(TOUR_SLIDES[4].id); // last card: it does not loop
    });

    it('prevents the page behind from scrolling and ignores pinch-zoom', () => {
      render(<App />);
      expect(wheel(tourbox(), 100, 1000).defaultPrevented).toBe(true);
      expect(wheel(tourbox(), 100, 3000, { ctrlKey: true }).defaultPrevented).toBe(false);
      expect(activeId()).toBe(TOUR_SLIDES[1].id); // the ctrl-wheel did not move it
    });

    it('on a wide screen the wheel works anywhere in the intro, not only over the cards', () => {
      matchWide(true);
      render(<App />);
      wheel(screen.getByRole('heading', { name: 'COGNIS' }), 100, 1000);
      expect(activeId()).toBe(TOUR_SLIDES[1].id);
    });

    it('the cursor never moves the cards: pointer movement and mouse drags do nothing', () => {
      render(<App />);
      const box = tourbox();
      for (let x = 0; x < 1200; x += 40) fireEvent.pointerMove(box, { clientX: x, clientY: 200, pointerType: 'mouse' });
      fireEvent.mouseMove(box, { clientX: 900, clientY: 300 });
      fireEvent.pointerDown(box, { clientX: 900, clientY: 200, pointerType: 'mouse' });
      fireEvent.pointerUp(box, { clientX: 100, clientY: 200, pointerType: 'mouse' });
      expect(activeId()).toBe(TOUR_SLIDES[0].id);
      expect(introTourSource).not.toMatch(/mousemove|pointermove|requestAnimationFrame|setInterval/);
    });

    it('previous / next arrows and the step indicators move; the arrows disable at the ends', () => {
      render(<App />);
      const prev = screen.getByRole('button', { name: 'Previous step' });
      const next = screen.getByRole('button', { name: 'Next step' });
      expect(prev).toBeDisabled();
      fireEvent.click(next);
      expect(activeId()).toBe(TOUR_SLIDES[1].id);
      expect(prev).not.toBeDisabled();
      fireEvent.click(screen.getByRole('button', { name: `Step 4: ${TOUR_SLIDES[3].title}` }));
      expect(activeId()).toBe(TOUR_SLIDES[3].id);
      expect(screen.getByRole('button', { name: `Step 4: ${TOUR_SLIDES[3].title}` })).toHaveAttribute('aria-current', 'step');
      fireEvent.click(next);
      expect(activeId()).toBe(TOUR_SLIDES[4].id);
      expect(next).toBeDisabled();
      fireEvent.click(prev);
      expect(activeId()).toBe(TOUR_SLIDES[3].id);
    });

    it('arrow keys, Home and End work on the focused tour', () => {
      render(<App />);
      fireEvent.keyDown(tourbox(), { key: 'ArrowRight' });
      fireEvent.keyDown(tourbox(), { key: 'ArrowDown' });
      expect(activeId()).toBe(TOUR_SLIDES[2].id);
      fireEvent.keyDown(tourbox(), { key: 'ArrowLeft' });
      expect(activeId()).toBe(TOUR_SLIDES[1].id);
      fireEvent.keyDown(tourbox(), { key: 'End' });
      expect(activeId()).toBe(TOUR_SLIDES[4].id);
      fireEvent.keyDown(tourbox(), { key: 'Home' });
      expect(activeId()).toBe(TOUR_SLIDES[0].id);
    });

    it('a finger swipe moves one card; a short touch does not', () => {
      render(<App />);
      fireEvent.pointerDown(tourbox(), { clientX: 300, pointerType: 'touch' });
      fireEvent.pointerUp(tourbox(), { clientX: 280, pointerType: 'touch' });
      expect(activeId()).toBe(TOUR_SLIDES[0].id);
      fireEvent.pointerDown(tourbox(), { clientX: 300, pointerType: 'touch' });
      fireEvent.pointerUp(tourbox(), { clientX: 120, pointerType: 'touch' });
      expect(activeId()).toBe(TOUR_SLIDES[1].id);
      fireEvent.pointerDown(tourbox(), { clientX: 100, pointerType: 'touch' });
      fireEvent.pointerUp(tourbox(), { clientX: 260, pointerType: 'touch' });
      expect(activeId()).toBe(TOUR_SLIDES[0].id);
    });

    it('the left-hand step list follows the active card; nothing advances on its own (no autoplay)', () => {
      render(<App />);
      fireEvent.click(screen.getByRole('button', { name: 'Next step' }));
      expect(screen.getByLabelText('The five-step tour').querySelector('.is-on')).toHaveTextContent(TOUR_SLIDES[1].title);
      act(() => void vi.advanceTimersByTime(60_000));
      expect(activeId()).toBe(TOUR_SLIDES[1].id);
    });

    it('still dismisses through Enter COGNIS while the tour is up', () => {
      render(<App />);
      fireEvent.click(screen.getByRole('button', { name: /Enter COGNIS/ }));
      expect(screen.getByText('Dashboard')).toBeInTheDocument();
    });

    it('reduced motion: the tour is flagged, transitions and animations are off, and the gesture rule is unchanged', () => {
      usePreferences.setState({ motion: 'reduced' });
      render(<App />);
      expect(screen.getByRole('dialog')).toHaveAttribute('data-reduced');
      expect(tourbox()).toHaveAttribute('data-reduced');
      expect(introCss).toMatch(/\[data-reduced\][\s\S]*animation: none !important/);
      expect(introCss).toMatch(/\.launch-intro\[data-reduced\] \.li-card[\s\S]*?transition: none !important/);
      expect(introCss).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*transition: none !important/);
      wheel(tourbox(), 100, 1000);
      wheel(tourbox(), 100, 1100); // inside the lock: ignored
      expect(activeId()).toBe(TOUR_SLIDES[1].id);
    });

    it('the card transition is light: transform + opacity only, no filters, no permanent will-change', () => {
      const card = introCss.slice(introCss.indexOf('.li-card {'), introCss.indexOf('.li-card img {'));
      expect(card).toMatch(/transition:[\s\S]*transform[\s\S]*opacity/);
      expect(card).not.toMatch(/filter|blur|backdrop|will-change/);
      expect(introCss).not.toMatch(/\.li-depth|depth-carousel/);
    });
  });
});

describe('tour slides', () => {
  it('five slides, each with a local SVG that exists, no external image URLs', () => {
    expect(TOUR_SLIDES).toHaveLength(5);
    expect(Object.keys(svgs)).toHaveLength(5);
    for (const s of TOUR_SLIDES) {
      const key = Object.keys(svgs).find((k) => k.endsWith(`/${s.file}`));
      expect(key, s.file).toBeTruthy();
      expect(svgs[key!]).toMatch(/^<svg[^>]+width="1200"[^>]+height="800"/);
      // (provenance metadata added by the file-sync layer may reference c2pa.org; that is a namespace, not a fetched image)
      expect(svgs[key!]).not.toMatch(/https?:\/\/(?!www\.w3\.org|c2pa\.org)/);
      expect(s.alt.length).toBeGreaterThan(15);
    }
  });
  it('the tour is plain React + CSS: no gsap / DepthCarousel, no autoplay, no per-frame work; the gesture rule lives in wheelGate', () => {
    expect(introTourSource).not.toMatch(/gsap|DepthCarousel|autoplay|AUTOPLAY|requestAnimationFrame|setInterval|mousemove|pointermove/);
    expect(introTourSource).toContain('createWheelGate');
    expect(gateSource).not.toMatch(/clientX|clientY|pageX|pageY|offsetX|offsetY/); // the cursor position plays no part
  });
});

describe('dot cursor', () => {
  const media = (fine: boolean) =>
    vi.spyOn(window, 'matchMedia').mockImplementation(
      (q: string) =>
        ({ matches: fine && q.includes('pointer: fine'), media: q, addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false, onchange: null }) as unknown as MediaQueryList,
    );
  const move = (x: number, y: number, target: Element | Window = window) => fireEvent(target, new MouseEvent('pointermove', { clientX: x, clientY: y, bubbles: true }));

  it('does not exist on touch / coarse-pointer devices', () => {
    media(false);
    render(<DotCursor />);
    expect(screen.queryByTestId('dot-cursor')).not.toBeInTheDocument();
    expect(document.documentElement).not.toHaveClass('cg-cursor-on');
  });

  it('with a mouse: one non-interactive dot that follows the pointer, steps aside over text fields and grows over controls', () => {
    media(true);
    usePreferences.setState({ motion: 'reduced' }); // follows exactly, no easing
    render(
      <>
        <DotCursor />
        <button>btn</button>
        <input aria-label="field" />
      </>,
    );
    const dot = screen.getByTestId('dot-cursor');
    expect(document.querySelectorAll('.cg-dot-cursor')).toHaveLength(1);
    expect(document.documentElement).toHaveClass('cg-cursor-on');
    move(120, 80);
    expect(dot.style.transform).toContain('120px, 80px');
    move(10, 10, screen.getByRole('button'));
    expect(dot).toHaveAttribute('data-active');
    move(10, 10, screen.getByLabelText('field'));
    expect(dot).toHaveAttribute('data-hidden');
    expect(dot).not.toHaveAttribute('data-active');
    expect(cursorCss).toMatch(/\.cg-dot-cursor\s*{[^}]*pointer-events:\s*none/);
    expect(cursorCss).not.toMatch(/user-select/); // text selection is untouched
  });

  it('eases towards the pointer with requestAnimationFrame when motion is allowed', () => {
    media(true);
    usePreferences.setState({ motion: 'full' });
    const raf = vi.spyOn(window, 'requestAnimationFrame');
    render(<DotCursor />);
    move(50, 50); // first move places it
    move(300, 300); // later moves ease
    expect(raf).toHaveBeenCalled();
  });

  it('cleans up completely on unmount: listeners, animation frame and the root class', () => {
    media(true);
    usePreferences.setState({ motion: 'full' });
    const add = vi.spyOn(window, 'addEventListener');
    const remove = vi.spyOn(window, 'removeEventListener');
    const cancel = vi.spyOn(window, 'cancelAnimationFrame');
    const r = render(<DotCursor />);
    move(1, 1);
    move(200, 200);
    const added = add.mock.calls.filter(([t]) => String(t).startsWith('pointer')).map(([t]) => t);
    expect(added.length).toBeGreaterThan(0);
    r.unmount();
    for (const t of added) expect(remove.mock.calls.some(([x]) => x === t)).toBe(true);
    expect(cancel).toHaveBeenCalled();
    expect(document.documentElement).not.toHaveClass('cg-cursor-on');
  });
});

describe('premium intro: backdrop and art contract', () => {
  it('renders a decorative, aria-hidden CSS backdrop with no canvas/WebGL', () => {
    usePreferences.setState({ theme: 'dark', motion: 'full' });
    render(<App />);
    const bg = screen.getByTestId('intro-backdrop');
    expect(bg).toHaveAttribute('aria-hidden', 'true');
    expect(bg.querySelector('canvas')).toBeNull();
  });

  it('the one-off entrance animations are switched off by reduced motion', () => {
    expect(introCss).toMatch(/@keyframes li-/);
    expect(introCss).not.toMatch(/gradient[^;]*animation|WebGL/i);
    expect(introCss).toMatch(/prefers-reduced-motion: reduce/);
    expect(introCss).toMatch(/\.launch-intro\[data-reduced\] \*/);
  });

  it('every slide SVG is labelled as sample data and carries an accessible name', () => {
    for (const [k, v] of Object.entries(svgs)) {
      expect(v, k).toMatch(/aria-label="[^"]*[Ss]ample/);
      expect(v, k).toMatch(/Sample data/);
    }
  });

  it('the backdrop is a still: no continuous animation, so nothing repaints while the tour is used', () => {
    const infinite = [...introCss.matchAll(/animation:[^;]*infinite[^;]*;/g)];
    expect(infinite).toHaveLength(0);
    expect(introCss).not.toMatch(/@keyframes li-(spin|drift|float-a|float-b)/);
    expect(introCss).not.toMatch(/filter:\s*blur|backdrop-filter/);
  });

  it('dependency audit: gsap stays declared (the vendored, unused DepthCarousel imports it), ogl / FlexCarousel are not, and the lockfile agrees', () => {
    const lock = css('../../package-lock.json');
    expect(pkg.dependencies.gsap).toBeTruthy();
    expect(lock).toContain('node_modules/gsap');
    expect(pkg.dependencies.ogl).toBeUndefined();
    expect(lock).not.toContain('node_modules/ogl');
  });
});
