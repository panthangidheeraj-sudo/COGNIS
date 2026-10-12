/**
 * The natural Earth. Used only where the product tells its story (About), as a special visual moment.
 *
 * Look: NASA Blue Marble imagery (public domain) with a natural ocean grade, a soft day/night terminator,
 * a sun glint on water, a restrained procedural cloud layer and a thin atmosphere. The textures are only
 * requested when this look is mounted, so the workspace globe (intel) never downloads them.
 */
import * as THREE from 'three';
import type { GlobeSurface, SurfaceContext } from '../surface';
import { createHalo } from './halo';
import dayUrl from '../assets/earth-day-2k.jpg';
import dayLowUrl from '../assets/earth-day-1k.jpg';
import cloudsUrl from '../assets/earth-clouds-1k.jpg';

const ARC_HUBS: [number, number][] = [
  [51.5, -0.12], // London
  [40.7, -74.0], // New York
  [1.35, 103.8], // Singapore
  [50.1, 8.68], // Frankfurt
  [59.33, 18.07], // Stockholm
  [55.68, 12.57], // Copenhagen
  [35.68, 139.7], // Tokyo
];

export function createEarthSurface({ renderer, lowPower, light, invalidate }: SurfaceContext): GlobeSurface {
  // Sun fixed in view space (upper left, in front): the lit face turns towards the reader and the
  // terminator sits on the right limb, which keeps the sphere's visual weight low.
  const sun = new THREE.Vector3(-0.74, 0.4, 0.54).normalize();

  // ---- Textures ----
  const loader = new THREE.TextureLoader();
  const maxAniso = Math.min(4, renderer.capabilities.getMaxAnisotropy());
  const day = loader.load(
    lowPower ? dayLowUrl : dayUrl,
    () => {
      earthMat.uniforms.uHasDay.value = 1;
      invalidate();
    },
    undefined,
    () => {
      // keep the static fallback; nothing else to do
    },
  );
  day.anisotropy = maxAniso;
  const clouds = loader.load(cloudsUrl, () => {
    earthMat.uniforms.uCloudAmt.value = light ? 0.34 : 0.38;
    invalidate();
  });
  clouds.wrapS = THREE.RepeatWrapping;
  clouds.anisotropy = maxAniso;

  // ---- Earth ----
  const earthMat = new THREE.ShaderMaterial({
    uniforms: {
      uDay: { value: day },
      uClouds: { value: clouds },
      uHasDay: { value: 0 },
      uCloudAmt: { value: 0 },
      uCloudShift: { value: 0 },
      uSun: { value: sun },
      uAtmo: { value: new THREE.Color(light ? '#8db6ea' : '#7fb0f2') },
      uNight: { value: light ? 0.3 : 0.13 },
      uExposure: { value: light ? 0.97 : 0.86 },
      uOcean: { value: new THREE.Color('#0d3a6e') },
    },
    vertexShader: `
      varying vec2 vUv; varying vec3 vN; varying vec3 vView;
      void main(){
        vUv = uv;
        vN = normalize(normalMatrix * normal);
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        vView = normalize(-mv.xyz);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      uniform sampler2D uDay; uniform sampler2D uClouds;
      uniform float uHasDay; uniform float uCloudAmt; uniform float uCloudShift;
      uniform vec3 uSun; uniform vec3 uAtmo; uniform float uNight; uniform float uExposure; uniform vec3 uOcean;
      varying vec2 vUv; varying vec3 vN; varying vec3 vView;
      void main(){
        vec3 n = normalize(vN);
        vec3 v = normalize(vView);
        vec3 tex = texture2D(uDay, vUv).rgb;
        vec3 day = mix(uOcean, tex, uHasDay);
        // Water is blue-dominant in the imagery. Lift the deep navy of the open ocean to a natural blue,
        // keep land in its own greens and browns (warmed a touch), leave ice white.
        float water = smoothstep(0.025, 0.11, day.b - max(day.r, day.g) * 0.96) * uHasDay + (1.0 - uHasDay);
        vec3 ocean = day * vec3(0.8, 1.02, 1.22) + vec3(0.004, 0.028, 0.072);
        vec3 land = day * vec3(1.03, 1.01, 0.95);
        vec3 base = mix(land, ocean, water);
        // a touch below full saturation: natural, not poster-bright
        base = mix(vec3(dot(base, vec3(0.299, 0.587, 0.114))), base, 0.9);

        float ndl = dot(n, uSun);
        float lit = smoothstep(-0.25, 0.55, ndl);
        vec3 col = base * (uNight + (1.0 - uNight) * lit);

        float cl = texture2D(uClouds, vec2(vUv.x + uCloudShift, vUv.y)).r * uCloudAmt;
        // sun glint on open water (not under clouds)
        vec3 h = normalize(uSun + v);
        float spec = pow(max(dot(n, h), 0.0), 55.0) * water * (1.0 - cl);
        col += vec3(0.6, 0.72, 0.88) * spec * 0.38;
        // clouds: white in sunlight, cool grey in shade
        col = mix(col, mix(vec3(0.3, 0.36, 0.46), vec3(0.96, 0.97, 0.99), lit), cl);
        // thin atmosphere scattering at the limb, stronger on the day side
        float fres = pow(1.0 - max(dot(n, v), 0.0), 2.8);
        col += uAtmo * fres * (0.06 + 0.94 * lit) * 0.6;
        gl_FragColor = vec4(min(col * uExposure, vec3(1.0)), 1.0);
      }`,
  });
  const segs = lowPower ? 40 : 64;
  const earth = new THREE.Mesh(new THREE.SphereGeometry(1, segs, segs), earthMat);

  // ---- Atmosphere halo (outside the limb) ----
  const atmo = createHalo({
    color: new THREE.Color(light ? '#6f98d8' : '#86b8ff'),
    strength: light ? 0.3 : 0.34,
    sun,
    additive: !light,
  });

  return {
    globe: [earth],
    scene: [atmo],
    markers: {
      core: '#f7f3ea',
      focusCore: '#ffffff',
      ring: '#bcd6ff',
      focusRing: '#ffffff',
      coreScale: 0.009,
      focusCoreScale: 0.014,
      ringBase: 0.018,
      focusRingBase: 0.03,
      ringSpan: 0.05,
      focusRingSpan: 0.09,
      ringOpacity: 0.5,
      focusRingOpacity: 0.85,
    },
    arcs: { hubs: ARC_HUBS, color: new THREE.Color('#d6e6ff'), base: 1.4, signal: 0.55 },
    motion: { baseSpeed: 0.06, maxImpulse: 0.24, impulsePerPx: 0.0009, impulseDecayS: 0.85, pointerYaw: 0.12, pointerPitch: 0.07, pointerCam: 0.08 },
    update(time) {
      earthMat.uniforms.uCloudShift.value = (time * 0.0016) % 1;
    },
    ready: () => earthMat.uniforms.uHasDay.value === 1,
    dispose() {
      day.dispose();
      clouds.dispose();
    },
  };
}
