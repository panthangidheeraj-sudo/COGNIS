/**
 * MOCK BACKEND — fixture companies.
 * ALL companies, people, addresses and figures below are FICTIONAL demo data
 * designed to exercise every UI state:
 *   complete · partial · ambiguous · blocked · conflicting · changing · many
 */
import type { CompanySpec, JobSpec, PersonSpec, Sector } from './profileBuilder';
import { slug } from './profileBuilder';
import { MUNICIPALITIES } from './geo';

/* ------------------------------ seeded RNG -------------------------------- */
function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const NACE: Record<Sector, { code: string; description: string; original: string }> = {
  saas: { code: '58.290', description: 'Software publishing', original: 'Utgivelse av annen programvare' },
  software: { code: '62.010', description: 'Computer programming', original: 'Programmeringstjenester' },
  healthtech: { code: '62.010', description: 'Computer programming', original: 'Programmeringstjenester' },
  medtech: { code: '32.500', description: 'Medical and dental instruments', original: 'Produksjon av medisinske og tanntekniske instrumenter og utstyr' },
  logistics: { code: '49.410', description: 'Freight transport by road', original: 'Godstransport på vei' },
  energy: { code: '35.110', description: 'Production of electricity', original: 'Produksjon av elektrisitet' },
  seafood: { code: '03.211', description: 'Marine aquaculture', original: 'Produksjon av matfisk og skalldyr i hav- og kystbasert akvakultur' },
  maritime: { code: '50.201', description: 'Sea and coastal freight', original: 'Utenriks sjøfart med gods' },
  fintech: { code: '66.190', description: 'Other activities auxiliary to financial services', original: 'Andre tjenester tilknyttet finansieringsvirksomhet' },
  construction: { code: '41.200', description: 'Construction of buildings', original: 'Oppføring av bygninger' },
  consulting: { code: '70.220', description: 'Business and management consultancy', original: 'Bedriftsrådgivning og annen administrativ rådgivning' },
  data: { code: '63.110', description: 'Data processing and hosting', original: 'Databehandling, databaselagring og tilknyttede tjenester' },
};

/** Keyword groups the mock interpreter maps natural language onto. */
export const SECTOR_KEYWORDS: Record<Sector, string[]> = {
  saas: ['saas', 'software', 'technology', 'tech'],
  software: ['software', 'technology', 'tech', 'it'],
  healthtech: ['health', 'healthcare', 'technology', 'tech', 'software'],
  medtech: ['medtech', 'medical', 'health', 'healthcare'],
  logistics: ['logistics', 'transport', 'freight'],
  energy: ['energy', 'power', 'renewable'],
  seafood: ['seafood', 'aquaculture', 'fish', 'salmon'],
  maritime: ['maritime', 'shipping', 'ocean'],
  fintech: ['fintech', 'finance', 'payments', 'financial', 'technology', 'tech'],
  construction: ['construction', 'building', 'real estate'],
  consulting: ['consulting', 'advisory'],
  data: ['data', 'hosting', 'technology', 'tech', 'cloud'],
};

const M = 1_000_000;
const RESEARCHED = '2026-10-03T10:32:00Z';

/* ============================== Scenario companies ============================== */

const NORDVIK_JOBS: JobSpec[] = [
  { title: 'Senior backend developer (Kotlin)', department: 'Engineering', location: 'Bodø', postedAt: '2026-09-29' },
  { title: 'Product manager — clinical workflows', department: 'Product', location: 'Oslo', postedAt: '2026-09-28' },
  { title: 'DevOps engineer', department: 'Engineering', location: 'Bodø', postedAt: '2026-09-27', sourceId: 'web' },
  { title: 'UX designer', department: 'Design', location: 'Oslo', postedAt: '2026-09-26' },
  { title: 'Clinical application specialist', department: 'Customer', location: 'Tromsø', postedAt: '2026-09-24' },
  { title: 'Frontend developer (React)', department: 'Engineering', location: 'Trondheim', postedAt: '2026-09-22', sourceId: 'web' },
  { title: 'Data engineer', department: 'Engineering', location: 'Oslo', postedAt: '2026-09-20' },
  { title: 'QA engineer', department: 'Engineering', location: 'Bodø', postedAt: '2026-09-18' },
  { title: 'Customer success manager', department: 'Customer', location: 'Bergen', postedAt: '2026-09-15' },
  { title: 'Security engineer', department: 'Engineering', location: 'Oslo', postedAt: '2026-09-12', sourceId: 'web' },
  { title: 'Integration developer (HL7 / FHIR)', department: 'Engineering', location: 'Bodø', postedAt: '2026-09-10' },
  { title: 'Technical writer', department: 'Product', location: 'Trondheim', postedAt: '2026-09-08' },
  { title: 'Sales engineer', department: 'Sales', location: 'Oslo', postedAt: '2026-06-02', state: 'stale' },
];

