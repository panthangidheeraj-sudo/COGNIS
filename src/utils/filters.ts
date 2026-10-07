/**
 * Discover filter helpers: chips ⇄ filter object ⇄ URL params.
 * Pure UI plumbing — the backend owns interpretation and matching.
 */
import type { DiscoverFilters, DiscoverFilterKey, FilterCapability, InterpretedFilter } from '@/types';
import { formatMoneyCompact } from './format';

export function filtersToChips(filters: DiscoverFilters, caps: FilterCapability[] = []): InterpretedFilter[] {
  return (Object.entries(filters) as [DiscoverFilterKey, unknown][])
    .filter(([, v]) => v !== undefined && v !== '' && v !== false && v !== null)
    .map(([key, value]) => {
      const cap = caps.find((c) => c.key === key);
      const opt = cap?.options?.find((o) => o.value === String(value));
      return { key, label: cap?.label ?? labelFor(key), value: value as InterpretedFilter['value'], display: opt?.label ?? displayFor(key, value) };
    });
}

export function chipsToFilters(chips: InterpretedFilter[]): DiscoverFilters {
  const f: DiscoverFilters = {};
  for (const c of chips) (f as Record<string, unknown>)[c.key] = c.value;
  return f;
}

export function labelFor(key: DiscoverFilterKey): string {
  return (
    {
      location: 'Location',
      municipality: 'Municipality',
      industry: 'Industry',
      status: 'Status',
      employeesMin: 'Employees',
      employeesMax: 'Employees',
      revenueMin: 'Revenue',
      revenueMax: 'Revenue',
      hiring: 'Hiring',
      coverageMin: 'Coverage',
      recentActivity: 'Recent activity',
      foundedAfter: 'Founded',
    } as Record<DiscoverFilterKey, string>
  )[key];
}

export function displayFor(key: DiscoverFilterKey, value: unknown): string {
  switch (key) {
    case 'employeesMin':
      return `> ${value}`;
    case 'employeesMax':
      return `< ${value}`;
    case 'revenueMin':
      return `> ${formatMoneyCompact(Number(value), 'NOK')}`;
    case 'revenueMax':
      return `< ${formatMoneyCompact(Number(value), 'NOK')}`;
    case 'hiring':
      return 'Current openings';
    case 'coverageMin':
      return `≥ ${value}/5 areas`;
    case 'recentActivity':
      return 'New locations · 12 mo.';
    case 'foundedAfter':
      return `after ${value}`;
    default:
      return String(value);
  }
}

const NUMERIC: DiscoverFilterKey[] = ['employeesMin', 'employeesMax', 'revenueMin', 'revenueMax', 'coverageMin', 'foundedAfter'];
const BOOL: DiscoverFilterKey[] = ['hiring', 'recentActivity'];

export function filtersToParams(filters: DiscoverFilters, params = new URLSearchParams()): URLSearchParams {
  for (const [k, v] of Object.entries(filters)) {
    if (v === undefined || v === '' || v === false || v === null) params.delete(`f.${k}`);
    else params.set(`f.${k}`, String(v));
  }
  return params;
}

export function paramsToFilters(params: URLSearchParams): DiscoverFilters {
  const f: DiscoverFilters = {};
  params.forEach((value, key) => {
    if (!key.startsWith('f.')) return;
    const k = key.slice(2) as DiscoverFilterKey;
    if (NUMERIC.includes(k)) (f as Record<string, unknown>)[k] = Number(value);
    else if (BOOL.includes(k)) (f as Record<string, unknown>)[k] = value === 'true';
    else (f as Record<string, unknown>)[k] = value;
  });
  return f;
}
