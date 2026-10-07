/**
 * WebGL Earth. Lazy-loaded (three.js and the textures are only fetched where the globe is shown).
 *
 * Look: NASA Blue Marble imagery (public domain) with a natural ocean grade, a soft day/night terminator,
 * a sun glint on water, a restrained procedural cloud layer and a thin atmosphere. It is an atmospheric
 * anchor, so exposure is kept below the UI's text and actions.
 *
 * Motion: a slow, continuous eastward rotation that never waits for input. The pointer adds a small
 * orientation/parallax offset; the wheel and page scroll add a decaying spin impulse (down = faster
 * forward, up = eases into reverse). Every response is smoothed and capped, then settles back to the
 * normal rotation. Reduced motion or the pause button holds the Earth still and the scene stops rendering;
 * pressing play under reduced motion brings back only the slow rotation (no parallax, scroll or cloud drift).
 *
 * Data: `focus` and `points` come from backend data; the globe turns towards the focus and keeps a slight
 * sway so it never looks frozen. The decorative arcs are faint and carry no data meaning.
 */
import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import type { GlobePoint } from '@/stores/ui';
import dayUrl from './assets/earth-day-2k.jpg';
import dayLowUrl from './assets/earth-day-1k.jpg';
import cloudsUrl from './assets/earth-clouds-1k.jpg';

export interface GlobeCanvasProps {
  focus: GlobePoint | null;
  points: GlobePoint[];
  reducedMotion: boolean;
  /** Idle rotation. Separate from reducedMotion so the viewer can start or stop it explicitly. */
  spin: boolean;
  lowPower: boolean;
  theme: 'dark' | 'light';
  /** Called once the Earth imagery is on screen (the stage then fades the static fallback out). */
  onReady?: () => void;
}

const DEG = Math.PI / 180;
const HOME = { lat: 58, lon: 14 }; // Northern Europe in view first
const REST_PITCH = 0.36; // ~21°: a classic three-quarter view while spinning freely
const BASE_SPEED = 0.06; // rad/s ≈ 105 s per turn: slow and cinematic
const MAX_IMPULSE = 0.24; // rad/s added by scrolling, at most (≈ 14°/s on top of the base): noticeable, never violent
const IMPULSE_PER_PX = 0.0009;
const IMPULSE_DECAY_S = 0.85;
const POINTER_IDLE_MS = 2500;

function latLonToVec(lat: number, lon: number, r = 1) {
  const phi = (90 - lat) * DEG;
  const theta = (lon + 180) * DEG;
  return new THREE.Vector3(-r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta));
}
function targetRotation(lat: number, lon: number) {
  const v = latLonToVec(0, lon);
  const alpha = Math.atan2(v.x, v.z);
  return { y: -alpha, x: Math.max(-0.9, Math.min(0.9, lat * DEG * 0.82)) };
}
const wrap = (a: number) => Math.atan2(Math.sin(a), Math.cos(a));
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

const ARC_HUBS: [number, number][] = [
  [51.5, -0.12], // London
  [40.7, -74.0], // New York
  [1.35, 103.8], // Singapore
  [50.1, 8.68], // Frankfurt
  [59.33, 18.07], // Stockholm
  [55.68, 12.57], // Copenhagen
  [35.68, 139.7], // Tokyo
];
const ORIGIN: [number, number] = [59.91, 10.75];