export const NORDVIK: CompanySpec = {
  org: '921604337',
  name: 'Nordvik Helseteknologi AS',
  legalForm: 'AS',
  municipality: 'Bodø',
  address: 'Sjøgata 21',
  postalCode: '8006',
  nace: NACE.healthtech,
  sector: 'healthtech',
  status: 'active',
  founded: '1999-03-12',
  domain: 'nordvikhelse.no',
  description:
    'Nordvik Helseteknologi develops electronic patient record and clinical workflow software used by hospitals and municipal health services in Norway.',
  summary:
    'Nordvik Helseteknologi AS is a Bodø-based healthcare software company building electronic patient record and clinical workflow systems for hospitals and municipal health services. It reported revenue of NOK 790.4 million for FY2025, up 6.5% from FY2024, with an operating result of NOK 83.9 million. The registry lists 365 employees. Ingrid Solberg became CEO on 1 September 2026, and the company registered new workplaces in Oslo and Kristiansand in September. It currently has 12 verified open positions, mostly in engineering.',
  years: [2021, 2022, 2023, 2024, 2025],
  revenue: [512.3 * M, 588.9 * M, 620.4 * M, 742.1 * M, 790400865],
  operating: [41.2 * M, 52.8 * M, 49.6 * M, 71.3 * M, 83.9 * M],
  result: [30.1 * M, 39.5 * M, 36.2 * M, 54.8 * M, 64.2 * M],
  assets: [401 * M, 455 * M, 498 * M, 571 * M, 612 * M],
  equity: [170 * M, 196 * M, 214 * M, 251 * M, 288 * M],
  debt: [231 * M, 259 * M, 284 * M, 320 * M, 324 * M],
  cash: [88 * M, 97 * M, 104 * M, 126 * M, 141 * M],
  avgEmployees: [236, 255, 278, 304, 331],
  employeesNow: 365,
  people: [
    { name: 'Ingrid Solberg', role: 'CEO', group: 'executive', since: '2026-09-01', otherRoles: [{ companyName: 'Polarlys Medtech AS', role: 'Board member', current: true }] },
    { name: 'Henrik Aas', role: 'CEO', group: 'executive', since: '2014-01-01', until: '2026-08-31', current: false },
    { name: 'Kari Lunde', role: 'Chair of the board', group: 'board', since: '2021-05-20' },
    { name: 'Per Iversen', role: 'Board member', group: 'board', since: '2019-06-01' },
    { name: 'Mette Dahl', role: 'Board member', group: 'board', since: '2022-05-18' },
    { name: 'Jonas Berg', role: 'Board member', group: 'board', since: '2024-05-22' },
  ],
  locations: [
    { kind: 'headquarters', label: 'Headquarters (verified)', address: 'Sjøgata 21', municipality: 'Bodø', verified: true },
    { kind: 'operating', label: 'Operating location', address: 'Storgata 88', municipality: 'Tromsø', verified: true },
    { kind: 'operating', label: 'Operating location', address: 'Kongens gate 30', municipality: 'Trondheim', verified: true },
    { kind: 'operating', label: 'Operating location', address: 'Lars Hilles gate 19', municipality: 'Bergen', verified: true },
    { kind: 'operating', label: 'Operating location (new)', address: 'Dronning Eufemias gate 16', municipality: 'Oslo', verified: true, sourceId: 'brreg' },
    { kind: 'operating', label: 'Operating location (new)', address: 'Markens gate 5', municipality: 'Kristiansand', verified: true, sourceId: 'brreg' },
  ],
  jobs: NORDVIK_JOBS,
  hiringHistory: [
    { month: '2026-04', count: 3 },
    { month: '2026-05', count: 2 },
    { month: '2026-06', count: 4 },
    { month: '2026-07', count: 2 },
    { month: '2026-08', count: 2 },
    { month: '2026-09', count: 7 },
    { month: '2026-10', count: 12 },
  ],
  events: [
    { date: '2026-09-28', type: 'jobs', title: 'Six new job postings', description: 'Engineering, product and design roles in Oslo, Bodø and Tromsø.', sourceId: 'nav', major: true },
    { date: '2026-09-22', type: 'location', title: 'New workplace registered: Kristiansand', sourceId: 'brreg', excerpt: 'Ny underenhet registrert: Markens gate 5, 4611 Kristiansand' },
    { date: '2026-09-18', type: 'announcement', title: 'Product update published: clinical workflow module', description: 'Release notes on the company website.', sourceId: 'web' },
    { date: '2026-09-10', type: 'location', title: 'New workplace registered: Oslo', sourceId: 'brreg', excerpt: 'Ny underenhet registrert: Dronning Eufemias gate 16, 0191 Oslo' },
    { date: '2026-09-01', type: 'leadership', title: 'New CEO registered', description: 'Ingrid Solberg registered as CEO (daglig leder), succeeding Henrik Aas.', sourceId: 'announcements', excerpt: 'Endring i roller: Daglig leder Ingrid Solberg' },
    { date: '2026-08-14', type: 'contract', title: 'Public contract award', description: 'Framework agreement for clinical documentation software with a regional health trust.', sourceId: 'doffin' },
    { date: '2026-07-03', type: 'jobs', title: 'Two job postings', description: 'Customer success and integration roles.', sourceId: 'nav' },
    { date: '2026-06-10', type: 'filing', title: 'Annual accounts FY2025 filed', sourceId: 'accounts', excerpt: 'Årsregnskap 2025 mottatt' },
    { date: '2026-05-27', type: 'registration', title: 'Board re-elected at annual general meeting', description: 'No change in board members.', sourceId: 'announcements', major: false },
    { date: '2025-06-12', type: 'filing', title: 'Annual accounts FY2024 filed', sourceId: 'accounts', excerpt: 'Årsregnskap 2024 mottatt' },
    { date: '2025-02-03', type: 'acquisition', title: 'Acquired Medisync AS', description: 'Merger registered with subsidiary Medisync AS.', sourceId: 'announcements', excerpt: 'Fusjon registrert: Medisync AS' },
  ],
  changesSince: '2026-08-21T09:00:00Z',
  changes: [
    { detectedAt: '2026-10-03T10:31:00Z', kind: 'modified', category: 'employees', label: 'Employee count', previous: '312', current: '365', sourceId: 'brreg' },
    { detectedAt: '2026-10-03T10:31:00Z', kind: 'modified', category: 'hiring', label: 'Open positions', previous: '2', current: '12', sourceId: 'nav' },
    { detectedAt: '2026-09-22T08:00:00Z', kind: 'added', category: 'location', label: 'New workplace', current: 'Kristiansand', sourceId: 'brreg' },
    { detectedAt: '2026-09-18T08:00:00Z', kind: 'modified', category: 'website', label: 'Website newsroom', previous: '14 posts', current: '15 posts', sourceId: 'web', material: false },
    { detectedAt: '2026-09-10T08:00:00Z', kind: 'added', category: 'location', label: 'New workplace', current: 'Oslo', sourceId: 'brreg' },
    { detectedAt: '2026-09-01T08:00:00Z', kind: 'modified', category: 'leadership', label: 'CEO', previous: 'Henrik Aas', current: 'Ingrid Solberg', sourceId: 'roles' },
    { detectedAt: '2026-08-14T08:00:00Z', kind: 'added', category: 'event', label: 'Public contract award', current: 'Clinical documentation framework agreement', sourceId: 'doffin', headline: 'Public contract awarded' },
  ],
  reported: [
    {
      subject: 'revenue',
      sourceId: 'accounts',
      documentTitle: 'Årsberetning 2025 — Nordvik Helseteknologi AS',
      text: 'The board’s report attributes FY2025 revenue growth to new municipal customers and a full year of Medisync AS after the merger.',
      quote: 'Økningen i driftsinntekter skyldes hovedsakelig nye kommunekunder og helårseffekt av fusjonen med Medisync AS.',
      quoteLanguage: 'no',
      date: '2026-06-10',
    },
    {
      subject: 'employees',
      sourceId: 'web',
      documentTitle: 'Careers — Nordvik Helseteknologi',
      text: 'The company’s careers page says it is expanding its engineering teams in Oslo and Bodø.',
      quote: 'We are growing our engineering teams in Oslo and Bodø to deliver the next generation of clinical workflows.',
      date: '2026-09-29',
    },
    {
      subject: 'hiring',
      sourceId: 'web',
      documentTitle: 'Careers — Nordvik Helseteknologi',
      text: 'The company’s careers page says it is expanding its engineering teams in Oslo and Bodø.',
      quote: 'We are growing our engineering teams in Oslo and Bodø to deliver the next generation of clinical workflows.',
      date: '2026-09-29',
    },
    {
      subject: 'leadership',
      sourceId: 'announcements',
      documentTitle: 'Kunngjøring: endring i roller',
      text: 'The registry announcement records Ingrid Solberg as the new daily manager; a company news post describes it as a planned succession.',
      quote: 'Henrik Aas går av etter tolv år som daglig leder, som planlagt. Ingrid Solberg tiltrer 1. september.',
      quoteLanguage: 'no',
      date: '2026-09-01',
    },
  ],
  relationships: [
    { kind: 'subsidiary', label: 'Subsidiary', type: 'organization', name: 'Nordvik Helse Sverige AB', sourceId: 'announcements' },
    { kind: 'subsidiary', label: 'Subsidiary (merged 2025)', type: 'organization', name: 'Medisync AS', orgNumber: '915338204', sourceId: 'announcements' },
    { kind: 'parent', label: 'Parent company', type: 'organization', name: 'Nordvik Holding AS', orgNumber: '921604221', sourceId: 'brreg' },
    { kind: 'partner', label: 'Contract partner', type: 'organization', name: 'Regional health trust (public buyer)', sourceId: 'doffin' },
  ],
  social: [
    { network: 'linkedin', handle: 'nordvik-helseteknologi' },
    { network: 'github', handle: 'nordvikhelse' },
  ],
  pagesFound: ['about', 'products', 'contact', 'careers', 'news', 'sustainability'],
  researchedAt: RESEARCHED,
  tags: ['Healthcare', 'Prospect'],
};

