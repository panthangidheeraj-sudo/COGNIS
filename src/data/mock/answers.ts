/**
 * MOCK BACKEND — deterministic stand-in for the backend's LLM synthesis.
 * It only restates facts that exist in the profile, with their evidence,
 * mirroring the contract the real backend must honour.
 */
import type { AnswerBlock, AnswerCitation, CompanyProfile, Evidence, Fact, ResearchAnswer } from '@/types';
import { NOW } from './profileBuilder';

const nok = (v: number) => {
  const abs = Math.abs(v);
  const s = abs >= 1e9 ? `${(abs / 1e9).toFixed(2)} billion` : `${(abs / 1e6).toFixed(1)} million`;
  return `${v < 0 ? '−' : ''}NOK ${s}`;
};

function cite(p: CompanyProfile, evs: Evidence[]): AnswerCitation[] {
  const seen = new Set<string>();
  return evs
    .filter((e) => (seen.has(e.sourceId) ? false : (seen.add(e.sourceId), true)))
    .slice(0, 3)
    .map((e) => ({ evidence: e, sourceName: p.sourceIndex[e.sourceId]?.name ?? e.sourceId }));
}

let blockN = 0;
const block = (p: CompanyProfile, text: string, facts: (Fact | undefined)[], extra: Partial<AnswerBlock> = {}): AnswerBlock => {
  const fs = facts.filter(Boolean) as Fact[];
  return {
    id: `b${++blockN}`,
    text,
    factIds: fs.map((f) => f.id),
    citations: cite(p, fs.flatMap((f) => f.evidence)),
    reportingPeriod: fs.find((f) => f.reportingPeriod)?.reportingPeriod,
    ...extra,
  };
};

