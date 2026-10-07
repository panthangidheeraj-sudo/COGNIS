/**
 * MOCK BACKEND — in-memory database. Resets on page reload.
 */
import type {
  ArtifactSummary,
  CompanyArtifact,
  CompanyProfile,
  CompanySummary,
  DataSheet,
  DataSheetCell,
  DataSheetColumn,
  DataSheetRow,
  ReportArtifact,
  ResearchEvent,
  ResearchRun,
  Signal,
  WatchlistItem,
} from '@/types';
import { ALL_SPECS, NORDVIK, SECTOR_KEYWORDS } from './companies';
import { buildProfile, NOW, registryOnly, type CompanySpec } from './profileBuilder';
import { formatDate, formatMoneyCompact } from '@/utils/format';

export const specsByOrg = new Map<string, CompanySpec>(ALL_SPECS.map((s) => [s.org, s]));
const fullCache = new Map<string, CompanyProfile>();
export const researched = new Set<string>(ALL_SPECS.filter((s) => s.researchedAt).map((s) => s.org));
/** Research time overrides after a mock run completes. */
export const researchedAtOverride = new Map<string, string>();

export function fullProfile(org: string): CompanyProfile {
  let p = fullCache.get(org);
  if (!p) {
    const spec = specsByOrg.get(org);
    if (!spec) throw new Error('not found');
    const at = researchedAtOverride.get(org);
    p = buildProfile(at ? { ...spec, researchedAt: at } : spec.researchedAt ? spec : { ...spec, researchedAt: NOW });
    fullCache.set(org, p);
  }
  return p;
}

export function profileFor(org: string): CompanyProfile {
  const p = fullProfile(org);
  const withArtifact = { ...p, artifactId: researched.has(org) ? `art-${org}` : undefined };
  return researched.has(org) ? withArtifact : registryOnly(withArtifact);
}

export function markResearched(org: string, at: string) {
  researched.add(org);
  researchedAtOverride.set(org, at);
  fullCache.delete(org);
}

let summaryCache: CompanySummary[] | null = null;
export function allSummaries(): CompanySummary[] {
  if (!summaryCache) summaryCache = ALL_SPECS.map((s) => profileFor(s.org).company);
  return summaryCache;
}
export function invalidateSummaries() {
  summaryCache = null;
}

export function sectorOf(org: string) {
  return specsByOrg.get(org)?.sector;
}
export function matchesIndustry(org: string, term: string) {
  const sector = sectorOf(org);
  if (!sector) return false;
  const t = term.toLowerCase();
  return SECTOR_KEYWORDS[sector].some((k) => k === t || t.includes(k)) || specsByOrg.get(org)!.nace.description.toLowerCase().includes(t);
}

/* ============================== Library ============================== */

export const artifactMeta = new Map<string, { title: string; tags: string[]; pinned: boolean; archived: boolean; viewedAt?: string }>();

