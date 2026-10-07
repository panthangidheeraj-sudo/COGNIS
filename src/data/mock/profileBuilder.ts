/**
 * MOCK BACKEND — builds CompanyProfile objects from compact fixture specs.
 * Output is structurally identical to the live contract (src/types).
 * All companies, people and figures produced here are FICTIONAL demo data.
 */
import type {
  CompanyProfile,
  CompanyStatus,
  CompanySummary,
  Coverage,
  CoverageArea,
  CoverageAreaState,
  CoverageAreaStatus,
  Change,
  ChangeCategory,
  ChangeKind,
  Evidence,
  EvidenceState,
  Fact,
  FactPrimitive,
  FinancialMetricKey,
  FinancialSeries,
  Job,
  KnownItem,
  Person,
  Relationship,
  RelationshipKind,
  SocialProfile,
  Source,
  SourceUsage,
  TimelineEvent,
  TimelineEventType,
  WebsitePage,
  CompanyLocation,
} from '@/types';
import { SOURCES, websiteSource } from './sources';
import { MUNI_BY_NAME } from './geo';

export const NOW = '2026-10-03T10:32:00Z';
export const TODAY = '2026-10-03';

export type Sector = 'saas' | 'software' | 'healthtech' | 'medtech' | 'logistics' | 'energy' | 'seafood' | 'maritime' | 'fintech' | 'construction' | 'consulting' | 'data';

export interface PersonSpec {
  name: string;
  role: string;
  group: Person['roleGroup'];
  since?: string;
  until?: string;
  current?: boolean;
  otherRoles?: { companyName: string; role: string; current: boolean }[];
}
export interface LocSpec {
  kind: CompanyLocation['kind'];
  label: string;
  address: string;
  municipality: string;
  verified: boolean;
  sourceId?: string;
}
export interface JobSpec {
  title: string;
  department: string;
  location: string;
  postedAt: string;
  state?: Job['state'];
  sourceId?: 'nav' | 'web';
}
export interface EventSpec {
  date: string;
  type: TimelineEventType;
  title: string;
  description?: string;
  sourceId: string;
  excerpt?: string;
  /** Override the default significance for this event type. */
  major?: boolean;
}
export interface ChangeSpec {
  detectedAt: string;
  kind: ChangeKind;
  category: ChangeCategory;
  label: string;
  previous?: string;
  current?: string;
  sourceId: string;
  headline?: string;
  material?: boolean;
}
/** An explanation a source itself states (fictional fixture text). */
export interface ReportedSpec {
  subject: 'revenue' | 'employees' | 'hiring' | 'leadership' | 'status' | 'location';
  sourceId: string;
  documentTitle: string;
  text: string;
  quote: string;
  quoteLanguage?: 'no' | 'en';
  date: string;
}
export interface RelSpec {
  kind: RelationshipKind;
  label: string;
  type: 'person' | 'organization';
  name: string;
  orgNumber?: string;
  sourceId: string;
}

export interface CompanySpec {
  org: string;
  name: string;
  legalForm: 'AS' | 'ASA';
  municipality: string;
  address: string;
  postalCode: string;
  nace: { code: string; description: string; original: string };
  sector: Sector;
  status: CompanyStatus;
  statusLabel?: string;
  founded: string;
  domain: string | null;
  websiteBlocked?: boolean;
  linkedinBlocked?: boolean;
  description: string;
  summary: string;
  years: number[];
  revenue?: number[];
  operating?: number[];
  result?: number[];
  assets?: number[];
  equity?: number[];
  debt?: number[];
  cash?: number[];
  avgEmployees?: number[];
  employeesNow: number | null;
  people: PersonSpec[];
  locations: LocSpec[];
  jobs: JobSpec[] | null;
  hiringHistory?: { month: string; count: number }[];
  events: EventSpec[];
  changes: ChangeSpec[];
  changesSince?: string;
  relationships: RelSpec[];
  revenueConflict?: { value: number; reason?: string };
  activityFailed?: boolean;
  social?: { network: SocialProfile['network']; handle: string }[];
  pagesFound?: WebsitePage['kind'][];
  researchedAt: string | null;
  tags?: string[];
  coverageOverride?: Partial<Record<CoverageArea, { status: CoverageAreaStatus; note?: string }>>;
  reported?: ReportedSpec[];
}

/* -------------------------------------------------------------------------- */

const nb = (n: number) => Math.round(n).toLocaleString('nb-NO').replace(/ | /g, ' ');
const noDate = (iso: string) => {
  const [y, m, d] = iso.slice(0, 10).split('-');
  return `${d}.${m}.${y}`;
};
const daysBefore = (iso: string, days: number) => {
  const d = new Date(iso);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().replace('.000', '');
};

