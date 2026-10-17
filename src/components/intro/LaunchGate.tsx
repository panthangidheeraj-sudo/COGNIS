import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { ArrowRight } from 'lucide-react';
import { CognisLogo } from '@/components/common/CognisLogo';
import { useReducedMotion } from '@/hooks/useMediaQuery';
import { TOUR_SLIDES } from './slides';
import { IntroBackdrop } from './IntroBackdrop';
import { IntroTour } from './IntroTour';
import './intro.css';

/** Time the intro takes to fade out once dismissed. */
export const LEAVE_MS = 450;

/**
 * Launch gate: shows the introduction on every fresh launch and the application after it is dismissed.
 *
 * The decision lives in React state, so it survives SPA navigation (the gate sits above the router) and is gone on the next reload or
 * app start. Nothing is written to storage. The application itself is not mounted until the intro is dismissed, so the dashboard never
 * flashes behind the intro and its own entrance animations play when the user enters.
 */
export function LaunchGate({ children }: { children: ReactNode }) {
  const reduced = useReducedMotion();
  const [phase, setPhase] = useState<'intro' | 'leaving' | 'done'>('intro');
  const dismiss = useCallback(() => setPhase((p) => (p === 'intro' ? 'leaving' : p)), []);
  useEffect(() => {
    if (phase !== 'leaving') return;
    const t = window.setTimeout(() => setPhase('done'), reduced ? 0 : LEAVE_MS);
    return () => window.clearTimeout(t);
  }, [phase, reduced]);
  return (
    <>
      {phase !== 'intro' && children}
      {phase !== 'done' && createPortal(<LaunchIntro leaving={phase === 'leaving'} onEnter={dismiss} />, document.body)}
    </>
  );
}

const FOCUSABLE = 'button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])';

export function LaunchIntro({ leaving, onEnter }: { leaving: boolean; onEnter: () => void }) {
  const reduced = useReducedMotion();
  const uid = useId();
  const root = useRef<HTMLDivElement>(null);
  const enterBtn = useRef<HTMLButtonElement>(null);
  const [active, setActive] = useState(0);

  // lock background scrolling and tell the cursor/theme layers an intro is up; restore on unmount
  useEffect(() => {
    const html = document.documentElement;
    html.classList.add('cg-intro-lock');
    return () => html.classList.remove('cg-intro-lock');
  }, []);
  useEffect(() => {
    enterBtn.current?.focus({ preventScroll: true });
  }, []);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape' && !e.defaultPrevented) {
      e.preventDefault();
      onEnter();
      return;
    }
    if (e.key !== 'Tab' || !root.current) return;
    const els = Array.from(root.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (!els.length) return;
    const first = els[0];
    const last = els[els.length - 1];
    const at = document.activeElement;
    if (e.shiftKey && (at === first || !root.current.contains(at))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (at === last || !root.current.contains(at))) {
      e.preventDefault();
      first.focus();
    }
  };

  return (
    <div
      ref={root}
      className={`launch-intro${leaving ? ' is-leaving' : ''}`}
      data-reduced={reduced || undefined}
      role="dialog"
      aria-modal="true"
      aria-labelledby={`${uid}-t`}
      aria-describedby={`${uid}-d`}
      onKeyDown={onKeyDown}
      data-testid="launch-intro"
    >
      <IntroBackdrop />
      <div className="li-inner">
        <section className="li-hero" aria-label="COGNIS">
          <div className="li-brand">
            <div className="li-logo" aria-hidden>
              <CognisLogo variant="navy" height={112} compact decorative />
              <span className="li-sheen" />
            </div>
            <h1 id={`${uid}-t`} className="li-title">
              COGNIS
            </h1>
          </div>
          <p className="li-headline" aria-hidden>
            Company intelligence, <em>built from evidence.</em>
          </p>
          <p id={`${uid}-d`} className="li-desc">
            Search any Norwegian company, trace every fact to its source, and ask questions you can verify.
          </p>
          <ol className="li-steps" aria-label="The five-step tour">
            {TOUR_SLIDES.map((s, i) => (
              <li key={s.id} className={i === active ? 'is-on' : undefined} aria-current={i === active ? 'step' : undefined}>
                <span>{String(i + 1).padStart(2, '0')}</span>
                {s.title}
              </li>
            ))}
          </ol>
        </section>

        <div className="li-actions">
          <button ref={enterBtn} type="button" className="li-enter" onClick={onEnter}>
            Enter COGNIS <ArrowRight aria-hidden />
          </button>
          <button type="button" className="li-skip" onClick={onEnter}>
            Skip intro
          </button>
        </div>

        <section className="li-tour" aria-label="Product tour">
          <IntroTour onActive={setActive} />
        </section>
      </div>
    </div>
  );
}
