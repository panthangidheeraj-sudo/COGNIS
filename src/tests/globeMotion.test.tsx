/**
 * Globe animation: the Home and Discover globes really turn while playing, really stop (and stop drawing) when paused, and keep reduced-motion behaviour.
 *
 * Regressions measured in a browser before the fix: on Discover the results' centre was used as a *focus*, which holds the globe, so play/pause
 * changed nothing visible while the scene was still re-rendered every frame; and every frame was capped at 50 ms of motion, so at 7 fps the
 * globe turned at 0.7°/s instead of 2.9°/s. The motion is pure (globeMotion.ts), so it is tested here frame by frame without WebGL.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from './utils';
import { frameSeconds, initialMotion, MAX_FRAME_S, needsRender, stepMotion, type MotionInput, type MotionState } from '@/components/globe/globeMotion';
import { targetRotation, wrap } from '@/components/globe/globeMath';
import type { MotionTuning } from '@/components/globe/surface';
import { GlobeStage } from '@/components/globe/GlobeStage';
import { useGlobe } from '@/stores/ui';
import { usePreferences } from '@/stores/preferences';

const TUNE: MotionTuning = { baseSpeed: 0.05, maxImpulse: 0.16, impulsePerPx: 0.0006, impulseDecayS: 1.1, pointerYaw: 0.09, pointerPitch: 0.05, pointerCam: 0.06 };
const NORWAY = { lat: 64.5, lon: 11 };
const PLAY: MotionInput = { spin: true, reducedMotion: false, focus: null, anchor: null, pointer: { x: 0, y: 0, live: false } };
const PAUSE: MotionInput = { ...PLAY, spin: false };
const RAD = 180 / Math.PI;

/** Run the motion for `seconds` at `fps`; returns the end state, how far it turned (rad) and the frames that would have been drawn. */
function run(state: MotionState, input: MotionInput, seconds: number, fps = 60) {
  let s = state;
  let turned = 0;
  let drawn = 0;
  const frames = Math.round(seconds * fps);
  for (let i = 0; i < frames; i++) {
    const step = stepMotion(s, input, frameSeconds(1000 / fps), TUNE);
    turned += wrap(step.state.yaw - s.yaw);
    if (needsRender({ lively: input.spin && !input.reducedMotion, moved: step.moved, dirty: false })) drawn++;
    s = step.state;
  }
  return { state: s, turned, drawn, frames };
}
const spunUp = () => run(initialMotion({ lat: 58, lon: 14 }), PLAY, 3).state;

describe('playing', () => {
  it('turns at the base speed (≈2.9°/s for the intel globe)', () => {
    const { turned } = run(spunUp(), PLAY, 4);
    expect((turned / 4) * RAD).toBeCloseTo(TUNE.baseSpeed * RAD, 1);
  });

  it('keeps real time on a slow device: 7 fps turns as far as 60 fps (no slow motion)', () => {
    const fast = run(spunUp(), PLAY, 4, 60).turned;
    const slow = run(spunUp(), PLAY, 4, 7).turned;
    expect(slow / fast).toBeGreaterThan(0.97);
    expect(frameSeconds(1000 / 7)).toBeCloseTo(1 / 7, 5);
    expect(frameSeconds(60_000)).toBe(MAX_FRAME_S); // a stalled tab is not caught up in one jump
  });

  it('keeps turning when the results set an anchor (the Discover globe used to stand still here)', () => {
    const { turned } = run(spunUp(), { ...PLAY, anchor: NORWAY }, 4);
    expect((turned / 4) * RAD).toBeGreaterThan(2.5);
  });

  it('turns to an explicit focus (a hovered result) and holds it, then turns on once the focus is gone', () => {
    const held = run(spunUp(), { ...PLAY, focus: NORWAY }, 6);
    const t = targetRotation(NORWAY.lat, NORWAY.lon);
    expect(Math.abs(wrap(held.state.yaw - t.y))).toBeLessThan(0.06); // only the gentle sway remains
    const later = run(held.state, { ...PLAY, focus: NORWAY }, 3);
    expect(Math.abs(later.turned)).toBeLessThan(0.1);
    const free = run(later.state, PLAY, 4);
    expect(free.turned).toBeGreaterThan(0.12); // rotation resumes from where it held
  });
});

describe('pause and resume', () => {
  it('pausing stops the rotation within a second and then draws nothing at all', () => {
    const paused = run(spunUp(), PAUSE, 1.2);
    expect(paused.state.vel).toBe(0);
    const still = run(paused.state, PAUSE, 5);
    expect(still.turned).toBe(0);
    expect(still.drawn).toBe(0); // no GPU work while paused
  });

  it('pausing never makes the globe jump, not even with an anchor set', () => {
    const playing = run(spunUp(), { ...PLAY, anchor: NORWAY }, 2).state;
    const paused = run(playing, { ...PAUSE, anchor: NORWAY }, 3);
    expect(Math.abs(paused.turned)).toBeLessThan(0.02); // only the ease-out of the spin, no turn towards Norway
  });

  it('a paused globe turns to NEW results once, then holds still', () => {
    const paused = run(spunUp(), PAUSE, 2).state;
    const seek = run(paused, { ...PAUSE, anchor: NORWAY }, 4);
    const t = targetRotation(NORWAY.lat, NORWAY.lon);
    expect(Math.abs(wrap(seek.state.yaw - t.y))).toBeLessThan(1e-3);
    const after = run(seek.state, { ...PAUSE, anchor: NORWAY }, 3);
    expect(after.drawn).toBe(0);
  });

  it('resuming turns it again', () => {
    const paused = run(run(spunUp(), PAUSE, 3).state, PAUSE, 1).state;
    const resumed = run(paused, PLAY, 4);
    expect(resumed.turned).toBeGreaterThan(0.15);
    expect(resumed.drawn).toBe(resumed.frames); // full motion animates every frame
  });
});