class Ctx {
  n = 0;
  evidence: Evidence[] = [];
  facts: Fact[] = [];
  factSections = new Map<string, string>();
  section = 'identity';
  sources: Record<string, Source> = {};
  constructor(public spec: CompanySpec) {
    for (const s of Object.values(SOURCES)) this.sources[s.id] = s;
    if (spec.domain) {
      const ws = websiteSource(spec.org, spec.domain);
      this.sources[ws.id] = ws;
    }
  }
  srcId(id: string) {
    return id === 'web' ? `web-${this.spec.org}` : id;
  }
  retrieved(sourceId: string) {
    const base = this.spec.researchedAt ?? NOW;
    // registries refreshed at research time; secondary sources slightly earlier
    const offset = sourceId === 'proff' || sourceId === 'linkedin' ? 2 : 0;
    return daysBefore(base, offset);
  }
  ev(sourceId: string, o: Partial<Evidence> = {}): Evidence {
    const sid = this.srcId(sourceId);
    const src = this.sources[sid];
    const e: Evidence = {
      id: `${this.spec.org}-e${++this.n}`,
      sourceId: sid,
      url: o.url ?? src?.url,
      retrievedAt: o.retrievedAt ?? this.retrieved(sid),
      ...o,
    };
    this.evidence.push(e);
    return e;
  }
  fact<T extends FactPrimitive>(field: string, label: string, value: T | null, o: Partial<Fact<T>> & { evidence: Evidence[] }): Fact<T> {
    const primaryCount = o.evidence.filter((e) => this.sources[e.sourceId]?.tier === 'primary').length;
    const state: EvidenceState =
      o.evidenceState ??
      (o.conflict ? 'conflict' : o.evidence.length >= 2 && primaryCount >= 1 ? 'verified' : primaryCount === 1 ? 'primary' : o.evidence.length ? 'secondary' : 'unverified');
    const f: Fact<T> = {
      id: `${this.spec.org}:${field}`,
      field,
      label,
      status: o.status ?? (value === null ? 'not_available' : 'verified'),
      value,
      verifiedAt: value === null ? undefined : (o.verifiedAt ?? this.spec.researchedAt ?? NOW),
      freshness: o.freshness ?? 'current',
      ...o,
      evidenceState: state,
    };
    this.facts.push(f as Fact);
    this.factSections.set(f.id, this.section);
    return f;
  }
}

