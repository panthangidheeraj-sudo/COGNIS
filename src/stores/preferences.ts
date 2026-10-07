/** Local UI preferences (per viewer). Persisted to localStorage when available. */
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import type { ResearchMode } from '@/types';

export type ThemePref = 'dark' | 'light' | 'system';
export type MotionPref = 'system' | 'reduced' | 'full';
/** Comfortable is the default reading density; Compact tightens tables, sheets, compare and research views. */
export type DensityPref = 'comfortable' | 'compact';
/** Home globe spin: 'auto' follows the motion setting; 'on'/'off' are the viewer's explicit choice. */
export type GlobeSpinPref = 'auto' | 'on' | 'off';

interface PreferencesState {
  theme: ThemePref;
  motion: MotionPref;
  globeSpin: GlobeSpinPref;
  density: DensityPref;
  researchMode: ResearchMode;
  libraryView: 'cards' | 'list' | 'table';
  discoverView: 'cards' | 'table' | 'landscape';
  recentSearches: string[];
  set: (patch: Partial<Omit<PreferencesState, 'set' | 'pushRecentSearch'>>) => void;
  pushRecentSearch: (q: string) => void;
}

const safeStorage = createJSONStorage(() => {
  try {
    const k = '__cg_test__';
    localStorage.setItem(k, '1');
    localStorage.removeItem(k);
    return localStorage;
  } catch {
    const mem = new Map<string, string>();
    return { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => void mem.set(k, v), removeItem: (k) => void mem.delete(k) };
  }
});

export const usePreferences = create<PreferencesState>()(
  persist(
    (set) => ({
      theme: 'dark',
      motion: 'system',
      globeSpin: 'auto',
      density: 'comfortable',
      researchMode: 'quick',
      libraryView: 'cards',
      discoverView: 'cards',
      recentSearches: [],
      set: (patch) => set(patch),
      pushRecentSearch: (q) =>
        set((s) => ({ recentSearches: [q, ...s.recentSearches.filter((x) => x.toLowerCase() !== q.toLowerCase())].slice(0, 6) })),
    }),
    {
      name: 'cognis.preferences',
      storage: safeStorage,
      version: 1,
      // v0 had a three-step density ('comfortable' | 'balanced' | 'compact').
      // 'balanced' was the old default and maps to today's Comfortable.
      migrate: (persisted, version) => {
        const s = (persisted ?? {}) as Partial<PreferencesState> & { density?: string };
        if (version < 1 && s.density !== 'compact') s.density = 'comfortable';
        return s as PreferencesState;
      },
    },
  ),
);

/** True when the viewer chose Compact density. */
export const useCompact = () => usePreferences((s) => s.density === 'compact');