/** Older research versions for the "changing company" scenario. */
const NORDVIK_V1: CompanySpec = {
  ...NORDVIK,
  researchedAt: '2026-08-21T09:00:00Z',
  employeesNow: 312,
  people: NORDVIK.people.filter((p) => p.name !== 'Ingrid Solberg').map((p) => (p.name === 'Henrik Aas' ? { ...p, until: undefined, current: true } : p)),
  locations: NORDVIK.locations.slice(0, 4),
  jobs: [
    { title: 'Integration developer (HL7 / FHIR)', department: 'Engineering', location: 'Bodø', postedAt: '2026-08-12' },
    { title: 'Customer success manager', department: 'Customer', location: 'Bergen', postedAt: '2026-08-04' },
  ],
  hiringHistory: NORDVIK.hiringHistory!.slice(0, 5),
  events: NORDVIK.events.filter((e) => e.date <= '2026-08-21'),
  changes: [],
  summary:
    'Nordvik Helseteknologi AS is a Bodø-based healthcare software company. It reported revenue of NOK 790.4 million for FY2025. The registry lists 312 employees and Henrik Aas is the registered CEO. Two verified openings were found.',
};
const NORDVIK_V2: CompanySpec = {
  ...NORDVIK,
  researchedAt: '2026-09-15T09:00:00Z',
  employeesNow: 312,
  locations: NORDVIK.locations.slice(0, 5),
  jobs: NORDVIK.jobs!.slice(3, 10),
  hiringHistory: NORDVIK.hiringHistory!.slice(0, 6),
  events: NORDVIK.events.filter((e) => e.date <= '2026-09-15'),
  changes: NORDVIK.changes.filter((c) => c.detectedAt <= '2026-09-15'),
  summary:
    'Nordvik Helseteknologi AS is a Bodø-based healthcare software company. It reported revenue of NOK 790.4 million for FY2025. Ingrid Solberg became CEO on 1 September 2026 and a new Oslo workplace was registered. Seven verified openings were found.',
};
export const VERSIONS: Record<string, { id: string; createdAt: string; label: string; spec?: CompanySpec }[]> = {
  [`art-${NORDVIK.org}`]: [
    { id: 'v3', createdAt: '2026-10-03T10:32:00Z', label: 'Current' },
    { id: 'v2', createdAt: '2026-09-15T09:00:00Z', label: 'Update', spec: NORDVIK_V2 },
    { id: 'v1', createdAt: '2026-08-21T09:00:00Z', label: 'First research', spec: NORDVIK_V1 },
  ],
};
const versionProfileCache = new Map<string, CompanyProfile>();
export function versionProfile(artifactId: string, versionId: string): CompanyProfile | null {
  const v = VERSIONS[artifactId]?.find((x) => x.id === versionId);
  if (!v) return null;
  if (!v.spec) return profileFor(artifactId.replace('art-', ''));
  const key = `${artifactId}:${versionId}`;
  if (!versionProfileCache.has(key)) versionProfileCache.set(key, { ...buildProfile(v.spec), artifactId });
  return versionProfileCache.get(key)!;
}
export function versionsFor(artifactId: string, org: string) {
  const list = VERSIONS[artifactId];
  if (list) return list;
  const at = researchedAtOverride.get(org) ?? specsByOrg.get(org)?.researchedAt ?? NOW;
  return [{ id: 'v1', createdAt: at, label: 'Current' }];
}

export function companyArtifact(org: string): CompanyArtifact {
  const p = profileFor(org);
  const id = `art-${org}`;
  const meta = artifactMeta.get(id);
  const versions = versionsFor(id, org);
  const age = (Date.parse(NOW) - Date.parse(p.company.lastResearchedAt ?? NOW)) / 86400000;
  const stale = age >= 14 ? 2 : age >= 3 ? 1 : 0;
  return {
    id,
    type: 'company',
    title: meta?.title ?? p.company.legalName,
    orgNumber: org,
    createdAt: versions.at(-1)!.createdAt,
    updatedAt: versions[0].createdAt,
    versionId: versions[0].id,
    versions: versions.map((v, i) => ({ id: v.id, createdAt: v.createdAt, label: v.label, isCurrent: i === 0 })),
    freshness: {
      state: stale ? 'fresh_available' : 'saved',
      lastUpdatedAt: p.company.lastResearchedAt ?? NOW,
      staleAreas: stale,
      changedSources: stale * 2,
      newFilings: stale === 2 ? 1 : 0,
    },
    tags: meta?.tags ?? p.company.tags ?? [],
    pinned: meta?.pinned ?? false,
    profile: p,
  };
}

export const reports: ReportArtifact[] = [];
export function seedReports() {
  if (reports.length) return;
  reports.push({
    id: 'rep-nordvik-brief',
    type: 'report',
    title: 'Nordvik Helseteknologi AS — Company brief',
    kind: 'company_brief',
    orgNumber: NORDVIK.org,
    createdAt: '2026-10-03T10:40:00Z',
    updatedAt: '2026-10-03T10:40:00Z',
    sections: ['summary', 'financials', 'people', 'locations', 'hiring', 'activity', 'sources'],
    profile: profileFor(NORDVIK.org),
    tags: ['Healthcare'],
    pinned: true,
  });
}

