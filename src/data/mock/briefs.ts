/**
 * MOCK BACKEND — executive briefs and change explanations.
 * Both are compiled only from the saved profile (plus fictional fixture
 * statements in `spec.reported`). Nothing here scores, ranks or advises.
 */
import type {
  BriefItem,
  BriefSection,
  Change,
  ChangeExplanation,
  CompanyProfile,
  Evidence,
  ExecutiveBrief,
  ExplainSubject,
  Fact,
  FinancialMetricKey,
} from '@/types';
import type { CompanySpec, ReportedSpec } from './profileBuilder';
import { formatDate, formatInteger, formatMoneyCompact, formatPercent, isCurrencyUnit } from '@/utils/format';

const nowIso = () => new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');

/** Display order for "What changed?" — mirrors the frontend ordering. */
export const CHANGE_PRIORITY: Change['category'][] = ['leadership', 'status', 'financial', 'filing', 'ownership', 'location', 'address', 'hiring', 'employees', 'event', 'website'];

function item(id: string, text: string, evidence: Evidence[], o: Partial<BriefItem> = {}): BriefItem {
  return { id, text, evidence, status: 'verified', ...o };
}
function fromFact(id: string, f: Fact | undefined | null, text: (f: Fact) => string, label?: string): BriefItem | null {
  if (!f || f.value == null || f.status !== 'verified') return null;
  return item(id, text(f), f.evidence, { label, factId: f.id, reportingPeriod: f.reportingPeriod, evidenceState: f.evidenceState });
}

