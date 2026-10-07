/** Regression (QA, Equinor ASA): the screens must show the currency the filing states — USD stays USD everywhere a revenue figure appears. */
import { describe, expect, it } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import { renderWithProviders } from './utils';
import { MetricCard } from '@/components/evidence/MetricCard';
import { EvidenceDrawer } from '@/components/evidence/EvidenceDrawer';
import { AmbiguousCandidates } from '@/components/research/AmbiguousCandidates';
import { CompanyCard } from '@/components/company/CompanyCard';
import { useUi } from '@/stores/ui';
import type { CompanySummary, Fact } from '@/types';

const source = { id: 'accounts', name: 'Regnskapsregisteret', kind: 'financial' as const, tier: 'primary' as const, official: true };
const excerpt = 'resultatregnskapResultat.driftsresultat.driftsinntekter.sumDriftsinntekter = 67960000000 USD (regnskapsperiode 2025-01-01–2025-12-31, regnskapstype SELSKAP)';
const equinorRevenue: Fact = {
  id: '923609016:financials.revenue.2025',
  field: 'financials.revenue.2025',
  label: 'Revenue',
  status: 'verified',
  value: 67_960_000_000,
  displayValue: 'USD 67.96B',
  unit: 'USD',
  currency: 'USD',
  reportingPeriod: 'FY2025',
  verifiedAt: '2026-10-05T10:00:00Z',
  evidenceState: 'primary',
  evidence: [{ id: 'e1', sourceId: 'accounts', retrievedAt: '2026-10-05T10:00:00Z', excerpt, reportingPeriod: 'FY2025' }],
};
const equinor = (over: Partial<CompanySummary> = {}): CompanySummary => ({
  orgNumber: '923609016',
  legalName: 'EQUINOR ASA',
  country: 'Norway',
  status: 'active',
  coverage: { complete: 4, total: 5, areas: [] },
  researchState: 'researched',
  revenue: { value: 67_960_000_000, currency: 'USD', period: 'FY2025' },
  ...over,
});

describe('USD filings are shown as USD', () => {
  it('the revenue metric card and its evidence agree on the currency', () => {
    renderWithProviders(
      <>
        <MetricCard fact={equinorRevenue} sourceIndex={{ accounts: source }} />
        <EvidenceDrawer />
      </>,
    );
    const card = screen.getByRole('button', { name: /Revenue/ });
    expect(card).toHaveTextContent('USD 67.96B');
    expect(card).not.toHaveTextContent('NOK');
    fireEvent.click(card);
    const dialog = screen.getByRole('dialog', { name: /Evidence: Revenue/ });
    expect(dialog).toHaveTextContent('67960000000 USD');
    expect(dialog).not.toHaveTextContent('NOK');
    useUi.getState().closeEvidence();
  });

  it('a conflicting secondary value is labelled with the fact’s own currency, not NOK', () => {
    const conflicted: Fact = {
      ...equinorRevenue,
      evidenceState: 'conflict',
      conflict: { reason: 'Different accounting scope.', candidates: [{ sourceId: 'accounts', value: 67_960_000_000, evidenceId: 'e1' }, { sourceId: 'proff', value: 68_100_000_000, evidenceId: 'e2' }] },
      evidence: [...equinorRevenue.evidence, { id: 'e2', sourceId: 'proff', retrievedAt: '2026-10-05T10:00:00Z', excerpt: 'Driftsinntekter 68100000000', statedValue: '68100000000' }],
    };
    renderWithProviders(
      <>
        <MetricCard fact={conflicted} sourceIndex={{ accounts: source, proff: { ...source, id: 'proff', name: 'Proff.no', tier: 'secondary', official: false } }} />
        <EvidenceDrawer />
      </>,
    );
    fireEvent.click(screen.getByRole('button', { name: /Revenue/ }));
    const dialog = screen.getByRole('dialog', { name: /Evidence: Revenue/ });
    expect(dialog).toHaveTextContent('68 100 000 000 USD');
    expect(dialog).not.toHaveTextContent('NOK');
    useUi.getState().closeEvidence();
  });

  it('company cards and ambiguous-match lists use the revenue currency from the snapshot', () => {
    renderWithProviders(<CompanyCard c={equinor()} />);
    expect(screen.getByText('USD 67.96B')).toBeInTheDocument();
    expect(screen.queryByText(/NOK/)).not.toBeInTheDocument();
  });

  it('ambiguous candidates never relabel a USD revenue as NOK', () => {
    renderWithProviders(<AmbiguousCandidates match={{ query: 'Equinor', message: 'Possible matches.', candidates: [equinor()] }} />);
    expect(screen.getByText(/USD 67\.96B \(FY2025\)/)).toBeInTheDocument();
    expect(screen.queryByText(/NOK/)).not.toBeInTheDocument();
  });

  it('a revenue snapshot without a stated currency shows the bare number', () => {
    renderWithProviders(<AmbiguousCandidates match={{ query: 'x', message: 'm', candidates: [equinor({ revenue: { value: 123_000_000, currency: '', period: 'FY2025' } })] }} />);
    expect(screen.getByText(/123M \(FY2025\)/)).toBeInTheDocument();
    expect(screen.queryByText(/NOK/)).not.toBeInTheDocument();
  });
});