export function buildProfile(spec: CompanySpec): CompanyProfile {
  const c = new Ctx(spec);
  const muni = MUNI_BY_NAME[spec.municipality];
  const fullAddress = `${spec.address}, ${spec.postalCode} ${spec.municipality}`;
  const lastYear = spec.years[spec.years.length - 1];

  /* ------------------------------ identity ------------------------------ */
  c.section = 'identity';
  const regDoc = { documentTitle: `Enhetsregisteret — ${spec.name}`, excerptLanguage: 'no' as const };
  const identity: CompanyProfile['identity'] = {
    orgNumber: spec.org,
    legalName: c.fact('identity.legalName', 'Legal name', spec.name, {
      evidence: [c.ev('brreg', { ...regDoc, excerpt: `Navn/foretaksnavn: ${spec.name.toUpperCase()}`, excerptTranslation: `Registered name: ${spec.name}` })],
    }),
    status: c.fact('identity.status', 'Status', spec.statusLabel ?? statusLabel(spec.status), {
      evidence: [
        c.ev('brreg', {
          ...regDoc,
          excerpt: spec.status === 'active' ? 'Registrert i Foretaksregisteret. Ingen registrerte opplysninger om konkurs eller avvikling.' : 'Under avvikling: Ja',
          excerptTranslation: spec.status === 'active' ? 'Registered in the Register of Business Enterprises. No bankruptcy or liquidation recorded.' : 'Under liquidation: Yes',
        }),
      ],
    }),
    legalForm: c.fact('identity.legalForm', 'Legal form', spec.legalForm === 'AS' ? 'Private limited company (AS)' : 'Public limited company (ASA)', {
      evidence: [c.ev('brreg', { ...regDoc, excerpt: `Organisasjonsform: ${spec.legalForm === 'AS' ? 'Aksjeselskap' : 'Allmennaksjeselskap'}` })],
    }),
    founded: c.fact('identity.founded', 'Founded', spec.founded, {
      evidence: [c.ev('brreg', { ...regDoc, excerpt: `Stiftelsesdato: ${noDate(spec.founded)}`, excerptTranslation: `Date of incorporation: ${spec.founded}` })],
      freshness: 'historical',
    }),
    industry: c.fact('identity.industry', 'Industry', `${spec.nace.description} (${spec.nace.code})`, {
      evidence: [c.ev('brreg', { ...regDoc, excerpt: `Næringskode 1: ${spec.nace.code} ${spec.nace.original}`, excerptTranslation: `Industry code: ${spec.nace.code} ${spec.nace.description}` })],
    }),
    registeredAddress: c.fact('identity.registeredAddress', 'Registered address', fullAddress, {
      evidence: [c.ev('brreg', { ...regDoc, excerpt: `Forretningsadresse: ${spec.address}, ${spec.postalCode} ${spec.municipality.toUpperCase()}`, excerptTranslation: `Business address: ${fullAddress}` })],
    }),
  };
  const hq = spec.locations.find((l) => l.kind === 'headquarters' && l.verified);
  if (hq) {
    identity.headquarters = c.fact('identity.headquarters', 'Headquarters (verified)', `${hq.address}, ${hq.municipality}`, {
      evidence: [
        c.ev('brreg', { ...regDoc, excerpt: `Forretningsadresse: ${spec.address}` }),
        ...(spec.domain && !spec.websiteBlocked ? [c.ev('web', { documentTitle: 'Contact', url: `https://${spec.domain}/contact`, excerpt: `Head office: ${hq.address}, ${hq.municipality}` })] : []),
      ],
    });
  }
  if (spec.domain) {
    identity.website = c.fact('identity.website', 'Official website', spec.domain, {
      evidence: [
        c.ev('brreg', { ...regDoc, excerpt: `Hjemmeside: www.${spec.domain}`, excerptTranslation: `Website: www.${spec.domain}` }),
        ...(spec.websiteBlocked ? [] : [c.ev('web', { documentTitle: 'Home', excerpt: `© ${spec.name} · Org.nr. ${spec.org}` })]),
      ],
      note: spec.websiteBlocked ? 'Listed in the registry. The website itself blocked automated access, so its content could not be verified.' : undefined,
    });
  }

  /* ------------------------------ description --------------------------- */
  let description: Fact<string> | undefined;
  if (spec.domain && !spec.websiteBlocked) {
    c.section = 'overview';
    description = c.fact('overview.description', 'What the company does', spec.description, {
      evidence: [c.ev('web', { documentTitle: 'About us', url: `https://${spec.domain}/about`, excerpt: spec.description })],
    });
  }

  /* ------------------------------ financials ---------------------------- */
  c.section = 'financials';
  const hasFin = !!spec.revenue?.length;
  const series: FinancialSeries[] = [];
  const mkSeries = (key: FinancialMetricKey, label: string, values: number[] | undefined, nbLabel: string, unit = 'NOK') => {
    if (!values?.length) return;
    const yrs = spec.years.slice(-values.length);
    series.push({
      key,
      label,
      unit,
      points: values.map((v, i) => {
        const year = yrs[i];
        const period = `FY${year}`;
        const isLatest = year === lastYear;
        const evs = [
          c.ev(unit === 'NOK' ? 'accounts' : 'accounts', {
            documentTitle: `Årsregnskap ${year} — ${spec.name}`,
            page: key === 'revenue' || key === 'operating_result' || key === 'annual_result' ? 3 : 5,
            excerpt: `${nbLabel} ${nb(v)}`,
            excerptLanguage: 'no',
            excerptTranslation: `${label}: ${nb(v)} ${unit === 'NOK' ? 'NOK' : ''}`.trim(),
            reportingPeriod: period,
            retrievedAt: isLatest ? c.retrieved('accounts') : `${year + 1}-07-0${(year % 7) + 1}T08:00:00Z`,
          }),
        ];
        let conflict: Fact['conflict'];
        if (key === 'revenue' && isLatest && spec.revenueConflict) {
          const pe = c.ev('proff', {
            documentTitle: `${spec.name} — regnskap`,
            excerpt: `Driftsinntekter ${nb(spec.revenueConflict.value)}`,
            excerptLanguage: 'no',
            reportingPeriod: period,
            statedValue: String(spec.revenueConflict.value),
          });
          evs[0].statedValue = String(v);
          evs.push(pe);
          conflict = {
            reason: spec.revenueConflict.reason,
            candidates: [
              { sourceId: 'accounts', value: v, reportingPeriod: period, evidenceId: evs[0].id },
              { sourceId: 'proff', value: spec.revenueConflict.value, reportingPeriod: period, evidenceId: pe.id },
            ],
          };
        } else if (key === 'revenue' && isLatest) {
          evs.push(c.ev('proff', { documentTitle: `${spec.name} — regnskap`, excerpt: `Driftsinntekter ${nb(v)}`, excerptLanguage: 'no', reportingPeriod: period }));
        }
        return {
          period,
          year,
          fact: c.fact(`financials.${key}.${year}`, label, v, {
            evidence: evs,
            unit,
            currency: unit === 'NOK' ? 'NOK' : undefined,
            reportingPeriod: period,
            freshness: isLatest ? 'current' : 'historical',
            conflict,
          }),
        };
      }),
    });
  };
  if (hasFin) {
    mkSeries('revenue', 'Revenue', spec.revenue, 'Sum driftsinntekter');
    mkSeries('operating_result', 'Operating result', spec.operating, 'Driftsresultat');
    mkSeries('annual_result', 'Annual result', spec.result, 'Årsresultat');
    mkSeries('total_assets', 'Total assets', spec.assets, 'Sum eiendeler');
    mkSeries('equity', 'Equity', spec.equity, 'Sum egenkapital');
    mkSeries('debt', 'Total debt', spec.debt, 'Sum gjeld');
    mkSeries('cash', 'Cash and equivalents', spec.cash, 'Bankinnskudd, kontanter o.l.');
    mkSeries('employees', 'Average FTEs (annual accounts)', spec.avgEmployees, 'Gjennomsnittlig antall årsverk', 'people');
  }
  const latest = (key: FinancialMetricKey) => series.find((s) => s.key === key)?.points.at(-1);
  const ratios: CompanyProfile['financials']['ratios'] = [];
  const ratioHistory: NonNullable<CompanyProfile['financials']['ratioHistory']> = [];
  {
    const at = (key: FinancialMetricKey, period: string) => series.find((s) => s.key === key)?.points.find((p) => p.period === period)?.fact.value ?? null;
    const periods = series.find((s) => s.key === 'revenue')?.points.map((p) => p.period) ?? [];
    const defs: { key: string; label: string; formula: string; f: (p: string, i: number) => number | null }[] = [
      { key: 'operating_margin', label: 'Operating margin', formula: 'Operating result ÷ Revenue', f: (p) => { const r = at('revenue', p); const o = at('operating_result', p); return r && o != null ? (o / r) * 100 : null; } },
      { key: 'profit_margin', label: 'Profit margin', formula: 'Annual result ÷ Revenue', f: (p) => { const r = at('revenue', p); const o = at('annual_result', p); return r && o != null ? (o / r) * 100 : null; } },
      { key: 'equity_ratio', label: 'Equity ratio', formula: 'Equity ÷ Total assets', f: (p) => { const a = at('total_assets', p); const e = at('equity', p); return a && e != null ? (e / a) * 100 : null; } },
      { key: 'revenue_growth', label: 'Revenue growth', formula: '(Revenue FY − Revenue FY−1) ÷ Revenue FY−1', f: (p, i) => { if (i === 0) return null; const a = at('revenue', periods[i - 1]); const b = at('revenue', p); return a && b != null ? ((b - a) / a) * 100 : null; } },
    ];
    for (const d of defs) {
      const points = periods.map((p, i) => ({ period: p, value: d.f(p, i) })).filter((x): x is { period: string; value: number } => x.value != null).map((x) => ({ ...x, value: round1(x.value) }));
      if (points.length) ratioHistory.push({ key: d.key, label: d.label, formula: d.formula, points });
    }
  }
  const rev = latest('revenue')?.fact.value;
  const op = latest('operating_result')?.fact.value;
  const eq = latest('equity')?.fact.value;
  const as = latest('total_assets')?.fact.value;
  const res = latest('annual_result')?.fact.value;
  if (rev && op != null) ratios.push({ key: 'operating_margin', label: 'Operating margin', value: round1((op / rev) * 100), period: `FY${lastYear}`, formula: 'Operating result ÷ Revenue' });
  if (rev && res != null) ratios.push({ key: 'profit_margin', label: 'Profit margin', value: round1((res / rev) * 100), period: `FY${lastYear}`, formula: 'Annual result ÷ Revenue' });
  if (as && eq != null) ratios.push({ key: 'equity_ratio', label: 'Equity ratio', value: round1((eq / as) * 100), period: `FY${lastYear}`, formula: 'Equity ÷ Total assets' });
  const revSeries = series.find((s) => s.key === 'revenue');
  if (revSeries && revSeries.points.length >= 2) {
    const a = revSeries.points.at(-2)!.fact.value!;
    const b = revSeries.points.at(-1)!.fact.value!;
    ratios.push({ key: 'revenue_growth', label: 'Revenue growth', value: round1(((b - a) / a) * 100), period: `FY${lastYear - 1}→FY${lastYear}`, formula: '(Revenue FY − Revenue FY−1) ÷ Revenue FY−1' });
  }

  /* ------------------------------ people -------------------------------- */
  c.section = 'people';
  const people: Person[] = spec.people.map((p, i) => {
    const current = p.current ?? !p.until;
    const roleNo = p.role === 'CEO' ? 'Daglig leder' : p.role === 'Chair of the board' ? 'Styrets leder' : p.role === 'Board member' ? 'Styremedlem' : p.role;
    const evs = [
      c.ev('roles', {
        documentTitle: `Roller — ${spec.name}`,
        excerpt: `${roleNo}: ${p.name}${p.since ? ` (fra ${noDate(p.since)})` : ''}${p.until ? ` (til ${noDate(p.until)})` : ''}`,
        excerptLanguage: 'no',
        excerptTranslation: `${p.role}: ${p.name}${p.since ? ` (from ${p.since})` : ''}${p.until ? ` (until ${p.until})` : ''}`,
      }),
    ];
    if (p.group === 'executive' && spec.domain && !spec.websiteBlocked && current)
      evs.push(c.ev('web', { documentTitle: 'Leadership', url: `https://${spec.domain}/about/leadership`, excerpt: `${p.name} — ${p.role}` }));
    return {
      id: `${spec.org}-p${i}`,
      name: p.name,
      role: p.role,
      roleGroup: p.group,
      current,
      since: p.since,
      until: p.until,
      fact: c.fact(`people.${i}`, p.role, p.name, { evidence: evs, freshness: current ? 'current' : 'historical' }),
      otherRoles: p.otherRoles?.map((r) => ({
        ...r,
        evidence: [c.ev('roles', { documentTitle: `Roller — ${r.companyName}`, excerpt: `${r.role}: ${p.name}`, excerptLanguage: 'no' })],
      })),
    };
  });

  /* ------------------------------ locations ----------------------------- */
  c.section = 'locations';
  const locations: CompanyLocation[] = [
    {
      id: `${spec.org}-loc-reg`,
      kind: 'registered_address',
      label: 'Registered address',
      address: spec.address,
      postalCode: spec.postalCode,
      municipality: spec.municipality,
      geo: muni ? { lat: muni.lat, lon: muni.lon } : undefined,
      verified: true,
      fact: identity.registeredAddress!,
    },
    ...spec.locations.map((l, i) => {
      const m = MUNI_BY_NAME[l.municipality];
      const src = l.sourceId ?? (spec.domain && !spec.websiteBlocked ? 'web' : 'brreg');
      return {
        id: `${spec.org}-loc${i}`,
        kind: l.kind,
        label: l.label,
        address: l.address,
        municipality: l.municipality,
        geo: m ? { lat: m.lat + ((i % 3) - 1) * 0.01, lon: m.lon + ((i % 2) - 0.5) * 0.02 } : undefined,
        verified: l.verified,
        fact: c.fact(`locations.${i}`, l.label, `${l.address}, ${l.municipality}`, {
          evidence: [
            c.ev(src, {
              documentTitle: src === 'brreg' ? 'Underenheter' : 'Offices',
              url: src === 'web' ? `https://${spec.domain}/contact` : undefined,
              excerpt: src === 'brreg' ? `Underenhet: ${l.address}, ${l.municipality.toUpperCase()}` : `Our office in ${l.municipality}: ${l.address}`,
              excerptLanguage: src === 'brreg' ? 'no' : 'en',
            }),
          ],
          evidenceState: l.verified ? undefined : 'secondary',
        }),
      };
    }),
  ];

  /* ------------------------------ website ------------------------------- */
  c.section = 'website';
  const allPages: WebsitePage['kind'][] = ['about', 'products', 'contact', 'careers', 'news', 'investors', 'sustainability'];
  const pageTitle: Record<WebsitePage['kind'], string> = {
    about: 'About',
    products: 'Products & services',
    contact: 'Contact',
    careers: 'Careers',
    news: 'News',
    investors: 'Investor relations',
    sustainability: 'Sustainability',
  };
  const found = new Set(spec.pagesFound ?? ['about', 'products', 'contact', 'careers', 'news']);
  const website: CompanyProfile['website'] = !spec.domain
    ? {
        status: 'not_available',
        message: 'No official website verified in the searched permitted sources.',
        pages: [],
        social: [],
        signals: [],
        searchedSourceIds: ['brreg', 'websearch'],
      }
    : spec.websiteBlocked
      ? {
          status: 'blocked',
          message: 'Source access blocked. The official website refused automated access, so its content could not be verified.',
          domain: spec.domain,
          url: `https://${spec.domain}`,
          verification: identity.website,
          pages: [],
          social: [],
          signals: [],
          searchedSourceIds: [`web-${spec.org}`],
        }
      : {
          status: 'available',
          domain: spec.domain,
          url: `https://${spec.domain}`,
          verification: c.fact('website.verification', 'Website ownership', `Verified — org. no. ${spec.org} shown on site and listed in the registry`, {
            evidence: [identity.website!.evidence[0], c.ev('web', { documentTitle: 'Footer', excerpt: `${spec.name} · Org.nr. ${spec.org}` })],
          }),
          description,
          pages: allPages.map((k) => ({ kind: k, title: pageTitle[k], found: found.has(k), url: found.has(k) ? `https://${spec.domain}/${k}` : undefined })),
          social: (spec.social ?? [{ network: 'linkedin' as const, handle: slug(spec.name) }]).map((s) => ({
            network: s.network,
            handle: s.handle,
            url: s.network === 'linkedin' ? `https://www.linkedin.com/company/${s.handle}` : `https://${s.network}.com/${s.handle}`,
            fact: c.fact(`website.social.${s.network}`, s.network, s.handle, {
              evidence: [c.ev('web', { documentTitle: 'Footer', excerpt: `Follow us on ${s.network}` })],
            }),
          })),
          signals: [
            { label: 'Careers page', value: found.has('careers') ? 'Found' : 'Not found' },
            { label: 'Newsroom', value: found.has('news') ? 'Found' : 'Not found' },
            { label: 'Languages', value: 'Norwegian, English' },
            { label: 'HTTPS', value: 'Yes' },
          ],
        };

  /* ------------------------------ hiring -------------------------------- */
  c.section = 'hiring';
  let hiring: CompanyProfile['hiring'];
  if (spec.jobs === null) {
    hiring = {
      status: 'not_available',
      message: 'No current verified job openings were found in the searched sources.',
      totalCurrent: null,
      locations: [],
      categories: [],
      jobs: [],
      history: [],
      searchedSourceIds: ['nav', ...(spec.domain ? [`web-${spec.org}`] : [])],
    };
  } else {
    const jobs: Job[] = spec.jobs.map((j, i) => {
      const src = j.sourceId === 'web' && spec.domain ? `web-${spec.org}` : 'nav';
      return {
        id: `${spec.org}-job${i}`,
        title: j.title,
        department: j.department,
        location: j.location,
        postedAt: j.postedAt,
        sourceId: src,
        url: src === 'nav' ? 'https://arbeidsplassen.nav.no/' : `https://${spec.domain}/careers`,
        state: j.state ?? 'current',
        evidence: [
          c.ev(src, {
            documentTitle: j.title,
            excerpt: src === 'nav' ? `Stillingstittel: ${j.title}. Arbeidssted: ${j.location}. Publisert: ${noDate(j.postedAt)}` : `${j.title} — ${j.location}. Apply now.`,
            excerptLanguage: src === 'nav' ? 'no' : 'en',
          }),
        ],
      };
    });
    const current = jobs.filter((j) => j.state === 'current');
    hiring = {
      status: 'available',
      totalCurrent: current.length,
      locations: countBy(current, (j) => j.location ?? 'Unspecified'),
      categories: countBy(current, (j) => j.department ?? 'Other'),
      jobs,
      history: spec.hiringHistory ?? [],
      verifiedAt: spec.researchedAt ?? NOW,
      searchedSourceIds: ['nav', ...(spec.domain ? [`web-${spec.org}`] : [])],
      message: current.length === 0 ? 'No current verified job openings were found in the searched sources.' : undefined,
    };
  }

  /* ------------------------------ activity ------------------------------ */
  c.section = 'activity';
  const events: TimelineEvent[] = spec.events
    .slice()
    .sort((a, b) => b.date.localeCompare(a.date))
    .map((e, i) => ({
      id: `${spec.org}-ev${i}`,
      date: e.date,
      type: e.type,
      title: e.title,
      description: e.description,
      significance: (e.major ?? MAJOR_EVENT_TYPES.includes(e.type)) ? ('major' as const) : ('minor' as const),
      sourceIds: [c.srcId(e.sourceId)],
      evidence: [c.ev(e.sourceId, { documentTitle: e.title, excerpt: e.excerpt ?? e.description, retrievedAt: `${e.date}T12:00:00Z` })],
    }));
  const activity: CompanyProfile['activity'] = spec.activityFailed
    ? { status: 'partial', message: 'Doffin (public procurement) did not respond. Events from other sources are shown.', events }
    : events.length
      ? { status: 'available', events }
      : { status: 'not_available', message: 'No verified major public changes were found in the searched sources.', events: [] };

  /* ------------------------------ changes ------------------------------- */
  c.section = 'changes';
  const changes: Change[] = spec.changes.map((ch, i) => {
    const prevN = Number(ch.previous?.replace(/[^\d.-]/g, ''));
    const curN = Number(ch.current?.replace(/[^\d.-]/g, ''));
    const numeric = ch.kind === 'modified' && ch.previous != null && ch.current != null && Number.isFinite(prevN) && Number.isFinite(curN) && /^\D*[\d\s.,]+\D*$/.test(ch.current ?? '');
    const direction: Change['direction'] = ch.kind === 'added' ? 'up' : ch.kind === 'removed' ? 'down' : numeric ? (curN > prevN ? 'up' : curN < prevN ? 'down' : undefined) : undefined;
    return {
      id: `${spec.org}-ch${i}`,
      detectedAt: ch.detectedAt,
      kind: ch.kind,
      category: ch.category,
      label: ch.label,
      previous: ch.previous,
      current: ch.current,
      headline: ch.headline ?? defaultHeadline(ch),
      material: ch.material ?? ch.category !== 'website',
      direction,
      explainable: ['financial', 'employees', 'hiring', 'leadership', 'status', 'location'].includes(ch.category),
      evidence: [c.ev(ch.sourceId, { documentTitle: ch.label, excerpt: ch.current ? `${ch.label}: ${ch.current}` : ch.label, retrievedAt: ch.detectedAt })],
    };
  });

  /* ------------------------------ relationships ------------------------- */
  c.section = 'relationships';
  const relationships: Relationship[] = [
    ...people
      .filter((p) => p.current && (p.roleGroup === 'executive' || p.roleGroup === 'board'))
      .map((p) => ({
        id: `${p.id}-rel`,
        kind: (p.role === 'CEO' ? 'ceo' : 'board') as RelationshipKind,
        label: p.role,
        entity: { type: 'person' as const, name: p.name },
        evidence: p.fact.evidence.slice(0, 1),
      })),
    ...spec.relationships.map((r, i) => ({
      id: `${spec.org}-rel${i}`,
      kind: r.kind,
      label: r.label,
      entity: { type: r.type, name: r.name, orgNumber: r.orgNumber },
      evidence: [c.ev(r.sourceId, { documentTitle: r.label, excerpt: `${r.label}: ${r.name}${r.orgNumber ? ` (${r.orgNumber})` : ''}` })],
    })),
  ];

  /* ------------------------------ key metrics --------------------------- */
  c.section = 'overview';
  const keyMetrics: Fact[] = [];
  const lr = latest('revenue');
  if (lr) keyMetrics.push(lr.fact);
  const lo = latest('operating_result');
  if (lo) keyMetrics.push(lo.fact);
  const la = latest('annual_result');
  if (la) keyMetrics.push(la.fact);
  keyMetrics.push(
    spec.employeesNow != null
      ? c.fact('overview.employees', 'Employees', spec.employeesNow, {
          unit: 'people',
          evidence: [
            c.ev('brreg', { ...regDoc, excerpt: `Antall ansatte: ${spec.employeesNow}`, excerptTranslation: `Number of employees: ${spec.employeesNow}` }),
            ...(spec.linkedinBlocked ? [] : [c.ev('linkedin', { documentTitle: `${spec.name} — LinkedIn`, excerpt: `${bucket(spec.employeesNow)} employees` })]),
          ],
        })
      : c.fact('overview.employees', 'Employees', null, { evidence: [], note: 'Employee count not reported in the registry.' }),
  );
  keyMetrics.push(identity.founded!);
  keyMetrics.push(
    c.fact('overview.locations', 'Locations', new Set(locations.filter((l) => l.verified && l.kind !== 'postal').map((l) => l.municipality)).size, {
      unit: 'sites',
      evidence: locations.flatMap((l) => l.fact.evidence.slice(0, 1)).slice(0, 4),
      evidenceState: 'verified',
    }),
  );
  keyMetrics.push(
    hiring.totalCurrent != null
      ? c.fact('overview.openPositions', 'Open positions', hiring.totalCurrent, {
          unit: 'roles',
          evidence: hiring.jobs.slice(0, 3).flatMap((j) => j.evidence),
          verifiedAt: hiring.verifiedAt,
        })
      : c.fact('overview.openPositions', 'Open positions', null, { evidence: [], note: 'No current verified openings found in searched sources.' }),
  );

  /* ------------------------------ coverage ------------------------------ */
  const areaState = (area: CoverageArea, status: CoverageAreaStatus, note?: string): CoverageAreaState => {
    const ov = spec.coverageOverride?.[area];
    return { area, status: ov?.status ?? status, note: ov?.note ?? note, factCount: 0 };
  };
  const areas: CoverageAreaState[] = [
    areaState('company_record', 'complete'),
    areaState('financials', hasFin ? (series.length >= 3 && revSeries!.points.length >= 2 ? 'complete' : 'partial') : 'unavailable', hasFin ? undefined : 'No filed annual accounts found'),
    areaState('people_locations', people.length ? 'complete' : 'partial'),
    areaState(
      'website',
      !spec.domain ? 'unavailable' : spec.websiteBlocked ? 'blocked' : 'complete',
      !spec.domain ? 'No official website verified' : spec.websiteBlocked ? 'Website blocked automated access' : undefined,
    ),
    areaState(
      'hiring_activity',
      spec.jobs === null ? (events.length ? 'partial' : 'unavailable') : spec.activityFailed ? 'partial' : 'complete',
      spec.jobs === null ? 'Hiring data unavailable' : spec.activityFailed ? 'A procurement source did not respond' : undefined,
    ),
  ];
  const areaSections: Record<CoverageArea, string[]> = {
    company_record: ['identity', 'overview'],
    financials: ['financials'],
    people_locations: ['people', 'locations'],
    website: ['website'],
    hiring_activity: ['hiring', 'activity'],
  };
  for (const a of areas) a.factCount = c.facts.filter((f) => areaSections[a.area].includes(c.factSections.get(f.id) ?? '')).length;
  const coverage: Coverage = { complete: areas.filter((a) => a.status === 'complete').length, total: 5, areas };

  /* ------------------------------ sources ------------------------------- */
  const usage = new Map<string, SourceUsage>();
  for (const f of c.facts) {
    for (const e of f.evidence) {
      const src = c.sources[e.sourceId];
      if (!src) continue;
      const u = usage.get(src.id) ?? { source: src, factCount: 0, lastRetrievedAt: e.retrievedAt, sections: [], evidenceIds: [] };
      u.factCount += 1;
      if (e.retrievedAt > u.lastRetrievedAt) u.lastRetrievedAt = e.retrievedAt;
      const sec = c.factSections.get(f.id) ?? 'overview';
      if (!u.sections.includes(sec)) u.sections.push(sec);
      if (!u.evidenceIds.includes(e.id)) u.evidenceIds.push(e.id);
      usage.set(src.id, u);
    }
  }
  for (const e of [...events.flatMap((x) => x.evidence), ...changes.flatMap((x) => x.evidence), ...hiring.jobs.flatMap((j) => j.evidence)]) {
    const src = c.sources[e.sourceId];
    if (!src) continue;
    const u = usage.get(src.id) ?? { source: src, factCount: 0, lastRetrievedAt: e.retrievedAt, sections: [], evidenceIds: [] };
    if (!u.evidenceIds.includes(e.id)) {
      u.evidenceIds.push(e.id);
      u.factCount += 1;
    }
    usage.set(src.id, u);
  }
  const sources = [...usage.values()].sort((a, b) => tierRank(a.source.tier) - tierRank(b.source.tier) || b.factCount - a.factCount);
  const sourceIndex: Record<string, Source> = {};
  for (const s of Object.values(c.sources)) sourceIndex[s.id] = s;

  /* ------------------------------ knowns -------------------------------- */
  const founder = people.find((p) => p.roleGroup === 'founder');
  const ceo = people.find((p) => p.role === 'CEO' && p.current);
  const knowns: KnownItem[] = [
    { id: 'k-identity', label: 'Identity', text: `Matched to org. no. ${spec.org} in the registry.`, status: 'verified', factId: identity.legalName.id },
    ceo
      ? { id: 'k-ceo', label: 'CEO', text: `${ceo.name}, registered${ceo.since ? ` since ${ceo.since}` : ''}.`, status: 'verified', factId: ceo.fact.id }
      : { id: 'k-ceo', label: 'CEO', text: 'Not verified in searched permitted sources.', status: 'unknown' },
    lr
      ? { id: 'k-rev', label: 'Latest revenue', text: `${lr.period} figure from filed annual accounts.`, status: lr.fact.conflict ? 'conflict' : 'verified', factId: lr.fact.id }
      : { id: 'k-rev', label: 'Revenue', text: 'No filed annual accounts found.', status: 'unknown' },
    founder
      ? { id: 'k-founder', label: 'Founder', text: founder.name, status: 'verified', factId: founder.fact.id }
      : { id: 'k-founder', label: 'Founder', text: 'Not verified in searched permitted sources.', status: 'unknown' },
    hiring.totalCurrent != null
      ? { id: 'k-hiring', label: 'Current hiring', text: `${hiring.totalCurrent} verified opening${hiring.totalCurrent === 1 ? '' : 's'}.`, status: 'verified' }
      : { id: 'k-hiring', label: 'Current hiring', text: 'No current verified openings found in searched sources.', status: 'unknown' },
    spec.websiteBlocked
      ? { id: 'k-web', label: 'Website content', text: 'Source access blocked.', status: 'blocked' }
      : spec.domain
        ? { id: 'k-web', label: 'Official website', text: `${spec.domain}, ownership verified.`, status: 'verified' }
        : { id: 'k-web', label: 'Official website', text: 'Not verified in searched permitted sources.', status: 'unknown' },
    { id: 'k-hq', label: 'Headquarters', text: hq ? `${hq.municipality} (verified).` : 'Only the registered address is known; headquarters not verified.', status: hq ? 'verified' : 'unknown' },
  ];

  /* ------------------------------ assemble ------------------------------ */
  const company: CompanySummary = {
    orgNumber: spec.org,
    legalName: spec.name,
    municipality: spec.municipality,
    county: muni?.county,
    country: 'Norway',
    industry: { code: spec.nace.code, description: spec.nace.description },
    status: spec.status,
    statusLabel: spec.statusLabel ?? statusLabel(spec.status),
    employees: spec.employeesNow,
    revenue: lr ? { value: lr.fact.value!, currency: 'NOK', period: lr.period } : null,
    openPositions: hiring.totalCurrent,
    coverage,
    lastResearchedAt: spec.researchedAt,
    researchState: spec.researchedAt ? 'researched' : 'not_researched',
    website: spec.domain,
    geo: muni ? { lat: muni.lat, lon: muni.lon } : null,
    changeCount: changes.filter((ch) => !spec.changesSince || ch.detectedAt >= spec.changesSince).length,
    tags: spec.tags ?? [],
  };

  const primaryEvidence = c.evidence.filter((e) => c.sources[e.sourceId]?.tier === 'primary');
  return {
    company,
    identity,
    summary: spec.researchedAt
      ? {
          text: spec.summary,
          sourceIds: [...new Set(primaryEvidence.map((e) => e.sourceId))].slice(0, 5),
          evidenceIds: primaryEvidence.slice(0, 6).map((e) => e.id),
          generatedAt: spec.researchedAt,
        }
      : null,
    description,
    keyMetrics,
    financials: hasFin
      ? { status: 'available', currency: 'NOK', latestPeriod: `FY${lastYear}`, series, ratios, ratioHistory }
      : { status: 'not_available', message: 'No filed annual accounts were found for this company.', currency: 'NOK', series: [], ratios: [], searchedSourceIds: ['accounts', 'proff'] },
    people: people.length
      ? { status: spec.linkedinBlocked ? 'partial' : 'available', people, message: spec.linkedinBlocked ? 'LinkedIn blocked automated access; roles shown are from the official registry.' : undefined }
      : { status: 'not_available', people: [], message: 'No registered roles found.' },
    locations: { status: 'available', locations },
    website,
    hiring,
    activity,
    changes: changes.length
      ? { status: 'available', since: spec.changesSince, baselineLabel: spec.changesSince ? 'previous research' : undefined, changes }
      : { status: 'not_available', message: 'No verified material changes were detected since the previous research.', since: spec.changesSince, baselineLabel: spec.changesSince ? 'previous research' : undefined, changes: [] },
    relationships,
    sources,
    sourceIndex,
    quality: {
      coverage,
      primarySources: sources.filter((s) => s.source.tier === 'primary').length,
      secondarySources: sources.filter((s) => s.source.tier !== 'primary').length,
      conflicts: c.facts.filter((f) => f.conflict).length,
      lastRefreshedAt: spec.researchedAt,
    },
    knowns,
  };
}

