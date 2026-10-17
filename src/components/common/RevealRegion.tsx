import { useRef, type CSSProperties, type ReactNode } from 'react';
import { useAutoReveal } from '@/hooks/useRevealOnScroll';
import { useReducedMotion } from '@/hooks/useMediaQuery';

/**
 * Wraps a routed page. Every box on it fades in with a small upward motion, in order (see `useAutoReveal`).
 * Mount it with `key={pathname}` so a navigation starts a new sequence; re-renders of the same page never replay it.
 */
export function RevealRegion({ children, className, style }: { children: ReactNode; className?: string; style?: CSSProperties }) {
  const ref = useRef<HTMLDivElement>(null);
  useAutoReveal(ref, !useReducedMotion());
  return (
    <div ref={ref} className={className} style={style}>
      {children}
    </div>
  );
}
