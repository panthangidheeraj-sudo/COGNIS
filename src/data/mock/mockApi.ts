/**
 * MOCK BACKEND — implements the full CognisApi contract in the browser.
 * Enabled when VITE_API_MODE=mock (the default). Swap to the live backend by
 * setting VITE_API_MODE=live; no UI code changes are needed.
 */
import type { CognisApi } from '@/api/contract';
import { ApiError, type StreamHandlers } from '@/api/http';
import { formatDate } from '@/utils/format';
import type {
  ArtifactSummary,
  BatchStatus,
  ColumnPreview,
  ColumnValueType,
  CompanySummary,
  Comparison,
  ComparisonRow,
  ContinueResearchAssessment,
  DataSheet,
  DataSheetColumn,
  DataSheetSummary,
  DiscoverFilters,
  DiscoverQuery,
  DiscoverResult,
  ExportRequest,
  ExportResult,
  Fact,
  InterpretedFilter,
  LibraryQuery,
  QueryInterpretation,
  ResearchEvent,
  ResearchRun,
  SearchResult,
  SheetEvent,
  SignalFeedGroup,
  SystemStatus,
  Watchlist,
} from '@/types';
import { ALL_SPECS, SECTOR_KEYWORDS } from './companies';
import { MUNICIPALITIES } from './geo';
import { NOW } from './profileBuilder';
import { answerFromProfile } from './answers';
import { briefFromProfile, explainFromProfile } from './briefs';
import { buildScript, planFor } from './researchScript';
import {
  STANDARD_COLUMNS,
  VERSIONS,
  allSummaries,
  artifactMeta,
  cellFor,
  companyArtifact,
  extraArtifacts,
  fullProfile,
  invalidateSummaries,
  markResearched,
  matchesIndustry,
  newSheet,
  profileFor,
  reports,
  researched,
  runs,
  seedReports,
  seedSheets,
  seedWatch,
  sheets,
  signalsFor,
  specsByOrg,
  versionProfile,
  watch,
  watchItems,
} from './store';

/* ------------------------------ helpers ------------------------------ */
type DistOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;
const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(t);
      reject(new DOMException('Aborted', 'AbortError'));
    });
  });
const latency = (base = 180, signal?: AbortSignal) => sleep(base + Math.random() * 160, signal);
const clone = <T>(x: T): T => structuredClone(x);
const nowIso = () => new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
const M = 1_000_000;

function seed() {
  seedReports();
  seedSheets();
  seedWatch();
}

/* ------------------------------ interpretation ------------------------------ */
const INDUSTRY_TERMS: { re: RegExp; value: string; display: string }[] = [
  { re: /\bsaas\b/i, value: 'saas', display: 'SaaS' },
  { re: /\bfintech|payments?\b/i, value: 'fintech', display: 'Fintech' },
  { re: /\bmedtech|medical devices?\b/i, value: 'medtech', display: 'Medtech' },
  { re: /\bhealth ?care|health ?tech|\bhealth\b/i, value: 'healthcare', display: 'Healthcare' },
  { re: /\bsoftware\b/i, value: 'software', display: 'Software' },
  { re: /\btech(nology)?\b/i, value: 'technology', display: 'Technology' },
  { re: /\blogistics|freight|transport\b/i, value: 'logistics', display: 'Logistics' },
  { re: /\benergy|power|renewable\b/i, value: 'energy', display: 'Energy' },
  { re: /\bseafood|aquaculture|salmon\b/i, value: 'seafood', display: 'Seafood & aquaculture' },
  { re: /\bmaritime|shipping\b/i, value: 'maritime', display: 'Maritime' },
  { re: /\bconstruction|real estate\b/i, value: 'construction', display: 'Construction' },
  { re: /\bconsult(ing|ancy)\b/i, value: 'consulting', display: 'Consulting' },
  { re: /\bdata|analytics\b/i, value: 'data', display: 'Data & analytics' },
];

function parseAmount(num: string, unit?: string) {
  const n = parseFloat(num.replace(/,/g, ''));
  const u = (unit ?? '').toLowerCase();
  if (u.startsWith('b')) return n * 1000 * M;
  if (u.startsWith('m') || u === '') return n * M;
  return n;
}

export function interpretText(text: string): QueryInterpretation {
  const t = ` ${text} `;
  const filters: InterpretedFilter[] = [];
  const notes: string[] = [];
  for (const m of MUNICIPALITIES) {
    if (new RegExp(`\\b${m.name}\\b`, 'i').test(t)) {
      filters.push({ key: 'location', label: 'Location', value: m.name, display: m.name });
      break;
    }
  }
  const ind = INDUSTRY_TERMS.find((i) => i.re.test(t));
  if (ind) filters.push({ key: 'industry', label: 'Industry', value: ind.value, display: ind.display });
  const emp = t.match(/(?:over|more than|above|at least|>)\s*([\d,]+)\s*(?:employees|people|staff|ansatte)/i) ?? t.match(/([\d,]+)\+\s*(?:employees|people)/i);
  if (emp) filters.push({ key: 'employeesMin', label: 'Employees', value: parseInt(emp[1].replace(/,/g, ''), 10), display: `> ${emp[1]}` });
  const empMax = t.match(/(?:under|fewer than|less than|below|<)\s*([\d,]+)\s*(?:employees|people|staff)/i);
  if (empMax) filters.push({ key: 'employeesMax', label: 'Employees', value: parseInt(empMax[1].replace(/,/g, ''), 10), display: `< ${empMax[1]}` });
  const rev = t.match(/revenue\s+(?:above|over|of more than|more than|exceeding|>)\s*(?:nok\s*)?([\d.,]+)\s*(m|mill|million|mnok|b|bn|billion)?/i);
  if (rev) {
    const v = parseAmount(rev[1], rev[2]);
    filters.push({ key: 'revenueMin', label: 'Revenue', value: v, display: `> NOK ${v >= 1e9 ? `${v / 1e9}B` : `${v / 1e6}M`}` });
  }
  if (/\bhiring|recruiting|open (?:positions|roles)|job openings\b/i.test(t)) {
    filters.push({ key: 'hiring', label: 'Hiring', value: true, display: 'Current openings' });
    const role = t.match(/hiring\s+([a-z ]+?)(?:\s+in\b|\s*$|,)/i);
    if (role && role[1].trim() && !/^(now|currently)$/i.test(role[1].trim()))
      notes.push(`Role-level filtering (“${role[1].trim()}”) is not supported yet; showing companies with any verified current openings.`);
  }
  if (/\bnew (?:offices?|locations?|workplaces?)\b|\bexpanded\b|\bopened\b/i.test(t))
    filters.push({ key: 'recentActivity', label: 'Recent activity', value: true, display: 'New locations · last 12 months' });
  const founded = t.match(/founded (?:after|since) (\d{4})/i);
  if (founded) filters.push({ key: 'foundedAfter', label: 'Founded', value: parseInt(founded[1], 10), display: `after ${founded[1]}` });
  if (/\bactive companies\b|\bonly active\b/i.test(t)) filters.push({ key: 'status', label: 'Status', value: 'active', display: 'Active' });
  if (/\bnorw(ay|egian)\b/i.test(t) && !filters.some((f) => f.key === 'location')) notes.push('Country: Norway (all companies in this dataset are Norwegian).');
  return { original: text, filters, keywords: filters.length ? undefined : text.trim(), notes: notes.length ? notes : undefined };
}

function filtersFrom(list: InterpretedFilter[]): DiscoverFilters {
  const f: DiscoverFilters = {};
  for (const i of list) (f as Record<string, unknown>)[i.key] = i.value;
  return f;
}