describe('reduced motion', () => {
  const RM: MotionInput = { ...PAUSE, reducedMotion: true };

  it('holds the globe completely still by default and draws nothing', () => {
    const { turned, drawn } = run(initialMotion({ lat: 58, lon: 14 }), RM, 5);
    expect(turned).toBe(0);
    expect(drawn).toBe(0);
  });

  it('explicit play brings back only the slow rotation: no sway, no pointer parallax, no scroll impulse', () => {
    const input: MotionInput = { ...RM, spin: true, pointer: { x: 0.8, y: -0.5, live: true } };
    let s = initialMotion({ lat: 58, lon: 14 });
    s.impulse = 0.15; // a scroll just happened
    const r = run(s, input, 4);
    expect((r.turned / 4) * RAD).toBeGreaterThan(2.5);
    expect(r.state.offX).toBe(0);
    expect(r.state.offY).toBe(0);
    expect(r.state.impulse).toBe(0);
    expect(r.state.time).toBe(0); // no pulses or sway clock
    s = r.state;
    const held = run(s, { ...input, focus: NORWAY }, 2); // a focus under reduced motion is a single cut, then nothing moves
    expect(run(held.state, { ...input, focus: NORWAY }, 2).drawn).toBe(0);
  });
});

/* ------------------------------------------------------------------------------- the pause button and the stage -- */
type GlobeProps = { focus: unknown; anchor: unknown; spin: boolean; reducedMotion: boolean };
const seen: GlobeProps[] = [];
vi.mock('@/components/globe/IntelGlobe', () => ({
  default: (p: GlobeProps) => {
    seen.push(p);
    return <div data-testid="webgl-globe" data-spin={String(p.spin)} />;
  },
}));

describe('the globe button', () => {
  const getContext = HTMLCanvasElement.prototype.getContext;
  beforeEach(() => {
    seen.length = 0;
    usePreferences.setState({ globeSpin: 'auto', motion: 'system' });
    useGlobe.setState({ focus: null, anchor: null, points: [] });
    // jsdom has no WebGL: report one so the stage mounts the (mocked) WebGL globe and its pause button
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, kind: string) {
      return kind.startsWith('webgl') ? ({} as RenderingContext) : getContext.call(this, kind as '2d');
    } as typeof getContext;
  });
  afterEach(() => {
    HTMLCanvasElement.prototype.getContext = getContext;
  });

  it('pauses and resumes the rotation and remembers the choice', async () => {
    renderWithProviders(<GlobeStage />);
    const globe = await screen.findByTestId('webgl-globe');
    expect(globe).toHaveAttribute('data-spin', 'true');
    fireEvent.click(screen.getByRole('button', { name: 'Pause globe rotation' }));
    expect(await screen.findByTestId('webgl-globe')).toHaveAttribute('data-spin', 'false');
    expect(usePreferences.getState().globeSpin).toBe('off');
    fireEvent.click(screen.getByRole('button', { name: 'Rotate globe' }));
    expect(await screen.findByTestId('webgl-globe')).toHaveAttribute('data-spin', 'true');
    expect(screen.getByRole('button', { name: 'Pause globe rotation' })).toHaveAttribute('aria-pressed', 'true');
    expect(usePreferences.getState().globeSpin).toBe('on');
  });

  it('starts paused under reduced motion, and play still works', async () => {
    usePreferences.setState({ motion: 'reduced' });
    renderWithProviders(<GlobeStage />);
    expect(await screen.findByTestId('webgl-globe')).toHaveAttribute('data-spin', 'false');
    fireEvent.click(screen.getByRole('button', { name: 'Rotate globe' }));
    await waitFor(() => expect(screen.getByTestId('webgl-globe')).toHaveAttribute('data-spin', 'true'));
    expect(seen.at(-1)?.reducedMotion).toBe(true); // the globe still knows to leave out sway, parallax and pulses
  });

  it('passes the results as an anchor, separate from the hover focus', async () => {
    renderWithProviders(<GlobeStage />);
    await screen.findByTestId('webgl-globe');
    act(() => useGlobe.getState().setAnchor({ id: 'disc-centroid', ...NORWAY }));
    await waitFor(() => expect(seen.at(-1)?.anchor).toMatchObject(NORWAY));
    expect(seen.at(-1)?.focus).toBeNull();
  });
});
