/**
 * Discover enrichment: for the results on screen that have not been researched, ask the backend for the figures their cards are missing
 * (filed accounts, the registered employee count, NAV ads and a verified careers page). Small batches, two at a time, cached per company for
 * half an hour, cancelled when the results change. Never research: nothing is saved, and every figure comes back with what was really established.
 */
import { useEffect, useMemo, useState } from 'react';
import { api } from '@/api';
import type { CompanyEnrichment, CompanySummary, EnrichedFigure, EnrichmentField } from '@/types';

export const ENRICH_BATCH = 6;
export const ENRICH_PARALLEL = 2;
const TTL_MS = 30 * 60_000;
const cache = new Map<string, { at: number; data: CompanyEnrichment }>();

/** Forget cached lookups (tests, and after a company was researched). */
export function clearEnrichmentCache() {
  cache.clear();
}

/**
 * The shared lookup cache. Discover and Compare read and write the same entries, so a figure looked up for a card is not fetched again for the
 * comparison (and the other way round). Fields are merged per company; only figures that were actually established are kept
 * (an unreachable source is retried on the next visit rather than remembered).
 */
export function readCachedField(org: string, field: EnrichmentField): EnrichedFigure | undefined {
  const hit = cache.get(org);
  if (!hit || Date.now() - hit.at >= TTL_MS) return undefined;
  return hit.data.fields[field];
}
export function writeCachedLookup(r: CompanyEnrichment): void {
  // per figure: one that was established is kept, one whose source was unreachable is not (it is tried again on the next visit)
  const kept = Object.fromEntries(Object.entries(r.fields).filter(([, f]) => f && f.state !== 'unavailable'));
  if (!Object.keys(kept).length) return;
  const prev = cache.get(r.orgNumber);
  const fresh = prev && Date.now() - prev.at < TTL_MS ? prev.data.fields : {};
  cache.set(r.orgNumber, { at: Date.now(), data: { ...r, fields: { ...fresh, ...kept } } });
}

/** The figures a result card is missing that a lookup can answer. Researched companies already show what research established. */
export function missingFigures(c: CompanySummary): EnrichmentField[] {
  if (c.researchState !== 'not_researched') return [];
  const out: EnrichmentField[] = [];
  if (!c.revenue) out.push('revenue');
  if (c.employees == null) out.push('employees');
  if (c.openPositions == null) out.push('openPositions');
  return out;
}

export interface EnrichmentProgress {
  total: number;
  done: number;
  running: boolean;
}

export interface DiscoverEnrichment {
  byOrg: Record<string, CompanyEnrichment>;
  pending: Set<string>;
  progress: EnrichmentProgress;
}

const failedLookup = (org: string, fields: EnrichmentField[], message: string): CompanyEnrichment => {
  const figure: EnrichedFigure = { state: 'unavailable', note: `The lookup could not be run (${message}). Nothing is concluded; it is tried again on a later visit.`, sources: [] };
  return { orgNumber: org, checkedAt: new Date().toISOString(), fields: Object.fromEntries(fields.map((f) => [f, figure])) };
};

/** `limit`: how many of `items` (in order) may be looked up. `enabled=false` only reads what is cached. */
export function useDiscoverEnrichment(items: CompanySummary[] | undefined, { enabled = true, limit = 24 }: { enabled?: boolean; limit?: number } = {}): DiscoverEnrichment {
  const wanted = useMemo(() => (items ?? []).map((c) => ({ org: c.orgNumber, fields: missingFigures(c) })).filter((w) => w.fields.length > 0).slice(0, limit), [items, limit]);
  const key = wanted.map((w) => `${w.org}:${w.fields.join(',')}`).join('|');
  const [byOrg, setByOrg] = useState<Record<string, CompanyEnrichment>>({});
  const [pending, setPending] = useState<Set<string>>(() => new Set());
  const [progress, setProgress] = useState<EnrichmentProgress>({ total: 0, done: 0, running: false });

  useEffect(() => {
    const now = Date.now();
    const known: Record<string, CompanyEnrichment> = {};
    const todo: { org: string; fields: EnrichmentField[] }[] = [];
    for (const w of wanted) {
      const hit = cache.get(w.org);
      if (hit && now - hit.at < TTL_MS && w.fields.every((f) => hit.data.fields[f])) known[w.org] = hit.data;
      else todo.push(w);
    }
    setByOrg(known);
    if (!enabled || todo.length === 0) {
      setPending(new Set());
      setProgress({ total: wanted.length, done: wanted.length - todo.length, running: false });
      return;
    }
    const ctrl = new AbortController();
    let done = wanted.length - todo.length;
    setPending(new Set(todo.map((w) => w.org)));
    setProgress({ total: wanted.length, done, running: true });
    const batches: (typeof todo)[] = [];
    for (let i = 0; i < todo.length; i += ENRICH_BATCH) batches.push(todo.slice(i, i + ENRICH_BATCH));
    const fieldsOf = (b: typeof todo) => [...new Set(b.flatMap((w) => w.fields))];

    const runBatch = async (b: typeof todo) => {
      let results: CompanyEnrichment[];
      try {
        const res = await api.companies.enrich(
          b.map((w) => w.org),
          { fields: fieldsOf(b), signal: ctrl.signal },
        );
        results = res.items;
      } catch (err) {
        if (ctrl.signal.aborted || (err as Error).name === 'AbortError') return;
        results = b.map((w) => failedLookup(w.org, w.fields, (err as Error).message || 'request failed'));
      }
      if (ctrl.signal.aborted) return;
      for (const r of results) writeCachedLookup(r);
      done += b.length;
      setByOrg((prev) => ({ ...prev, ...Object.fromEntries(results.map((r) => [r.orgNumber, r])) }));
      setPending((prev) => {
        const next = new Set(prev);
        b.forEach((w) => next.delete(w.org));
        return next;
      });
      setProgress({ total: wanted.length, done, running: done < wanted.length });
    };
    const queue = [...batches];
    const worker = async () => {
      while (queue.length && !ctrl.signal.aborted) await runBatch(queue.shift()!);
    };
    void Promise.all(Array.from({ length: Math.min(ENRICH_PARALLEL, batches.length) }, worker));
    return () => ctrl.abort();
    // `key` captures `wanted`; re-running on every new array identity would restart the lookups needlessly
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled]);

  return { byOrg, pending, progress };
}

/** A summary with the verified looked-up figures filled in (only `verified` ones; everything else stays empty). */
export function withVerifiedFigures(c: CompanySummary, e?: CompanyEnrichment): CompanySummary {
  if (!e) return c;
  const rev = e.fields.revenue;
  const emp = e.fields.employees;
  const jobs = e.fields.openPositions;
  return {
    ...c,
    revenue: c.revenue ?? (rev?.state === 'verified' && rev.value != null ? { value: rev.value, currency: rev.currency ?? '', period: rev.period ?? '' } : c.revenue),
    employees: c.employees ?? (emp?.state === 'verified' && emp.value != null ? emp.value : c.employees),
    openPositions: c.openPositions ?? (jobs?.state === 'verified' && jobs.value != null ? jobs.value : c.openPositions),
  };
}
