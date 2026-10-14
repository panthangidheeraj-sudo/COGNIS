/**
 * WebGL globe scene, shared by both looks (see ./surface.ts): the monochrome `intel` globe and the natural `earth`.
 * Lazy-loaded through IntelGlobe / EarthGlobe, so three.js and any imagery are only fetched where a globe is shown.
 *
 * Motion (see ./globeMotion.ts, which is pure and tested): a slow, continuous eastward rotation in real time —
 * slow frames do not turn it into slow motion. The pointer adds a small orientation/parallax offset; the wheel
 * and page scroll add a decaying spin impulse (down = faster forward, up = eases into reverse). Every response is
 * smoothed and capped, then settles back to the normal rotation. Reduced motion or the pause button holds the
 * globe still and the scene stops rendering; pressing play under reduced motion brings back only the slow
 * rotation (no parallax, scroll or pulses). Each look sets its own speeds and caps (`surface.motion`).
 *
 * Data: `focus`, `anchor` and `points` come from backend data. A focus (an explicit point) turns the globe to it
 * and holds it; an anchor (where results are) never stops the rotation — a paused globe turns to a new anchor
 * once. The decorative arcs are faint and carry no data meaning.
 */
import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import type { GlobePoint } from '@/stores/ui';
import type { SurfaceFactory } from './surface';
import { clamp } from './globeMath';
import { frameSeconds, initialMotion, needsRender, stepMotion } from './globeMotion';
import { latLonToVec } from './globeVec';

export interface GlobeCanvasProps {
  /** An explicit point (hovered result, search match): the globe turns to it and holds it while it is set. */
  focus: GlobePoint | null;
  /** Where the results are (passive): never stops the rotation; a paused globe turns to a new anchor once. */
  anchor?: GlobePoint | null;
  points: GlobePoint[];
  reducedMotion: boolean;
  /** Idle rotation. Separate from reducedMotion so the viewer can start or stop it explicitly. */
  spin: boolean;
  lowPower: boolean;
  theme: 'dark' | 'light';
  /** Called once the globe is fully on screen (the stage then fades the static fallback out). */
  onReady?: () => void;
}

const HOME = { lat: 58, lon: 14 }; // Northern Europe in view first
const POINTER_IDLE_MS = 2500;
const ORIGIN: [number, number] = [59.91, 10.75];