/** Registry-only view for companies that have not been researched yet. */
export function registryOnly(profile: CompanyProfile): CompanyProfile {
  const pendingMsg = 'Not researched yet. Run research to gather this area from public sources.';
  const areas = profile.company.coverage.areas.map((a) =>
    a.area === 'company_record' || a.area === 'financials' ? a : { ...a, status: 'pending' as const, note: 'Not researched yet', factCount: 0 },
  );
  const coverage = { complete: areas.filter((a) => a.status === 'complete').length, total: 5, areas };
  return {
    ...profile,
    company: { ...profile.company, coverage, researchState: 'not_researched', lastResearchedAt: null, openPositions: null, changeCount: 0 },
    summary: null,
    description: undefined,
    keyMetrics: profile.keyMetrics.filter((f) => !f.field.startsWith('overview.openPositions') && !f.field.startsWith('overview.locations')),
    people: { status: 'pending', people: [], message: pendingMsg },
    locations: { status: 'available', locations: profile.locations.locations.filter((l) => l.kind === 'registered_address') },
    website: { status: 'pending', message: pendingMsg, pages: [], social: [], signals: [] },
    hiring: { status: 'pending', message: pendingMsg, totalCurrent: null, locations: [], categories: [], jobs: [], history: [] },
    activity: { status: 'pending', message: pendingMsg, events: [] },
    changes: { status: 'pending', message: pendingMsg, changes: [] },
    relationships: [],
    sources: profile.sources.filter((s) => s.source.id === 'brreg' || s.source.id === 'accounts'),
    quality: { ...profile.quality, coverage, primarySources: 2, secondarySources: 0, conflicts: 0, lastRefreshedAt: null },
    knowns: profile.knowns.map((k) => (k.id === 'k-identity' || k.id === 'k-rev' ? k : { ...k, status: 'unknown' as const, text: 'Not researched yet.', factId: undefined })),
  };
}