export function briefFromProfile(p: CompanyProfile): ExecutiveBrief {
  const c = p.company;
  const id = p.identity;
  const researched = c.researchState !== 'not_researched';
  const series = (k: FinancialMetricKey) => p.financials.series.find((s) => s.key === k);
  const latest = (k: FinancialMetricKey) => series(k)?.points.at(-1);
  const prev = (k: FinancialMetricKey) => series(k)?.points.at(-2);
  const sections: BriefSection[] = [];

  /* What it does */
  const what: BriefItem[] = [];
  const desc = fromFact('what-desc', p.description, (f) => String(f.value));
  if (desc) what.push(desc);
  const ind = fromFact('what-ind', id.industry, (f) => `Registered industry: ${f.value}.`);
  if (ind) what.push(ind);
  const founded = id.founded?.value ? String(id.founded.value).slice(0, 4) : null;
  if (founded && id.legalForm?.value) what.push(item('what-form', `${id.legalForm.value}, founded ${founded}, registered in ${c.municipality}.`, [...id.legalForm.evidence, ...id.founded!.evidence], { factId: id.founded!.id }));
  sections.push({ id: 'what', title: 'What the company does', items: what, emptyText: 'No verified description.' });

  /* Scale */
  const scale: BriefItem[] = [];
  const emp = p.keyMetrics.find((k) => k.field === 'overview.employees');
  const e1 = fromFact('scale-emp', emp, (f) => `${formatInteger(f.value as number)} employees registered.`, 'Employees');
  if (e1) scale.push({ ...e1, value: formatInteger(emp!.value as number) });
  const fte = latest('employees');
  if (fte?.fact.value != null) scale.push(item('scale-fte', `${formatInteger(fte.fact.value)} average FTEs in the ${fte.period} annual accounts.`, fte.fact.evidence, { label: 'Average FTEs', reportingPeriod: fte.period, factId: fte.fact.id, value: formatInteger(fte.fact.value) }));
  const sites = p.keyMetrics.find((k) => k.field === 'overview.locations');
  const s1 = fromFact('scale-sites', sites, (f) => `${f.value} verified location${f.value === 1 ? '' : 's'}.`, 'Locations');
  if (s1) scale.push(s1);
  sections.push({ id: 'scale', title: 'Scale', items: scale, emptyText: 'No verified size information.' });

  /* Financials */
  const fin: BriefItem[] = [];
  const rev = latest('revenue');
  const rev0 = prev('revenue');
  if (rev?.fact.value != null) {
    const growth = rev0?.fact.value ? ((rev.fact.value - rev0.fact.value) / rev0.fact.value) * 100 : null;
    const conflict = rev.fact.conflict;
    let text = `Revenue ${formatMoneyCompact(rev.fact.value, rev.fact.currency)} in ${rev.period}`;
    if (growth != null && rev0) text += `, ${growth >= 0 ? 'up' : 'down'} ${formatPercent(Math.abs(growth))} from ${formatMoneyCompact(rev0.fact.value, rev0.fact.currency)} in ${rev0.period}`;
    text += '.';
    if (conflict) {
      const alt = conflict.candidates.find((x) => x.value !== rev.fact.value);
      if (alt) text += ` A secondary source states ${formatMoneyCompact(alt.value as number, rev.fact.currency)} for the same period; the filed figure is shown.`;
    }
    fin.push(item('fin-rev', text, rev.fact.evidence, { label: 'Revenue', value: formatMoneyCompact(rev.fact.value, rev.fact.currency), reportingPeriod: rev.period, factId: rev.fact.id, evidenceState: rev.fact.evidenceState }));
  }
  const op = latest('operating_result');
  if (op?.fact.value != null) fin.push(item('fin-op', `Operating result ${formatMoneyCompact(op.fact.value, op.fact.currency)} in ${op.period}.`, op.fact.evidence, { label: 'Operating result', value: formatMoneyCompact(op.fact.value, op.fact.currency), reportingPeriod: op.period, factId: op.fact.id }));
  const res = latest('annual_result');
  if (res?.fact.value != null) fin.push(item('fin-res', `Annual result ${formatMoneyCompact(res.fact.value, res.fact.currency)} in ${res.period}.`, res.fact.evidence, { label: 'Annual result', value: formatMoneyCompact(res.fact.value, res.fact.currency), reportingPeriod: res.period, factId: res.fact.id }));
  const eqr = p.financials.ratios.find((r) => r.key === 'equity_ratio');
  if (eqr) {
    const eq = latest('equity');
    fin.push(item('fin-eqr', `Equity ratio ${formatPercent(eqr.value)} (${eqr.formula}, ${eqr.period}).`, eq?.fact.evidence ?? [], { label: 'Equity ratio', value: formatPercent(eqr.value), reportingPeriod: eqr.period }));
  }
  sections.push({ id: 'financials', title: 'Latest financial position', items: fin, emptyText: p.financials.message ?? 'No filed annual accounts found.' });

  /* Leadership */
  const lead: BriefItem[] = [];
  const ceo = p.people.people.find((x) => x.role === 'CEO' && x.current);
  if (ceo) lead.push(item('lead-ceo', `${ceo.name} is the registered CEO${ceo.since ? ` since ${formatDate(ceo.since)}` : ''}.`, ceo.fact.evidence, { label: 'CEO', value: ceo.name, factId: ceo.fact.id }));
  const chair = p.people.people.find((x) => x.role === 'Chair of the board' && x.current);
  if (chair) lead.push(item('lead-chair', `${chair.name} chairs the board.`, chair.fact.evidence, { label: 'Chair', value: chair.name, factId: chair.fact.id }));
  const board = p.people.people.filter((x) => x.current && x.roleGroup === 'board').length;
  if (board > 1) lead.push(item('lead-board', `${board} current board members are registered.`, p.people.people.filter((x) => x.current && x.roleGroup === 'board').flatMap((x) => x.fact.evidence.slice(0, 1)), { label: 'Board' }));
  sections.push({ id: 'leadership', title: 'Leadership', items: lead, emptyText: researched ? 'Leadership not verified in the searched sources.' : 'Not researched yet.' });

  /* Locations */
  const locs = p.locations.locations.filter((l) => l.verified && l.kind !== 'postal');
  const munis = [...new Set(locs.map((l) => l.municipality))];
  const hq = p.identity.headquarters;
  const locItems: BriefItem[] = [];
  if (hq?.value) locItems.push(item('loc-hq', `Headquarters: ${hq.value}.`, hq.evidence, { label: 'Headquarters', factId: hq.id }));
  else if (id.registeredAddress?.value) locItems.push(item('loc-reg', `Registered address: ${id.registeredAddress.value}. Headquarters not verified.`, id.registeredAddress.evidence, { label: 'Registered address', factId: id.registeredAddress.id }));
  if (munis.length > 1) locItems.push(item('loc-all', `Verified locations in ${munis.join(', ')}.`, locs.flatMap((l) => l.fact.evidence.slice(0, 1)), { label: 'Locations' }));
  sections.push({ id: 'locations', title: 'Locations', items: locItems });

  /* Hiring */
  const h = p.hiring;
  const hiring: BriefItem[] = [];
  if (h.totalCurrent != null && h.totalCurrent > 0) {
    const cats = h.categories.slice(0, 3).map((x) => `${x.name} ${x.count}`).join(', ');
    const where = h.locations.slice(0, 3).map((x) => x.name).join(', ');
    hiring.push(item('hire', `${h.totalCurrent} current verified opening${h.totalCurrent === 1 ? '' : 's'} (${cats}) in ${where}.`, h.jobs.filter((j) => j.state === 'current').slice(0, 4).flatMap((j) => j.evidence), { label: 'Open positions', value: String(h.totalCurrent) }));
  }
  sections.push({ id: 'hiring', title: 'Hiring', items: hiring, emptyText: h.status === 'pending' ? 'Not researched yet.' : 'No current verified job openings were found in the searched sources.' });

  /* Changes */
  const changes = p.changes.changes
    .filter((x) => x.material)
    .sort((a, b) => CHANGE_PRIORITY.indexOf(a.category) - CHANGE_PRIORITY.indexOf(b.category))
    .slice(0, 5)
    .map((x) => item(`ch-${x.id}`, `${x.headline ?? x.label}${x.previous && x.current ? ` (${x.previous} → ${x.current})` : x.current ? `: ${x.current}` : ''} · detected ${formatDate(x.detectedAt)}.`, x.evidence, { label: x.label }));
  sections.push({
    id: 'changes',
    title: 'Major recent changes',
    items: changes,
    emptyText: p.changes.status === 'pending' ? 'Not researched yet.' : `No verified material changes were detected${p.changes.since ? ` since the previous research on ${formatDate(p.changes.since)}` : ''}.`,
  });

  const gaps = [
    ...p.knowns.filter((k) => k.status === 'unknown' || k.status === 'blocked').map((k) => `${k.label}: ${k.text}`),
    ...c.coverage.areas.filter((a) => a.status !== 'complete' && a.note).map((a) => a.note!),
  ];
  const sourceIds = [...new Set(sections.flatMap((s) => s.items.flatMap((i) => i.evidence.map((e) => e.sourceId))))];
  return {
    orgNumber: c.orgNumber,
    companyName: c.legalName,
    statusLabel: c.statusLabel ?? c.status,
    location: c.municipality ? `${c.municipality}, Norway` : undefined,
    generatedAt: nowIso(),
    researchedAt: c.lastResearchedAt ?? null,
    artifactId: p.artifactId,
    coverage: c.coverage,
    sections,
    gaps: [...new Set(gaps)],
    sourceIds,
    sourceIndex: p.sourceIndex,
  };
}