function genJobs(seed: number, count: number, cities: string[], start = '2026-09-30'): JobSpec[] {
  const r = mulberry32(seed);
  const roles: [string, string][] = [
    ['Backend developer', 'Engineering'],
    ['Frontend developer', 'Engineering'],
    ['Platform engineer', 'Engineering'],
    ['Data scientist', 'Data'],
    ['Product designer', 'Design'],
    ['Account executive', 'Sales'],
    ['Customer success manager', 'Customer'],
    ['Product manager', 'Product'],
    ['Site reliability engineer', 'Engineering'],
    ['Security analyst', 'Engineering'],
    ['Finance controller', 'Finance'],
    ['Solutions architect', 'Sales'],
    ['Operations coordinator', 'Operations'],
    ['HR partner', 'People'],
  ];
  const out: JobSpec[] = [];
  const d0 = new Date(`${start}T00:00:00Z`).getTime();
  for (let i = 0; i < count; i++) {
    const [title, dept] = roles[Math.floor(r() * roles.length)];
    const lvl = r() < 0.35 ? 'Senior ' : r() < 0.15 ? 'Lead ' : '';
    out.push({
      title: `${lvl}${lvl ? title.toLowerCase() : title}`,
      department: dept,
      location: cities[Math.floor(r() * cities.length)],
      postedAt: new Date(d0 - Math.floor(r() * 40) * 86400000).toISOString().slice(0, 10),
      sourceId: r() < 0.4 ? 'web' : 'nav',
    });
  }
  return out;
}