export function answerFromProfile(p: CompanyProfile, question: string, origin: ResearchAnswer['origin']): ResearchAnswer {
  const q = question.toLowerCase();
  const name = p.company.legalName;
  const blocks: AnswerBlock[] = [];
  const gaps: string[] = [];
  const rev = p.financials.series.find((s) => s.key === 'revenue');
  const op = p.financials.series.find((s) => s.key === 'operating_result');
  const res = p.financials.series.find((s) => s.key === 'annual_result');
  const ceo = p.people.people.find((x) => x.role === 'CEO' && x.current);
  const chair = p.people.people.find((x) => x.role === 'Chair of the board' && x.current);
  const emp = p.keyMetrics.find((f) => f.field === 'overview.employees');

  const financials = () => {
    if (!rev?.points.length) {
      gaps.push('No filed annual accounts were found, so revenue and results are unknown.');
      return;
    }
    const last = rev.points.at(-1)!;
    const prev = rev.points.at(-2);
    let t = `${name} reported revenue of ${nok(last.fact.value!)} for ${last.period}`;
    if (prev) t += `, compared with ${nok(prev.fact.value!)} in ${prev.period}`;
    t += '.';
    blocks.push(block(p, t, [last.fact, prev?.fact]));
    if (last.fact.conflict) {
      const other = last.fact.conflict.candidates.find((c) => c.sourceId !== 'accounts');
      blocks.push(
        block(p, `A secondary source states ${nok(Number(other?.value))} for the same period. The filed annual accounts are the primary source; the difference is flagged as a conflict.`, [last.fact]),
      );
    }
    const o = op?.points.at(-1);
    const r = res?.points.at(-1);
    if (o && r) blocks.push(block(p, `Operating result was ${nok(o.fact.value!)} and the annual result ${nok(r.fact.value!)} (${o.period}).`, [o.fact, r.fact]));
  };
  const leadership = () => {
    if (!p.people.people.length) {
      gaps.push(p.people.message ?? 'No registered roles were found.');
      return;
    }
    if (ceo) blocks.push(block(p, `${ceo.name} is the registered CEO${ceo.since ? ` since ${fmtDate(ceo.since)}` : ''}.`, [ceo.fact]));
    const prevCeo = p.people.people.find((x) => x.role === 'CEO' && !x.current);
    if (prevCeo) blocks.push(block(p, `${prevCeo.name} was CEO until ${fmtDate(prevCeo.until!)}.`, [prevCeo.fact]));
    if (chair) {
      const board = p.people.people.filter((x) => x.roleGroup === 'board' && x.current && x !== chair);
      blocks.push(block(p, `${chair.name} chairs the board${board.length ? `, with ${board.map((b) => b.name).join(', ')} as members` : ''}.`, [chair.fact, ...board.map((b) => b.fact)]));
    }
  };
  const where = () => {
    const locs = p.locations.locations;
    const reg = locs.find((l) => l.kind === 'registered_address');
    if (reg) blocks.push(block(p, `The registered address is ${reg.address}, ${reg.municipality}.`, [reg.fact]));
    const ops = [...new Set(locs.filter((l) => l.kind !== 'registered_address' && l.verified).map((l) => l.municipality))];
    if (ops.length) blocks.push(block(p, `Verified operating locations: ${ops.join(', ')}.`, locs.filter((l) => l.kind !== 'registered_address').map((l) => l.fact)));
    else gaps.push('No verified location data beyond the registered address.');
  };
  const hiring = () => {
    const h = p.hiring;
    if (h.totalCurrent == null) {
      gaps.push(h.message ?? 'No current verified job openings were found in the searched sources.');
      return;
    }
    if (h.totalCurrent === 0) {
      blocks.push(block(p, 'No current verified job openings were found in the searched sources.', []));
      return;
    }
    const cats = h.categories.slice(0, 3).map((c) => `${c.count} in ${c.name.toLowerCase()}`).join(', ');
    const f = p.keyMetrics.find((k) => k.field === 'overview.openPositions');
    blocks.push(block(p, `${h.totalCurrent} current openings were verified (${cats}). Hiring locations: ${h.locations.map((l) => l.name).join(', ')}.`, [f]));
  };
  const changes = () => {
    if (!p.changes.changes.length) {
      blocks.push(block(p, 'No changes were detected since the previous research.', []));
      return;
    }
    for (const c of p.changes.changes.slice(0, 5)) {
      blocks.push({
        id: `b${++blockN}`,
        text: c.previous ? `${c.label}: ${c.previous} → ${c.current} (detected ${fmtDate(c.detectedAt)}).` : `${c.label}: ${c.current} (detected ${fmtDate(c.detectedAt)}).`,
        citations: cite(p, c.evidence),
      });
    }
  };
  const activity = () => {
    if (!p.activity.events.length) {
      gaps.push('No verified major public changes were found in the searched sources.');
      return;
    }
    for (const e of p.activity.events.slice(0, 4)) blocks.push({ id: `b${++blockN}`, text: `${fmtDate(e.date)} — ${e.title}.`, citations: cite(p, e.evidence) });
    if (p.activity.status === 'partial' && p.activity.message) gaps.push(p.activity.message);
  };
  const unknowns = () => {
    for (const k of p.knowns.filter((k) => k.status !== 'verified')) gaps.push(`${k.label}: ${k.text}`);
    if (!gaps.length) blocks.push(block(p, 'All five coverage areas have verified evidence. Nothing material is currently marked unknown.', []));
  };

  if (/financ|revenue|result|profit|turnover|omsetning|numbers/.test(q)) financials();
  else if (/who runs|ceo|leader|board|management|chair|people/.test(q)) leadership();
  else if (/where|locat|office|operate|address/.test(q)) where();
  else if (/hir|job|opening|recruit/.test(q)) hiring();
  else if (/change|new since|differ/.test(q)) changes();
  else if (/activity|recent|news|event/.test(q)) activity();
  else if (/not know|don't know|unknown|missing|gap/.test(q)) unknowns();
  else if (/evidence for revenue|show evidence/.test(q)) financials();
  else {
    // company brief
    if (p.summary) blocks.push({ id: `b${++blockN}`, text: p.description?.value ?? `${name} is registered in ${p.company.municipality}.`, citations: cite(p, p.description?.evidence ?? p.identity.industry?.evidence ?? []) });
    financials();
    if (emp?.value != null) blocks.push(block(p, `The registry lists ${emp.value} employees.`, [emp]));
    if (ceo) blocks.push(block(p, `${ceo.name} is the registered CEO.`, [ceo.fact]));
    hiring();
  }

  return {
    id: `ans-${p.company.orgNumber}-${blockN}`,
    question,
    origin,
    blocks,
    gaps: gaps.length ? gaps : undefined,
    newSourceIds: origin === 'fresh_research' ? ['brreg', 'nav', `web-${p.company.orgNumber}`].filter((s) => p.sourceIndex[s]) : undefined,
    generatedAt: NOW,
  };
}

function fmtDate(iso: string) {
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' });
}
