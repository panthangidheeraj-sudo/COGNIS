import { describe, expect, it } from 'vitest';
import { formatFactValue, formatMoneyCompact, formatMoneyExact, formatOrgNumber, formatPercent } from '@/utils/format';
import { evidenceStateLabel, verification, VALUE_STATUS } from '@/utils/status';
import { filtersToChips, filtersToParams, paramsToFilters } from '@/utils/filters';

describe('financial formatting', () => {
  it('formats compact amounts in the currency they are given', () => {
    expect(formatMoneyCompact(790400865, 'NOK')).toBe('NOK 790.4M');
    expect(formatMoneyCompact(1284600000, 'NOK')).toBe('NOK 1.28B');
    expect(formatMoneyCompact(-12400000, 'NOK')).toBe('−NOK 12.4M');
    expect(formatMoneyCompact(67960000000, 'USD')).toBe('USD 67.96B');
    expect(formatMoneyCompact(null, 'NOK')).toBe('—');
  });
  it('never assumes a currency: no currency given → the bare number', () => {
    expect(formatMoneyCompact(67960000000, undefined)).toBe('67.96B');
    expect(formatMoneyCompact(67960000000, '')).toBe('67.96B');
    expect(formatMoneyExact(790400865, null)).toBe('790 400 865');
  });
  it('formats exact amounts with Norwegian digit grouping and the given currency', () => {
    expect(formatMoneyExact(790400865, 'NOK')).toBe('790 400 865 NOK');
    expect(formatMoneyExact(67960000000, 'USD')).toBe('67 960 000 000 USD');
  });
  it('formats percentages with a consistent decimal policy', () => {
    expect(formatPercent(10.62)).toBe('10.6%');
    expect(formatPercent(-2.3)).toBe('−2.3%');
  });
  it('groups organization numbers', () => {
    expect(formatOrgNumber('921604337')).toBe('921 604 337');
  });
  it('never renders a missing fact as a number', () => {
    expect(formatFactValue({ value: null, field: 'x', unit: 'NOK' })).toBe('Not available');
    expect(formatFactValue({ value: 365, field: 'overview.employees', unit: 'people' })).toBe('365');
    expect(formatFactValue({ value: '1999-03-12', field: 'identity.founded' })).toBe('1999');
  });
});

describe('status mapping', () => {
  it('uses evidence-quality language, not confidence scores', () => {
    expect(evidenceStateLabel('verified', 3)).toBe('Verified by 3 sources');
    expect(evidenceStateLabel('primary', 1)).toBe('Verified by 1 primary source');
    expect(evidenceStateLabel('secondary', 1)).toBe('Secondary-source evidence');
    expect(evidenceStateLabel('conflict', 2)).toBe('Potential conflict');
    expect(evidenceStateLabel('unverified', 0)).toBe('Not verified');
  });
  it('counts primary and secondary sources for verification labels', () => {
    const idx = {
      a: { id: 'a', name: 'Registry', kind: 'registry', tier: 'primary', official: true },
      b: { id: 'b', name: 'Accounts', kind: 'financial', tier: 'primary', official: true },
      c: { id: 'c', name: 'Proff', kind: 'financial', tier: 'secondary', official: false },
    } as const;
    const ev = (sourceId: string) => ({ id: sourceId + Math.random(), sourceId, retrievedAt: '2026-10-03T10:00:00Z' });
    const v = verification({ status: 'verified', evidenceState: 'verified', evidence: [ev('a'), ev('b'), ev('c'), ev('a')] }, idx as never);
    expect(v.label).toBe('Verified by 2 primary sources + 1 secondary source');
    expect(v.short).toBe('2 primary + 1 secondary');
    expect(verification({ status: 'verified', evidenceState: 'primary', evidence: [ev('a')] }, idx as never).label).toBe('Verified by 1 primary source');
    expect(verification({ status: 'verified', evidenceState: 'secondary', evidence: [ev('c')] }, idx as never).label).toBe('Secondary-source evidence');
    expect(verification({ status: 'verified', evidenceState: 'conflict', evidence: [ev('a'), ev('c')] }, idx as never).label).toBe('Potential conflict');
    expect(verification({ status: 'blocked', evidenceState: 'unverified', evidence: [] }, idx as never).label).toBe('Source blocked');
    expect(verification({ status: 'researching', evidenceState: 'unverified', evidence: [] }, idx as never).label).toBe('Researching');
    expect(verification({ status: 'not_available', evidenceState: 'unverified', evidence: [] }, idx as never).label).toBe('Not available');
    expect(verification({ status: 'verified', evidenceState: 'unverified', evidence: [] }, idx as never).label).toBe('Not verified');
    // Never a percentage
    expect(v.label).not.toMatch(/%/);
  });
  it('has a text label for every cell state', () => {
    for (const s of Object.values(VALUE_STATUS)) expect(s.label.length).toBeGreaterThan(2);
    expect(VALUE_STATUS.blocked.label).toBe('Source blocked');
  });
});

describe('filter parsing', () => {
  it('round-trips filters through URL params', () => {
    const f = { location: 'Oslo', employeesMin: 100, hiring: true };
    expect(paramsToFilters(filtersToParams(f))).toEqual(f);
  });
  it('turns filters into readable chips', () => {
    const chips = filtersToChips({ revenueMin: 200_000_000, hiring: true });
    expect(chips.map((c) => c.display)).toEqual(['> NOK 200M', 'Current openings']);
  });
});

describe('source stack layer states', async () => {
  const { layerState } = await import('@/components/research/SourceStack');
  const step = (kind: string, status: string, outcome?: string) => ({ id: kind + status, key: kind, label: kind, sourceKind: kind, optional: false, status, outcome }) as never;
  it('reflects only backend step states', () => {
    expect(layerState(null, ['registry']).state).toBe('idle');
    expect(layerState([step('registry', 'pending')], ['registry']).state).toBe('queued');
    expect(layerState([step('registry', 'running')], ['registry']).state).toBe('researching');
    expect(layerState([step('registry', 'done', 'verified')], ['registry']).state).toBe('verified');
    expect(layerState([step('website', 'done', 'not_available')], ['website']).state).toBe('unavailable');
    expect(layerState([step('jobs', 'blocked')], ['jobs']).state).toBe('blocked');
  });
});