function applyFilters(items: CompanySummary[], f: DiscoverFilters): CompanySummary[] {
  return items.filter((c) => {
    if (f.location && c.municipality?.toLowerCase() !== String(f.location).toLowerCase() && c.county?.toLowerCase() !== String(f.location).toLowerCase()) return false;
    if (f.municipality && c.municipality?.toLowerCase() !== f.municipality.toLowerCase()) return false;
    if (f.industry && !industryMatch(c.orgNumber, f.industry)) return false;
    if (f.status && c.status !== f.status) return false;
    if (f.employeesMin != null && (c.employees ?? -1) <= f.employeesMin) return false;
    if (f.employeesMax != null && (c.employees ?? Infinity) >= f.employeesMax) return false;
    if (f.revenueMin != null && (c.revenue?.value ?? -1) <= f.revenueMin) return false;
    if (f.revenueMax != null && (c.revenue?.value ?? Infinity) >= f.revenueMax) return false;
    if (f.hiring && !((c.openPositions ?? 0) > 0)) return false;
    if (f.coverageMin != null && c.coverage.complete < f.coverageMin) return false;
    if (f.recentActivity && !fullProfile(c.orgNumber).activity.events.some((e) => e.type === 'location' && e.date >= '2025-10-03')) return false;
    if (f.foundedAfter != null && parseInt(specsByOrg.get(c.orgNumber)!.founded.slice(0, 4), 10) <= f.foundedAfter) return false;
    return true;
  });
}

function industryMatch(org: string, term: string) {
  const t = term.toLowerCase();
  const sector = specsByOrg.get(org)?.sector;
  if (!sector) return false;
  if (t === sector) return true;
  if (t === 'healthcare') return sector === 'healthtech' || sector === 'medtech';
  if (t === 'technology') return ['saas', 'software', 'healthtech', 'fintech', 'data'].includes(sector);
  if (t === 'software') return ['saas', 'software', 'healthtech'].includes(sector);
  return SECTOR_KEYWORDS[sector].includes(t) || matchesIndustry(org, t);
}

function keywordMatch(c: CompanySummary, kw: string) {
  const k = kw.toLowerCase().trim();
  const digits = k.replace(/\s/g, '');
  if (/^\d{3,9}$/.test(digits)) return c.orgNumber.includes(digits);
  return (
    c.legalName.toLowerCase().includes(k) ||
    (c.municipality ?? '').toLowerCase().includes(k) ||
    (c.industry?.description ?? '').toLowerCase().includes(k) ||
    k.split(/\s+/).every((w) => c.legalName.toLowerCase().includes(w))
  );
}

/* ------------------------------ library summaries ------------------------------ */
function companySummaryArtifact(org: string): ArtifactSummary {
  const a = companyArtifact(org);
  const meta = artifactMeta.get(a.id);
  const rev = a.profile.financials.series.find((s) => s.key === 'revenue');
  return {
    id: a.id,
    type: 'company',
    title: a.title,
    subtitle: a.profile.company.industry?.description,
    orgNumber: org,
    municipality: a.profile.company.municipality,
    updatedAt: a.updatedAt,
    researchedAt: a.profile.company.lastResearchedAt ?? undefined,
    viewedAt: meta?.viewedAt,
    coverage: a.profile.company.coverage,
    tags: a.tags,
    pinned: a.pinned,
    archived: meta?.archived ?? false,
    changeCount: a.profile.company.changeCount,
    openPositions: a.profile.company.openPositions,
    sparkline: rev?.points.map((p) => p.fact.value!) ?? undefined,
  };
}
function sheetSummaryArtifact(s: DataSheet): ArtifactSummary {
  const meta = artifactMeta.get(s.id);
  return {
    id: s.id,
    type: 'data_sheet',
    title: meta?.title ?? s.title,
    subtitle: `${s.rowCount} companies · ${s.columns.length} columns`,
    updatedAt: s.updatedAt,
    tags: meta?.tags ?? [],
    pinned: meta?.pinned ?? s.id === 'sheet-saas',
    archived: meta?.archived ?? false,
    targetId: s.id,
    itemCount: s.rowCount,
  };
}
function allArtifacts(): ArtifactSummary[] {
  seed();
  const comp = [...researched].filter((o) => specsByOrg.has(o)).map(companySummaryArtifact);
  const reps: ArtifactSummary[] = reports.map((r) => {
    const meta = artifactMeta.get(r.id);
    return {
      id: r.id,
      type: 'report',
      title: meta?.title ?? r.title,
      subtitle: r.kind === 'company_brief' ? 'Company brief' : 'Deep research report',
      orgNumber: r.orgNumber,
      updatedAt: r.updatedAt,
      tags: meta?.tags ?? r.tags,
      pinned: meta?.pinned ?? r.pinned,
      archived: meta?.archived ?? false,
      coverage: r.profile.company.coverage,
    };
  });
  const sh = [...sheets.values()].map(sheetSummaryArtifact);
  const extra = extraArtifacts.map((a) => {
    const meta = artifactMeta.get(a.id);
    const base = a.type === 'watchlist' ? { ...a, itemCount: watch.orgs.size, changeCount: watchItems().filter((i) => i.signals.length).length } : a;
    return { ...base, title: meta?.title ?? base.title, tags: meta?.tags ?? base.tags, pinned: meta?.pinned ?? base.pinned, archived: meta?.archived ?? base.archived };
  });
  return [...comp, ...reps, ...sh, ...extra];
}

