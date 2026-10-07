import { Moon, Sun } from 'lucide-react';
import { usePreferences } from '@/stores/preferences';

export function ThemeToggle() {
  const theme = usePreferences((s) => s.theme);
  const set = usePreferences((s) => s.set);
  const effective = theme === 'system' ? (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark') : theme;
  return (
    <button className="btn btn--ghost btn--icon" onClick={() => set({ theme: effective === 'dark' ? 'light' : 'dark' })} aria-label={`Switch to ${effective === 'dark' ? 'light' : 'dark'} mode`} title="Toggle theme">
      {effective === 'dark' ? <Sun aria-hidden /> : <Moon aria-hidden />}
    </button>
  );
}
