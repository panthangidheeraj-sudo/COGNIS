import { lazy, Suspense, useEffect, useState } from 'react';
import { Pause, Play } from 'lucide-react';
import { useGlobe } from '@/stores/ui';
import { usePreferences } from '@/stores/preferences';
import { useReducedMotion } from '@/hooks/useMediaQuery';
import { ErrorBoundary } from '@/components/common/ErrorState';
import { GlobeFallback } from './GlobeFallback';
import './globe.css';

const GlobeCanvas = lazy(() => import('./GlobeCanvas'));

function hasWebGL() {
  try {
    const c = document.createElement('canvas');
    return !!(c.getContext('webgl2') || c.getContext('webgl'));
  } catch {
    return false;
  }
}
function isLowPower() {
  const nav = navigator as Navigator & { deviceMemory?: number; connection?: { saveData?: boolean } };
  return (nav.hardwareConcurrency ?? 8) <= 4 || (nav.deviceMemory ?? 8) <= 4 || !!nav.connection?.saveData;
}

/**
 * Hero globe controller. Defers the WebGL chunk until after first paint,
 * falls back to a static globe when WebGL is missing or fails.
 */
export function GlobeStage({ className }: { className?: string }) {
  const { focus, points } = useGlobe();
  const reduced = useReducedMotion();
  const spinPref = usePreferences((s) => s.globeSpin);
  const setPrefs = usePreferences((s) => s.set);
  const spin = spinPref === 'on' || (spinPref === 'auto' && !reduced);
  const pref = usePreferences((s) => s.theme);
  const theme: 'dark' | 'light' = pref === 'system' ? (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark') : pref;
  const [ready, setReady] = useState(false);
  // The static globe stays underneath until the WebGL Earth has its imagery on screen, then fades out.
  const [glReady, setGlReady] = useState(false);
  const [webgl] = useState(hasWebGL);
  const [lowPower] = useState(isLowPower);
  useEffect(() => {
    const idle = (window as Window & { requestIdleCallback?: (cb: () => void) => number }).requestIdleCallback;
    const id = idle ? idle(() => setReady(true)) : window.setTimeout(() => setReady(true), 200);
    return () => window.clearTimeout(id);
  }, []);
  const fallback = <GlobeFallback theme={theme} lat={focus?.lat ?? 25} lon={focus?.lon ?? 14} />;
  // keep the static globe until the WebGL Earth has faded in (globe.css: 700 ms)
  const onGlReady = () => window.setTimeout(() => setGlReady(true), 760);
  return (
    <div className={`globe-stage ${className ?? ''}`}>
      <div className="globe-glow" aria-hidden />
      {!glReady && fallback}
      {webgl && ready && (
        // On failure the static globe simply stays (it is already shown until the Earth is ready).
        <ErrorBoundary label="Globe" fallback={glReady ? fallback : <></>}>
          <Suspense fallback={<></>}>
            <GlobeCanvas focus={focus} points={points} reducedMotion={reduced} spin={spin} lowPower={lowPower} theme={theme} onReady={onGlReady} />
          </Suspense>
        </ErrorBoundary>
      )}
      {webgl && (
        <button
          type="button"
          className="globe-toggle"
          onClick={() => setPrefs({ globeSpin: spin ? 'off' : 'on' })}
          aria-pressed={spin}
          aria-label={spin ? 'Pause globe rotation' : 'Rotate globe'}
          title={spin ? 'Pause globe rotation' : reduced ? 'Rotate globe (your system asks for reduced motion)' : 'Rotate globe'}
        >
          {spin ? <Pause aria-hidden /> : <Play aria-hidden />}
        </button>
      )}
      {focus?.label && (
        <div className="globe-label pill pill--glass" key={focus.id} aria-hidden>
          <span className="pill-dot" style={{ color: 'var(--accent-ice)' }} />
          {focus.label}
        </div>
      )}
    </div>
  );
}
