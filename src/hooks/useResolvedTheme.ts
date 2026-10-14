import { useSyncExternalStore } from 'react';
import { usePreferences } from '@/stores/preferences';

const QUERY = '(prefers-color-scheme: light)';

function subscribe(onChange: () => void): () => void {
  const mql = typeof window.matchMedia === 'function' ? window.matchMedia(QUERY) : null;
  mql?.addEventListener?.('change', onChange);
  return () => mql?.removeEventListener?.('change', onChange);
}

const systemTheme = (): 'dark' | 'light' => (typeof window.matchMedia === 'function' && window.matchMedia(QUERY).matches ? 'light' : 'dark');

/**
 * The theme that is actually showing: the viewer's choice, or the operating system's when the choice is "system".
 * It follows the OS live, the same way the `data-theme` attribute on <html> does (see PreferenceSync in app/providers.tsx).
 */
export function useResolvedTheme(): 'dark' | 'light' {
  const pref = usePreferences((s) => s.theme);
  const system = useSyncExternalStore<'dark' | 'light'>(subscribe, systemTheme, () => 'dark');
  return pref === 'system' ? system : pref;
}
