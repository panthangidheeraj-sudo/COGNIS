import { useEffect, useState } from 'react';
import { usePreferences } from '@/stores/preferences';

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => (typeof window !== 'undefined' ? window.matchMedia(query).matches : false));
  useEffect(() => {
    const mql = window.matchMedia(query);
    const on = () => setMatches(mql.matches);
    on();
    mql.addEventListener('change', on);
    return () => mql.removeEventListener('change', on);
  }, [query]);
  return matches;
}

export const useIsMobile = () => useMediaQuery('(max-width: 640px)');
export const useIsTablet = () => useMediaQuery('(max-width: 960px)');

/** True when the user (setting) or the OS asks for reduced motion. */
export function useReducedMotion(): boolean {
  const pref = usePreferences((s) => s.motion);
  const system = useMediaQuery('(prefers-reduced-motion: reduce)');
  return pref === 'reduced' || (pref === 'system' && system);
}