export const TINDRA: CompanySpec = {
  org: '918877231',
  name: 'Tindra Software AS',
  legalForm: 'AS',
  municipality: 'Oslo',
  address: 'Karl Johans gate 41',
  postalCode: '0162',
  nace: NACE.saas,
  sector: 'saas',
  status: 'active',
  founded: '2016-08-30',
  domain: 'tindra.io',
  description: 'Tindra builds a subscription platform for field-service scheduling used by utilities and facility-management companies across the Nordics.',
  summary:
    'Tindra Software AS is an Oslo-based SaaS company providing field-service scheduling software to utilities and facility-management firms in the Nordics. Revenue grew to NOK 246.7 million in FY2025 from NOK 201.4 million in FY2024. The registry lists 142 employees, and 28 verified openings were found across Oslo, Bergen and Stockholm-facing sales roles.',
  years: [2021, 2022, 2023, 2024, 2025],
  revenue: [88.2 * M, 121.5 * M, 158.9 * M, 201.4 * M, 246.7 * M],
  operating: [-12.4 * M, -6.1 * M, 4.8 * M, 18.9 * M, 31.2 * M],
  result: [-10.8 * M, -5.2 * M, 3.1 * M, 14.2 * M, 24.6 * M],
  assets: [96 * M, 132 * M, 171 * M, 214 * M, 262 * M],
  equity: [41 * M, 58 * M, 79 * M, 105 * M, 129 * M],
  debt: [55 * M, 74 * M, 92 * M, 109 * M, 133 * M],
  cash: [38 * M, 51 * M, 63 * M, 77 * M, 98 * M],
  avgEmployees: [61, 84, 102, 121, 136],
  employeesNow: 142,
  people: [
    { name: 'Sindre Hauge', role: 'CEO', group: 'executive', since: '2016-08-30' },
    { name: 'Sindre Hauge', role: 'Founder', group: 'founder', since: '2016-08-30' },
    { name: 'Live Strand', role: 'Chair of the board', group: 'board', since: '2020-03-10' },
    { name: 'Erik Nygård', role: 'Board member', group: 'board', since: '2021-06-15' },
    { name: 'Hanna Moe', role: 'Board member', group: 'board', since: '2023-06-01' },
  ],
  locations: [
    { kind: 'headquarters', label: 'Headquarters (verified)', address: 'Karl Johans gate 41', municipality: 'Oslo', verified: true },
    { kind: 'operating', label: 'Operating location', address: 'Strandkaien 2', municipality: 'Bergen', verified: true },
  ],
  jobs: genJobs(11, 28, ['Oslo', 'Oslo', 'Oslo', 'Bergen', 'Remote (Norway)']),
  hiringHistory: [
    { month: '2026-04', count: 14 },
    { month: '2026-05', count: 17 },
    { month: '2026-06', count: 19 },
    { month: '2026-07', count: 18 },
    { month: '2026-08', count: 22 },
    { month: '2026-09', count: 25 },
    { month: '2026-10', count: 28 },
  ],
  events: [
    { date: '2026-09-15', type: 'jobs', title: 'Hiring push in engineering', description: '9 new engineering roles posted.', sourceId: 'nav', major: true },
    { date: '2026-06-20', type: 'filing', title: 'Annual accounts FY2025 filed', sourceId: 'accounts' },
    { date: '2026-04-02', type: 'funding', title: 'Share capital increase registered', description: 'Capital increase registered in the Register of Business Enterprises.', sourceId: 'announcements' },
    { date: '2025-06-18', type: 'filing', title: 'Annual accounts FY2024 filed', sourceId: 'accounts' },
  ],
  changesSince: '2026-09-01T00:00:00Z',
  changes: [{ detectedAt: '2026-10-02T08:00:00Z', kind: 'modified', category: 'hiring', label: 'Open positions', previous: '22', current: '28', sourceId: 'nav' }],
  relationships: [{ kind: 'investor', label: 'Shareholder (registered)', type: 'organization', name: 'Fjordinvest Ventures AS', sourceId: 'announcements' }],
  researchedAt: '2026-09-29T14:05:00Z',
  tags: ['SaaS', 'Competitor'],
};

export const HAVBRIS: CompanySpec = {
  org: '914552108',
  name: 'Havbris Sjømat AS',
  legalForm: 'AS',
  municipality: 'Ålesund',
  address: 'Brosundet 4',
  postalCode: '6002',
  nace: NACE.seafood,
  sector: 'seafood',
  status: 'active',
  founded: '2004-11-02',
  domain: 'havbris.no',
  description: 'Havbris Sjømat farms Atlantic salmon at coastal sites in Møre og Romsdal and sells to European processors.',
  summary:
    'Havbris Sjømat AS is an aquaculture company in Ålesund farming Atlantic salmon. Filed annual accounts report FY2025 revenue of NOK 1,284.6 million, while a secondary source lists NOK 1,312.0 million for the same period; the difference is shown as a conflict. The registry lists 214 employees. Public procurement activity could not be checked because the source did not respond.',
  years: [2022, 2023, 2024, 2025],
  revenue: [968.2 * M, 1104.7 * M, 1196.3 * M, 1284.6 * M],
  operating: [182.4 * M, 241.9 * M, 205.3 * M, 228.8 * M],
  result: [133.1 * M, 178.6 * M, 151.2 * M, 169.4 * M],
  assets: [1520 * M, 1688 * M, 1795 * M, 1902 * M],
  equity: [702 * M, 811 * M, 866 * M, 934 * M],
  avgEmployees: [188, 197, 205, 211],
  employeesNow: 214,
  revenueConflict: { value: 1312.0 * M, reason: 'Possible difference in accounting scope (company vs. group figures) or a later source update.' },
  activityFailed: true,
  people: [
    { name: 'Torstein Vik', role: 'CEO', group: 'executive', since: '2012-02-01' },
    { name: 'Anne Brekke', role: 'Chair of the board', group: 'board', since: '2018-05-30' },
    { name: 'Ola Sunde', role: 'Board member', group: 'board', since: '2015-05-28' },
  ],
  locations: [
    { kind: 'operating', label: 'Farming site', address: 'Storholmen', municipality: 'Ålesund', verified: true, sourceId: 'brreg' },
    { kind: 'operating', label: 'Office', address: 'Fannestrandvegen 12', municipality: 'Molde', verified: false },
  ],
  jobs: genJobs(23, 5, ['Ålesund', 'Molde']),
  events: [
    { date: '2026-06-25', type: 'filing', title: 'Annual accounts FY2025 filed', sourceId: 'accounts' },
    { date: '2026-03-14', type: 'announcement', title: 'New farming licence volume announced', sourceId: 'web', major: true },
  ],
  changesSince: '2026-06-01T08:00:00Z',
  changes: [
    { detectedAt: '2026-06-25T08:00:00Z', kind: 'modified', category: 'financial', label: 'Revenue (FY2025 accounts filed)', previous: 'NOK 1,196.3M (FY2024)', current: 'NOK 1,284.6M (FY2025)', sourceId: 'accounts', headline: 'Revenue updated' },
  ],
  relationships: [{ kind: 'parent', label: 'Parent company', type: 'organization', name: 'Havbris Holding AS', sourceId: 'brreg' }],
  researchedAt: '2026-09-15T09:12:00Z',
  tags: ['Seafood'],
};

