/**
 * The globe's motion, one frame at a time — pure, with no three.js and no DOM, so pause/resume, focus and reduced motion can be tested exactly.
 * GlobeCanvas calls `stepMotion` from its render loop and draws only when `needsRender` says something on screen changed.
 *
 * Rules:
 * - Playing (`spin`): the globe turns at `baseSpeed`, in real time. Slow frames do not slow it down (a frame may count up to MAX_FRAME_S).
 * - A *focus* (an explicit point: a hovered result, the search's top match, a story chapter) turns the globe to it and holds it there while it lasts.
 * - An *anchor* (a passive region, e.g. where the Discover results are) never stops the rotation. A paused globe turns to a NEW anchor once
 *   (so a paused or reduced-motion Discover globe shows the results); pausing never makes it jump.
 * - Paused: the rotation eases out and the globe then holds completely still — nothing moves, so nothing is rendered.
 * - Reduced motion: no sway, pointer parallax, scroll impulse or pulses. Explicit play still brings back the slow rotation.
 */
import type { MotionTuning } from './surface';
import { targetRotation, wrap } from './globeMath';

export const REST_PITCH = 0.36; // ~21°: a classic three-quarter view while spinning freely
/** Longest frame the motion counts in full. Rotation stays true to time down to ~4 fps; only a stall (tab in the background) is not caught up. */
export const MAX_FRAME_S = 0.25;
const STILL = 1e-6; // rad: below this nothing visible changed
const VEL_STOP = 0.002; // rad/s: a pausing globe below this speed has stopped (avoids seconds of invisible creeping)
const OFFSET_STOP = 1e-4; // rad: pointer/scroll offsets this small are settled

export interface GeoPoint {
  lat: number;
  lon: number;
}

export interface MotionState {
  yaw: number;
  pitch: number;
  vel: number; // current spin speed (rad/s)
  impulse: number; // wheel/scroll spin impulse (rad/s), decays to 0
  offX: number; // pointer orientation offsets (rad)
  offY: number;
  tilt: number; // scroll orientation nudge (rad)
  time: number; // animation clock for pulses and sway (advances only with full motion)
  anchorKey: string; // last anchor seen
  seek: GeoPoint | null; // one-shot target of a paused globe (a new anchor)
}

export interface MotionInput {
  spin: boolean; // resolved play/pause choice
  reducedMotion: boolean;
  focus: GeoPoint | null;
  anchor: GeoPoint | null;
  pointer: { x: number; y: number; live: boolean };
}

export function initialMotion(home: GeoPoint): MotionState {
  return { yaw: targetRotation(home.lat, home.lon).y, pitch: REST_PITCH, vel: 0, impulse: 0, offX: 0, offY: 0, tilt: 0, time: 0, anchorKey: '', seek: null };
}

export function frameSeconds(elapsedMs: number): number {
  return Math.max(0, Math.min(MAX_FRAME_S, elapsedMs / 1000));
}

const keyOf = (p: GeoPoint | null) => (p ? `${p.lat.toFixed(3)},${p.lon.toFixed(3)}` : '');

/** Advance the motion by `dt` seconds. Returns the new state and whether the orientation visibly changed. */
export function stepMotion(s: MotionState, input: MotionInput, dt: number, tune: MotionTuning): { state: MotionState; moved: boolean } {
  const rm = input.reducedMotion;
  const rotating = input.spin;
  const lively = rotating && !rm;
  const ease = (rate: number) => 1 - Math.exp(-dt * rate);
  const n = { ...s };

  // A new anchor (e.g. new Discover results) is remembered; a paused globe turns to it once. Pausing itself never turns the globe anywhere.
  const anchorKey = keyOf(input.anchor);
  if (anchorKey !== n.anchorKey) {
    n.anchorKey = anchorKey;
    n.seek = !rotating && input.anchor ? { ...input.anchor } : null;
  }
  if (rotating) n.seek = null;

  n.impulse = lively ? n.impulse * Math.exp(-dt / tune.impulseDecayS) : 0;
  if (Math.abs(n.impulse) < 1e-4) n.impulse = 0;

  const target = input.focus ?? n.seek;
  if (target) {
    // turn towards the point, then hold it (a gentle sway keeps a held globe from looking frozen when motion is allowed)
    const t = targetRotation(target.lat, target.lon);
    const sway = lively && input.focus ? Math.sin(n.time * 0.22) * 0.05 : 0;
    const k = rm ? 1 : ease(2.4);
    n.yaw += wrap(t.y + sway - n.yaw) * k;
    n.pitch += (t.x - n.pitch) * k;
    n.vel += (0 - n.vel) * (rm ? 1 : ease(3));
    if (n.seek && Math.abs(wrap(t.y - n.yaw)) < 1e-4 && Math.abs(t.x - n.pitch) < 1e-4) {
      n.yaw = t.y;
      n.pitch = t.x;
      n.seek = null; // arrived: the paused globe now holds still
    }
  } else {
    const want = (rotating ? tune.baseSpeed : 0) + n.impulse;
    n.vel = rm && !rotating ? 0 : n.vel + (want - n.vel) * ease(3);
    if (!rotating && Math.abs(n.vel) < VEL_STOP) n.vel = 0;
    n.yaw += n.vel * dt;
    if (rotating) {
      // a turning globe settles into the three-quarter view; a paused one keeps the view it was left at (e.g. the results it turned to)
      n.pitch += (REST_PITCH - n.pitch) * (rm ? 1 : ease(1.2));
      if (Math.abs(REST_PITCH - n.pitch) < 1e-5) n.pitch = REST_PITCH;
    }
  }
  if (n.yaw > Math.PI || n.yaw <= -Math.PI) n.yaw = wrap(n.yaw); // only when it left the range: re-wrapping an unchanged angle would add float noise

  // pointer: small orientation offset that relaxes once the pointer rests; scroll: a small tilt while the impulse lasts
  const pointerLive = lively && input.pointer.live;
  n.offX += ((pointerLive ? input.pointer.x * tune.pointerYaw : 0) - n.offX) * ease(1.8);
  n.offY += ((pointerLive ? input.pointer.y * tune.pointerPitch : 0) - n.offY) * ease(1.8);
  n.tilt += ((lively ? -n.impulse * 0.25 : 0) - n.tilt) * ease(2.5);
  if (!pointerLive) {
    if (Math.abs(n.offX) < OFFSET_STOP) n.offX = 0;
    if (Math.abs(n.offY) < OFFSET_STOP) n.offY = 0;
  }
  if (!lively && Math.abs(n.tilt) < OFFSET_STOP) n.tilt = 0;
  if (lively) n.time += dt;

  const moved =
    Math.abs(wrap(n.yaw - s.yaw)) + Math.abs(n.pitch - s.pitch) + Math.abs(n.offX - s.offX) + Math.abs(n.offY - s.offY) + Math.abs(n.tilt - s.tilt) > STILL;
  return { state: n, moved };
}

/** Draw only when something on screen changes: full motion animates pulses every frame; otherwise only a moved globe or a scene change. */
export function needsRender({ lively, moved, dirty }: { lively: boolean; moved: boolean; dirty: boolean }): boolean {
  return lively || moved || dirty;
}