export function GlobeCanvas({ focus, anchor = null, points, reducedMotion, spin, lowPower, theme, onReady, surface: createSurface }: GlobeCanvasProps & { surface: SurfaceFactory }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef({ focus, anchor, points, reducedMotion, spin, theme, onReady });
  stateRef.current = { focus, anchor, points, reducedMotion, spin, theme, onReady };
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
    let mo = initialMotion(HOME); // orientation, spin speed, offsets and the animation clock (globeMotion.ts)
    globe.rotation.set(mo.pitch, mo.yaw, 0);

    let dirty = true;
    let readySent = false;

    // ---- The look: sphere, atmosphere, marker/arc style and motion tuning ----
    const surface = createSurface({ renderer, lowPower, light, invalidate: () => (dirty = true) });
    surface.globe.forEach((o) => globe.add(o));
    surface.scene.forEach((o) => scene.add(o));
    surface.resize?.(width, height);
    const { markers: mk, arcs: arcStyle, motion } = surface;

    // ---- Decorative arcs (no data meaning) with a travelling signal ----
    const arcMat = new THREE.ShaderMaterial({
      uniforms: { uTime: { value: 0 }, uColor: { value: arcStyle.color }, uMotion: { value: 1 }, uBase: { value: arcStyle.base }, uSignal: { value: arcStyle.signal } },
      vertexShader: `attribute float aT; varying float vT; void main(){ vT = aT; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
      fragmentShader: `
        uniform float uTime; uniform vec3 uColor; uniform float uMotion; uniform float uBase; uniform float uSignal; varying float vT;
        void main(){
          float head = fract(uTime * 0.1);
          float sig = uMotion * smoothstep(0.1, 0.0, abs(vT - head));
          float base = 0.1 * sin(vT * 3.14159);
          gl_FragColor = vec4(uColor, base * uBase + sig * uSignal);
        }`,
      transparent: true,
      depthWrite: false,
    });
    const arcs: THREE.Line[] = [];
    if (!lowPower) {
      const o = latLonToVec(ORIGIN[0], ORIGIN[1], 1.005);
      arcStyle.hubs.forEach(([la, lo], k) => {
        const d = latLonToVec(la, lo, 1.005);
        const mid = o.clone().add(d).multiplyScalar(0.5);
        mid.normalize().multiplyScalar(1 + o.distanceTo(d) * 0.3);
        const pts = new THREE.QuadraticBezierCurve3(o, mid, d).getPoints(64);
        const g = new THREE.BufferGeometry().setFromPoints(pts);
        g.setAttribute('aT', new THREE.BufferAttribute(new Float32Array(pts.length).map((_, i) => (i / (pts.length - 1) + k * 0.13) % 1.0), 1));
        const line = new THREE.Line(g, arcMat);
        arcs.push(line);
        globe.add(line);
        if (arcStyle.nodes) {
          const node = new THREE.Mesh(
            new THREE.SphereGeometry(1, 10, 10),
            new THREE.MeshBasicMaterial({ color: arcStyle.nodes.color, transparent: true, opacity: arcStyle.nodes.opacity, depthWrite: false }),
          );
          node.scale.setScalar(arcStyle.nodes.size);
          node.position.copy(d);
          globe.add(node);
        }
      });
      if (arcStyle.nodes) {
        const origin = new THREE.Mesh(
          new THREE.SphereGeometry(1, 10, 10),
          new THREE.MeshBasicMaterial({ color: arcStyle.nodes.color, transparent: true, opacity: Math.min(1, arcStyle.nodes.opacity + 0.2), depthWrite: false }),
        );
        origin.scale.setScalar(arcStyle.nodes.size * 1.35);
        origin.position.copy(o);
        globe.add(origin);
      }
    }

    // ---- Data points (from backend geo) + pulsing rings ----
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
        const core = new THREE.Mesh(coreGeo, new THREE.MeshBasicMaterial({ color: isFocus ? mk.focusCore : mk.core }));
        core.scale.setScalar(isFocus ? mk.focusCoreScale : mk.coreScale);
        core.position.copy(v);
        markerGroup.add(core);
        const ring = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ color: isFocus ? mk.focusRing : mk.ring, transparent: true, opacity: 0.6, side: THREE.DoubleSide, depthWrite: false }));
        ring.position.copy(v);
        ring.lookAt(v.clone().multiplyScalar(2));
        ring.scale.setScalar(isFocus ? mk.focusRingBase * 1.6 : mk.ringBase * 1.6);
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
    let lastWheel = -Infinity;
    const addImpulse = (px: number) => {
      // a spin impulse from wheel/scroll (rad/s); the motion step decays it, and drops it entirely without full motion
      mo.impulse = clamp(mo.impulse + clamp(px, -240, 240) * motion.impulsePerPx, -motion.maxImpulse, motion.maxImpulse);
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
      surface.resize?.(width, height);
      dirty = true;
    });
    ro.observe(mount);

    // ---- Loop: capped frame rate, renders only when something changes ----
    const frameMs = lowPower ? 1000 / 30 : 1000 / 60;
    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      if (!visible || document.hidden) {
        last = now;
        return;
      }
      if (now - last < frameMs - 1.5) return;
      const dt = frameSeconds(now - last);
      last = now;
      const { focus: f, anchor: a, reducedMotion: rm, spin: sp } = stateRef.current;
      // `sp` is the resolved spin choice (auto = on unless reduced motion; play/pause is explicit), so an explicit
      // play still rotates under reduced motion. Everything else (pointer, scroll, pulses) needs full motion.
      const lively = sp && !rm;
      const ease = (rate: number) => 1 - Math.exp(-dt * rate);

      if (markerVersion !== pointsVersion.current) {
        markerVersion = pointsVersion.current;
        rebuildMarkers();
      }
      const pointerLive = lively && now - pointer.at < POINTER_IDLE_MS;
      const step = stepMotion(mo, { spin: sp, reducedMotion: rm, focus: f, anchor: a, pointer: { x: pointer.x, y: pointer.y, live: pointerLive } }, dt, motion);
      mo = step.state;
      globe.rotation.set(mo.pitch + mo.offY + mo.tilt, mo.yaw + mo.offX, 0);

      // camera parallax + scroll depth (tiny remainders are settled so a still globe really stops rendering)
      const cam = { x: camera.position.x, y: camera.position.y, z: camera.position.z };
      const scroll = Math.min(1, window.scrollY / 600);
      camera.position.x += ((pointerLive ? pointer.x * motion.pointerCam : 0) - camera.position.x) * ease(3);
      camera.position.y += ((pointerLive ? -pointer.y * motion.pointerCam * 0.56 : 0) - camera.position.y) * ease(3);
      if (!pointerLive && Math.abs(camera.position.x) < 1e-5) camera.position.x = 0;
      if (!pointerLive && Math.abs(camera.position.y) < 1e-5) camera.position.y = 0;
      camera.position.z = 5.1 + (rm ? 0 : scroll * 0.5);
      camera.lookAt(0, 0, 0);
      const camMoved = Math.abs(camera.position.x - cam.x) + Math.abs(camera.position.y - cam.y) + Math.abs(camera.position.z - cam.z) > 1e-6;

      surface.update(mo.time, lively);
      arcMat.uniforms.uTime.value = mo.time;
      arcMat.uniforms.uMotion.value = lively ? 1 : 0;
      for (const r of rings) {
        const p = lively ? (mo.time * 0.6 + r.phase) % 1 : 0.5;
        r.mesh.scale.setScalar((r.focus ? mk.focusRingBase : mk.ringBase) + p * (r.focus ? mk.focusRingSpan : mk.ringSpan));
        (r.mesh.material as THREE.MeshBasicMaterial).opacity = (1 - p) * (r.focus ? mk.focusRingOpacity : mk.ringOpacity);
      }

      if (!needsRender({ lively, moved: step.moved || camMoved, dirty })) return; // still scene: no GPU work at all
      dirty = false;
      renderer.render(scene, camera);
      if (!readySent && surface.ready()) {
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
      surface.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
    // theme/lowPower changes rebuild the scene; focus/anchor/points/motion are read live.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lowPower, theme, createSurface]);

  return <div ref={mountRef} className="globe-canvas" />;
}