export const FJELLMARK: CompanySpec = {
  org: '987112450',
  name: 'Fjellmark Logistikk AS',
  legalForm: 'AS',
  municipality: 'Trondheim',
  address: 'Heggstadmoen 18',
  postalCode: '7080',
  nace: NACE.logistics,
  sector: 'logistics',
  status: 'active',
  founded: '2004-05-17',
  domain: null,
  description: '',
  summary:
    'Fjellmark Logistikk AS is a road-freight company registered in Trondheim. Filed accounts for FY2024 and FY2025 are available; FY2025 revenue was NOK 143.8 million. No official website was verified, and no current job openings were found in the searched sources.',
  years: [2024, 2025],
  revenue: [131.2 * M, 143.8 * M],
  operating: [6.4 * M, 7.9 * M],
  result: [4.8 * M, 5.9 * M],
  employeesNow: 96,
  people: [
    { name: 'Rune Haugen', role: 'CEO', group: 'executive', since: '2010-01-01' },
    { name: 'Gunn Fjell', role: 'Chair of the board', group: 'board', since: '2004-05-17' },
  ],
  locations: [{ kind: 'operating', label: 'Terminal', address: 'Heggstadmoen 18', municipality: 'Trondheim', verified: true, sourceId: 'brreg' }],
  jobs: null,
  events: [{ date: '2026-07-01', type: 'filing', title: 'Annual accounts FY2025 filed', sourceId: 'accounts' }],
  changes: [],
  relationships: [],
  researchedAt: '2026-09-21T11:40:00Z',
  tags: ['Logistics'],
};

export const BRATTORA: CompanySpec = {
  org: '996450218',
  name: 'Brattøra Maritime AS',
  legalForm: 'AS',
  municipality: 'Trondheim',
  address: 'Pirsenteret, Brattørkaia 17',
  postalCode: '7010',
  nace: NACE.maritime,
  sector: 'maritime',
  status: 'active',
  founded: '2011-02-08',
  domain: 'brattora-maritime.no',
  websiteBlocked: true,
  linkedinBlocked: true,
  description: '',
  summary:
    'Brattøra Maritime AS is a Trondheim-registered sea-freight company. Registry and annual-account data are verified; FY2025 revenue was NOK 412.5 million. The company website and LinkedIn blocked automated access, so website content and online presence could not be verified.',
  years: [2021, 2022, 2023, 2024, 2025],
  revenue: [301.4 * M, 377.9 * M, 359.2 * M, 388.1 * M, 412.5 * M],
  operating: [22.1 * M, 41.6 * M, 28.7 * M, 31.9 * M, 35.2 * M],
  result: [15.3 * M, 30.2 * M, 19.9 * M, 22.4 * M, 26.1 * M],
  assets: [512 * M, 560 * M, 571 * M, 590 * M, 618 * M],
  equity: [188 * M, 214 * M, 228 * M, 241 * M, 259 * M],
  employeesNow: 58,
  people: [
    { name: 'Kjetil Rønning', role: 'CEO', group: 'executive', since: '2019-09-01' },
    { name: 'Siri Holm', role: 'Chair of the board', group: 'board', since: '2016-06-01' },
  ],
  locations: [],
  jobs: genJobs(31, 3, ['Trondheim']),
  events: [{ date: '2026-06-28', type: 'filing', title: 'Annual accounts FY2025 filed', sourceId: 'accounts' }],
  changes: [],
  relationships: [],
  researchedAt: '2026-09-30T16:20:00Z',
  tags: ['Maritime'],
};

export const KVARTSFJORD: CompanySpec = {
  org: '919340066',
  name: 'Kvartsfjord Energi AS',
  legalForm: 'AS',
  municipality: 'Stavanger',
  address: 'Kirkegata 9',
  postalCode: '4006',
  nace: NACE.energy,
  sector: 'energy',
  status: 'under_liquidation',
  statusLabel: 'Under liquidation',
  founded: '2017-04-21',
  domain: 'kvartsfjord.no',
  description: 'Kvartsfjord Energi developed small-scale hydropower projects in Rogaland.',
  summary:
    'Kvartsfjord Energi AS is a Stavanger-registered electricity producer. The registry records the company as under liquidation since 1 July 2026. FY2024 is the latest filed annual account, with revenue of NOK 18.2 million.',
  years: [2022, 2023, 2024],
  revenue: [24.9 * M, 21.4 * M, 18.2 * M],
  operating: [3.1 * M, -1.2 * M, -4.6 * M],
  result: [1.9 * M, -2.4 * M, -5.8 * M],
  employeesNow: 4,
  people: [
    { name: 'Lars Eide', role: 'CEO', group: 'executive', since: '2017-04-21' },
    { name: 'Advokatfirma (liquidator)', role: 'Liquidator', group: 'other', since: '2026-07-01' },
  ],
  locations: [],
  jobs: [],
  events: [
    { date: '2026-07-01', type: 'registration', title: 'Liquidation registered', sourceId: 'announcements', excerpt: 'Avvikling registrert' },
    { date: '2025-07-03', type: 'filing', title: 'Annual accounts FY2024 filed', sourceId: 'accounts' },
  ],
  changesSince: '2026-05-01T08:00:00Z',
  changes: [{ detectedAt: '2026-07-02T08:00:00Z', kind: 'modified', category: 'status', label: 'Legal status', previous: 'Active', current: 'Under liquidation', sourceId: 'brreg' }],
  reported: [
    {
      subject: 'status',
      sourceId: 'announcements',
      documentTitle: 'Kunngjøring: avvikling',
      text: 'The registry announcement states that the general meeting resolved to dissolve the company.',
      quote: 'Generalforsamlingen har vedtatt at selskapet skal oppløses og avvikles.',
      quoteLanguage: 'no',
      date: '2026-07-01',
    },
  ],
  relationships: [],
  researchedAt: '2026-08-02T08:10:00Z',
  tags: ['Energy'],
};

