/**
 * One key figure of a result card or table row — revenue, employees or openings — with what is actually known about it.
 *
 * A value is shown only when a source verified it (research, the registry search, or a Discover lookup). Otherwise the cell says why there is no
 * value instead of a bare "Not available", which read as if the information did not exist: "Checking…", "Not reported" (the official source holds
 * none — not a zero), "None verified" (openings: sources checked, none found — not "0"), "Source unavailable" or "Not checked". The full
 * explanation is the cell's title and its accessible description.
 */
import type { CompanyEnrichment, CompanySummary, EnrichedFigure, EnrichmentField, EnrichmentState } from '@/types';
import { formatInteger, formatMoneyCompact } from '@/utils/format';

const STATE_LABEL: Record<EnrichmentState, (f: EnrichmentField) => string> = {
  verified: () => '',
  none_found: () => 'None verified',
  not_reported: (f) => (f === 'employees' ? 'Not registered' : 'Not reported'),
  unavailable: () => 'Source unavailable',
  not_checked: () => 'Not checked',
  unverified: () => 'Not verified',
};

const RESEARCH_HIRING: Record<string, { label: string; note: string }> = {
  none_found: { label: 'None verified', note: 'Research checked the hiring sources and found no verified opening. This does not mean the company is not hiring.' },
  source_unavailable: { label: 'Source unavailable', note: 'A hiring source could not be reached during research, so no conclusion was drawn.' },
  incomplete: { label: 'Not verified', note: 'Research could not check every hiring source, so no count is shown.' },
  pending: { label: 'Not checked', note: 'Hiring has not been researched yet.' },
};

export interface FigureView {
  /** formatted value, when verified */
  value?: string;
  /** small line under the value (period / source) */
  detail?: string;
  /** state text, when there is no value */
  label?: string;
  note: string;
  checking?: boolean;
}

function fromLookup(field: EnrichmentField, f: EnrichedFigure): FigureView {
  if (f.state === 'verified' && f.value != null) {
    const source = f.sources.find((s) => s.state === 'checked')?.name;
    if (field === 'revenue') return { value: formatMoneyCompact(f.value, f.currency ?? ''), detail: f.period, note: `${f.note}${source ? ` Source: ${source}.` : ''}` };
    if (field === 'openPositions') return { value: f.lowerBound ? `${formatInteger(f.value)}+` : formatInteger(f.value), note: f.note };
    return { value: formatInteger(f.value), note: `${f.note}${source ? ` Source: ${source}.` : ''}` };
  }
  return { label: STATE_LABEL[f.state](field), note: f.note };
}

/** What a cell shows for one figure of one company. */
export function figureView(field: EnrichmentField, c: CompanySummary, lookup?: CompanyEnrichment, checking = false): FigureView {
  const researched = c.researchState !== 'not_researched';
  if (field === 'revenue' && c.revenue) return { value: formatMoneyCompact(c.revenue.value, c.revenue.currency), detail: c.revenue.period, note: `Latest filed annual accounts (${c.revenue.period}).` };
  if (field === 'employees' && c.employees != null) return { value: formatInteger(c.employees), note: 'Employee count registered in Enhetsregisteret.' };
  if (field === 'openPositions') {
    const status = c.openPositionsStatus;
    if (status && status !== 'verified' && RESEARCH_HIRING[status]) {
      const r = RESEARCH_HIRING[status];
      return { label: r.label, note: r.note }; // a researched "0" is "none verified", never "0 openings"
    }
    if (c.openPositions != null && (status === 'verified' || (!status && c.openPositions > 0))) return { value: formatInteger(c.openPositions), note: 'Verified current openings.' };
    if (c.openPositions != null && !status && c.openPositions === 0) return { label: 'None verified', note: RESEARCH_HIRING.none_found.note };
  }
  const f = lookup?.fields[field];
  if (f) return fromLookup(field, f);
  if (checking) return { label: 'Checking…', note: 'Looking this up in the official registers and authorised job sources…', checking: true };
  return researched
    ? { label: 'Not verified', note: 'Research did not verify this figure. Open the company to see why.' }
    : { label: 'Not checked', note: 'Not looked up yet. Open the company to research it.' };
}

/** The value (or the reason there is none) as it appears in a card or a table cell. */
export function FigureValue({ view, naClass = 'co-card-na' }: { view: FigureView; naClass?: string }) {
  if (view.value != null) return <span title={view.note}>{view.value}</span>;
  return (
    <span className={naClass} title={view.note} aria-busy={view.checking || undefined} data-checking={view.checking || undefined}>
      {view.label}
      <span className="sr-only"> — {view.note}</span>
    </span>
  );
}
