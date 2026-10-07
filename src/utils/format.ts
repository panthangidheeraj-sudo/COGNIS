/**
 * Formatting helpers. Financials use tabular numerals in the UI; values are
 * never rounded beyond one decimal in compact form, and the exact value is
 * always available via `formatExact*` for tooltips / evidence.
 */
import type { Fact } from '@/types';

const LOCALE = 'en-GB';

/**
 * Currency helpers. A currency label is only ever the one a record itself states (the filing's `valuta`, carried on the
 * fact / series / snapshot): there is deliberately no default, and amounts are never converted between currencies.
 */
/** "NOK", "USD", … — a series/fact unit that is an ISO-4217 code. "people", "%", "mixed currencies" are not. */
export const isCurrencyUnit = (unit?: string | null): boolean => !!unit && /^[A-Z]{3}$/.test(unit);
/** Unit the backend uses for a series whose filings are in different currencies. */
export const MIXED_CURRENCIES = 'mixed currencies';
/** True for single-currency and mixed-currency monetary series (anything plotted/formatted as an amount). */
export const isMoneyUnit = (unit?: string | null): boolean => isCurrencyUnit(unit) || unit === MIXED_CURRENCIES;

/** Percent change between two facts — only when both are stated in the same currency (or are the same non-money unit). */
export function factChange(a: Pick<Fact, 'value' | 'currency' | 'unit'> | null | undefined, b: Pick<Fact, 'value' | 'currency' | 'unit'> | null | undefined): number | null {
  if (!a || !b || typeof a.value !== 'number' || typeof b.value !== 'number' || a.value === 0) return null;
  const comparable = a.currency || b.currency ? a.currency === b.currency : !!a.unit && a.unit === b.unit;
  return comparable ? ((b.value - a.value) / Math.abs(a.value)) * 100 : null;
}

/** NOK 790.4M · USD 67.96B · −NOK 12.4M — labelled with the given currency; no currency given → the bare number (never an assumed NOK). */
export function formatMoneyCompact(value: number | null | undefined, currency: string | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—';
  const abs = Math.abs(value);
  const sign = value < 0 ? '−' : '';
  let body: string;
  if (abs >= 1e9) body = `${trim(abs / 1e9, 2)}B`;
  else if (abs >= 1e6) body = `${trim(abs / 1e6, 1)}M`;
  else if (abs >= 1e3) body = `${trim(abs / 1e3, 0)}k`;
  else body = trim(abs, 0);
  return currency ? `${sign}${currency} ${body}` : `${sign}${body}`;
}

/** 790 400 865 NOK — exact, Norwegian digit grouping, in the given currency (bare number when none is given). */
export function formatMoneyExact(value: number | null | undefined, currency: string | null | undefined): string {
  if (value == null) return '—';
  const s = Math.round(Math.abs(value))
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  return `${value < 0 ? '−' : ''}${s}${currency ? ` ${currency}` : ''}`;
}

/** Axis label: 790M, 1.3B */
export function formatAxisMoney(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? '−' : '';
  if (abs >= 1e9) return `${sign}${trim(abs / 1e9, 1)}B`;
  if (abs >= 1e6) return `${sign}${trim(abs / 1e6, 0)}M`;
  if (abs >= 1e3) return `${sign}${trim(abs / 1e3, 0)}k`;
  return `${sign}${abs}`;
}

export function formatInteger(value: number | null | undefined): string {
  if (value == null) return '—';
  return Math.round(value).toLocaleString(LOCALE);
}

export function formatPercent(value: number | null | undefined, decimals = 1): string {
  if (value == null) return '—';
  return `${value < 0 ? '−' : ''}${Math.abs(value).toFixed(decimals)}%`;
}

function trim(n: number, decimals: number) {
  return n.toFixed(decimals).replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1');
}

function toDate(iso: string) {
  return new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
}

/** 03 Oct 2026 */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = toDate(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(LOCALE, { day: '2-digit', month: 'short', year: 'numeric', timeZone: iso.length === 10 ? 'UTC' : undefined });
}

/** 03 October 2026 */
export function formatDateLong(iso: string | null | undefined): string {
  if (!iso) return '—';
  return toDate(iso).toLocaleDateString(LOCALE, { day: '2-digit', month: 'long', year: 'numeric' });
}

/** Exact timestamp for tooltips: 03 Oct 2026, 10:32 (local time) */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  return toDate(iso).toLocaleString(LOCALE, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function formatTime(iso: string, seconds = true): string {
  return toDate(iso).toLocaleTimeString(LOCALE, { hour: '2-digit', minute: '2-digit', second: seconds ? '2-digit' : undefined });
}

/** today · yesterday · 3 days ago · 03 Oct 2026 */
export function formatRelative(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return '—';
  const d = toDate(iso);
  const days = Math.floor((startOfDay(now) - startOfDay(d)) / 86400000);
  if (days <= 0) {
    const mins = Math.round((now.getTime() - d.getTime()) / 60000);
    if (mins >= 0 && mins < 1) return 'just now';
    if (mins > 0 && mins < 60) return `${mins} min ago`;
    return 'today';
  }
  if (days === 1) return 'yesterday';
  if (days < 7) return `${days} days ago`;
  return formatDate(iso);
}
function startOfDay(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** Display a fact value according to its unit. */
export function formatFactValue(fact: Pick<Fact, 'value' | 'unit' | 'currency' | 'displayValue' | 'field'>, opts: { exact?: boolean } = {}): string {
  if (fact.displayValue && !opts.exact) return fact.displayValue;
  const v = fact.value;
  if (v == null) return 'Not available';
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (typeof v === 'number') {
    if (fact.currency || isCurrencyUnit(fact.unit)) {
      const currency = fact.currency ?? fact.unit;
      return opts.exact ? formatMoneyExact(v, currency) : formatMoneyCompact(v, currency);
    }
    if (fact.unit === '%') return formatPercent(v);
    return formatInteger(v);
  }
  if (/founded$/.test(fact.field) && /^\d{4}-\d{2}-\d{2}$/.test(v)) return opts.exact ? formatDate(v) : v.slice(0, 4);
  return v;
}

export function formatUnitLabel(unit?: string): string {
  if (!unit) return '';
  if (unit === 'people') return 'employees';
  if (unit === 'sites') return 'verified sites';
  if (unit === 'roles') return 'current openings';
  return unit;
}

export function formatOrgNumber(org: string): string {
  const d = org.replace(/\s/g, '');
  return d.length === 9 ? `${d.slice(0, 3)} ${d.slice(3, 6)} ${d.slice(6)}` : org;
}

export function pluralize(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}
