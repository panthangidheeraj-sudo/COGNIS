import { describe, expect, it } from 'vitest';
import { mockApi, interpretText } from '@/data/mock/mockApi';
import { reduceResearchEvent, initialStreamState } from '@/api/runs';
import type { ResearchEvent, ResearchStreamState } from '@/types';

describe('mock backend contract', () => {
  it('builds every company profile with consistent coverage', async () => {
    const res = await mockApi.companies.discover({ filters: {}, sort: 'name', page: 1, pageSize: 500 });
    expect(res.total).toBeGreaterThan(150);
    for (const c of res.items) {
      expect(c.coverage.total).toBe(5);
      expect(c.coverage.complete).toBe(c.coverage.areas.filter((a) => a.status === 'complete').length);
    }
  });

  it('interprets natural-language discovery queries into editable filters', () => {
    const i = interpretText('Norwegian technology companies in Oslo with more than 100 employees and current hiring');
    const keys = i.filters.map((f) => f.key);
    expect(keys).toEqual(expect.arrayContaining(['location', 'industry', 'employeesMin', 'hiring']));
    expect(i.filters.find((f) => f.key === 'employeesMin')?.value).toBe(100);
  });

  it('returns an ambiguous run instead of guessing identity', async () => {
    const run = await mockApi.research.start({ query: 'Solstad Data', mode: 'quick' });
    expect(run.status).toBe('ambiguous');
    expect(run.ambiguity?.candidates.length).toBe(3);
  });

  it('exposes conflicting evidence on the conflict scenario', async () => {
    const p = await mockApi.companies.get('914552108');
    const rev = p.financials.series.find((s) => s.key === 'revenue')!.points.at(-1)!.fact;
    expect(rev.evidenceState).toBe('conflict');
    expect(rev.conflict?.candidates).toHaveLength(2);
  });

  it('marks blocked sources honestly', async () => {
    const p = await mockApi.companies.get('996450218');
    expect(p.website.status).toBe('blocked');
    expect(p.company.coverage.areas.find((a) => a.area === 'website')?.status).toBe('blocked');
  });

  it('stream reducer ignores duplicate events', () => {
    const base: ResearchStreamState = { ...initialStreamState };
    const e: ResearchEvent = { type: 'synthesis.delta', seq: 1, runId: 'r', at: '2026-10-03T10:00:00Z', text: 'Hello ' };
    const once = reduceResearchEvent(base, e);
    const twice = reduceResearchEvent(once, e);
    expect(twice.synthesisText).toBe('Hello ');
    expect(twice.events).toHaveLength(1);
  });
});

describe('corporate features (mock backend contract)', () => {
  it('compiles an executive brief with sourced items and no scores', async () => {
    const b = await mockApi.companies.brief('921604337');
    expect(b.sections.map((s) => s.id)).toEqual(expect.arrayContaining(['what', 'scale', 'financials', 'leadership', 'locations', 'hiring', 'changes']));
    for (const s of b.sections) for (const it of s.items) expect(it.evidence.length).toBeGreaterThan(0);
    const text = JSON.stringify(b).toLowerCase();
    expect(text).not.toMatch(/\b(score|rating|recommend|best|winner)\b/);
    for (const id of b.sourceIds) expect(b.sourceIndex[id]).toBeTruthy();
  });

  it('keeps observed facts, reported reasons and AI synthesis separate in explanations', async () => {
    const p = await mockApi.companies.get('921604337');
    const ceo = p.changes.changes.find((c) => c.category === 'leadership' && c.explainable)!;
    const x = await mockApi.companies.explain('921604337', { kind: 'change', changeId: ceo.id });
    expect(x.observed.length).toBeGreaterThan(0);
    expect(x.reported.every((r) => r.sourceId && r.evidence.length)).toBe(true);
    if (x.synthesis) expect(x.synthesis.caveat).toMatch(/not a verified fact/i);
  });

  it('marks material changes and orders event significance', async () => {
    const p = await mockApi.companies.get('921604337');
    expect(p.changes.changes.some((c) => c.material)).toBe(true);
    expect(p.changes.changes.some((c) => !c.material)).toBe(true);
    expect(p.activity.events.every((e) => e.significance === 'major' || e.significance === 'minor')).toBe(true);
  });

  it('returns a comparison executive strip without winners', async () => {
    const c = await mockApi.compare.get(['921604337', '925116702']);
    expect(c.summary.map((r) => r.key)).toEqual(['revenue', 'employees', 'hiring', 'locations', 'filing']);
    for (const r of c.summary) expect(r.values).toHaveLength(2);
    expect(c.sections.map((s) => s.id)).toContain('changes');
  });

  it('returns library type facets independent of the type filter', async () => {
    const all = await mockApi.library.list({ type: 'all', sort: 'updated', page: 1, pageSize: 5 });
    const reports = await mockApi.library.list({ type: 'report', sort: 'updated', page: 1, pageSize: 5 });
    expect(all.facets?.company).toBeGreaterThan(0);
    expect(reports.facets?.company).toBe(all.facets?.company);
    expect(reports.items.every((a) => a.type === 'report')).toBe(true);
  });

  it('previews an AI column before adding it', async () => {
    const pv = await mockApi.sheets.previewColumn('sheet-saas', { instruction: "Find the company's current CEO" });
    expect(pv.valueType).toBe('person');
    expect(pv.plannedSources.length).toBeGreaterThan(0);
    expect(pv.supported).toBe(true);
  });
});
