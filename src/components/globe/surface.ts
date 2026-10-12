import type * as THREE from 'three';

/**
 * What a globe look provides to the shared scene (GlobeCanvas): the sphere and its atmosphere, the style of the data
 * markers and decorative arcs, and its own motion tuning. Two looks exist:
 *  - `intel`: the monochrome corporate-intelligence globe (Home, Discover). No imagery.
 *  - `earth`: the natural Blue Marble Earth (the About story only).
 */
export interface SurfaceContext {
  renderer: THREE.WebGLRenderer;
  lowPower: boolean;
  light: boolean;
  /** Ask for another frame (textures arriving after the first render). */
  invalidate: () => void;
}

export interface MarkerStyle {
  core: string;
  focusCore: string;
  ring: string;
  focusRing: string;
  coreScale: number;
  focusCoreScale: number;
  ringBase: number;
  focusRingBase: number;
  ringSpan: number;
  focusRingSpan: number;
  ringOpacity: number;
  focusRingOpacity: number;
}

export interface ArcStyle {
  /** Decorative connection arcs from Oslo; they carry no data meaning. */
  hubs: [number, number][];
  color: THREE.Color;
  /** multipliers of the faint resting line and of the travelling signal */
  base: number;
  signal: number;
  /** small static nodes at the arc ends */
  nodes?: { color: string; size: number; opacity: number };
}

export interface MotionTuning {
  baseSpeed: number; // rad/s of the idle rotation
  maxImpulse: number; // rad/s a scroll can add, at most
  impulsePerPx: number;
  impulseDecayS: number; // seconds to settle back to the idle rotation
  pointerYaw: number; // rad of orientation shift at the screen edge
  pointerPitch: number;
  pointerCam: number; // camera parallax
}

export interface GlobeSurface {
  /** rotates with the globe */
  globe: THREE.Object3D[];
  /** stays with the camera (atmosphere halo) */
  scene: THREE.Object3D[];
  markers: MarkerStyle;
  arcs: ArcStyle;
  motion: MotionTuning;
  /** per frame; `time` only advances while the globe is fully lively */
  update(time: number, lively: boolean): void;
  resize?(width: number, height: number): void;
  /** true once the look is fully on screen; the stage then fades the static globe out */
  ready(): boolean;
  dispose(): void;
}

export type SurfaceFactory = (ctx: SurfaceContext) => GlobeSurface;