export const LUMEN: CompanySpec = {
  org: '922781540',
  name: 'Lumen Betaling AS',
  legalForm: 'AS',
  municipality: 'Oslo',
  address: 'Tjuvholmen allé 3',
  postalCode: '0252',
  nace: NACE.fintech,
  sector: 'fintech',
  status: 'active',
  founded: '2019-01-15',
  domain: 'lumenbetaling.no',
  description: 'Lumen Betaling provides account-to-account payment infrastructure for Nordic merchants and platforms.',
  summary:
    'Lumen Betaling AS is an Oslo-based payments company providing account-to-account payment infrastructure. FY2025 revenue was NOK 318.9 million with an operating result of NOK 12.4 million. The registry lists 210 employees and 9 verified openings were found.',
  years: [2021, 2022, 2023, 2024, 2025],
  revenue: [41.3 * M, 96.8 * M, 162.5 * M, 241.0 * M, 318.9 * M],
  operating: [-38.2 * M, -29.4 * M, -14.1 * M, -2.3 * M, 12.4 * M],
  result: [-36.9 * M, -28.0 * M, -13.2 * M, -1.1 * M, 9.8 * M],
  assets: [180 * M, 244 * M, 301 * M, 355 * M, 402 * M],
  equity: [121 * M, 153 * M, 176 * M, 190 * M, 214 * M],
  avgEmployees: [72, 118, 151, 187, 203],
  employeesNow: 210,
  people: [
    { name: 'Maria Lie', role: 'CEO', group: 'executive', since: '2021-03-01' },
    { name: 'Thomas Riise', role: 'Founder', group: 'founder', since: '2019-01-15' },
    { name: 'Thomas Riise', role: 'Chair of the board', group: 'board', since: '2021-03-01' },
    { name: 'Nina Aasen', role: 'Board member', group: 'board', since: '2022-06-01' },
  ],
  locations: [{ kind: 'headquarters', label: 'Headquarters (verified)', address: 'Tjuvholmen allé 3', municipality: 'Oslo', verified: true }],
  jobs: genJobs(41, 9, ['Oslo']),
  events: [
    { date: '2026-06-18', type: 'filing', title: 'Annual accounts FY2025 filed', sourceId: 'accounts' },
    { date: '2026-02-10', type: 'announcement', title: 'Payment-institution licence update announced', sourceId: 'web' },
  ],
  changes: [],
  relationships: [{ kind: 'investor', label: 'Shareholder (registered)', type: 'organization', name: 'Nordlig Kapital AS', sourceId: 'announcements' }],
  researchedAt: '2026-09-25T10:00:00Z',
  tags: ['Fintech'],
};

export const POLARLYS: CompanySpec = {
  org: '925116702',
  name: 'Polarlys Medtech AS',
  legalForm: 'AS',
  municipality: 'Tromsø',
  address: 'Sykehusvegen 23',
  postalCode: '9019',
  nace: NACE.medtech,
  sector: 'medtech',
  status: 'active',
  founded: '2020-06-04',
  domain: 'polarlysmedtech.no',
  description: 'Polarlys Medtech develops portable ultrasound accessories and image-analysis software for primary care.',
  summary:
    'Polarlys Medtech AS is a Tromsø-based medical device company developing portable ultrasound accessories and image-analysis software. FY2025 revenue was NOK 61.7 million. The registry lists 86 employees and 4 verified openings were found.',
  years: [2022, 2023, 2024, 2025],
  revenue: [12.4 * M, 27.9 * M, 44.6 * M, 61.7 * M],
  operating: [-21.5 * M, -14.0 * M, -6.2 * M, 1.4 * M],
  result: [-20.1 * M, -13.6 * M, -6.0 * M, 0.9 * M],
  assets: [88 * M, 104 * M, 121 * M, 139 * M],
  equity: [61 * M, 71 * M, 80 * M, 92 * M],
  avgEmployees: [38, 54, 71, 82],
  employeesNow: 86,
  people: [
    { name: 'Eirik Nilsen', role: 'CEO', group: 'executive', since: '2020-06-04' },
    { name: 'Ingrid Solberg', role: 'Board member', group: 'board', since: '2023-05-10' },
    { name: 'Camilla Rød', role: 'Chair of the board', group: 'board', since: '2022-05-12' },
  ],
  locations: [{ kind: 'headquarters', label: 'Headquarters (verified)', address: 'Sykehusvegen 23', municipality: 'Tromsø', verified: true }],
  jobs: genJobs(53, 4, ['Tromsø', 'Oslo']),
  events: [{ date: '2026-06-30', type: 'filing', title: 'Annual accounts FY2025 filed', sourceId: 'accounts' }],
  changes: [],
  relationships: [],
  researchedAt: '2026-09-12T13:00:00Z',
  tags: ['Healthcare', 'Watch'],
};

export const ISBRE: CompanySpec = {
  org: '927004418',
  name: 'Isbre Analyse AS',
  legalForm: 'AS',
  municipality: 'Bergen',
  address: 'Damsgårdsveien 131',
  postalCode: '5160',
  nace: NACE.data,
  sector: 'data',
  status: 'active',
  founded: '2021-09-14',
  domain: 'isbre.ai',
  description: 'Isbre Analyse builds analytics pipelines and dashboards for energy and utility customers.',
  summary:
    'Isbre Analyse AS is a Bergen-based data analytics company serving energy and utility customers. FY2025 revenue was NOK 34.2 million. The registry lists 41 employees and 6 verified openings were found.',
  years: [2022, 2023, 2024, 2025],
  revenue: [4.1 * M, 11.8 * M, 22.5 * M, 34.2 * M],
  operating: [-3.2 * M, -1.1 * M, 1.8 * M, 3.9 * M],
  result: [-2.9 * M, -1.0 * M, 1.4 * M, 3.0 * M],
  assets: [9 * M, 15 * M, 22 * M, 31 * M],
  equity: [4 * M, 6 * M, 9 * M, 13 * M],
  avgEmployees: [9, 19, 31, 39],
  employeesNow: 41,
  people: [
    { name: 'Vegard Lyngstad', role: 'CEO', group: 'executive', since: '2021-09-14' },
    { name: 'Vegard Lyngstad', role: 'Founder', group: 'founder', since: '2021-09-14' },
    { name: 'Tone Halvorsen', role: 'Chair of the board', group: 'board', since: '2021-09-14' },
  ],
  locations: [{ kind: 'headquarters', label: 'Headquarters (verified)', address: 'Damsgårdsveien 131', municipality: 'Bergen', verified: true }],
  jobs: genJobs(61, 6, ['Bergen', 'Oslo']),
  events: [{ date: '2026-06-29', type: 'filing', title: 'Annual accounts FY2025 filed', sourceId: 'accounts' }],
  changes: [],
  relationships: [],
  researchedAt: null,
  tags: [],
};

