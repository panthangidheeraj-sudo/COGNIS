/** Ephemeral UI state: overlays, evidence target, toasts, compare tray, globe focus. */
import { create } from 'zustand';
import type { CompanySummary, Evidence, Fact, Source } from '@/types';

export interface EvidenceTarget {
  /** A fact with full provenance … */
  fact?: Fact;
  /** … or a loose evidence list (timeline events, jobs, changes) */
  evidence?: Evidence[];
  title?: string;
  value?: string;
  sourceIndex: Record<string, Source>;
  /** Optional context line, e.g. company name */
  context?: string;
}

export interface Toast {
  id: number;
  tone: 'ok' | 'info' | 'warn' | 'err';
  text: string;
  action?: { label: string; href: string };
}

interface UiState {
  paletteOpen: boolean;
  paletteQuery: string;
  evidence: EvidenceTarget | null;
  toasts: Toast[];
  openPalette: (q?: string) => void;
  closePalette: () => void;
  openEvidence: (t: EvidenceTarget) => void;
  closeEvidence: () => void;
  toast: (t: Omit<Toast, 'id'>) => void;
  dismissToast: (id: number) => void;
}

let toastId = 0;
export const useUi = create<UiState>((set) => ({
  paletteOpen: false,
  paletteQuery: '',
  evidence: null,
  toasts: [],
  openPalette: (q = '') => set({ paletteOpen: true, paletteQuery: q }),
  closePalette: () => set({ paletteOpen: false }),
  openEvidence: (evidence) => set({ evidence }),
  closeEvidence: () => set({ evidence: null }),
  toast: (t) => {
    const id = ++toastId;
    set((s) => ({ toasts: [...s.toasts.slice(-2), { ...t, id }] }));
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })), 5200);
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })),
}));

/** Companies selected for comparison (2–5). Harmless optimistic UI state. */
interface CompareState {
  selected: Pick<CompanySummary, 'orgNumber' | 'legalName'>[];
  toggle: (c: Pick<CompanySummary, 'orgNumber' | 'legalName'>) => void;
  remove: (org: string) => void;
  clear: () => void;
  setAll: (c: Pick<CompanySummary, 'orgNumber' | 'legalName'>[]) => void;
}
export const MAX_COMPARE = 5;
export const useCompare = create<CompareState>((set) => ({
  selected: [],
  toggle: (c) =>
    set((s) =>
      s.selected.some((x) => x.orgNumber === c.orgNumber)
        ? { selected: s.selected.filter((x) => x.orgNumber !== c.orgNumber) }
        : s.selected.length >= MAX_COMPARE
          ? s
          : { selected: [...s.selected, { orgNumber: c.orgNumber, legalName: c.legalName }] },
    ),
  remove: (org) => set((s) => ({ selected: s.selected.filter((x) => x.orgNumber !== org) })),
  clear: () => set({ selected: [] }),
  setAll: (selected) => set({ selected: selected.slice(0, MAX_COMPARE) }),
}));

/** Globe focus + research pulses. Points only come from backend geo data. */
export interface GlobePoint {
  id: string;
  lat: number;
  lon: number;
  label?: string;
}
interface GlobeState {
  focus: GlobePoint | null;
  points: GlobePoint[];
  setFocus: (p: GlobePoint | null) => void;
  setPoints: (p: GlobePoint[]) => void;
}
export const useGlobe = create<GlobeState>((set) => ({
  focus: null,
  points: [],
  setFocus: (focus) => set({ focus }),
  setPoints: (points) => set({ points }),
}));