export const extraArtifacts: ArtifactSummary[] = [
  {
    id: 'cmp-health',
    type: 'comparison',
    title: 'Health technology peers',
    subtitle: 'Nordvik · Polarlys · Tindra',
    updatedAt: '2026-10-02T15:10:00Z',
    tags: ['Healthcare'],
    pinned: false,
    archived: false,
    targetId: `${NORDVIK.org},925116702,918877231`,
    itemCount: 3,
  },
  {
    id: 'watch-main',
    type: 'watchlist',
    title: 'My Watchlist',
    updatedAt: '2026-10-03T10:32:00Z',
    tags: [],
    pinned: true,
    archived: false,
    itemCount: 0,
  },
  {
    id: 'ss-oslo-hiring',
    type: 'saved_search',
    title: 'Oslo technology companies currently hiring',
    subtitle: 'Discover · natural-language query',
    updatedAt: '2026-09-28T08:00:00Z',
    tags: ['Prospect'],
    pinned: false,
    archived: false,
    targetId: 'Technology companies in Oslo currently hiring',
  },
];

/* ============================== Data sheets ============================== */

export const sheets = new Map<string, DataSheet>();

export const STANDARD_COLUMNS: DataSheetColumn[] = [
  { id: 'company', title: 'Company', kind: 'identity', valueType: 'text', width: 260, frozen: true },
  { id: 'revenue', title: 'Revenue', kind: 'standard', valueType: 'currency', width: 150, unit: 'NOK' },
  { id: 'employees', title: 'Employees', kind: 'standard', valueType: 'number', width: 120 },
  { id: 'ceo', title: 'CEO', kind: 'standard', valueType: 'person', width: 180 },
  { id: 'hiring', title: 'Hiring', kind: 'standard', valueType: 'number', width: 120 },
  { id: 'website', title: 'Website', kind: 'standard', valueType: 'url', width: 200 },
  { id: 'filing', title: 'Latest filing', kind: 'standard', valueType: 'date', width: 150 },
];

export function cellFor(org: string, columnId: string, instruction?: string): DataSheetCell {
  const p = fullProfile(org);
  const spec = specsByOrg.get(org)!;
  const src = (id: string) => p.sourceIndex[id]?.name ?? id;
  const ok = (value: DataSheetCell['value'], display: string, evidence: DataSheetCell['evidence'], sourceId: string, state: DataSheetCell['evidenceState'] = 'primary'): DataSheetCell => ({
    status: 'verified',
    value,
    display,
    evidence,
    evidenceState: state,
    sourceName: src(sourceId),
    updatedAt: p.company.lastResearchedAt ?? NOW,
  });
  const na = (note = 'No verified evidence found in the searched permitted sources.'): DataSheetCell => ({ status: 'not_available', value: null, evidence: [], note });
  const rev = p.financials.series.find((s) => s.key === 'revenue')?.points.at(-1);
  const ceo = p.people.people.find((x) => x.role === 'CEO' && x.current);
  switch (columnId) {
    case 'revenue':
      return rev
        ? { ...ok(rev.fact.value!, `${formatMoneyCompact(rev.fact.value!, undefined)} · ${rev.period}`, rev.fact.evidence, 'accounts', rev.fact.evidenceState) }
        : na('No filed annual accounts found.');
    case 'employees': {
      const f = p.keyMetrics.find((k) => k.field === 'overview.employees');
      return f?.value != null ? ok(f.value, String(f.value), f.evidence, 'brreg', f.evidenceState) : na('Not reported in the registry.');
    }
    case 'ceo':
      return ceo ? ok(ceo.name, ceo.name, ceo.fact.evidence, 'roles', ceo.fact.evidenceState) : na();
    case 'hiring':
      if (spec.jobs === null) return na('No current verified openings found in searched sources.');
      return ok(p.hiring.totalCurrent ?? 0, p.hiring.totalCurrent ? `${p.hiring.totalCurrent} open` : '0 open', p.hiring.jobs.slice(0, 2).flatMap((j) => j.evidence), 'nav');
    case 'website':
      if (spec.websiteBlocked) return { status: 'blocked', value: spec.domain, display: spec.domain ?? undefined, evidence: p.identity.website?.evidence ?? [], note: 'Source access blocked. Domain listed in registry; content not verified.' };
      return spec.domain ? ok(spec.domain, spec.domain, p.identity.website!.evidence, `web-${org}`, p.identity.website!.evidenceState) : na('No official website verified.');
    case 'filing': {
      const ev = p.activity.events.find((e) => e.type === 'filing');
      return ev ? ok(ev.date, `Filed ${formatDate(ev.date)}`, ev.evidence, 'accounts') : rev ? ok(rev.period, rev.period, rev.fact.evidence, 'accounts') : na('No filing found.');
    }
    default:
      return resolveInstruction(p, spec, instruction ?? '', org);
  }
}

