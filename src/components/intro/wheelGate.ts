/**
 * Turns the stream of wheel / trackpad events into at most ONE step per deliberate gesture.
 *
 * A mouse wheel notch is one large event; a trackpad swipe is dozens of events that keep arriving for a second or more as inertia dies out. Counting events
 * (or even time alone) would skip several cards for one swipe. A step is allowed only when the previous one has settled and the event starts a NEW gesture:
 * either it follows a pause in the stream, or it is clearly stronger than the tail that came before it (the visitor pushed again). The cursor position plays
 * no part: only the wheel deltas do.
 */
export const WHEEL_LOCK_MS = 650;
export const WHEEL_PAUSE_MS = 180;
export const WHEEL_MIN_DELTA = 4;

export interface WheelSample {
  deltaX: number;
  deltaY: number;
  /** 0 = pixels, 1 = lines, 2 = pages (WheelEvent.deltaMode). */
  deltaMode: number;
  /** Milliseconds, any monotonic clock. */
  t: number;
}

export function createWheelGate(opts: { lockMs?: number; pauseMs?: number; minDelta?: number } = {}) {
  const lockMs = opts.lockMs ?? WHEEL_LOCK_MS;
  const pauseMs = opts.pauseMs ?? WHEEL_PAUSE_MS;
  const minDelta = opts.minDelta ?? WHEEL_MIN_DELTA;
  let lockedUntil = -Infinity;
  let lastT = -Infinity;
  let lastAbs = 0;
  return {
    /** +1 = next card, -1 = previous card, 0 = ignore this event. */
    push(s: WheelSample): -1 | 0 | 1 {
      const raw = Math.abs(s.deltaX) > Math.abs(s.deltaY) ? s.deltaX : s.deltaY; // a sideways swipe counts as well
      const d = raw * (s.deltaMode === 1 ? 16 : s.deltaMode === 2 ? 800 : 1);
      const abs = Math.abs(d);
      const gap = s.t - lastT;
      lastT = s.t;
      const previous = lastAbs;
      lastAbs = abs;
      if (abs < minDelta) return 0;
      if (s.t < lockedUntil) return 0;
      const fresh = gap > pauseMs; // the stream paused: this is a new gesture
      const pushedAgain = abs > previous * 1.6 + 12; // still inside a tail, but clearly a new push
      if (!fresh && !pushedAgain) return 0;
      lockedUntil = s.t + lockMs;
      return d > 0 ? 1 : -1;
    },
    reset(): void {
      lockedUntil = -Infinity;
      lastT = -Infinity;
      lastAbs = 0;
    },
  };
}
