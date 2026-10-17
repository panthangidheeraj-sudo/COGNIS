import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { ArrowLeft, ArrowRight } from 'lucide-react';
import { useMediaQuery, useReducedMotion } from '@/hooks/useMediaQuery';
import { TOUR_SLIDES } from './slides';
import { createWheelGate } from './wheelGate';

/** Horizontal travel (px) of a touch swipe that changes the card. A mouse never drags the cards. */
const SWIPE_PX = 48;

/**
 * The product tour: five cards, one at a time, inside the space the intro gives it (a single viewport, no page scroll).
 *
 * Controls: one deliberate wheel / trackpad gesture moves exactly one card (see `wheelGate.ts`); the previous / next arrows, the step indicators and the
 * arrow keys move too; a finger swipe moves on touch screens. The cursor's position or movement never moves anything. Nothing advances by itself and there is no
 * continuous animation: a card change is one short opacity + transform transition (switched off under reduced motion).
 */
export function IntroTour({ onActive }: { onActive: (i: number) => void }) {
  const reduced = useReducedMotion();
  const wide = useMediaQuery('(min-width: 861px)');
  const box = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);
  const at = useRef(0);
  const last = TOUR_SLIDES.length - 1;

  const go = useCallback(
    (to: number) => {
      const next = Math.max(0, Math.min(last, to));
      if (next === at.current) return;
      at.current = next;
      setActive(next);
      onActive(next);
    },
    [last, onActive],
  );

  // wheel / trackpad: on a desktop the whole intro is the target (nothing else in it scrolls); on a phone the page scrolls, so only the tour itself listens
  useEffect(() => {
    const el = wide ? (box.current?.closest<HTMLElement>('.launch-intro') ?? box.current) : box.current;
    if (!el) return;
    const gate = createWheelGate();
    const onWheel = (e: WheelEvent) => {
      if (e.ctrlKey) return; // pinch-zoom on a trackpad
      e.preventDefault();
      const step = gate.push({ deltaX: e.deltaX, deltaY: e.deltaY, deltaMode: e.deltaMode, t: e.timeStamp || performance.now() });
      if (step) go(at.current + step);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [wide, go]);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const k = e.key;
    if (k === 'ArrowRight' || k === 'ArrowDown' || k === 'PageDown') go(at.current + 1);
    else if (k === 'ArrowLeft' || k === 'ArrowUp' || k === 'PageUp') go(at.current - 1);
    else if (k === 'Home') go(0);
    else if (k === 'End') go(last);
    else return;
    e.preventDefault();
  };

  // touch swipe only: pointerType "mouse" is ignored on purpose
  const down = useRef<number | null>(null);
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    down.current = e.pointerType === 'touch' ? e.clientX : null;
  };
  const onPointerUp = (e: PointerEvent<HTMLDivElement>) => {
    const from = down.current;
    down.current = null;
    if (from == null || e.pointerType !== 'touch') return;
    const dx = e.clientX - from;
    if (Math.abs(dx) >= SWIPE_PX) go(at.current + (dx < 0 ? 1 : -1));
  };

  const slide = TOUR_SLIDES[active];
  return (
    <div
      ref={box}
      className="li-tourbox"
      data-testid="tour-carousel"
      data-reduced={reduced || undefined}
      role="group"
      aria-roledescription="carousel"
      aria-label="Product tour"
      tabIndex={0}
      onKeyDown={onKeyDown}
      onPointerDown={onPointerDown}
      onPointerUp={onPointerUp}
      onPointerCancel={() => (down.current = null)}
    >
      <div className="li-cards">
        {TOUR_SLIDES.map((s, i) => (
          <figure
            key={s.id}
            className="li-card"
            data-state={i === active ? 'active' : i < active ? 'before' : 'after'}
            role="group"
            aria-roledescription="slide"
            aria-label={`${i + 1} of ${TOUR_SLIDES.length}: ${s.title}`}
            aria-hidden={i === active ? undefined : true}
            data-testid={`tour-card-${s.id}`}
          >
            <img src={`${import.meta.env.BASE_URL}intro/${s.file}`} alt={i === active ? s.alt : ''} width={1200} height={800} decoding="async" draggable={false} />
          </figure>
        ))}
      </div>

      <div className="li-band">
        <div className="li-caption" aria-live="polite" data-testid="tour-caption">
          <span className="li-caption-n">
            {String(active + 1).padStart(2, '0')} / {String(TOUR_SLIDES.length).padStart(2, '0')}
          </span>
          <strong>{slide.title}</strong>
          <span className="li-caption-s">{slide.subtitle}</span>
        </div>
        <ol className="li-dots" aria-label="Tour steps">
          {TOUR_SLIDES.map((s, i) => (
            <li key={s.id}>
              <button type="button" className={`li-dot${i === active ? ' is-active' : ''}`} aria-label={`Step ${i + 1}: ${s.title}`} aria-current={i === active ? 'step' : undefined} onClick={() => go(i)} />
            </li>
          ))}
        </ol>
        <div className="li-arrows">
          <button type="button" className="li-arrow" aria-label="Previous step" disabled={active === 0} onClick={() => go(at.current - 1)}>
            <ArrowLeft aria-hidden />
          </button>
          <button type="button" className="li-arrow" aria-label="Next step" disabled={active === last} onClick={() => go(at.current + 1)}>
            <ArrowRight aria-hidden />
          </button>
        </div>
      </div>
    </div>
  );
}
