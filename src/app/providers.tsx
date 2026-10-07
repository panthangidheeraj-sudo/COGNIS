import { useEffect, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApiError } from '@/api/http';
import { usePreferences } from '@/stores/preferences';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000, // cache repeated company responses
      gcTime: 10 * 60_000,
      refetchOnWindowFocus: false,
      retry: (count, err) => !(err instanceof ApiError && ['not_found', 'invalid', 'ambiguous', 'blocked'].includes(err.code)) && count < 2,
    },
  },
});

/** Mirrors preferences onto <html> data attributes consumed by the token CSS. */
function PreferenceSync() {
  const { theme, motion, density } = usePreferences();
  useEffect(() => {
    const root = document.documentElement;
    const mql = window.matchMedia('(prefers-color-scheme: light)');
    const apply = () => {
      const t = theme === 'system' ? (mql.matches ? 'light' : 'dark') : theme;
      root.setAttribute('data-theme', t);
      document.querySelector('meta[name="theme-color"]')?.setAttribute('content', t === 'dark' ? '#06111C' : '#F7F3EA');
    };
    apply();
    mql.addEventListener('change', apply);
    return () => mql.removeEventListener('change', apply);
  }, [theme]);
  useEffect(() => {
    const root = document.documentElement;
    if (motion === 'system') root.removeAttribute('data-motion');
    else root.setAttribute('data-motion', motion);
  }, [motion]);
  useEffect(() => {
    const root = document.documentElement;
    if (density !== 'compact') root.removeAttribute('data-density');
    else root.setAttribute('data-density', density);
  }, [density]);
  return null;
}

export function Providers({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <PreferenceSync />
      {children}
    </QueryClientProvider>
  );
}
