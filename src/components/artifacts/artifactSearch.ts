/**
 * "Search this research". Runs locally over the already-loaded artifact
 * (plain text matching, no business logic) so long dossiers stay navigable.
 * Indexes sections, metrics, exact values, people and their other roles,
 * locations, jobs, events, changes, relationships, dates, source names and
 * evidence excerpts / document titles.
 */
import type { CompanyProfile, Evidence } from '@/types';
import { formatDate, formatDateLong, formatFactValue } from '@/utils/format';

export type SearchKind = 'Section' | 'Metric' | 'Value' | 'Person' | 'Role' | 'Location' | 'Job' | 'Event' | 'Change' | 'Relationship' | 'Evidence' | 'Source' | 'Website';

export interface SearchEntry {
  section: DossierSection;
  sectionLabel: string;
  kind: SearchKind;
  /** Primary line shown in results. */
  text: string;
  /** Secondary context (period, source, date) — searchable too. */
  meta?: string;
  /** Present for evidence hits: opens the evidence drawer directly. */
  evidence?: { title: string; value?: string; items: Evidence[] };
}
export interface SearchHit extends SearchEntry {
  index: number;
  score: number;
}

export const DOSSIER_SECTIONS = [
  { id: 'summary', label: 'Executive Summary' },
  { id: 'financials', label: 'Financial Performance' },
  { id: 'people', label: 'People & Leadership' },
  { id: 'locations', label: 'Locations' },
  { id: 'website', label: 'Website & Online' },
  { id: 'hiring', label: 'Hiring' },
  { id: 'activity', label: 'Recent Activity' },
  { id: 'changes', label: 'Changes' },
  { id: 'sources', label: 'Sources' },
] as const;
export type DossierSection = (typeof DOSSIER_SECTIONS)[number]['id'];

const L = Object.fromEntries(DOSSIER_SECTIONS.map((s) => [s.id, s.label])) as Record<DossierSection, string>;

export function buildIndex(p: CompanyProfile): SearchEntry[] {
  const out: SearchEntry[] = [];
  const src = (id: string) => p.sourceIndex[id]?.name ?? id;
  const add = (section: DossierSection, kind: SearchKind, text: string, meta?: string, evidence?: SearchEntry['evidence']) => {
    if (text) out.push({ section, sectionLabel: L[section], kind, text, meta, evidence });
  };
  const addEvidence = (section: DossierSection, title: string, items: Evidence[], value?: string) => {
    for (const e of items) {
      const body = e.excerptTranslation ?? e.excerpt;
      if (!body && !e.documentTitle) continue;
      add(section, 'Evidence', body ?? e.documentTitle!, [title, e.documentTitle, src(e.sourceId), e.reportingPeriod, `retrieved ${formatDate(e.retrievedAt)}`].filter(Boolean).join(' · '), { title, value, items: [e] });
      if (e.excerpt && e.excerptTranslation) add(section, 'Evidence', e.excerpt, `${title} · original text · ${src(e.sourceId)}`, { title, value, items: [e] });
    }
  };

  for (const s of DOSSIER_SECTIONS) add(s.id, 'Section', s.label);

  if (p.summary) p.summary.text.split(/(?<=\.)\s+/).forEach((s) => add('summary', 'Value', s, 'Executive summary'));
  for (const m of p.keyMetrics)
    if (m.value != null) {
      const v = formatFactValue(m);
      const exact = formatFactValue(m, { exact: true });
      add('summary', 'Metric', `${m.label}: ${v}`, [m.reportingPeriod, exact !== v ? exact : '', [...new Set(m.evidence.map((e) => src(e.sourceId)))].join(', ')].filter(Boolean).join(' · '), { title: m.label, value: v, items: m.evidence });
      addEvidence('summary', m.label, m.evidence, v);
    }

  for (const s of p.financials.series)
    for (const pt of s.points) {
      const v = formatFactValue(pt.fact);
      const exact = formatFactValue(pt.fact, { exact: true });
      add('financials', 'Metric', `${s.label} ${pt.period}: ${v}`, [exact !== v ? exact : '', [...new Set(pt.fact.evidence.map((e) => src(e.sourceId)))].join(', ')].filter(Boolean).join(' · '), { title: `${s.label} ${pt.period}`, value: v, items: pt.fact.evidence });
      addEvidence('financials', `${s.label} ${pt.period}`, pt.fact.evidence, v);
    }
  for (const r of p.financials.ratios) add('financials', 'Metric', `${r.label} ${r.period}: ${r.value}%`, r.formula);

  for (const x of p.people.people) {
    add('people', 'Person', `${x.role}: ${x.name}${x.current ? '' : ' (historical)'}`, [x.since && `since ${formatDateLong(x.since)}`, x.until && `until ${formatDateLong(x.until)}`].filter(Boolean).join(' · ') || undefined, { title: `${x.role}: ${x.name}`, value: x.name, items: x.fact.evidence });
    for (const o of x.otherRoles ?? []) add('people', 'Role', `${x.name} — ${o.role}, ${o.companyName}`, o.current ? 'Other current role' : 'Other former role', { title: `${x.name}: ${o.role}, ${o.companyName}`, items: o.evidence });
    addEvidence('people', `${x.role}: ${x.name}`, x.fact.evidence, x.name);
  }
  for (const r of p.relationships) add('people', 'Relationship', `${r.label}: ${r.entity.name}`, r.entity.orgNumber ? `Org. no. ${r.entity.orgNumber}` : undefined, { title: `${r.label}: ${r.entity.name}`, items: r.evidence });

  for (const l of p.locations.locations) add('locations', 'Location', `${l.label}: ${l.address}${l.postalCode ? `, ${l.postalCode}` : ''} ${l.municipality}`, l.verified ? 'Verified location' : 'Unverified');

  if (p.website.domain) add('website', 'Website', `Website: ${p.website.domain}`);
  if (p.website.description?.value) add('website', 'Value', p.website.description.value, 'Website description');
  for (const s of p.website.social) add('website', 'Website', `${s.network}: ${s.handle}`);

  for (const j of p.hiring.jobs) add('hiring', 'Job', `${j.title}${j.location ? ` — ${j.location}` : ''}${j.department ? ` (${j.department})` : ''}`, [j.postedAt && `posted ${formatDate(j.postedAt)}`, src(j.sourceId), j.state].filter(Boolean).join(' · '), { title: j.title, items: j.evidence });

  for (const e of p.activity.events)
    add('activity', 'Event', `${e.title}${e.description ? ` — ${e.description}` : ''}`, [formatDate(e.date), formatDateLong(e.date), e.date, e.significance === 'major' ? 'Major event' : 'Minor update', e.sourceIds.map(src).join(', ')].join(' · '));

  for (const c of p.changes.changes) {
    add('changes', 'Change', c.previous ? `${c.label}: ${c.previous} → ${c.current}` : `${c.label}: ${c.current}`, [c.headline, `detected ${formatDate(c.detectedAt)}`, c.material ? 'Material change' : 'Minor update'].filter(Boolean).join(' · '));
    addEvidence('changes', c.label, c.evidence, c.current ?? undefined);
  }

  for (const s of p.sources) add('sources', 'Source', `${s.source.name}${s.source.originalTitle ? ` (${s.source.originalTitle})` : ''}`, `${s.factCount} references · ${s.source.domain ?? ''} · retrieved ${formatDate(s.lastRetrievedAt)}`);
  return out;
}

