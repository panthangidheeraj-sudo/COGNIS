/**
 * Compare auto-enrichment. Opening Compare (or adding a company to it) looks up the figures a comparison needs and the saved profile does not
 * hold — filed revenue, the registered employee count and verified openings — through the same `companies.enrich` endpoint and lookup cache
 * Discover uses. It is not a second research engine: nothing is saved, every figure comes back with what was really established, and the
 * cache is shared, so a figure already looked up for a card (or for an earlier comparison) is reused, never fetched again.
 *
 * Every cell is in exactly one of these states, and says so:
 *   idle        not fetched (lookups are off, or have not started)
 *   fetching    a lookup is running
 *   verified    a source established the value (it keeps the lookup's own sources and note)
 *   none_found  the sources were checked and hold nothing ("None verified" / "Not reported") — a confirmed absence, not a gap in the fetch
 *   unavailable a source could not be reached, so nothing is concluded
 *   failed      the request itself failed (offline, server error); a retry is offered
 *
 * Results are matched to a company by the exact organisation number they were requested for. An item for any other number is dropped.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '@/api';
import type { CompanyEnrichment, CompanySummary, Comparison, EnrichedFigure, EnrichmentField, EnrichmentSource } from '@/types';
import { ENRICH_BATCH, ENRICH_PARALLEL, readCachedField, writeCachedLookup } from './useDiscoverEnrichment';
import { figureView, type FigureView } from '@/components/company/CompanyFigure';

/** The comparison rows a lookup can answer, by row key (the summary strip and the detail sections use different keys). */
export const ROW_FIELD: Record<string, EnrichmentField> = {
  revenue: 'revenue',
  employees: 'employees',
  hiring: 'openPositions',
  open_positions: 'openPositions',
};

export type CellState = 'idle' | 'fetching' | 'verified' | 'none_found' | 'unavailable' | 'failed';

export interface CompareCell {
  state: CellState;
  view: FigureView;
  /** Where a looked-up value came from (kept with the value, shown as its citation). */
  sources?: EnrichmentSource[];
}

const key = (org: string, f: EnrichmentField) => `${org}:${f}`;

/** Fields of each company the comparison shows empty (or stale) and a lookup could answer. */
export function neededFields(cmp: Comparison): { org: string; fields: EnrichmentField[] }[] {
  const out: { org: string; fields: EnrichmentField[] }[] = [];
  cmp.companies.forEach((c, i) => {
    const fields = new Set<EnrichmentField>();
    for (const row of [...cmp.summary, ...cmp.sections.flatMap((s) => s.rows)]) {
      const field = ROW_FIELD[row.key];
      if (!field) continue;
      const fact = row.values[i];
      const ok = fact && fact.status === 'verified' && fact.freshness !== 'stale';
      // research already reached a conclusion about hiring ("none verified", "source unavailable"): that is shown as it is, not re-looked-up
      if (field === 'openPositions' && c.openPositionsStatus && c.openPositionsStatus !== 'verified') continue;
      if (!ok) fields.add(field);
    }
    if (fields.size) out.push({ org: c.orgNumber, fields: [...fields] });
  });
  return out;
}

const STATE_OF: Record<EnrichedFigure['state'], CellState> = {
  verified: 'verified',
  none_found: 'none_found',
  not_reported: 'none_found',
  unavailable: 'unavailable',
  not_checked: 'idle',
  unverified: 'unavailable',
};

export interface CompareEnrichment {
  /** What the cell for this row and company shows when the profile holds no verified fact. */
  cell: (rowKey: string, company: CompanySummary) => CompareCell | null;
  progress: { total: number; done: number; running: boolean };
  /** Try the failed lookups of one company again. */
  retry: (org: string) => void;
}

