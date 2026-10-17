/**
 * The monochrome intelligence globe (Home, Discover and anywhere else the workspace shows the globe).
 *
 * Look: a bright ivory-white sphere (the oceans) with navy-ink geography: fine dots for land, a crisp coastline with one faint
 * inland contour, a soft steel rim that rounds the limb, and a barely-there silver halo. No satellite imagery: geography comes
 * from Natural Earth (the same dots as the static fallback, plus a 2048x1024 land mask for the coast). Sparse, small nodes mark
 * places. It is an instrument, not a picture of the planet, so nothing in it glows or colours.
 */
import * as THREE from 'three';
import type { GlobeSurface, SurfaceContext } from '../surface';
import { createHalo } from './halo';
import { SPHERE_RADIUS } from '../globeMath';
import { latLonToVec } from '../globeVec';
import { DOT_LIMB, dotCountForRadius, dotSeed, dotSizeForRadius, orderedLandDots } from '../dotLattice';
import { INTEL_DARK, INTEL_LIGHT, INTEL_SUN } from '../intelPalette';
import maskUrl from '../assets/land-mask-2k.png';

/** Straight sRGB values (the shaders write to the canvas without a colour-space conversion). */
const raw = (hex: string) => new THREE.Color().setStyle(hex, THREE.LinearSRGBColorSpace);

// A few connection points, drawn from Oslo: decorative, they carry no data meaning.
const ARC_HUBS: [number, number][] = [
  [51.5, -0.12], // London
  [40.7, -74.0], // New York
  [25.2, 55.27], // Dubai
  [1.35, 103.8], // Singapore
  [35.68, 139.7], // Tokyo
];