/** Ambiguity scenario: three similarly named entities. */
const solstadBase = (org: string, name: string, municipality: string, address: string, postal: string, sector: Sector, emp: number, rev: number[]): CompanySpec => ({
  org,
  name,
  legalForm: 'AS',
  municipality,
  address,
  postalCode: postal,
  nace: NACE[sector],
  sector,
  status: 'active',
  founded: '2013-03-01',
  domain: null,
  description: '',
  summary: `${name} is registered in ${municipality}.`,
  years: [2023, 2024, 2025].slice(-rev.length),
  revenue: rev.map((r) => r * M),
  operating: rev.map((r) => r * 0.06 * M),
  result: rev.map((r) => r * 0.045 * M),
  employeesNow: emp,
  people: [{ name: 'Bjørn Solstad', role: 'CEO', group: 'executive', since: '2013-03-01' }],
  locations: [],
  jobs: null,
  events: [],
  changes: [],
  relationships: [],
  researchedAt: null,
});
export const SOLSTAD_A = solstadBase('913775602', 'Solstad Data AS', 'Kongsberg', 'Kirkegata 1', '3616', 'software', 23, [18.1, 19.6, 21.3]);
export const SOLSTAD_B = solstadBase('920113457', 'Solstad Datasystemer AS', 'Drammen', 'Bragernes torg 6', '3017', 'consulting', 7, [5.2, 5.9]);
export const SOLSTAD_C = solstadBase('913775521', 'Solstad Data Holding AS', 'Kongsberg', 'Kirkegata 1', '3616', 'consulting', 0, [0.4]);

export const SCENARIOS: CompanySpec[] = [NORDVIK, TINDRA, HAVBRIS, FJELLMARK, BRATTORA, KVARTSFJORD, LUMEN, POLARLYS, ISBRE, SOLSTAD_A, SOLSTAD_B, SOLSTAD_C];

/* ============================== Generated companies ============================== */

const PREFIX = ['Nord', 'Fjell', 'Hav', 'Brein', 'Lys', 'Skog', 'Elv', 'Vind', 'Stein', 'Tind', 'Myr', 'Kyst', 'Fjord', 'Sol', 'Berg', 'Vik', 'Dal', 'Ask', 'Lind', 'Furu', 'Polar', 'Kvarts', 'Granitt', 'Bølge', 'Strand', 'Holm', 'Nes', 'Rein', 'Mjøl', 'Glimt'];
const SUFFIX = ['vik', 'heim', 'dal', 'berg', 'lia', 'mark', 'nes', 'stad', 'ås', 'voll', 'by', 'li', ''];
const WORD: Record<Sector, string[]> = {
  saas: ['Software', 'Cloud', 'Platform', 'Apps'],
  software: ['Data', 'Systemer', 'Utvikling', 'Teknologi'],
  healthtech: ['Helse', 'Helseteknologi', 'Care'],
  medtech: ['Medtech', 'Medisinsk', 'Diagnostics'],
  logistics: ['Logistikk', 'Transport', 'Frakt'],
  energy: ['Energi', 'Kraft', 'Vind'],
  seafood: ['Sjømat', 'Havbruk', 'Laks'],
  maritime: ['Maritime', 'Shipping', 'Rederi'],
  fintech: ['Betaling', 'Finans', 'Pay'],
  construction: ['Bygg', 'Entreprenør', 'Eiendom'],
  consulting: ['Rådgivning', 'Consulting', 'Partners'],
  data: ['Analyse', 'Innsikt', 'Data'],
};
const FIRST = ['Anders', 'Ingrid', 'Ole', 'Kari', 'Lars', 'Silje', 'Morten', 'Hilde', 'Even', 'Marte', 'Øyvind', 'Ragnhild', 'Sverre', 'Tuva', 'Håkon', 'Vilde', 'Geir', 'Sunniva', 'Trond', 'Astrid'];
const LAST = ['Hansen', 'Johansen', 'Olsen', 'Larsen', 'Andersen', 'Pedersen', 'Nilsen', 'Kristiansen', 'Jensen', 'Karlsen', 'Berntsen', 'Eriksen', 'Halvorsen', 'Moen', 'Strand', 'Bakke', 'Lie', 'Dahl', 'Myhre', 'Aune'];

const SECTOR_WEIGHTS: [Sector, number][] = [
  ['saas', 18],
  ['software', 16],
  ['healthtech', 8],
  ['medtech', 6],
  ['logistics', 8],
  ['energy', 7],
  ['seafood', 6],
  ['maritime', 5],
  ['fintech', 7],
  ['construction', 7],
  ['consulting', 6],
  ['data', 6],
];

function pick<T>(r: () => number, arr: T[]): T {
  return arr[Math.floor(r() * arr.length)];
}
function pickWeighted(r: () => number): Sector {
  const total = SECTOR_WEIGHTS.reduce((s, [, w]) => s + w, 0);
  let x = r() * total;
  for (const [s, w] of SECTOR_WEIGHTS) {
    if ((x -= w) <= 0) return s;
  }
  return 'software';
}