export function useCompareEnrichment(cmp: Comparison | undefined, { enabled = true }: { enabled?: boolean } = {}): CompareEnrichment {
  const needed = useMemo(() => (cmp ? neededFields(cmp) : []), [cmp]);
  const wantKey = needed.map((n) => `${n.org}:${[...n.fields].sort().join(',')}`).join('|');
  const [, bump] = useState(0);
  const failed = useRef(new Set<string>());
  const running = useRef(new Set<string>());
  const [attempt, setAttempt] = useState(0);
  const mounted = useRef<AbortController | null>(null);
  const lastSeen = useRef(new Map<string, EnrichedFigure>());

  useEffect(() => {
    const ctrl = new AbortController();
    mounted.current = ctrl;
    return () => ctrl.abort();
  }, []);

  useEffect(() => {
    if (!enabled || !needed.length) return;
    const ctrl = mounted.current;
    if (!ctrl || ctrl.signal.aborted) return;
    // only what is not cached, not failed (until retried) and not already on its way
    const todo = needed
      .map((n) => ({ org: n.org, fields: n.fields.filter((f) => !readCachedField(n.org, f) && !failed.current.has(key(n.org, f)) && !running.current.has(key(n.org, f))) }))
      .filter((n) => n.fields.length);
    if (!todo.length) return;
    for (const t of todo) t.fields.forEach((f) => running.current.add(key(t.org, f)));
    bump((n) => n + 1);
    const batches: typeof todo[] = [];
    for (let i = 0; i < todo.length; i += ENRICH_BATCH) batches.push(todo.slice(i, i + ENRICH_BATCH));

    const run = async (b: typeof todo) => {
      const orgs = b.map((t) => t.org);
      let items: CompanyEnrichment[] = [];
      let ok = true;
      try {
        const res = await api.companies.enrich(orgs, { fields: [...new Set(b.flatMap((t) => t.fields))], signal: ctrl.signal });
        items = res.items.filter((i) => orgs.includes(i.orgNumber)); // a result for another number is never attached to these companies
      } catch (err) {
        if (ctrl.signal.aborted || (err as Error).name === 'AbortError') {
          for (const t of b) t.fields.forEach((f) => running.current.delete(key(t.org, f)));
          return;
        }
        ok = false;
      }
      for (const t of b) {
        const got = items.find((i) => i.orgNumber === t.org);
        for (const f of t.fields) {
          running.current.delete(key(t.org, f));
          if (!ok || !got?.fields[f]) failed.current.add(key(t.org, f));
        }
        if (got) writeCachedLookup(got);
        // a figure whose source was unreachable is not cached; it is shown as unavailable from this lookup until the next visit
        if (got) for (const f of t.fields) if (got.fields[f] && !readCachedField(t.org, f)) lastSeen.current.set(key(t.org, f), got.fields[f]!);
      }
      if (!ctrl.signal.aborted) bump((n) => n + 1);
    };
    const queue = [...batches];
    const worker = async () => {
      while (queue.length && !ctrl.signal.aborted) await run(queue.shift()!);
    };
    void Promise.all(Array.from({ length: Math.min(ENRICH_PARALLEL, batches.length) }, worker));
    // not aborted on a changed selection: adding a company must not restart the lookups already under way
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wantKey, enabled, attempt]);


  const cell = useCallback<CompareEnrichment['cell']>(
    (rowKey, company) => {
      const field = ROW_FIELD[rowKey];
      if (!field) return null;
      const k = key(company.orgNumber, field);
      const fig = readCachedField(company.orgNumber, field) ?? lastSeen.current.get(k);
      if (fig) {
        const lookup: CompanyEnrichment = { orgNumber: company.orgNumber, checkedAt: '', fields: { [field]: fig } };
        return { state: STATE_OF[fig.state], view: figureView(field, company, lookup), sources: fig.sources.filter((x) => x.state === 'checked') };
      }
      if (running.current.has(k)) return { state: 'fetching', view: figureView(field, company, undefined, true) };
      if (failed.current.has(k)) return { state: 'failed', view: { label: 'Lookup failed', note: 'The lookup could not be completed. Nothing is concluded about this figure. Use Retry to try again.' } };
      if (!enabled) return { state: 'idle', view: { label: 'Not fetched', note: 'This figure has not been looked up yet.' } };
      const pre = figureView(field, company); // what the profile itself says (research result, registry employee count)
      return { state: 'idle', view: pre.value != null || pre.label !== 'Not checked' ? pre : { label: 'Not fetched', note: 'This figure has not been looked up yet.' } };
    },
    // the cache and the sets are mutable on purpose; `bump` re-renders readers
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [enabled, wantKey],
  );

  const retry = useCallback((org: string) => {
    for (const k of [...failed.current]) if (k.startsWith(`${org}:`)) failed.current.delete(k);
    setAttempt((n) => n + 1);
  }, []);

  const total = needed.reduce((n, t) => n + t.fields.length, 0);
  const pending = needed.reduce((n, t) => n + t.fields.filter((f) => running.current.has(key(t.org, f))).length, 0);
  return { cell, progress: { total, done: total - pending, running: pending > 0 }, retry };
}
