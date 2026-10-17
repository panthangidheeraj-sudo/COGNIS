/** The wheel / trackpad rule behind the intro tour: one deliberate gesture = one step. */
import { describe, expect, it } from 'vitest';
import { createWheelGate, WHEEL_LOCK_MS, WHEEL_PAUSE_MS } from '@/components/intro/wheelGate';

const ev = (deltaY: number, t: number, extra: { deltaX?: number; deltaMode?: number } = {}) => ({ deltaX: 0, deltaMode: 0, ...extra, deltaY, t });

describe('createWheelGate', () => {
  it('a single mouse-wheel notch is one step, in the direction of the scroll', () => {
    const g = createWheelGate();
    expect(g.push(ev(100, 1000))).toBe(1);
    g.reset();
    expect(g.push(ev(-100, 5000))).toBe(-1);
  });

  it('ignores tiny deltas', () => {
    const g = createWheelGate();
    expect(g.push(ev(1, 1000))).toBe(0);
    expect(g.push(ev(-2, 2000))).toBe(0);
  });

  it('a long decaying trackpad stream yields exactly one step', () => {
    const g = createWheelGate();
    let steps = 0;
    for (let i = 0; i < 120; i++) steps += Math.abs(g.push(ev(Math.max(5, 150 - i * 2), 1000 + i * 16)));
    expect(steps).toBe(1);
  });

  it('a second gesture after a pause steps again, but not while the lock is on', () => {
    const g = createWheelGate();
    expect(g.push(ev(100, 1000))).toBe(1);
    expect(g.push(ev(100, 1000 + WHEEL_PAUSE_MS + 10))).toBe(0); // still locked
    expect(g.push(ev(100, 1000 + WHEEL_LOCK_MS + WHEEL_PAUSE_MS + 400))).toBe(1);
  });

  it('a clearly stronger push inside a tail counts as a new gesture once the lock has ended', () => {
    const g = createWheelGate();
    expect(g.push(ev(120, 1000))).toBe(1);
    let t = 1016;
    for (; t < 1000 + WHEEL_LOCK_MS + 50; t += 16) g.push(ev(8, t)); // weak tail
    expect(g.push(ev(160, t))).toBe(1);
  });

  it('scales line and page deltas, and treats a sideways swipe like a vertical one', () => {
    const g = createWheelGate();
    expect(g.push(ev(0.5, 1000, { deltaMode: 1 }))).toBe(1); // 0.5 line = 8px
    g.reset();
    expect(g.push({ deltaX: 90, deltaY: 3, deltaMode: 0, t: 5000 })).toBe(1);
    g.reset();
    expect(g.push({ deltaX: -90, deltaY: 3, deltaMode: 0, t: 9000 })).toBe(-1);
  });
});