/* -------------------------------------------------------------------------- */
const MAJOR_EVENT_TYPES: TimelineEventType[] = ['filing', 'leadership', 'acquisition', 'location', 'contract', 'funding', 'registration'];

function defaultHeadline(ch: ChangeSpec): string {
  switch (ch.category) {
    case 'leadership':
      return `${ch.label} changed`;
    case 'status':
      return 'Legal status changed';
    case 'financial':
      return `${ch.label.replace(/\s*\(.*\)$/, '')} updated`;
    case 'filing':
      return 'New annual filing';
    case 'ownership':
      return 'Ownership changed';
    case 'location':
    case 'address':
      return ch.kind === 'added' ? 'New location' : ch.kind === 'removed' ? 'Location closed' : 'Address changed';
    case 'hiring':
      return ch.previous && ch.current ? `Open positions ${ch.previous} → ${ch.current}` : 'Hiring changed';
    case 'employees':
      return ch.previous && ch.current ? `Employees ${ch.previous} → ${ch.current}` : 'Employee count changed';
    case 'website':
      return 'Website changed';
    default:
      return ch.label;
  }
}

function statusLabel(s: CompanyStatus) {
  return {
    active: 'Active',
    inactive: 'Inactive',
    dissolved: 'Dissolved',
    bankruptcy: 'Bankruptcy proceedings',
    under_liquidation: 'Under liquidation',
    other: 'Other',
  }[s];
}
function round1(n: number) {
  return Math.round(n * 10) / 10;
}
function slug(s: string) {
  return s
    .toLowerCase()
    .replace(/æ/g, 'ae')
    .replace(/ø/g, 'o')
    .replace(/å/g, 'a')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '');
}
function bucket(n: number) {
  if (n <= 10) return '2-10';
  if (n <= 50) return '11-50';
  if (n <= 200) return '51-200';
  if (n <= 500) return '201-500';
  if (n <= 1000) return '501-1,000';
  return '1,001-5,000';
}
function tierRank(t: string) {
  return t === 'primary' ? 0 : t === 'secondary' ? 1 : 2;
}
function countBy<T>(items: T[], key: (t: T) => string) {
  const m = new Map<string, number>();
  for (const i of items) m.set(key(i), (m.get(key(i)) ?? 0) + 1);
  return [...m.entries()].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count);
}
export { slug };