export default function GlobeCanvas({ focus, points, reducedMotion, spin, lowPower, theme, onReady }: GlobeCanvasProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef({ focus, points, reducedMotion, spin, theme, onReady });
  stateRef.current = { focus, points, reducedMotion, spin, theme, onReady };
  const pointsVersion = useRef(0);
  const lastPointsKey = useRef('');
  const key = points.map((p) => p.id).join('|');
  if (key !== lastPointsKey.current) {
    lastPointsKey.current = key;
    pointsVersion.current += 1;
  }

  useEffect(() => {
    const mount = mountRef.current!;
    let width = mount.clientWidth || 600;
    let height = mount.clientHeight || 600;
    const light = theme === 'light';

    const renderer = new THREE.WebGLRenderer({ antialias: !lowPower, alpha: true, powerPreference: lowPower ? 'low-power' : 'default' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, lowPower ? 1 : 1.5));
    renderer.setSize(width, height);
    renderer.setClearColor(0x000000, 0);
    renderer.domElement.setAttribute('aria-hidden', 'true');
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, width / height, 0.1, 100);
    camera.position.set(0, 0, 5.1);

    const globe = new THREE.Group();
    scene.add(globe);
    const home = targetRotation(HOME.lat, HOME.lon);
    let yaw = home.y;
    let pitch = REST_PITCH;
    globe.rotation.set(pitch, yaw, 0);

    // Sun fixed in view space (upper left, in front): the lit face turns towards the reader and the
    // terminator sits on the right limb, which keeps the sphere's visual weight low.
    const sun = new THREE.Vector3(-0.74, 0.4, 0.54).normalize();

    // ---- Textures ----
    const loader = new THREE.TextureLoader();
    const maxAniso = Math.min(4, renderer.capabilities.getMaxAnisotropy());
    let dirty = true;
    let readySent = false;
    const day = loader.load(
      lowPower ? dayLowUrl : dayUrl,
      () => {
        earthMat.uniforms.uHasDay.value = 1;
        dirty = true;
      },
      undefined,
      () => {
        // keep the static fallback; nothing else to do
      },
    );
    day.anisotropy = maxAniso;
    const clouds = loader.load(cloudsUrl, () => {
      earthMat.uniforms.uCloudAmt.value = light ? 0.34 : 0.38;
      dirty = true;
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
    globe.add(earth);

    // ---- Atmosphere halo (outside the limb) ----
    const atmoMat = new THREE.ShaderMaterial({
      uniforms: { uColor: { value: new THREE.Color(light ? '#6f98d8' : '#86b8ff') }, uSun: { value: sun }, uStrength: { value: light ? 0.3 : 0.34 } },
      vertexShader: `
        varying vec3 vN; varying vec3 vView;
        void main(){ vN = normalize(normalMatrix * normal); vec4 mv = modelViewMatrix * vec4(position,1.0); vView = normalize(-mv.xyz); gl_Position = projectionMatrix * mv; }`,
      fragmentShader: `
        uniform vec3 uColor; uniform vec3 uSun; uniform float uStrength; varying vec3 vN; varying vec3 vView;
        void main(){
          // back faces: -dot is 0 at the halo's outer edge and peaks at the globe's silhouette
          float k = clamp(-dot(normalize(vN), normalize(vView)) / 0.42, 0.0, 1.0);
          float day = 0.15 + 0.85 * smoothstep(-0.3, 0.6, dot(normalize(vN), uSun)); // outward normal: sun-side rim glows
          gl_FragColor = vec4(uColor, pow(k, 3.0) * uStrength * day);
        }`,
      side: THREE.BackSide,
      // additive light reads as glow on the navy canvas; on ivory it would wash out, so blend normally there
      blending: light ? THREE.NormalBlending : THREE.AdditiveBlending,
      transparent: true,
      depthWrite: false,
    });
    const atmo = new THREE.Mesh(new THREE.SphereGeometry(1.1, 48, 48), atmoMat);
    scene.add(atmo);

    // ---- Decorative arcs (no data meaning) with a travelling signal ----
    const arcMat = new THREE.ShaderMaterial({
      uniforms: { uTime: { value: 0 }, uColor: { value: new THREE.Color('#d6e6ff') }, uMotion: { value: 1 } },
      vertexShader: `attribute float aT; varying float vT; void main(){ vT = aT; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
      fragmentShader: `
        uniform float uTime; uniform vec3 uColor; uniform float uMotion; varying float vT;
        void main(){
          float head = fract(uTime * 0.1);
          float sig = uMotion * smoothstep(0.1, 0.0, abs(vT - head));
          float base = 0.1 * sin(vT * 3.14159);
          gl_FragColor = vec4(uColor, base * 1.4 + sig * 0.55);
        }`,
      transparent: true,
      depthWrite: false,
    });
    const arcs: THREE.Line[] = [];
    if (!lowPower) {
      const o = latLonToVec(ORIGIN[0], ORIGIN[1], 1.005);
      ARC_HUBS.forEach(([la, lo], k) => {
        const d = latLonToVec(la, lo, 1.005);
        const mid = o.clone().add(d).multiplyScalar(0.5);
        mid.normalize().multiplyScalar(1 + o.distanceTo(d) * 0.3);
        const pts = new THREE.QuadraticBezierCurve3(o, mid, d).getPoints(64);
        const g = new THREE.BufferGeometry().setFromPoints(pts);
        g.setAttribute('aT', new THREE.BufferAttribute(new Float32Array(pts.length).map((_, i) => (i / (pts.length - 1) + k * 0.13) % 1.0), 1));
        const line = new THREE.Line(g, arcMat);
        arcs.push(line);
        globe.add(line);
      });
    }

    // ---- Data points (from backend geo) + pulsing rings: warm white cores read on ocean and on land ----
    const markerGroup = new THREE.Group();
    globe.add(markerGroup);
    const ringGeo = new THREE.RingGeometry(0.9, 1, 48);
    const coreGeo = new THREE.SphereGeometry(1, 12, 12);
    let markerVersion = -1;
    const rings: { mesh: THREE.Mesh; phase: number; focus: boolean }[] = [];
    const rebuildMarkers = () => {
      markerGroup.children.forEach((c) => ((c as THREE.Mesh).material as THREE.Material).dispose());
      markerGroup.clear();
      rings.length = 0;
      const { points: pts, focus: f } = stateRef.current;
      const all = f && !pts.some((p) => p.id === f.id) ? [...pts, f] : pts;
      all.slice(0, 40).forEach((p, i) => {
        const isFocus = f?.id === p.id;
        const v = latLonToVec(p.lat, p.lon, 1.006);
        const core = new THREE.Mesh(coreGeo, new THREE.MeshBasicMaterial({ color: isFocus ? '#ffffff' : '#f7f3ea' }));
        core.scale.setScalar(isFocus ? 0.014 : 0.009);
        core.position.copy(v);
        markerGroup.add(core);
        const ring = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ color: isFocus ? '#ffffff' : '#bcd6ff', transparent: true, opacity: 0.6, side: THREE.DoubleSide, depthWrite: false }));
        ring.position.copy(v);
        ring.lookAt(v.clone().multiplyScalar(2));
        ring.scale.setScalar(isFocus ? 0.05 : 0.03);
        markerGroup.add(ring);
        rings.push({ mesh: ring, phase: i * 0.37, focus: isFocus });
      });
      dirty = true;
    };

    // ---- Interaction ----
    const pointer = { x: 0, y: 0, at: -Infinity };
    const onPointer = (e: PointerEvent) => {
      pointer.x = (e.clientX / window.innerWidth - 0.5) * 2;
      pointer.y = (e.clientY / window.innerHeight - 0.5) * 2;
      pointer.at = performance.now();
    };
    let impulse = 0; // rad/s from wheel/scroll, decays to 0
    let lastWheel = -Infinity;
    const addImpulse = (px: number) => {
      impulse = clamp(impulse + clamp(px, -240, 240) * IMPULSE_PER_PX, -MAX_IMPULSE, MAX_IMPULSE);
    };
    const onWheel = (e: WheelEvent) => {
      const px = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaMode === 2 ? e.deltaY * window.innerHeight : e.deltaY;
      addImpulse(px);
      lastWheel = performance.now();
    };
    let lastScrollY = window.scrollY;
    const onScroll = () => {
      const y = window.scrollY;
      const d = y - lastScrollY;
      lastScrollY = y;
      // wheel scrolling is already counted; this catches touch, keyboard and scrollbar scrolling
      if (performance.now() - lastWheel > 160) addImpulse(d);
    };
    window.addEventListener('pointermove', onPointer, { passive: true });
    window.addEventListener('wheel', onWheel, { passive: true });
    window.addEventListener('scroll', onScroll, { passive: true });

    // ---- Visibility & size ----
    let visible = true;
    const io = new IntersectionObserver(([e]) => (visible = e.isIntersecting), { threshold: 0.01 });
    io.observe(mount);
    const ro = new ResizeObserver(() => {
      width = mount.clientWidth || width;
      height = mount.clientHeight || height;
      renderer.setSize(width, height);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      dirty = true;
    });
    ro.observe(mount);

    // ---- Loop: capped frame rate, renders only when something changes ----
    const frameMs = lowPower ? 1000 / 30 : 1000 / 60;
    let raf = 0;
    let last = performance.now();
    let time = 0;
    let vel = 0; // current spin speed (rad/s), eased towards its target so it never jerks
    let offX = 0; // pointer orientation offsets (rad)
    let offY = 0;
    let tilt = 0; // scroll orientation nudge (rad)
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      if (!visible || document.hidden) {
        last = now;
        return;
      }
      if (now - last < frameMs - 1.5) return;
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const { focus: f, reducedMotion: rm, spin: sp } = stateRef.current;
      // `sp` is the resolved spin choice (auto = on unless reduced motion; play/pause is explicit), so an explicit
      // play still rotates under reduced motion. Everything else (pointer, scroll, clouds, pulses) needs full motion.
      const rotating = sp;
      const lively = sp && !rm;
      const ease = (rate: number) => 1 - Math.exp(-dt * rate);

      if (markerVersion !== pointsVersion.current) {
        markerVersion = pointsVersion.current;
        rebuildMarkers();
      }
      const prev = { yaw, pitch, offX, offY, tilt, cx: camera.position.x, cy: camera.position.y, cz: camera.position.z };

      // spin impulse from wheel/scroll decays smoothly back to the normal rotation
      impulse = lively ? impulse * Math.exp(-dt / IMPULSE_DECAY_S) : 0;
      if (Math.abs(impulse) < 1e-4) impulse = 0;

      if (f) {
        // turn towards the backend-provided location, then sway gently around it
        const t = targetRotation(f.lat, f.lon);
        const sway = lively ? Math.sin(time * 0.22) * 0.05 : 0;
        const k = rm ? 1 : ease(2.4);
        yaw += wrap(t.y + sway - yaw) * k;
        pitch += (t.x - pitch) * k;
        vel += (0 - vel) * ease(3);
      } else {
        const target = (rotating ? BASE_SPEED : 0) + impulse;
        vel = rm && !rotating ? 0 : vel + (target - vel) * ease(3);
        yaw += vel * dt;
        pitch += (REST_PITCH - pitch) * (rm ? 1 : ease(1.2));
      }
      yaw = wrap(yaw);

      // pointer: small orientation offset, relaxes to centre once the pointer rests
      const pointerLive = lively && now - pointer.at < POINTER_IDLE_MS;
      offX += ((pointerLive ? pointer.x * 0.12 : 0) - offX) * ease(1.8);
      offY += ((pointerLive ? pointer.y * 0.07 : 0) - offY) * ease(1.8);
      tilt += ((lively ? -impulse * 0.25 : 0) - tilt) * ease(2.5);
      globe.rotation.set(pitch + offY + tilt, yaw + offX, 0);

      // camera parallax + scroll depth
      const scroll = Math.min(1, window.scrollY / 600);
      camera.position.x += ((pointerLive ? pointer.x * 0.08 : 0) - camera.position.x) * ease(3);
      camera.position.y += ((pointerLive ? -pointer.y * 0.045 : 0) - camera.position.y) * ease(3);
      camera.position.z = 5.1 + (rm ? 0 : scroll * 0.5);
      camera.lookAt(0, 0, 0);

      if (lively) time += dt;
      earthMat.uniforms.uCloudShift.value = (time * 0.0016) % 1;
      arcMat.uniforms.uTime.value = time;
      arcMat.uniforms.uMotion.value = lively ? 1 : 0;
      for (const r of rings) {
        const p = lively ? (time * 0.6 + r.phase) % 1 : 0.5;
        r.mesh.scale.setScalar((r.focus ? 0.03 : 0.018) + p * (r.focus ? 0.09 : 0.05));
        (r.mesh.material as THREE.MeshBasicMaterial).opacity = (1 - p) * (r.focus ? 0.85 : 0.5);
      }

      const changed =
        Math.abs(yaw - prev.yaw) + Math.abs(pitch - prev.pitch) + Math.abs(offX - prev.offX) + Math.abs(offY - prev.offY) + Math.abs(tilt - prev.tilt) +
          Math.abs(camera.position.x - prev.cx) + Math.abs(camera.position.y - prev.cy) + Math.abs(camera.position.z - prev.cz) >
        1e-6;
      if (!(rotating || lively || changed || dirty)) return; // still scene: no GPU work at all
      dirty = false;
      renderer.render(scene, camera);
      if (!readySent && earthMat.uniforms.uHasDay.value === 1) {
        readySent = true;
        mount.classList.add('is-ready');
        stateRef.current.onReady?.();
      }
    };
    raf = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('pointermove', onPointer);
      window.removeEventListener('wheel', onWheel);
      window.removeEventListener('scroll', onScroll);
      io.disconnect();
      ro.disconnect();
      scene.traverse((o) => {
        const m = o as THREE.Mesh;
        m.geometry?.dispose?.();
        const mat = m.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(mat)) mat.forEach((x) => x.dispose());
        else mat?.dispose?.();
      });
      day.dispose();
      clouds.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
    // theme/lowPower changes rebuild the scene; focus/points/motion are read live.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lowPower, theme]);

  return <div ref={mountRef} className="globe-canvas" />;
}
