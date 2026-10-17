/**
 * MOCK BACKEND — deterministic stand-in for the grounded company chat.
 * Every sentence comes from `answerFromProfile`, so it only restates facts that exist in the profile, each with its own source.
 * It never claims a check it did not make: patents and shareholders are "unavailable", live news/regulators are "not checked" in mock mode.
 */
import type { ChatContext, ChatCoverageRow, ChatReply, ChatSource, CompanyProfile } from '@/types';
import { answerFromProfile } from './answers';

const SUGGESTIONS = [
  'How has its revenue changed?',
  'Who runs this company, and what is its corporate structure?',
  'What recent contracts has it won?',
  'What are its biggest recent developments?',
  'Does it have patents or regulatory issues?',
  'What risks should I investigate further?',
];

export function chatCoverage(p: CompanyProfile): ChatCoverageRow[] {
  const has = (b: boolean, ok = 'verified' as const, none = 'no_public_results_found' as const) => (b ? ok : none);
  return [
    { area: 'structure', label: 'Corporate structure and public roles (Enhetsregisteret)', status: has(p.people.people.length > 0), note: p.people.people.length ? 'Registered roles were read from the register.' : 'No registered roles were found.' },
    { area: 'ownership', label: 'Shareholders and ownership shares', status: 'unavailable', note: "Skatteetaten's shareholder register is released only on formal request; not used." },
    { area: 'financials', label: 'Financial statements (Regnskapsregisteret)', status: p.financials.series.length ? 'verified' : 'not_reported', note: p.financials.series.length ? 'Filed annual accounts were read.' : 'No filed annual accounts were found; not every company publishes accounts.' },
    { area: 'contracts', label: 'Procurement notices (TED, Doffin open data)', status: 'not_checked', note: 'Not checked in this demo data.' },
    { area: 'news', label: 'Company announcements and press coverage', status: has(p.activity.events.length > 0), note: p.activity.events.length ? 'Announcements were read.' : 'No public results were found in the checked sources.' },
    { area: 'regulatory', label: 'Regulators and public notices', status: 'not_checked', note: 'Not checked in this demo data.' },
    { area: 'ip', label: 'Patents, trademarks and designs (Patentstyret)', status: 'unavailable', note: 'Not used: Patentstyret requires a registered key.' },
  ];
}

export function chatContextFor(p: CompanyProfile): ChatContext {
  return {
    company: { orgNumber: p.company.orgNumber, legalName: p.company.legalName, status: p.company.statusLabel ?? null, municipality: p.company.municipality },
    suggestions: SUGGESTIONS,
    coverage: chatCoverage(p),
    capabilities: { chat: true, aiModel: false, freshResearch: false, maxQuestionChars: 1000 },
    researchedAt: p.company.lastResearchedAt ?? null,
  };
}

export function chatReplyFor(p: CompanyProfile, question: string, now: string): ChatReply {
  const ans = answerFromProfile(p, question, 'saved_evidence');
  const sources: ChatSource[] = [];
  const nOf = (url: string | undefined, key: string, make: () => Omit<ChatSource, 'n'>) => {
    const k = url ?? key;
    const found = sources.find((s) => (s.url ?? s.title) === k);
    if (found) return found.n;
    const n = sources.length + 1;
    sources.push({ n, ...make() });
    return n;
  };
  const parts: string[] = [];
  for (const b of ans.blocks) {
    const marks = b.citations.map((c) =>
      nOf(c.evidence.url, c.evidence.sourceId, () => ({
        kind: 'fact',
        title: c.evidence.documentTitle ?? c.sourceName,
        url: c.evidence.url ?? null,
        retrievedAt: c.evidence.retrievedAt,
        sourceLabel: c.sourceName,
        reportingPeriod: c.evidence.reportingPeriod ?? null,
        excerpt: c.evidence.excerpt,
        origin: 'saved',
      })),
    );
    parts.push(`${b.text}${[...new Set(marks)].map((n) => ` [${n}]`).join('')}`);
  }
  const text = parts.length ? parts.join(' ') : ans.limitation ?? (ans.gaps?.join(' ') || 'The saved evidence does not answer this question.');
  return {
    company: { orgNumber: p.company.orgNumber, legalName: p.company.legalName, status: p.company.statusLabel ?? null },
    kind: 'evidence_only',
    answer: text,
    citations: sources,
    sources,
    coverage: chatCoverage(p),
    unsupported: ans.gaps ?? [],
    search: { state: 'not_used', note: 'Answered from saved, verified research.' },
    model: null,
    modelNote: 'Demo data: answers are written from saved evidence without an AI model.',
    origin: 'saved',
    generatedAt: now,
    // demo suggestions are generic; the live backend derives them from the answer and the evidence gaps
    followUps: ['Compare this with the previous reporting period', 'Which claims could not be verified?', 'Check the latest company announcements'],
  };
}