/* ------------------------------ export builder ------------------------------ */
function csvEscape(v: unknown) {
  const s = v == null ? '' : String(v);
  return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
function toCsv(rows: Record<string, unknown>[]) {
  if (!rows.length) return '';
  const cols = Object.keys(rows[0]);
  return [cols.join(','), ...rows.map((r) => cols.map((c) => csvEscape(r[c])).join(','))].join('\n');
}
function factRows(facts: Fact[], opts: ExportRequest['options'], sourceName: (id: string) => string) {
  return facts.map((f) => {
    const e = f.evidence[0];
    const row: Record<string, unknown> = { field: f.field, label: f.label, value: f.value ?? '', unit: f.unit ?? '', status: f.status, evidence_state: f.evidenceState };
    if (opts.reportingPeriods) row.reporting_period = f.reportingPeriod ?? '';
    row.source = e ? sourceName(e.sourceId) : '';
    if (opts.retrievalDates) row.retrieved_at = e?.retrievedAt ?? '';
    if (opts.sourceLinks) row.source_url = e?.url ?? '';
    if (opts.evidence) row.evidence_excerpt = e?.excerpt ?? '';
    return row;
  });
}

/* ------------------------------ research stream ------------------------------ */
const sheetSubs = new Map<string, (e: SheetEvent) => void>();
const sheetSeq = new Map<string, number>();
const sheetTimers = new Map<string, ReturnType<typeof setTimeout>>();

function runSheetBatch(id: string) {
  const s = sheets.get(id)!;
  const targets: { rowId: string; columnId: string }[] = [];
  for (const r of s.rows) for (const c of s.columns) if (c.kind !== 'identity' && ['pending', 'failed'].includes(r.cells[c.id]?.status ?? 'pending')) targets.push({ rowId: r.id, columnId: c.id });
  const batch: BatchStatus = { runId: `batch-${Date.now()}`, state: targets.length ? 'running' : 'completed', total: targets.length, done: 0, running: 0, pending: targets.length, failed: 0, errors: [], sourceUsage: [] };
  s.batch = batch;
  const usage = new Map<string, number>();
  const emit = (e: DistOmit<SheetEvent, 'seq'>) => {
    const seq = (sheetSeq.get(id) ?? 0) + 1;
    sheetSeq.set(id, seq);
    sheetSubs.get(id)?.({ ...e, seq } as SheetEvent);
  };
  const CONC = 6;
  let i = 0;
  const startCell = (k: number) => {
    const t = targets[k];
    if (!t) return;
    const row = s.rows.find((r) => r.id === t.rowId)!;
    row.cells[t.columnId] = { status: 'researching', value: null, evidence: [] };
    batch.running += 1;
    batch.pending -= 1;
    emit({ type: 'cell.updated', rowId: t.rowId, columnId: t.columnId, cell: clone(row.cells[t.columnId]) });
  };
  for (let k = 0; k < Math.min(CONC, targets.length); k++) startCell(k);
  const tick = () => {
    if (i >= targets.length) {
      batch.state = 'completed';
      batch.running = 0;
      s.updatedAt = nowIso();
      emit({ type: 'batch.completed', batch: clone(batch) });
      sheetTimers.delete(id);
      return;
    }
    const t = targets[i];
    const row = s.rows.find((r) => r.id === t.rowId)!;
    const col = s.columns.find((c) => c.id === t.columnId)!;
    const cell = cellFor(row.company.orgNumber, col.id, col.instruction);
    row.cells[t.columnId] = cell;
    batch.running -= 1;
    if (cell.status === 'failed') {
      batch.failed += 1;
      batch.errors.push({ rowId: t.rowId, columnId: t.columnId, message: cell.note ?? 'Failed' });
    } else batch.done += 1;
    if (cell.sourceName) usage.set(cell.sourceName, (usage.get(cell.sourceName) ?? 0) + 1);
    batch.sourceUsage = [...usage.entries()].map(([sourceName, calls]) => ({ sourceName, calls })).sort((a, b) => b.calls - a.calls);
    batch.etaSeconds = Math.ceil(((targets.length - i - 1) * 70) / 1000);
    emit({ type: 'cell.updated', rowId: t.rowId, columnId: t.columnId, cell: clone(cell) });
    startCell(i + CONC);
    i += 1;
    if (i % 4 === 0 || i === targets.length) emit({ type: 'batch.progress', batch: clone(batch) });
    sheetTimers.set(id, setTimeout(tick, 55 + Math.random() * 40));
  };
  sheetTimers.set(id, setTimeout(tick, 300));
  return batch;
}

/* ============================== The API ============================== */
let runCounter = 0;
let reportCounter = 0;
let sheetCounter = 0;
let colCounter = 0;

export const mockApi: CognisApi = {
  system: {
    async status(): Promise<SystemStatus> {
      await latency(120);
      return {
        mode: 'mock',
        backend: 'connected',
        research: 'online',
        version: '0.1.0 · mock backend',
        checkedAt: nowIso(),
        sources: [
          { name: 'Brønnøysundregistrene', kind: 'registry', status: 'available' },
          { name: 'Regnskapsregisteret', kind: 'financial', status: 'available' },
          { name: 'arbeidsplassen.nav.no', kind: 'jobs', status: 'available' },
          { name: 'Doffin', kind: 'regulatory', status: 'degraded', note: 'Intermittent timeouts' },
          { name: 'Company websites', kind: 'website', status: 'available', note: 'Some sites block automated access' },
          { name: 'LinkedIn', kind: 'people', status: 'degraded', note: 'Blocks automated access for some companies' },
          { name: 'Proff.no', kind: 'financial', status: 'available' },
          { name: 'Web search', kind: 'web', status: 'available' },
        ],
        capabilities: {
          exports: ['csv', 'json'],
          pdfReports: false,
          pauseResearch: false,
          cancelResearch: true,
          watchlist: true,
          versions: true,
          archive: true,
          tags: true,
          share: false,
          discoverFilters: [
            { key: 'location', label: 'Location', type: 'select', options: MUNICIPALITIES.map((m) => ({ value: m.name, label: m.name })) },
            {
              key: 'industry',
              label: 'Industry',
              type: 'select',
              options: INDUSTRY_TERMS.map((i) => ({ value: i.value, label: i.display })),
            },
            { key: 'status', label: 'Company status', type: 'select', options: [{ value: 'active', label: 'Active' }, { value: 'under_liquidation', label: 'Under liquidation' }, { value: 'bankruptcy', label: 'Bankruptcy' }] },
            { key: 'employeesMin', label: 'Employees, more than', type: 'number' },
            { key: 'revenueMin', label: 'Revenue, more than', type: 'number', unit: 'NOK' },
            { key: 'hiring', label: 'Has verified current openings', type: 'boolean' },
            { key: 'coverageMin', label: 'Minimum coverage (areas)', type: 'number' },
            { key: 'recentActivity', label: 'New locations in last 12 months', type: 'boolean' },
          ],
        },
      };
    },
  },

  search: {
    async global(query: string, signal?: AbortSignal): Promise<SearchResult> {
      await latency(140, signal);
      seed();
      const q = query.trim();
      const ql = q.toLowerCase();
      const all = allSummaries();
      const companies = all
        .filter((c) => keywordMatch(c, q))
        .sort((a, b) => Number(b.legalName.toLowerCase().startsWith(ql)) - Number(a.legalName.toLowerCase().startsWith(ql)) || (b.revenue?.value ?? 0) - (a.revenue?.value ?? 0))
        .slice(0, 6);
      const arts = allArtifacts().filter((a) => !a.archived && (a.title.toLowerCase().includes(ql) || (a.orgNumber ?? '').includes(ql.replace(/\s/g, ''))));
      const interp = interpretText(q);
      const digits = q.replace(/\s/g, '');
      let intent: SearchResult['intent'] = { kind: 'mixed' };
      if (/^\d{9}$/.test(digits) && specsByOrg.has(digits)) intent = { kind: 'company', orgNumber: digits };
      else if (interp.filters.length) intent = { kind: 'discover', text: q };
      else if (companies.length === 1 && q.length > 3) intent = { kind: 'company', orgNumber: companies[0].orgNumber };
      return clone({
        query: q,
        intent,
        companies,
        artifacts: arts.filter((a) => a.type === 'company' || a.type === 'comparison').slice(0, 5),
        sheets: [...sheets.values()].filter((s) => s.title.toLowerCase().includes(ql)).slice(0, 4).map(sheetToSummary),
        reports: arts.filter((a) => a.type === 'report').slice(0, 3),
        savedSearches: extraArtifacts.filter((a) => a.type === 'saved_search' && a.title.toLowerCase().includes(ql)).map((a) => ({ id: a.id, title: a.title, query: a.targetId ?? a.title })),
      });
    },
  },

  companies: {
    async discover(query: DiscoverQuery, signal?: AbortSignal): Promise<DiscoverResult> {
      await latency(260, signal);
      let filters: DiscoverFilters = { ...query.filters };
      let interpretation: QueryInterpretation | undefined;
      let keywords = query.text?.trim();
      if (query.text && query.interpret) {
        interpretation = interpretText(query.text);
        filters = { ...filtersFrom(interpretation.filters), ...filters };
        keywords = interpretation.keywords;
      }
      let items = allSummaries();
      if (keywords) items = items.filter((c) => keywordMatch(c, keywords!));
      items = applyFilters(items, filters);
      const sorters: Record<DiscoverQuery['sort'], (a: CompanySummary, b: CompanySummary) => number> = {
        relevance: (a, b) =>
          Number(!!b.lastResearchedAt) - Number(!!a.lastResearchedAt) || (keywords ? Number(b.legalName.toLowerCase().startsWith(keywords.toLowerCase())) - Number(a.legalName.toLowerCase().startsWith(keywords.toLowerCase())) : 0) || (b.revenue?.value ?? 0) - (a.revenue?.value ?? 0),
        revenue: (a, b) => (b.revenue?.value ?? -1) - (a.revenue?.value ?? -1),
        employees: (a, b) => (b.employees ?? -1) - (a.employees ?? -1),
        name: (a, b) => a.legalName.localeCompare(b.legalName, 'nb'),
        researched: (a, b) => (b.lastResearchedAt ?? '').localeCompare(a.lastResearchedAt ?? ''),
        hiring: (a, b) => (b.openPositions ?? -1) - (a.openPositions ?? -1),
      };
      items = [...items].sort(sorters[query.sort]);
      const start = (query.page - 1) * query.pageSize;
      return clone({ items: items.slice(start, start + query.pageSize), total: items.length, page: query.page, pageSize: query.pageSize, interpretation, appliedFilters: filters });
    },
    async interpret(text: string, signal?: AbortSignal) {
      await latency(220, signal);
      return interpretText(text);
    },
    async get(orgNumber: string) {
      await latency(260);
      const org = orgNumber.replace(/\s/g, '');
      if (!specsByOrg.has(org)) throw new ApiError('not_found', `No company with organization number ${orgNumber} was found in the registry.`, 404);
      const meta = artifactMeta.get(`art-${org}`) ?? { title: '', tags: [], pinned: false, archived: false };
      artifactMeta.set(`art-${org}`, { ...meta, title: meta.title || fullProfile(org).company.legalName, viewedAt: nowIso() });
      return clone(profileFor(org));
    },
    async recent() {
      await latency(160);
      return clone(
        allSummaries()
          .filter((c) => c.lastResearchedAt)
          .sort((a, b) => b.lastResearchedAt!.localeCompare(a.lastResearchedAt!))
          .slice(0, 6),
      );
    },
    async brief(orgNumber) {
      await latency(650);
      const org = orgNumber.replace(/\s/g, '');
      if (!specsByOrg.has(org)) throw new ApiError('not_found', 'Company not found.', 404);
      return clone(briefFromProfile(profileFor(org)));
    },
    async explain(orgNumber, subject, opts) {
      await latency(opts?.fresh ? 1600 : 900);
      const org = orgNumber.replace(/\s/g, '');
      const spec = specsByOrg.get(org);
      if (!spec) throw new ApiError('not_found', 'Company not found.', 404);
      const ex = explainFromProfile(profileFor(org), spec, subject);
      return clone(opts?.fresh ? { ...ex, origin: 'fresh_research' as const } : ex);
    },
  },

  research: {
    async start(input) {
      await latency(300);
      let org = input.orgNumber?.replace(/\s/g, '');
      const q = input.query.trim();
      if (!org) {
        const digits = q.replace(/\s/g, '');
        if (/^\d{9}$/.test(digits)) org = specsByOrg.has(digits) ? digits : undefined;
        else {
          const ql = q.toLowerCase().replace(/^research\s+/, '');
          const matches = ALL_SPECS.filter((s) => s.name.toLowerCase().includes(ql) || ql.includes(s.name.toLowerCase().replace(/ as$| asa$/, '')));
          if (matches.length > 1) {
            const run: ResearchRun = {
              id: `run-${++runCounter}`,
              query: q,
              prompt: input.prompt,
              mode: input.mode,
              status: 'ambiguous',
              ambiguity: {
                query: q,
                candidates: matches.map((m) => profileFor(m.org).company),
                message: 'We found possible matches, but could not establish exact-company identity.',
              },
              plan: planFor(input.mode),
              startedAt: nowIso(),
              capabilities: { pause: false, cancel: false, retryFailed: false, editPlan: false },
              autoSaved: false,
            };
            runs.set(run.id, { run, script: [], delivered: 0 });
            return clone(run);
          }
          org = matches[0]?.org;
        }
      }
      if (!org || !specsByOrg.has(org)) throw new ApiError('not_found', `No Norwegian company matched “${q}”. Try the full legal name or the 9-digit organization number.`, 404);
      const plan = planFor(input.mode, input.stepKeys);
      const run: ResearchRun = {
        id: `run-${++runCounter}`,
        query: q,
        prompt: input.prompt,
        mode: input.mode,
        status: plan.requiresConfirmation ? 'awaiting_confirmation' : 'running',
        company: profileFor(org).company,
        plan,
        startedAt: nowIso(),
        capabilities: { pause: false, cancel: true, retryFailed: true, editPlan: true },
        autoSaved: false,
      };
      runs.set(run.id, { run, script: plan.requiresConfirmation ? [] : buildScript(run.id, org, plan, input), delivered: 0 });
      return clone(run);
    },
    async confirm(runId, stepKeys) {
      await latency(160);
      const r = runs.get(runId);
      if (!r || !r.run.company) throw new ApiError('not_found', 'Research run not found.', 404);
      r.run.plan = { ...planFor(r.run.mode, stepKeys), requiresConfirmation: false };
      r.run.status = 'running';
      r.script = buildScript(runId, r.run.company.orgNumber, r.run.plan, { query: r.run.query, prompt: r.run.prompt, mode: r.run.mode });
      return clone(r.run);
    },
    async get(runId) {
      await latency(80);
      const r = runs.get(runId);
      if (!r) throw new ApiError('not_found', 'Research run not found.', 404);
      return clone(r.run);
    },
    async pause() {
      throw new ApiError('invalid', 'Pausing research is not supported by this backend.', 400);
    },
    async cancel(runId) {
      await latency(100);
      const r = runs.get(runId);
      if (!r) throw new ApiError('not_found', 'Research run not found.', 404);
      const lastSeq = r.script[r.delivered - 1]?.event.seq ?? 0;
      r.script = r.script.slice(0, r.delivered);
      r.script.push({ delay: 50, event: { type: 'run.failed', seq: lastSeq + 1, runId, at: nowIso(), message: 'Research cancelled. Verified data gathered so far is kept.' } });
      r.run.status = 'cancelled';
      return clone(r.run);
    },
    async retryFailed(runId) {
      await latency(160);
      const r = runs.get(runId);
      if (!r || !r.run.company) throw new ApiError('not_found', 'Research run not found.', 404);
      const failed = r.script.filter((s) => s.event.type === 'step.failed').map((s) => (s.event as Extract<ResearchEvent, { type: 'step.failed' }>).stepId.replace('s-', ''));
      if (!failed.length) return clone(r.run);
      const lastSeq = r.script.at(-1)!.event.seq;
      r.script.push(...buildScript(runId, r.run.company.orgNumber, r.run.plan, { query: r.run.query, prompt: r.run.prompt, mode: r.run.mode }, lastSeq, failed));
      r.run.status = 'running';
      return clone(r.run);
    },
    stream(runId, handlers: StreamHandlers<ResearchEvent>, opts) {
      const r = runs.get(runId);
      let stopped = false;
      let timer: ReturnType<typeof setTimeout> | undefined;
      if (!r) {
        setTimeout(() => handlers.onError?.(new ApiError('not_found', 'Research run not found.', 404)), 0);
        return () => undefined;
      }
      let idx = r.script.findIndex((s) => s.event.seq > (opts?.lastSeq ?? 0));
      if (idx < 0) idx = r.script.length;
      setTimeout(() => handlers.onOpen?.(), 0);
      const step = () => {
        if (stopped) return;
        const item = r.script[idx];
        if (!item) {
          // wait for more events (e.g. after confirm / retry)
          timer = setTimeout(step, 250);
          return;
        }
        timer = setTimeout(() => {
          if (stopped) return;
          const ev = r.script[idx]?.event;
          if (!ev) return step();
          idx += 1;
          r.delivered = Math.max(r.delivered, idx);
          if (ev.type === 'run.completed' && r.run.company) {
            const org = r.run.company.orgNumber;
            const prevAt = r.run.company.lastResearchedAt;
            const at = nowIso();
            const artId = `art-${org}`;
            if (VERSIONS[artId]) {
              VERSIONS[artId][0].label = 'Update';
              VERSIONS[artId].unshift({ id: `v${VERSIONS[artId].length + 1}`, createdAt: at, label: 'Current' });
            } else if (prevAt && researched.has(org)) {
              VERSIONS[artId] = [
                { id: 'v2', createdAt: at, label: 'Current' },
                { id: 'v1', createdAt: prevAt, label: 'Previous research', spec: specsByOrg.get(org) },
              ];
            }
            markResearched(org, at);
            invalidateSummaries();
            r.run.status = 'completed';
            r.run.artifactId = artId;
            r.run.autoSaved = true;
          }
          if (ev.type === 'run.failed') r.run.status = r.run.status === 'cancelled' ? 'cancelled' : 'failed';
          handlers.onEvent(clone(ev));
          step();
        }, item.delay);
      };
      step();
      return () => {
        stopped = true;
        if (timer) clearTimeout(timer);
      };
    },
    async ask({ orgNumber, question, fresh }) {
      await latency(fresh ? 1400 : 500);
      if (!specsByOrg.has(orgNumber)) throw new ApiError('not_found', 'Company not found.', 404);
      return clone(answerFromProfile(profileFor(orgNumber), question, fresh ? 'fresh_research' : 'saved_evidence'));
    },
    async assess(artifactId): Promise<ContinueResearchAssessment> {
      await latency(400);
      const org = artifactId.replace('art-', '');
      const p = profileFor(org);
      const age = (Date.parse(NOW) - Date.parse(p.company.lastResearchedAt ?? NOW)) / 86400000;
      const days = Math.max(0, Math.round(age));
      const stale = age >= 14 ? 2 : age >= 3 ? 1 : 0;
      return {
        checkedAt: nowIso(),
        newFilings: stale === 2 ? 1 : 0,
        staleAreas: [
          { area: 'Hiring', reason: `Job listings last checked ${days} days ago` },
          { area: 'Recent activity', reason: 'Announcements and procurement not checked since last research' },
        ].slice(0, stale),
        changedSources: [
          { sourceId: 'nav', sourceName: 'arbeidsplassen.nav.no', detail: 'Listings changed since last check' },
          { sourceId: 'brreg', sourceName: 'Brønnøysundregistrene', detail: 'Registry record updated' },
          { sourceId: 'announcements', sourceName: 'Brønnøysundregistrene — announcements', detail: 'New announcement published' },
          { sourceId: 'accounts', sourceName: 'Regnskapsregisteret', detail: 'New filing available' },
        ].slice(0, stale * 2),
        missingFields: p.knowns.filter((k) => k.status === 'unknown').map((k) => k.label),
      };
    },
  },

  library: {
    async list(query: LibraryQuery, signal?: AbortSignal) {
      await latency(200, signal);
      const q = query.q?.toLowerCase().trim();
      let items = allArtifacts().filter((a) => (query.includeArchived ? true : !a.archived));
      if (query.tag) items = items.filter((a) => a.tags.includes(query.tag!));
      if (q) {
        const kw = q.replace(/\s/g, '');
        items = items.filter((a) => {
          const p = a.orgNumber ? specsByOrg.get(a.orgNumber) : undefined;
          return (
            a.title.toLowerCase().includes(q) ||
            (a.subtitle ?? '').toLowerCase().includes(q) ||
            (a.orgNumber ?? '').includes(kw) ||
            (a.municipality ?? '').toLowerCase().includes(q) ||
            a.tags.some((t) => t.toLowerCase().includes(q)) ||
            (p ? p.nace.description.toLowerCase().includes(q) || SECTOR_KEYWORDS[p.sector].includes(q) : false) ||
            (/hiring/.test(q) && (a.openPositions ?? 0) > 0)
          );
        });
      }
      // Per-type counts for the type filter (before the type filter is applied)
      const facets: Record<string, number> = { all: items.length };
      for (const it of items) facets[it.type] = (facets[it.type] ?? 0) + 1;
      if (query.type !== 'all') items = items.filter((a) => a.type === query.type);
      const sorters: Record<LibraryQuery['sort'], (a: ArtifactSummary, b: ArtifactSummary) => number> = {
        updated: (a, b) => b.updatedAt.localeCompare(a.updatedAt),
        researched: (a, b) => (b.researchedAt ?? '').localeCompare(a.researchedAt ?? ''),
        name: (a, b) => a.title.localeCompare(b.title, 'nb'),
        coverage: (a, b) => (b.coverage?.complete ?? -1) - (a.coverage?.complete ?? -1),
        changed: (a, b) => (b.changeCount ?? 0) - (a.changeCount ?? 0),
      };
      items.sort((a, b) => Number(b.pinned) - Number(a.pinned) || sorters[query.sort](a, b));
      const start = (query.page - 1) * query.pageSize;
      return clone({ items: items.slice(start, start + query.pageSize), total: items.length, page: query.page, pageSize: query.pageSize, facets });
    },
    async recent() {
      await latency(160);
      return clone(
        allArtifacts()
          .filter((a) => !a.archived && a.type !== 'watchlist')
          .sort((a, b) => (b.viewedAt ?? b.updatedAt).localeCompare(a.viewedAt ?? a.updatedAt))
          .slice(0, 8),
      );
    },
    async get(id: string) {
      await latency(260);
      seed();
      if (id.startsWith('art-')) {
        const org = id.slice(4);
        if (!researched.has(org)) throw new ApiError('not_found', 'This research artifact does not exist yet.', 404);
        return clone(companyArtifact(org));
      }
      const rep = reports.find((r) => r.id === id);
      if (rep) return clone(rep);
      throw new ApiError('not_found', 'Artifact not found.', 404);
    },
    async getVersion(id, versionId) {
      await latency(260);
      const a = companyArtifact(id.slice(4));
      const p = versionProfile(id, versionId);
      if (!p) throw new ApiError('not_found', 'Version not found.', 404);
      return clone({ ...a, versionId, profile: p });
    },
    async compareVersions(id, fromId, toId) {
      await latency(300);
      const a = companyArtifact(id.slice(4));
      const from = versionProfile(id, fromId);
      const to = versionProfile(id, toId);
      if (!from || !to) throw new ApiError('not_found', 'Version not found.', 404);
      const metric = (p: typeof from, field: string) => {
        const f = p.keyMetrics.find((k) => k.field === field);
        return f?.value == null ? null : String(f.value);
      };
      const ceo = (p: typeof from) => p.people.people.find((x) => x.role === 'CEO' && x.current)?.name ?? null;
      const rev = (p: typeof from) => {
        const pt = p.financials.series.find((s) => s.key === 'revenue')?.points.at(-1);
        return pt ? `NOK ${(pt.fact.value! / 1e6).toFixed(1)}M (${pt.period})` : null;
      };
      const rows = [
        { key: 'employees', label: 'Employees', from: metric(from, 'overview.employees'), to: metric(to, 'overview.employees') },
        { key: 'locations', label: 'Locations', from: metric(from, 'overview.locations'), to: metric(to, 'overview.locations') },
        { key: 'jobs', label: 'Open jobs', from: metric(from, 'overview.openPositions'), to: metric(to, 'overview.openPositions') },
        { key: 'ceo', label: 'CEO', from: ceo(from), to: ceo(to) },
        { key: 'revenue', label: 'Latest revenue', from: rev(from), to: rev(to) },
        { key: 'coverage', label: 'Coverage', from: `${from.company.coverage.complete}/5 areas`, to: `${to.company.coverage.complete}/5 areas` },
        { key: 'events', label: 'Recorded events', from: String(from.activity.events.length), to: String(to.activity.events.length) },
      ].map((r) => ({ ...r, changed: r.from !== r.to }));
      const v = (vid: string) => a.versions.find((x) => x.id === vid)!;
      return clone({ artifactId: id, from: v(fromId), to: v(toId), rows });
    },
    async update(id, patch) {
      await latency(140);
      const all = allArtifacts();
      const cur = all.find((a) => a.id === id);
      if (!cur) throw new ApiError('not_found', 'Artifact not found.', 404);
      const meta = artifactMeta.get(id) ?? { title: cur.title, tags: cur.tags, pinned: cur.pinned, archived: cur.archived };
      artifactMeta.set(id, { ...meta, ...patch });
      if (patch.title && sheets.has(id)) sheets.get(id)!.title = patch.title;
      return clone(allArtifacts().find((a) => a.id === id)!);
    },
    async duplicate() {
      throw new ApiError('invalid', 'Duplicating artifacts is not supported by this backend.', 400);
    },
    async capabilities() {
      return { rename: true, duplicate: false, tag: true, archive: true, delete: false, refresh: true, export: true, pin: true };
    },
    async saveRun(runId) {
      await latency(200);
      const r = runs.get(runId);
      if (!r?.run.company) throw new ApiError('not_found', 'Run not found.', 404);
      return clone(companySummaryArtifact(r.run.company.orgNumber));
    },
    async generateReport({ orgNumber, kind, sections }) {
      await latency(900);
      seed();
      const p = profileFor(orgNumber);
      const id = `rep-${orgNumber}-${++reportCounter}`;
      reports.unshift({
        id,
        type: 'report',
        title: `${p.company.legalName} — ${kind === 'company_brief' ? 'Company brief' : 'Deep research report'}`,
        kind,
        orgNumber,
        createdAt: nowIso(),
        updatedAt: nowIso(),
        sections,
        profile: p,
        tags: [],
        pinned: false,
      });
      return clone(allArtifacts().find((a) => a.id === id)!);
    },
    async findByOrg(orgNumber) {
      await latency(80);
      return researched.has(orgNumber) ? clone(companySummaryArtifact(orgNumber)) : null;
    },
  },

  sheets: {
    async list() {
      await latency(180);
      seed();
      return clone([...sheets.values()].map(sheetToSummary).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)));
    },
    async get(id) {
      await latency(240);
      seed();
      const s = sheets.get(id);
      if (!s) throw new ApiError('not_found', 'Data sheet not found.', 404);
      const sourceIndex = Object.assign({}, ...s.rows.map((r) => fullProfile(r.company.orgNumber).sourceIndex));
      return clone({ ...s, title: artifactMeta.get(id)?.title ?? s.title, sourceIndex });
    },
    async interpret(text) {
      await latency(380);
      return interpretText(text);
    },
    async create({ title, criteria }) {
      await latency(500);
      seed();
      const orgs = applyFilters(allSummaries(), filtersFrom(criteria)).map((c) => c.orgNumber);
      const id = `sheet-new-${++sheetCounter}`;
      return clone(sheetToSummary(newSheet(id, title, orgs, criteria)));
    },
    async rename(id, title) {
      await latency(120);
      const s = sheets.get(id);
      if (!s) throw new ApiError('not_found', 'Data sheet not found.', 404);
      s.title = title;
      artifactMeta.set(id, { ...(artifactMeta.get(id) ?? { tags: [], pinned: false, archived: false }), title });
      return clone(sheetToSummary(s));
    },
    async previewColumn(id, input) {
      await latency(380);
      const s = sheets.get(id);
      if (!s) throw new ApiError('not_found', 'Data sheet not found.', 404);
      return clone(previewFor(input.instruction, input.title, input.valueType, s.rows.length));
    },
    async addColumn(id, input) {
      await latency(450);
      const s = sheets.get(id);
      if (!s) throw new ApiError('not_found', 'Data sheet not found.', 404);
      const col: DataSheetColumn = {
        id: `ai-${++colCounter}`,
        title: input.title?.trim() || titleFromInstruction(input.instruction),
        kind: 'ai',
        valueType: input.valueType ?? 'text',
        instruction: input.instruction,
        width: 220,
      };
      s.columns.push(col);
      s.columnCount = s.columns.length;
      for (const r of s.rows) r.cells[col.id] = { status: 'pending', value: null, evidence: [] };
      return clone(col);
    },
    async updateColumn(id, columnId, patch) {
      await latency(80);
      const col = sheets.get(id)?.columns.find((c) => c.id === columnId);
      if (!col) throw new ApiError('not_found', 'Column not found.', 404);
      Object.assign(col, patch);
      return clone(col);
    },
    async removeColumn(id, columnId) {
      await latency(120);
      const s = sheets.get(id);
      if (!s) throw new ApiError('not_found', 'Data sheet not found.', 404);
      s.columns = s.columns.filter((c) => c.id !== columnId);
      s.columnCount = s.columns.length;
      for (const r of s.rows) delete r.cells[columnId];
    },
    async reorderColumns(id, columnIds) {
      await latency(80);
      const s = sheets.get(id);
      if (!s) throw new ApiError('not_found', 'Data sheet not found.', 404);
      s.columns = columnIds.map((cid) => s.columns.find((c) => c.id === cid)!).filter(Boolean);
    },
    async researchAll(id) {
      await latency(200);
      const s = sheets.get(id);
      if (!s) throw new ApiError('not_found', 'Data sheet not found.', 404);
      if (s.batch?.state === 'running') return clone(s.batch);
      return clone(runSheetBatch(id));
    },
    stream(id, handlers) {
      sheetSubs.set(id, handlers.onEvent);
      setTimeout(() => handlers.onOpen?.(), 0);
      return () => {
        if (sheetSubs.get(id) === handlers.onEvent) sheetSubs.delete(id);
      };
    },
  },

  compare: {
    async get(orgNumbers): Promise<Comparison> {
      await latency(380);
      const orgs = orgNumbers.filter((o) => specsByOrg.has(o)).slice(0, 5);
      if (orgs.length < 2) throw new ApiError('invalid', 'Choose at least two companies to compare.', 400);
      const ps = orgs.map(profileFor);
      const byField = (field: string) => ps.map((p) => p.keyMetrics.find((k) => k.field === field) ?? null);
      const fromSeries = (key: string) => ps.map((p) => p.financials.series.find((s) => s.key === key)?.points.at(-1)?.fact ?? null);
      const idf = (k: keyof (typeof ps)[number]['identity']) => ps.map((p) => (p.identity[k] as Fact | undefined) ?? null);
      const margin = ps.map((p): Fact | null => {
        const r = p.financials.ratios.find((x) => x.key === 'operating_margin');
        if (!r) return null;
        const src = p.financials.series.find((s) => s.key === 'operating_result')!.points.at(-1)!.fact;
        return { ...src, id: `${p.company.orgNumber}:ratio.margin`, field: 'ratio.operating_margin', label: 'Operating margin', value: r.value, unit: '%', currency: undefined, note: `Computed: ${r.formula}` };
      });
      const textFact = (p: (typeof ps)[number], field: string, label: string, value: string | null, evidence: Fact['evidence']): Fact | null =>
        value == null ? null : { id: `${p.company.orgNumber}:${field}`, field, label, value, status: 'verified', evidence, evidenceState: evidence.length ? 'primary' : 'unverified', freshness: 'current', verifiedAt: p.company.lastResearchedAt ?? undefined };
      const rows = (r: ComparisonRow[]) => r;
      const periods = [...new Set(ps.flatMap((p) => p.financials.series.find((s) => s.key === 'revenue')?.points.map((x) => x.period) ?? []))].sort();
      const empPeriods = [...new Set(ps.flatMap((p) => p.financials.series.find((s) => s.key === 'employees')?.points.map((x) => x.period) ?? []))].sort();
      const latestFiling = ps.map((p) => {
        const e = p.activity.events.find((ev) => ev.type === 'filing');
        if (e) return textFact(p, 'activity.latestFiling', 'Latest filing', `${e.title.replace(/^Annual accounts /, '')} · ${formatDate(e.date)}`, e.evidence);
        const rev = p.financials.series.find((x) => x.key === 'revenue')?.points.at(-1);
        return rev ? textFact(p, 'activity.latestFiling', 'Latest filing', `${rev.period} annual accounts`, rev.fact.evidence.slice(0, 1)) : null;
      });
      const materialChanges = ps.map((p) => p.changes.changes.filter((c) => c.material));
      return clone({
        companies: ps.map((p) => p.company),
        summary: rows([
          { key: 'revenue', label: 'Revenue', unit: 'NOK', values: fromSeries('revenue') },
          { key: 'employees', label: 'Employees', values: byField('overview.employees') },
          { key: 'hiring', label: 'Hiring', values: byField('overview.openPositions') },
          { key: 'locations', label: 'Locations', values: byField('overview.locations') },
          { key: 'filing', label: 'Latest filing', values: latestFiling },
        ]),
        generatedAt: nowIso(),
        sourceIndex: Object.assign({}, ...ps.map((p) => p.sourceIndex)),
        sections: [
          {
            id: 'overview',
            label: 'Overview',
            rows: rows([
              { key: 'industry', label: 'Industry', values: idf('industry') },
              { key: 'registered', label: 'Registered address', values: idf('registeredAddress') },
              { key: 'status', label: 'Status', values: idf('status') },
              { key: 'founded', label: 'Founded', values: idf('founded') },
              { key: 'website', label: 'Official website', values: idf('website') },
            ]),
          },
          {
            id: 'financials',
            label: 'Financials',
            rows: rows([
              { key: 'revenue', label: 'Revenue', unit: 'NOK', values: fromSeries('revenue') },
              { key: 'operating', label: 'Operating result', unit: 'NOK', values: fromSeries('operating_result') },
              { key: 'result', label: 'Annual result', unit: 'NOK', values: fromSeries('annual_result') },
              { key: 'margin', label: 'Operating margin', unit: '%', values: margin },
              { key: 'equity', label: 'Equity', unit: 'NOK', values: fromSeries('equity') },
            ]),
          },
          {
            id: 'people',
            label: 'People',
            rows: rows([
              { key: 'employees', label: 'Employees', values: byField('overview.employees') },
              { key: 'ceo', label: 'CEO', values: ps.map((p) => p.people.people.find((x) => x.role === 'CEO' && x.current)?.fact ?? null) },
              { key: 'chair', label: 'Chair', values: ps.map((p) => p.people.people.find((x) => x.role === 'Chair of the board' && x.current)?.fact ?? null) },
            ]),
          },
          {
            id: 'locations',
            label: 'Locations',
            rows: rows([
              { key: 'hq', label: 'Headquarters', values: idf('headquarters') },
              { key: 'locations', label: 'Verified locations', values: byField('overview.locations') },
            ]),
          },
          { id: 'hiring', label: 'Hiring', rows: rows([{ key: 'jobs', label: 'Open positions', values: byField('overview.openPositions') }]) },
          {
            id: 'activity',
            label: 'Activity',
            rows: rows([
              {
                key: 'latest',
                label: 'Latest event',
                values: ps.map((p) => {
                  const e = p.activity.events[0];
                  return e ? textFact(p, 'activity.latest', 'Latest event', `${e.title} (${formatDate(e.date)})`, e.evidence) : null;
                }),
              },
              { key: 'filing', label: 'Latest filing', values: latestFiling },
            ]),
          },
          {
            id: 'changes',
            label: 'Changes',
            rows: rows([
              {
                key: 'changes',
                label: 'Material changes since previous research',
                values: ps.map((p, i) => (p.changes.status === 'pending' ? null : textFact(p, 'changes.count', 'Material changes', String(materialChanges[i].length), materialChanges[i].flatMap((c) => c.evidence).slice(0, 3)))),
              },
              {
                key: 'latestChange',
                label: 'Most significant change',
                values: ps.map((p, i) => {
                  const order = ['leadership', 'status', 'financial', 'filing', 'ownership', 'location', 'address', 'hiring', 'employees', 'event', 'website'];
                  const c = [...materialChanges[i]].sort((a, b) => order.indexOf(a.category) - order.indexOf(b.category))[0];
                  return c ? textFact(p, 'changes.top', 'Most significant change', `${c.headline ?? c.label}${c.previous && c.current && !(c.headline ?? '').includes('→') ? ` (${c.previous} → ${c.current})` : ''}`, c.evidence) : null;
                }),
              },
            ]),
          },
        ],
        series: [
          {
            key: 'revenue',
            label: 'Revenue',
            unit: 'NOK',
            points: periods.map((period) => ({ period, values: ps.map((p) => p.financials.series.find((s) => s.key === 'revenue')?.points.find((x) => x.period === period)?.fact.value ?? null) })),
          },
          {
            key: 'employees',
            label: 'Average FTEs (annual accounts)',
            unit: 'people',
            points: empPeriods.map((period) => ({ period, values: ps.map((p) => p.financials.series.find((s) => s.key === 'employees')?.points.find((x) => x.period === period)?.fact.value ?? null) })),
          },
        ],
      });
    },
  },

  watchlist: {
    async get() {
      await latency(220);
      seed();
      return clone(buildWatchlist());
    },
    async add(orgNumber) {
      await latency(140);
      seed();
      watch.orgs.add(orgNumber);
      return clone(buildWatchlist());
    },
    async remove(orgNumber) {
      await latency(140);
      watch.orgs.delete(orgNumber);
      return clone(buildWatchlist());
    },
    async markChecked() {
      await latency(160);
      for (const i of watchItems()) for (const s of i.signals) watch.seen.add(s.id);
      return clone(buildWatchlist());
    },
    async feed(): Promise<SignalFeedGroup[]> {
      await latency(240);
      seed();
      const all = [...watch.orgs].flatMap(signalsFor).sort((a, b) => b.detectedAt.localeCompare(a.detectedAt));
      const groups = new Map<string, typeof all>();
      const label = (d: string) => {
        const diff = Math.round((Date.parse(NOW.slice(0, 10)) - Date.parse(d)) / 86400000);
        if (diff <= 0) return 'Today';
        if (diff === 1) return 'Yesterday';
        if (diff < 7) return 'Earlier this week';
        if (diff < 31) return 'Earlier this month';
        return 'Older';
      };
      for (const s of all) {
        const l = label(s.detectedAt.slice(0, 10));
        groups.set(l, [...(groups.get(l) ?? []), s]);
      }
      const phrase: Record<string, (n: number) => string> = {
        filing: (n) => `${n} ${n === 1 ? 'company' : 'companies'} received new filings`,
        hiring: (n) => `${n} ${n === 1 ? 'company' : 'companies'} changed hiring activity`,
        leadership: (n) => `${n} leadership ${n === 1 ? 'change' : 'changes'} detected`,
        location: (n) => `${n} new ${n === 1 ? 'location' : 'locations'} registered`,
        financial: (n) => `${n} financial or headcount ${n === 1 ? 'update' : 'updates'}`,
        announcement: (n) => `${n} ${n === 1 ? 'announcement' : 'announcements'}`,
      };
      return clone(
        [...groups.entries()].map(([lbl, sigs]) => {
          const kinds = new Map<string, Set<string>>();
          for (const s of sigs) kinds.set(s.kind, (kinds.get(s.kind) ?? new Set()).add(s.orgNumber));
          return {
            date: sigs[0].detectedAt.slice(0, 10),
            label: lbl,
            summary: [...kinds.entries()].map(([kind, orgs]) => ({ kind: kind as SignalFeedGroup['summary'][number]['kind'], count: orgs.size, label: phrase[kind](orgs.size) })),
            signals: sigs,
            sourceIndex: Object.assign({}, ...[...new Set(sigs.map((s) => s.orgNumber))].map((o) => fullProfile(o).sourceIndex)),
          };
        }),
      );
    },
  },

  exports: {
    async request(req: ExportRequest): Promise<ExportResult> {
      await latency(600);
      seed();
      if (req.format === 'pdf' || req.format === 'xlsx') return { status: 'failed', filename: '', message: `${req.format.toUpperCase()} export is not supported by this backend yet.` };
      let data: Record<string, unknown>[] | unknown = [];
      let base = 'cognis-export';
      if (req.target.type === 'company' || req.target.type === 'artifact') {
        const org = req.target.id.replace('art-', '');
        const p = profileFor(org);
        base = `cognis-${org}`;
        const facts = [
          ...Object.values(p.identity).filter((x): x is Fact => typeof x === 'object' && !!x),
          ...p.keyMetrics,
          ...p.financials.series.flatMap((s) => s.points.map((x) => x.fact)),
          ...p.people.people.map((x) => x.fact),
          ...p.locations.locations.map((x) => x.fact),
        ];
        const rows = factRows(facts, req.options, (id) => p.sourceIndex[id]?.name ?? id);
        if (req.options.changes) for (const c of p.changes.changes) rows.push({ field: `changes.${c.category}`, label: c.label, value: `${c.previous ?? ''} → ${c.current ?? ''}`, unit: '', status: 'verified', evidence_state: 'primary', source: p.sourceIndex[c.evidence[0]?.sourceId]?.name ?? '' });
        data = req.format === 'json' ? { company: p.company, facts: rows, generatedAt: nowIso(), note: 'COGNIS mock backend — fictional demo data' } : rows;
      } else if (req.target.type === 'sheet') {
        const s = sheets.get(req.target.id)!;
        base = `cognis-${s.id}`;
        data = s.rows.map((r) => {
          const o: Record<string, unknown> = { company: r.company.legalName, org_number: r.company.orgNumber };
          for (const c of s.columns.filter((c) => c.kind !== 'identity')) {
            const cell = r.cells[c.id];
            o[c.title] = cell?.display ?? cell?.value ?? '';
            o[`${c.title} — status`] = cell?.status ?? '';
            if (req.options.sourceLinks) o[`${c.title} — source`] = cell?.evidence[0]?.url ?? '';
            if (req.options.retrievalDates) o[`${c.title} — retrieved`] = cell?.evidence[0]?.retrievedAt ?? '';
          }
          return o;
        });
      } else if (req.target.type === 'comparison') {
        const orgs = req.target.id.split(',');
        const cmp = await mockApi.compare.get(orgs);
        base = 'cognis-comparison';
        data = cmp.sections.flatMap((s) =>
          s.rows.map((r) => {
            const o: Record<string, unknown> = { section: s.label, metric: r.label };
            cmp.companies.forEach((c, i) => {
              o[c.legalName] = r.values[i]?.value ?? 'Not available';
              if (req.options.reportingPeriods) o[`${c.legalName} — period`] = r.values[i]?.reportingPeriod ?? '';
              if (req.options.sourceLinks) o[`${c.legalName} — source`] = r.values[i]?.evidence[0]?.url ?? '';
            });
            return o;
          }),
        );
      }
      const body = req.format === 'json' ? JSON.stringify(data, null, 2) : toCsv(data as Record<string, unknown>[]);
      const blob = new Blob([body], { type: req.format === 'json' ? 'application/json' : 'text/csv' });
      return { status: 'ready', filename: `${base}.${req.format}`, url: typeof URL.createObjectURL === 'function' ? URL.createObjectURL(blob) : undefined };
    },
  },
};

