import type { CompanyProfile, Evidence, Fact } from '@/types';

/** Index of every evidence item in a profile, by id. */
export function collectEvidence(p: CompanyProfile): Map<string, Evidence> {
  const m = new Map<string, Evidence>();
  const add = (e: Evidence) => m.set(e.id, e);
  const addFact = (f?: Fact) => f?.evidence.forEach(add);
  Object.values(p.identity).forEach((f) => typeof f === 'object' && addFact(f as Fact));
  addFact(p.description);
  p.keyMetrics.forEach(addFact);
  p.financials.series.forEach((s) => s.points.forEach((pt) => addFact(pt.fact)));
  p.people.people.forEach((x) => addFact(x.fact));
  p.locations.locations.forEach((x) => addFact(x.fact));
  p.hiring.jobs.forEach((j) => j.evidence.forEach(add));
  p.activity.events.forEach((e) => e.evidence.forEach(add));
  p.changes.changes.forEach((c) => c.evidence.forEach(add));
  p.relationships.forEach((r) => r.evidence.forEach(add));
  addFact(p.website.verification);
  p.website.social.forEach((s) => addFact(s.fact));
  return m;
}

/** All facts in a profile (for search and exports). */
export function allFacts(p: CompanyProfile): Fact[] {
  const out: Fact[] = [];
  Object.values(p.identity).forEach((f) => typeof f === 'object' && f && out.push(f as Fact));
  if (p.description) out.push(p.description);
  out.push(...p.keyMetrics);
  p.financials.series.forEach((s) => s.points.forEach((pt) => out.push(pt.fact)));
  p.people.people.forEach((x) => out.push(x.fact));
  p.locations.locations.forEach((x) => out.push(x.fact));
  return out;
}
