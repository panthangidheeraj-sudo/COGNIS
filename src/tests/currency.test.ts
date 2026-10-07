/**
 * Regression (QA, Equinor ASA 923609016): a USD filing must never be shown — or exported — as NOK.
 * The backend states the currency on every fact/series/snapshot; the UI must use exactly that and never assume one.
 */
import { describe, expect, it } from 'vitest';
import { factChange, formatFactValue, formatMoneyCompact, formatMoneyExact, isCurrencyUnit, isMoneyUnit, MIXED_CURRENCIES } from '@/utils/format';

const usd = { value: 67_960_000_000, unit: 'USD', currency: 'USD', field: 'financials.revenue.2025' };

describe('currency is taken from the record, never assumed', () => {
  it('renders a USD fact as USD (compact and exact)', () => {
    expect(formatFactValue(usd)).toBe('USD 67.96B');
    expect(formatFactValue(usd, { exact: true })).toBe('67 960 000 000 USD');
    expect(formatFactValue({ ...usd, displayValue: 'USD 67.96B' })).toBe('USD 67.96B');
  });
  it('falls back to the unit only when it is a currency code', () => {
    expect(formatFactValue({ value: 1_000_000, unit: 'EUR', field: 'x' })).toBe('EUR 1M');
    expect(formatFactValue({ value: 21272, unit: 'people', field: 'overview.employees' })).toBe('21,272');
  });
  it('a fact without a stated currency shows the bare number, not NOK', () => {
    expect(formatFactValue({ value: 123_000_000, field: 'financials.revenue.2025' })).toBe('123,000,000');
    expect(formatMoneyCompact(123_000_000, undefined)).not.toMatch(/NOK/);
  });
  it('identifies money units', () => {
    expect(['NOK', 'USD', 'EUR'].every(isCurrencyUnit)).toBe(true);
    expect(['people', '%', 'sites', MIXED_CURRENCIES, 'currency not stated', '', undefined].some((u) => isCurrencyUnit(u))).toBe(false);
    expect(isMoneyUnit(MIXED_CURRENCIES) && isMoneyUnit('USD') && !isMoneyUnit('people')).toBe(true);
  });
});

describe('changes are only computed inside one currency', () => {
  it('computes a change between two USD amounts', () => {
    expect(factChange({ value: 72_540_000_000, currency: 'USD', unit: 'USD' }, { value: 67_960_000_000, currency: 'USD', unit: 'USD' })).toBeCloseTo(-6.31, 1);
  });
  it('refuses a change across a currency switch (no conversion)', () => {
    expect(factChange({ value: 8_000_000_000, currency: 'NOK', unit: 'NOK' }, { value: 900_000_000, currency: 'USD', unit: 'USD' })).toBeNull();
  });
  it('refuses a change between amounts that state no currency', () => {
    expect(factChange({ value: 110, currency: undefined, unit: undefined }, { value: 123, currency: undefined, unit: undefined })).toBeNull();
    expect(factChange({ value: 110, currency: 'NOK', unit: 'NOK' }, { value: 123, currency: undefined, unit: undefined })).toBeNull();
  });
  it('still computes non-money changes (employees)', () => {
    expect(factChange({ value: 100, unit: 'people' }, { value: 110, unit: 'people' })).toBeCloseTo(10, 5);
  });
});

describe('exact amounts keep their own label', () => {
  it('does not relabel a USD amount as NOK', () => {
    expect(formatMoneyExact(67_960_000_000, 'USD')).not.toContain('NOK');
  });
});