/** All terms must match (text or meta). Ranked: exact phrase in text > all terms in text > meta-only. */
export function searchIndex(index: SearchEntry[], q: string): SearchHit[] {
  const phrase = q.trim().toLowerCase();
  if (phrase.length < 2) return [];
  const terms = phrase.split(/\s+/).filter(Boolean);
  const hits: SearchHit[] = [];
  index.forEach((e, i) => {
    const text = e.text.toLowerCase();
    const all = `${text} ${(e.meta ?? '').toLowerCase()} ${e.sectionLabel.toLowerCase()}`;
    if (!terms.every((t) => all.includes(t))) return;
    let score = text.includes(phrase) ? 3 : terms.every((t) => text.includes(t)) ? 2 : 1;
    if (e.kind === 'Section') score += 1;
    if (e.kind === 'Evidence') score -= 0.5;
    hits.push({ ...e, index: i, score });
  });
  return hits.sort((a, b) => b.score - a.score || a.index - b.index);
}

/** Scroll to and flash the smallest element in a section containing the term; returns whether a match was found. */
export function revealInSection(sectionId: string, term: string): boolean {
  const root = document.getElementById(`sec-${sectionId}`);
  if (!root) return false;
  const terms = term.trim().toLowerCase().split(/\s+/).filter(Boolean);
  let best: HTMLElement | null = null;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
  let n = walker.nextNode() as HTMLElement | null;
  while (n) {
    const t = n.textContent?.toLowerCase() ?? '';
    if (terms.length && terms.every((x) => t.includes(x)) && n.children.length <= 6 && !['svg', 'TABLE', 'TBODY'].includes(n.tagName)) best = n;
    n = walker.nextNode() as HTMLElement | null;
  }
  const target = ((best ?? root).closest('li, tr, dd, p, .metric, .person, .loc-item, .source-card, .tl-item, .change, .fin-stat, .dos-sec') as HTMLElement | null) ?? best ?? root;
  target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  target.classList.remove('is-highlighted');
  void target.offsetWidth;
  target.classList.add('is-highlighted');
  setTimeout(() => target.classList.remove('is-highlighted'), 2200);
  return !!best;
}