function buildWatchlist(): Watchlist {
  const items = watchItems();
  return { id: 'watch-main', title: 'My Watchlist', items, changedCount: items.filter((i) => i.signals.length).length, lastCheckedAt: watch.lastCheckedAt };
}

function sheetToSummary(s: DataSheet): DataSheetSummary {
  return { id: s.id, title: artifactMeta.get(s.id)?.title ?? s.title, description: s.description, rowCount: s.rows.length, columnCount: s.columns.length, updatedAt: s.updatedAt, criteria: s.criteria };
}

function previewFor(instruction: string, title: string | undefined, requested: ColumnValueType | undefined, rowCount: number): ColumnPreview {
  const t = instruction.toLowerCase();
  const rules: { re: RegExp; type: ColumnValueType; cell: string; sources: string[]; note?: string }[] = [
    { re: /\b(ceo|chief executive|daglig leder|managing director)\b/, type: 'person', cell: "The current CEO's full name, with the registry role and start date as evidence.", sources: ['Brønnøysundregistrene — roles', 'Official website (leadership page)'] },
    { re: /\b(chair|board)\b/, type: 'person', cell: 'The current chair of the board, from the registered roles.', sources: ['Brønnøysundregistrene — roles'] },
    { re: /\b(founder)\b/, type: 'person', cell: 'The founder, only when a registry role or the official website names one.', sources: ['Brønnøysundregistrene — roles', 'Official website'] },
    { re: /\b(operating margin|margin)\b/, type: 'number', cell: 'Operating result ÷ revenue for the latest filed year, as a percentage with its period.', sources: ['Regnskapsregisteret'], note: 'Computed deterministically from filed figures.' },
    { re: /\b(revenue|turnover|sales|driftsinntekter)\b/, type: 'currency', cell: 'Latest filed revenue in NOK, with its reporting period (e.g. FY2025).', sources: ['Regnskapsregisteret', 'Proff.no (secondary, for cross-checking)'] },
    { re: /\b(employees|headcount|staff)\b/, type: 'number', cell: 'Registered number of employees, with the registry retrieval date.', sources: ['Brønnøysundregistrene'] },
    { re: /\b(hiring|job|jobs|openings|vacanc)/, type: 'number', cell: 'Number of current verified job openings, with links to the postings.', sources: ['arbeidsplassen.nav.no', 'Official careers pages'] },
    { re: /\b(office|offices|locations|sites|workplaces)\b/, type: 'number', cell: 'Number of verified operating locations (registered sub-units and offices named on the official website).', sources: ['Brønnøysundregistrene — sub-units', 'Official website (contact page)'] },
    { re: /\b(expand|expanded|expansion|international|abroad)\b/, type: 'boolean', cell: 'Yes when a source documents the expansion within the period, with the evidence; otherwise Not available.', sources: ['Brønnøysundregistrene — announcements', 'Official website news', 'Web & news discovery'], note: 'A “No” is only returned when a source states it; absence of evidence is shown as Not available.' },
    { re: /\b(website|domain|url)\b/, type: 'url', cell: 'The official website, verified against the registry entry.', sources: ['Brønnøysundregistrene', 'Official website'] },
  ];
  const rule = rules.find((r) => r.re.test(t));
  const valueType = requested && requested !== 'text' ? requested : (rule?.type ?? 'text');
  return {
    instruction,
    title: title?.trim() || titleFromInstruction(instruction),
    valueType,
    cellDescription: rule?.cell ?? 'A short factual answer per company, researched from its official sources. Unclear results are marked Ambiguous.',
    plannedSources: rule?.sources ?? ['Official website', 'Brønnøysundregistrene', 'Web & news discovery'],
    rowCount,
    supported: instruction.trim().length >= 4,
    notes: [
      ...(rule?.note ? [rule.note] : []),
      'Every cell carries its source, date and evidence.',
      'Cells the backend cannot verify are marked “Not available” — never guessed.',
    ],
  };
}

function titleFromInstruction(instr: string) {
  let t = instr
    .trim()
    .replace(/[.?!]+$/, '')
    .replace(/^(please\s+)?(find|identify|get|determine|list|check|look up|tell me)\s+(whether\s+|if\s+)?/i, '')
    .replace(/^(what is|what's|who is|is|does|did)\s+/i, '')
    .replace(/\bthe company'?s\b\s*/i, '')
    .replace(/\bthe company\b\s*/i, '');
  t = t.charAt(0).toUpperCase() + t.slice(1);
  return t.length > 36 ? `${t.slice(0, 34).trim()}…` : t || 'Research column';
}

/** Exposed for tests. */
export const __mockInternals = { interpretText, applyFilters, STANDARD_COLUMNS };
