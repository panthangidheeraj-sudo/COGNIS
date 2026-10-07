import { describe, expect, it } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import { renderWithProviders } from './utils';
import { MetricCard } from '@/components/evidence/MetricCard';
import { EvidenceDrawer } from '@/components/evidence/EvidenceDrawer';
import { CoverageMeter } from '@/components/company/Coverage';
import { StatusMark } from '@/components/common/StatusPill';
import { Tabs } from '@/components/common/Tabs';
import { ErrorState } from '@/components/common/ErrorState';
import { AmbiguousCandidates } from '@/components/research/AmbiguousCandidates';
import { ResearchPlanView } from '@/components/research/ResearchPlan';
import { useUi } from '@/stores/ui';
import { ApiError } from '@/api/http';
import { mockApi } from '@/data/mock/mockApi';
import type { Fact } from '@/types';

const source = { id: 'accounts', name: 'Regnskapsregisteret', kind: 'financial' as const, tier: 'primary' as const, official: true };
const revenue: Fact = {
  id: 'f1',
  field: 'financials.revenue.2025',
  label: 'Revenue',
  status: 'verified',
  value: 790400865,
  unit: 'NOK',
  currency: 'NOK',
  reportingPeriod: 'FY2025',
  verifiedAt: '2026-10-03T10:00:00Z',
  evidenceState: 'conflict',
  evidence: [{ id: 'e1', sourceId: 'accounts', retrievedAt: '2026-10-03T10:00:00Z', excerpt: 'Sum driftsinntekter 790 400 865', reportingPeriod: 'FY2025' }],
  conflict: { reason: 'Different accounting scope.', candidates: [{ sourceId: 'accounts', value: 790400865, evidenceId: 'e1' }, { sourceId: 'proff', value: 810000000, evidenceId: 'e2' }] },
};

describe('evidence UI', () => {
  it('metric card opens the evidence drawer with source, period and conflict', () => {
    renderWithProviders(
      <>
        <MetricCard fact={revenue} sourceIndex={{ accounts: source }} />
        <EvidenceDrawer />
      </>,
    );
    fireEvent.click(screen.getByRole('button', { name: /Revenue/ }));
    const dialog = screen.getByRole('dialog', { name: /Evidence: Revenue/ });
    expect(dialog).toHaveTextContent('Regnskapsregisteret');
    expect(dialog).toHaveTextContent('FY2025');
    expect(dialog).toHaveTextContent('Sources disagree');
    expect(dialog).toHaveTextContent('Different accounting scope.');
    useUi.getState().closeEvidence();
  });

  it('metric card shows missing values honestly', () => {
    renderWithProviders(<MetricCard fact={{ ...revenue, value: null, status: 'not_available', conflict: undefined, note: 'No filed annual accounts found.' }} sourceIndex={{}} />);
    expect(screen.getByText('Not available')).toBeInTheDocument();
    expect(screen.getByText('No filed annual accounts found.')).toBeInTheDocument();
  });

  it('coverage never hides missing areas', () => {
    renderWithProviders(
      <CoverageMeter
        coverage={{
          complete: 4,
          total: 5,
          areas: [
            { area: 'company_record', status: 'complete', factCount: 1 },
            { area: 'financials', status: 'complete', factCount: 1 },
            { area: 'people_locations', status: 'complete', factCount: 1 },
            { area: 'website', status: 'complete', factCount: 1 },
            { area: 'hiring_activity', status: 'unavailable', factCount: 0, note: 'Hiring data unavailable' },
          ],
        }}
      />,
    );
    expect(screen.getByText('4/5 areas')).toBeInTheDocument();
    expect(screen.getByText(/Hiring data unavailable/)).toBeInTheDocument();
  });

  it('status marks carry text, not color only', () => {
    renderWithProviders(<StatusMark status="blocked" />);
    expect(screen.getByRole('status')).toHaveTextContent('Source blocked');
  });
});

describe('states', () => {
  it('friendly error without stack traces', () => {
    renderWithProviders(<ErrorState error={new ApiError('network', 'The COGNIS backend could not be reached.')} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Backend unreachable');
    expect(screen.getByRole('alert')).not.toHaveTextContent('at ');
  });
  it('ambiguous identity asks instead of guessing', () => {
    renderWithProviders(
      <AmbiguousCandidates
        match={{
          query: 'Solstad Data',
          message: 'We found possible matches, but could not establish exact-company identity.',
          candidates: [
            { orgNumber: '1', legalName: 'Solstad Data AS', country: 'Norway', status: 'active', coverage: { complete: 1, total: 5, areas: [] }, researchState: 'not_researched' },
            { orgNumber: '2', legalName: 'Solstad Datasystemer AS', country: 'Norway', status: 'active', coverage: { complete: 1, total: 5, areas: [] }, researchState: 'not_researched' },
          ],
        }}
      />,
    );
    expect(screen.getByText(/could not establish exact-company identity/)).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Open' })).toHaveLength(2);
  });
  it('research plan shows only backend-reported step states', () => {
    renderWithProviders(
      <ResearchPlanView
        plan={{
          requiresConfirmation: false,
          availableSteps: [],
          steps: [
            { id: 's1', key: 'identity', label: 'Verify identity', sourceKind: 'registry', optional: false, status: 'done', sourceName: 'Brønnøysundregistrene', factCount: 7, evidenceCount: 7 },
            { id: 's2', key: 'website', label: 'Company website', sourceKind: 'website', optional: true, status: 'blocked', message: 'Source access blocked' },
            { id: 's3', key: 'hiring', label: 'Hiring', sourceKind: 'jobs', optional: true, status: 'pending' },
          ],
        }}
      />,
    );
    expect(screen.getByText('7 facts · 7 evidence')).toBeInTheDocument();
    expect(screen.getByText('Source access blocked')).toBeInTheDocument();
  });
});

describe('accessibility', () => {
  it('tabs support arrow-key navigation', () => {
    let value = 'a';
    const { rerender } = renderWithProviders(<Tabs label="t" value={value} onChange={(v) => (value = v)} tabs={[{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }]} />);
    fireEvent.keyDown(screen.getByRole('tablist'), { key: 'ArrowRight' });
    expect(value).toBe('b');
    rerender(<Tabs label="t" value={value} onChange={(v) => (value = v)} tabs={[{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }]} />);
  });
});

describe('mock backend integration', () => {
  it('blocked website is reported as blocked, not empty', async () => {
    const p = await mockApi.companies.get('996450218');
    expect(p.website.status).toBe('blocked');
    expect(p.knowns.find((k) => k.id === 'k-web')?.status).toBe('blocked');
  });
  it('unresearched companies expose registry data and pending areas only', async () => {
    const p = await mockApi.companies.get('927004418');
    expect(p.company.researchState).toBe('not_researched');
    expect(p.hiring.status).toBe('pending');
    expect(p.summary).toBeNull();
  });
});