function hash(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

/** Mock of the backend's AI-column research: maps instructions onto verified profile facts. */
function resolveInstruction(p: CompanyProfile, spec: CompanySpec, instruction: string, org: string): DataSheetCell {
  const q = instruction.toLowerCase();
  const src = (id: string) => p.sourceIndex[id]?.name ?? id;
  const done = (value: DataSheetCell['value'], display: string, evidence: DataSheetCell['evidence'], sourceId: string, state: DataSheetCell['evidenceState'] = 'primary'): DataSheetCell => ({
    status: 'verified',
    value,
    display,
    evidence,
    evidenceState: state,
    sourceName: src(sourceId),
    updatedAt: NOW,
  });
  const na = (note = 'No verified evidence found in the searched permitted sources.'): DataSheetCell => ({ status: 'not_available', value: null, evidence: [], note, updatedAt: NOW });
  // deterministic transient failures so batch UI shows ⚠ states
  if (hash(org + q) % 23 === 0) return { status: 'failed', value: null, evidence: [], note: 'A source did not respond. Retry to research this cell again.', updatedAt: NOW };

  if (/founder|grunnlegger/.test(q)) {
    const f = p.people.people.find((x) => x.roleGroup === 'founder');
    return f ? done(f.name, f.name, f.fact.evidence, 'roles') : na('Founder not verified in searched permitted sources.');
  }
  if (/chair|styreleder/.test(q)) {
    const c = p.people.people.find((x) => x.role === 'Chair of the board' && x.current);
    return c ? done(c.name, c.name, c.fact.evidence, 'roles') : na();
  }
  if (/ceo|chief executive|daglig leder|managing director|who runs/.test(q)) {
    const c = p.people.people.find((x) => x.role === 'CEO' && x.current);
    return c ? done(c.name, c.name, c.fact.evidence, 'roles', c.fact.evidenceState) : na();
  }
  if (/international|abroad|outside norway|expan/.test(q)) {
    const sub = p.relationships.find((r) => r.kind === 'subsidiary' && /AB|GmbH|Ltd|ApS/.test(r.entity.name));
    return sub
      ? done(true, `Yes — ${sub.entity.name}`, sub.evidence, 'announcements', 'primary')
      : { status: 'verified', value: false, display: 'No evidence found', evidence: p.identity.registeredAddress?.evidence ?? [], evidenceState: 'primary', sourceName: src('brreg'), note: 'No foreign subsidiaries or foreign workplaces found in the searched sources (last 12 months).', updatedAt: NOW };
  }
  if (/linkedin/.test(q)) {
    if (spec.linkedinBlocked) return { status: 'blocked', value: null, evidence: [], note: 'Source access blocked. LinkedIn refused automated access.', updatedAt: NOW };
    const s = p.website.social.find((x) => x.network === 'linkedin');
    return s ? done(s.url, s.handle ?? s.url, s.fact.evidence, `web-${org}`) : na();
  }
  if (/margin|profitab/.test(q)) {
    const m = p.financials.ratios.find((r) => r.key === 'operating_margin');
    return m ? done(m.value, `${m.value.toFixed(1)}% · ${m.period}`, p.financials.series[0].points.at(-1)!.fact.evidence, 'accounts') : na('Insufficient financial data to compute.');
  }
  if (/revenue|turnover|omsetning/.test(q)) return cellFor(org, 'revenue');
  if (/employee|headcount|ansatte|staff/.test(q)) return cellFor(org, 'employees');
  if (/hiring|job|opening|recruit/.test(q)) return cellFor(org, 'hiring');
  if (/website|domain|url/.test(q)) return cellFor(org, 'website');
  if (/founded|incorporat|established|year/.test(q)) {
    const f = p.identity.founded!;
    return done(f.value!, f.value!.slice(0, 4), f.evidence, 'brreg');
  }
  if (/office|location|workplace|sites?/.test(q)) {
    const locs = [...new Set(p.locations.locations.filter((l) => l.verified).map((l) => l.municipality))];
    return done(locs.length, locs.join(', '), p.locations.locations.flatMap((l) => l.fact.evidence).slice(0, 3), 'brreg');
  }
  if (/industry|nace|sector/.test(q)) {
    const f = p.identity.industry!;
    return done(f.value!, f.value!, f.evidence, 'brreg');
  }
  if (/address|hq|headquarter/.test(q)) {
    const f = p.identity.headquarters ?? p.identity.registeredAddress!;
    return done(f.value!, f.value!, f.evidence, 'brreg');
  }
  return na('The research instruction could not be answered from permitted public sources for this company.');
}

function rowFor(org: string): DataSheetRow {
  const p = fullProfile(org);
  return {
    id: `row-${org}`,
    company: { orgNumber: org, legalName: p.company.legalName, municipality: p.company.municipality, industry: p.company.industry, website: p.company.website },
    cells: {},
  };
}

function makeSheet(id: string, title: string, orgs: string[], description: string, criteria: DataSheet['criteria'], updatedAt: string, opts: { pendingUnresearched?: boolean } = {}): DataSheet {
  const columns = STANDARD_COLUMNS.map((c) => ({ ...c }));
  const rows = orgs.map((org) => {
    const row = rowFor(org);
    for (const col of columns) {
      if (col.kind === 'identity') continue;
      const registryCol = col.id === 'revenue' || col.id === 'employees' || col.id === 'filing';
      row.cells[col.id] = opts.pendingUnresearched && !researched.has(org) && !registryCol ? { status: 'pending', value: null, evidence: [] } : cellFor(org, col.id);
    }
    return row;
  });
  return { id, title, description, criteria, columns, rows, rowCount: rows.length, columnCount: columns.length, updatedAt };
}

export function seedSheets() {
  if (sheets.size) return;
  const tech = ALL_SPECS.filter((s) => s.sector === 'saas' || s.sector === 'software' || s.sector === 'data').map((s) => s.org);
  sheets.set(
    'sheet-saas',
    makeSheet(
      'sheet-saas',
      'Norwegian SaaS & software companies',
      tech,
      'Software publishers, programming and data companies registered in Norway.',
      [
        { key: 'location', label: 'Country', value: 'Norway', display: 'Norway' },
        { key: 'industry', label: 'Industry', value: 'software', display: 'Software & SaaS' },
      ],
      '2026-10-02T12:00:00Z',
      { pendingUnresearched: true },
    ),
  );
  const health = ALL_SPECS.filter((s) => s.sector === 'healthtech' || s.sector === 'medtech').map((s) => s.org);
  const hs = makeSheet(
    'sheet-health',
    'Health technology — Norway',
    health,
    'Healthcare software and medical device companies.',
    [{ key: 'industry', label: 'Industry', value: 'healthcare', display: 'Healthcare technology' }],
    '2026-09-30T09:00:00Z',
  );
  // AI column already researched
  const col: DataSheetColumn = { id: 'ai-intl', title: 'International expansion (12 mo.)', kind: 'ai', valueType: 'text', width: 230, instruction: 'Identify whether the company expanded internationally in the last 12 months.' };
  hs.columns.push(col);
  hs.columnCount += 1;
  for (const r of hs.rows) r.cells[col.id] = cellFor(r.company.orgNumber, col.id, col.instruction);
  sheets.set('sheet-health', hs);
  sheets.set(
    'sheet-universe',
    makeSheet('sheet-universe', 'Company universe (all demo companies)', ALL_SPECS.map((s) => s.org), 'Every company in the demo dataset. Useful for testing large sheets.', [], '2026-09-20T08:00:00Z'),
  );
}

export function newSheet(id: string, title: string, orgs: string[], criteria: DataSheet['criteria'], description?: string) {
  const s = makeSheet(id, title, orgs, description ?? '', criteria, NOW, { pendingUnresearched: true });
  sheets.set(id, s);
  return s;
}

/* ============================== Watchlist ============================== */

export const watch = {
  orgs: new Set<string>(),
  lastCheckedAt: '2026-09-26T08:00:00Z',
  seen: new Set<string>(),
};

export function seedWatch() {
  if (watch.orgs.size) return;
  const base = [NORDVIK.org, '918877231', '914552108', '925116702', '922781540', '996450218', '919340066', '927004418'];
  const gen = ALL_SPECS.filter((s) => s.changes.length && !base.includes(s.org)).slice(0, 12).map((s) => s.org);
  const more = ALL_SPECS.filter((s) => !base.includes(s.org) && !gen.includes(s.org) && s.researchedAt).slice(0, 5).map((s) => s.org);
  for (const o of [...base, ...gen, ...more]) watch.orgs.add(o);
}

export function signalsFor(org: string): Signal[] {
  const p = fullProfile(org);
  const kindOf = (cat: string): Signal['kind'] =>
    cat === 'financial' ? 'financial' : cat === 'leadership' ? 'leadership' : cat === 'hiring' ? 'hiring' : cat === 'location' || cat === 'address' ? 'location' : cat === 'employees' ? 'financial' : 'announcement';
  const sig: Signal[] = p.changes.changes
    .filter((c) => c.detectedAt >= '2026-09-01')
    .map((c) => ({
      id: `sig-${c.id}`,
      kind: kindOf(c.category),
      orgNumber: org,
      companyName: p.company.legalName,
      title: c.previous ? `${c.label}: ${c.previous} → ${c.current}` : `${c.label}: ${c.current}`,
      detectedAt: c.detectedAt,
      evidence: c.evidence,
    }));
  for (const e of p.activity.events.filter((e) => e.type === 'filing' && e.date >= '2026-06-01'))
    sig.push({ id: `sig-${e.id}`, kind: 'filing', orgNumber: org, companyName: p.company.legalName, title: e.title, detectedAt: `${e.date}T12:00:00Z`, evidence: e.evidence });
  return sig.sort((a, b) => b.detectedAt.localeCompare(a.detectedAt));
}

export function watchItems(): WatchlistItem[] {
  return [...watch.orgs].map((org) => ({
    company: profileFor(org).company,
    addedAt: '2026-08-01T08:00:00Z',
    lastCheckedAt: watch.lastCheckedAt,
    signals: signalsFor(org).filter((s) => s.detectedAt > watch.lastCheckedAt && !watch.seen.has(s.id)),
  }));
}

/* ============================== Research runs ============================== */

export interface MockRun {
  run: ResearchRun;
  script: { delay: number; event: ResearchEvent }[];
  delivered: number;
}
export const runs = new Map<string, MockRun>();