/* ============================== Explanations ============================== */

function reportedEvidence(spec: CompanySpec, r: ReportedSpec, i: number): Evidence {
  const sourceId = r.sourceId === 'web' ? `web-${spec.org}` : r.sourceId;
  return {
    id: `${spec.org}-rep${i}`,
    sourceId,
    documentTitle: r.documentTitle,
    excerpt: r.quote,
    excerptLanguage: r.quoteLanguage ?? 'en',
    excerptTranslation: r.quoteLanguage === 'no' ? r.text : undefined,
    retrievedAt: `${r.date}T12:00:00Z`,
    url: sourceId.startsWith('web-') && spec.domain ? `https://${spec.domain}/careers` : undefined,
  };
}

const CAVEAT = 'AI synthesis of the sources above. It is not a verified fact, and the evidence does not establish cause and effect on its own.';

export function explainFromProfile(p: CompanyProfile, spec: CompanySpec, subject: ExplainSubject): ChangeExplanation {
  const observed: ChangeExplanation['observed'] = [];
  const reported: ChangeExplanation['reported'] = [];
  const gaps: string[] = [];
  let question = 'What explains this change?';
  let topic: ReportedSpec['subject'] | null = null;
  const since = p.changes.since;
  const recentChanges = p.changes.changes;

  const addObs = (id: string, text: string, evidence: Evidence[]) => observed.push({ id, text, evidence });
  const series = (k: FinancialMetricKey) => p.financials.series.find((s) => s.key === k);

  if (subject.kind === 'metric') {
    const s = series(subject.metric);
    const a = s?.points.find((x) => x.period === subject.fromPeriod);
    const b = s?.points.find((x) => x.period === subject.toPeriod);
    question = `What explains the change in ${s?.label.toLowerCase() ?? subject.metric} from ${subject.fromPeriod} to ${subject.toPeriod}?`;
    topic = subject.metric === 'revenue' ? 'revenue' : subject.metric === 'employees' ? 'employees' : null;
    if (s && a && b && a.fact.value != null && b.fact.value != null) {
      const pct = ((b.fact.value - a.fact.value) / Math.abs(a.fact.value)) * 100;
      addObs('obs-metric', `${s.label} was ${isCurrencyUnit(s.unit) ? formatMoneyCompact(a.fact.value, a.fact.currency) : formatInteger(a.fact.value)} in ${a.period} and ${isCurrencyUnit(s.unit) ? formatMoneyCompact(b.fact.value, b.fact.currency) : formatInteger(b.fact.value)} in ${b.period} (${pct >= 0 ? '+' : '−'}${formatPercent(Math.abs(pct))}).`, [...a.fact.evidence.slice(0, 1), ...b.fact.evidence.slice(0, 1)]);
      for (const k of ['operating_result', 'employees'] as FinancialMetricKey[]) {
        if (k === subject.metric) continue;
        const ss = series(k);
        const x = ss?.points.find((pt) => pt.period === subject.fromPeriod);
        const y = ss?.points.find((pt) => pt.period === subject.toPeriod);
        if (ss && x?.fact.value != null && y?.fact.value != null)
          addObs(`obs-${k}`, `${ss.label} went from ${isCurrencyUnit(ss.unit) ? formatMoneyCompact(x.fact.value, x.fact.currency) : formatInteger(x.fact.value)} to ${isCurrencyUnit(ss.unit) ? formatMoneyCompact(y.fact.value, y.fact.currency) : formatInteger(y.fact.value)} over the same periods.`, [...x.fact.evidence.slice(0, 1), ...y.fact.evidence.slice(0, 1)]);
      }
      const y0 = Number(subject.fromPeriod.replace('FY', ''));
      const y1 = Number(subject.toPeriod.replace('FY', ''));
      for (const e of p.activity.events.filter((ev) => ['acquisition', 'contract', 'location', 'funding'].includes(ev.type) && Number(ev.date.slice(0, 4)) >= y0 && Number(ev.date.slice(0, 4)) <= y1 + 1))
        addObs(`obs-${e.id}`, `${formatDate(e.date)}: ${e.title}.`, e.evidence);
    } else gaps.push('Filed figures for both periods are not available.');
  } else {
    const ch = recentChanges.find((x) => x.id === subject.changeId);
    if (!ch) gaps.push('This change is no longer part of the saved research.');
    else {
      question = `What explains: ${ch.headline ?? ch.label}?`;
      addObs('obs-change', `${ch.label}: ${ch.previous ? `${ch.previous} → ` : ''}${ch.current ?? ''} (detected ${formatDate(ch.detectedAt)}).`, ch.evidence);
      topic = ch.category === 'employees' ? 'employees' : ch.category === 'hiring' ? 'hiring' : ch.category === 'leadership' ? 'leadership' : ch.category === 'status' ? 'status' : ch.category === 'location' ? 'location' : ch.category === 'financial' ? 'revenue' : null;
      // Co-occurring verified changes in the same research window
      const related: Change['category'][] = ch.category === 'employees' ? ['hiring', 'location'] : ch.category === 'hiring' ? ['employees', 'location'] : ch.category === 'location' ? ['hiring', 'employees'] : [];
      for (const r of recentChanges.filter((x) => x.id !== ch.id && related.includes(x.category)))
        addObs(`obs-${r.id}`, `${r.headline ?? r.label}${r.current && !r.previous ? `: ${r.current}` : ''} (detected ${formatDate(r.detectedAt)}).`, r.evidence);
      if (ch.category === 'leadership') {
        const prevP = p.people.people.find((x) => x.role === ch.label && !x.current);
        const curP = p.people.people.find((x) => x.role === ch.label && x.current);
        if (prevP?.until) addObs('obs-prev', `${prevP.name} was registered as ${ch.label} until ${formatDate(prevP.until)}.`, prevP.fact.evidence);
        if (curP?.since) addObs('obs-cur', `${curP.name} is registered as ${ch.label} from ${formatDate(curP.since)}.`, curP.fact.evidence);
      }
      if (ch.category === 'financial') {
        const s = series('revenue');
        const b = s?.points.at(-1);
        const a = s?.points.at(-2);
        if (a?.fact.value != null && b?.fact.value != null)
          addObs('obs-rev', `Filed revenue: ${formatMoneyCompact(a.fact.value, a.fact.currency)} (${a.period}) → ${formatMoneyCompact(b.fact.value, b.fact.currency)} (${b.period}).`, [...a.fact.evidence.slice(0, 1), ...b.fact.evidence.slice(0, 1)]);
      }
    }
  }

  (spec.reported ?? []).forEach((r, i) => {
    if (r.subject === topic) {
      const ev = reportedEvidence(spec, r, i);
      reported.push({ id: `rep-${i}`, text: r.text, sourceId: ev.sourceId, quote: r.quote, evidence: [ev] });
    }
  });
  if (!reported.length) gaps.push('No source in the saved evidence states a reason for this change.');

  let synthesis: ChangeExplanation['synthesis'] = null;
  // Lower-case only a leading common word, never names ("Revenue was…" → "revenue was…", "Ingrid Solberg…" unchanged).
  const clause = (t: string) => (/^(Revenue|Average|Employees|Open|The|A|An|Operating|Annual|Total|Equity|Cash|Debt|Registered|Verified|Current)\b/.test(t) ? t.charAt(0).toLowerCase() + t.slice(1) : t);
  if (reported.length && observed.length) {
    const lead = observed[0].text.replace(/\.$/, '');
    const others = observed.slice(1, 3).map((o) => o.text.replace(/\.$/, '').replace(/^\d{2} \w{3,4} \d{4}: /, ''));
    synthesis = {
      text: `${lead}. ${reported[0].text}${others.length ? ` Over the same period the evidence also shows that ${others.map(clause).join(', and that ')}.` : ''} Together these sources are consistent with the stated reason, but they do not prove it.`,
      basis: [...observed.map((o) => o.id), ...reported.map((r) => r.id)],
      caveat: CAVEAT,
    };
  } else if (observed.length >= 2) {
    synthesis = {
      text: `${observed[0].text.replace(/\.$/, '')}. This coincides with ${observed
        .slice(1, 3)
        .map((o) => clause(o.text.replace(/\.$/, '').replace(/ \(detected .*\)$/, '')))
        .join(' and ')}. No source links these facts directly, so this is a co-occurrence, not an explanation.`,
      basis: observed.map((o) => o.id),
      caveat: CAVEAT,
    };
  }
  if (since && subject.kind === 'change') gaps.push(`Only changes detected since the previous research on ${formatDate(since)} were considered.`);

  return { subject, question, observed, reported, synthesis, gaps, origin: 'saved_evidence', generatedAt: nowIso() };
}