export function createIntelSurface({ renderer, lowPower, light, invalidate }: SurfaceContext): GlobeSurface {
  const pal = light ? INTEL_LIGHT : INTEL_DARK;
  const sun = new THREE.Vector3(...INTEL_SUN).normalize();

  // ---- Land mask (coastline, faint land tone, inland contour) ----
  let maskLoaded = false;
  let maskFailed = false;
  const mask = new THREE.TextureLoader().load(
    maskUrl,
    () => {
      maskLoaded = true;
      sphereMat.uniforms.uHasMask.value = 1;
      invalidate();
    },
    undefined,
    () => {
      // dots and rim still draw; only the coastline is missing
      maskFailed = true;
      invalidate();
    },
  );
  mask.wrapS = THREE.RepeatWrapping;
  mask.wrapT = THREE.ClampToEdgeWrapping;
  mask.minFilter = THREE.LinearMipmapLinearFilter;
  mask.magFilter = THREE.LinearFilter;
  mask.generateMipmaps = true;
  mask.anisotropy = Math.min(4, renderer.capabilities.getMaxAnisotropy());

  // ---- Sphere: matte ivory-white, coast + contour from the mask, soft steel rim ----
  const sphereMat = new THREE.ShaderMaterial({
    uniforms: {
      uMask: { value: mask },
      uHasMask: { value: 0 },
      uSun: { value: sun },
      uDeep: { value: raw(pal.deep) },
      uMid: { value: raw(pal.mid) },
      uInk: { value: raw(pal.ink) },
      uRim: { value: raw(pal.rim) },
      uFill: { value: pal.fill },
      uCoast: { value: pal.coast },
      uContour: { value: pal.contour },
      uRimAmt: { value: pal.rimAmount },
      uRimPow: { value: pal.rimPower },
    },
    vertexShader: `
      varying vec3 vLocal; varying vec3 vN; varying vec3 vView;
      void main(){
        vLocal = position;
        vN = normalize(normalMatrix * normal);
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        vView = normalize(-mv.xyz);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      uniform sampler2D uMask; uniform float uHasMask;
      uniform vec3 uSun; uniform vec3 uDeep; uniform vec3 uMid; uniform vec3 uInk; uniform vec3 uRim;
      uniform float uFill; uniform float uCoast; uniform float uContour; uniform float uRimAmt; uniform float uRimPow;
      varying vec3 vLocal; varying vec3 vN; varying vec3 vView;
      const float TAU = 6.2831853;
      void main(){
        vec3 n = normalize(vN);
        float ndv = clamp(dot(n, normalize(vView)), 0.0, 1.0);
        float lit = smoothstep(-0.35, 0.75, dot(n, uSun));
        // matte: a soft fall-off from the lit face into the shade, no specular
        vec3 col = mix(uDeep, uMid, lit);

        // longitude / latitude of this fragment (the mesh turns with the globe, so object space is geographic)
        vec3 p = normalize(vLocal);
        vec2 uv = vec2(atan(-p.z, p.x) / TAU + 0.5, asin(clamp(p.y, -1.0, 1.0)) / (TAU * 0.5) + 0.5);
        // the wrap at +-180 degrees is not a real jump in the map: keep the derivatives continuous
        vec2 gx = dFdx(uv); vec2 gy = dFdy(uv);
        gx.x -= floor(gx.x + 0.5); gy.x -= floor(gy.x + 0.5);
        // a touch of extra filtering rounds off the mask's pixel steps without losing the coast's detail
        float m = textureGrad(uMask, uv, gx * 1.7, gy * 1.7).r;
        float soft = textureLod(uMask, uv, 2.0).r;
        float wide = textureLod(uMask, uv, 4.5).r;
        float view = smoothstep(0.04, 0.5, ndv); // lines thin out towards the limb
        float tone = (0.55 + 0.45 * lit) * uHasMask;

        // land: the faintest lift, so the continents read before the dots do
        col = mix(col, uInk, smoothstep(0.3, 0.75, soft) * uFill * tone);
        // coastline: the 0.5 contour of the mask, about one pixel wide
        float coast = 1.0 - smoothstep(0.0, max(fwidth(m), 0.004) * 1.0, abs(m - 0.5));
        col = mix(col, uInk, coast * uCoast * view * tone);
        // one soft contour a little inland: an echo of the coast, not a second outline
        float contour = 1.0 - smoothstep(0.0, max(fwidth(wide), 0.004) * 1.3, abs(wide - 0.7));
        col = mix(col, uInk, contour * uContour * view * tone);

        // restrained rim, a little stronger on the lit side
        float fres = pow(1.0 - ndv, uRimPow);
        col = mix(col, uRim, fres * uRimAmt * (0.35 + 0.65 * lit));
        gl_FragColor = vec4(col, 1.0);
      }`,
  });
  const segs = lowPower ? 40 : 64;
  const sphere = new THREE.Mesh(new THREE.SphereGeometry(1, segs, segs), sphereMat);

  // ---- Land dots (shared lattice with the static fallback; the coarse lattice comes first) ----
  const dots = orderedLandDots();
  const dotPos = new Float32Array(dots.total * 3);
  const dotSeeds = new Float32Array(dots.total);
  for (let i = 0; i < dots.total; i++) {
    const v = latLonToVec(dots.positions[i * 2], dots.positions[i * 2 + 1], 1.0025);
    dotPos[i * 3] = v.x;
    dotPos[i * 3 + 1] = v.y;
    dotPos[i * 3 + 2] = v.z;
    dotSeeds[i] = dotSeed(i); // deterministic, so the dots never shimmer between sessions
  }
  const dotGeo = new THREE.BufferGeometry();
  dotGeo.setAttribute('position', new THREE.BufferAttribute(dotPos, 3));
  dotGeo.setAttribute('aSeed', new THREE.BufferAttribute(dotSeeds, 1));
  const dotMat = new THREE.ShaderMaterial({
    uniforms: {
      uSize: { value: 1.5 },
      uSun: { value: sun },
      uInk: { value: raw(pal.ink) },
      uOpacity: { value: pal.dotOpacity },
      uFloor: { value: pal.dotFloor },
      uCore: { value: pal.dotCore },
    },
    vertexShader: `
      uniform float uSize; uniform vec3 uSun; uniform float uFloor;
      attribute float aSeed;
      varying float vAlpha; varying float vTone;
      void main(){
        vec3 n = normalize(normalMatrix * position);
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        float f = dot(n, normalize(-mv.xyz));
        float lit = smoothstep(-0.35, 0.75, dot(n, uSun));
        vAlpha = smoothstep(${DOT_LIMB.fadeStart.toFixed(2)}, ${DOT_LIMB.fadeEnd.toFixed(2)}, f) * (0.86 + 0.14 * aSeed); // dots dissolve at the limb
        vTone = uFloor + (1.0 - uFloor) * lit;
        gl_PointSize = uSize * (0.85 + 0.3 * aSeed) * (${DOT_LIMB.sizeFloor.toFixed(2)} + ${(1 - DOT_LIMB.sizeFloor).toFixed(2)} * f);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      uniform vec3 uInk; uniform float uOpacity; uniform float uCore;
      varying float vAlpha; varying float vTone;
      void main(){
        float d = length(gl_PointCoord - 0.5) * 2.0;
        float a = 1.0 - smoothstep(uCore, 1.0, d);
        gl_FragColor = vec4(uInk, a * vAlpha * vTone * uOpacity);
      }`,
    transparent: true,
    depthWrite: false,
  });
  const land = new THREE.Points(dotGeo, dotMat);
  land.frustumCulled = false;

  const halo = createHalo({
    color: raw(pal.halo),
    strength: pal.haloStrength,
    sun,
    additive: !light,
    reach: 0.34,
    nightFloor: 0.45,
  });

  return {
    globe: [sphere, land],
    scene: [halo],
    // markers take the geography's ink: navy on the pale dark-theme sphere, ivory on the navy light-theme sphere
    markers: light
      ? { core: '#f4efe3', focusCore: '#ffffff', ring: '#c6d3e4', focusRing: '#ffffff', coreScale: 0.005, focusCoreScale: 0.0085, ringBase: 0.012, focusRingBase: 0.022, ringSpan: 0.03, focusRingSpan: 0.062, ringOpacity: 0.42, focusRingOpacity: 0.7 }
      : { core: '#16243d', focusCore: '#0a1630', ring: '#33445f', focusRing: '#0a1630', coreScale: 0.005, focusCoreScale: 0.0085, ringBase: 0.012, focusRingBase: 0.022, ringSpan: 0.03, focusRingSpan: 0.062, ringOpacity: 0.38, focusRingOpacity: 0.66 },
    arcs: { hubs: ARC_HUBS, color: raw(pal.ink), base: 1.1, signal: 0.42, nodes: { color: pal.ink, size: 0.0052, opacity: light ? 0.6 : 0.55 } },
    motion: { baseSpeed: 0.05, maxImpulse: 0.16, impulsePerPx: 0.0006, impulseDecayS: 1.1, pointerYaw: 0.09, pointerPitch: 0.05, pointerCam: 0.06 },
    update() {
      // nothing breathes or twinkles: the globe only turns
    },
    resize(width, height) {
      const radius = SPHERE_RADIUS * Math.min(width, height); // CSS px
      dotMat.uniforms.uSize.value = dotSizeForRadius(radius) * renderer.getPixelRatio();
      dotGeo.setDrawRange(0, dotCountForRadius(dots, radius));
    },
    ready: () => maskLoaded || maskFailed,
    dispose() {
      mask.dispose();
      dotGeo.dispose();
    },
  };
}