export function generateCompanies(count: number, seed = 20261003): CompanySpec[] {
  const r = mulberry32(seed);
  const used = new Set(SCENARIOS.map((s) => s.name));
  const out: CompanySpec[] = [];
  const muniWeights = MUNICIPALITIES.map((m, i) => ({ m, w: i < 4 ? 6 : i < 8 ? 2.5 : 1 }));
  const mw = muniWeights.reduce((s, x) => s + x.w, 0);
  while (out.length < count) {
    const sector = pickWeighted(r);
    const name = `${pick(r, PREFIX)}${pick(r, SUFFIX)} ${pick(r, WORD[sector])} AS`;
    if (used.has(name)) continue;
    used.add(name);
    let x = r() * mw;
    let muni = MUNICIPALITIES[0];
    for (const { m, w } of muniWeights) {
      if ((x -= w) <= 0) {
        muni = m;
        break;
      }
    }
    const size = Math.exp(r() * 6.2) * 3; // 3 .. ~1500 employees
    const emp = Math.max(1, Math.round(size));
    const revPerEmp = (1.1 + r() * 1.8) * M;
    const base = emp * revPerEmp;
    const nYears = r() < 0.12 ? 2 : r() < 0.25 ? 3 : 5;
    const years = [2021, 2022, 2023, 2024, 2025].slice(-nYears);
    const growth = 0.92 + r() * 0.3;
    const revenue = years.map((_, i) => Math.round(base / growth ** (nYears - 1 - i)));
    const margin = -0.08 + r() * 0.22;
    const operating = revenue.map((v) => Math.round(v * (margin + (r() - 0.5) * 0.04)));
    const result = operating.map((v) => Math.round(v * 0.76));
    const assets = revenue.map((v) => Math.round(v * (0.6 + r() * 0.5)));
    const equity = assets.map((v) => Math.round(v * (0.25 + r() * 0.35)));
    const avgEmployees = years.map((_, i) => Math.max(1, Math.round(emp / growth ** (nYears - 1 - i))));
    const hasDomain = r() < 0.86;
    const domain = hasDomain ? `${slug(name.replace(/ AS$/, '')).replace(/-/g, '')}.no` : null;
    const researched = r() < 0.42;
    const hiringN = emp > 30 ? Math.floor(r() * Math.min(30, emp / 6)) : r() < 0.3 ? 1 : 0;
    const jobsUnavailable = r() < 0.12;
    const ceo = `${pick(r, FIRST)} ${pick(r, LAST)}`;
    const chair = `${pick(r, FIRST)} ${pick(r, LAST)}`;
    const people: PersonSpec[] = [
      { name: ceo, role: 'CEO', group: 'executive', since: `20${10 + Math.floor(r() * 15)}-0${1 + Math.floor(r() * 9)}-01` },
      { name: chair, role: 'Chair of the board', group: 'board', since: `20${12 + Math.floor(r() * 12)}-05-1${Math.floor(r() * 9)}` },
    ];
    if (r() < 0.7) people.push({ name: `${pick(r, FIRST)} ${pick(r, LAST)}`, role: 'Board member', group: 'board', since: '2022-06-01' });
    const founded = `${1985 + Math.floor(r() * 39)}-0${1 + Math.floor(r() * 9)}-1${Math.floor(r() * 9)}`;
    const org = String(910000000 + Math.floor(r() * 89999999));
    const extraCity = r() < 0.35 ? pick(r, MUNICIPALITIES).name : null;
    const statusRoll = r();
    out.push({
      org,
      name,
      legalForm: emp > 800 && r() < 0.4 ? 'ASA' : 'AS',
      municipality: muni.name,
      address: `${pick(r, ['Storgata', 'Kirkegata', 'Industriveien', 'Havnegata', 'Strandgata', 'Sentrumsveien', 'Teknologiveien'])} ${1 + Math.floor(r() * 120)}`,
      postalCode: String(1000 + Math.floor(r() * 8900)).padStart(4, '0'),
      nace: NACE[sector],
      sector,
      status: statusRoll < 0.03 ? 'under_liquidation' : statusRoll < 0.045 ? 'bankruptcy' : 'active',
      founded,
      domain,
      description: `${name.replace(/ AS$/, '')} operates in ${NACE[sector].description.toLowerCase()} from ${muni.name}.`,
      summary: `${name} is registered in ${muni.name} under industry code ${NACE[sector].code} (${NACE[sector].description.toLowerCase()}). The latest filed accounts (FY${years.at(-1)}) report revenue of NOK ${(revenue.at(-1)! / M).toFixed(1)} million, and the registry lists ${emp} employees.`,
      years,
      revenue,
      operating,
      result,
      assets,
      equity,
      avgEmployees,
      employeesNow: emp,
      people,
      locations: [
        { kind: 'headquarters', label: 'Headquarters (verified)', address: 'Main office', municipality: muni.name, verified: !!domain },
        ...(extraCity && extraCity !== muni.name ? [{ kind: 'operating' as const, label: 'Operating location', address: 'Branch office', municipality: extraCity, verified: true, sourceId: 'brreg' }] : []),
      ],
      jobs: jobsUnavailable ? null : genJobs(Math.floor(r() * 1e6), hiringN, [muni.name, ...(extraCity ? [extraCity] : [])]),
      events: [
        { date: `${years.at(-1)! + 1}-06-${String(10 + Math.floor(r() * 19))}`, type: 'filing', title: `Annual accounts FY${years.at(-1)} filed`, sourceId: 'accounts' },
        ...(r() < 0.3 ? [{ date: '2026-08-1' + Math.floor(r() * 9), type: 'jobs' as const, title: 'New job postings', sourceId: 'nav' }] : []),
      ],
      changes:
        r() < 0.2
          ? [{ detectedAt: '2026-10-01T08:00:00Z', kind: 'modified', category: 'employees', label: 'Employee count', previous: String(Math.round(emp * 0.92)), current: String(emp), sourceId: 'brreg' }]
          : [],
      relationships: [],
      researchedAt: researched ? `2026-0${7 + Math.floor(r() * 3)}-${String(1 + Math.floor(r() * 27)).padStart(2, '0')}T09:00:00Z` : null,
    });
  }
  return out;
}

export const GENERATED = generateCompanies(150);
export const ALL_SPECS: CompanySpec[] = [...SCENARIOS, ...GENERATED];
