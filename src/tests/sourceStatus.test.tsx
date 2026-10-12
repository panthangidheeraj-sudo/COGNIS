/**
 * Source availability: sources COGNIS deliberately does not use read as a choice ("Free alternative", "Not used"),
 * never as "Unavailable".
 */
import { describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';
import { renderWithProviders } from './utils';
import { HiringNotice } from '@/components/company/sections/OnlineHiring';
import type { HiringSection } from '@/types';
import SettingsPage from '@/pages/Settings/SettingsPage';
import { SOURCE_AVAILABILITY, toneClass } from '@/utils/status';

describe('source availability', () => {
  it('maps every backend status to a label and tone', () => {
    expect(SOURCE_AVAILABILITY.alternative.label).toBe('Free alternative');
    expect(SOURCE_AVAILABILITY.not_used.label).toBe('Not used');
    expect(toneClass(SOURCE_AVAILABILITY.not_used.tone)).toBe('');
    expect(toneClass(SOURCE_AVAILABILITY.unavailable.tone)).toBe('pill--err');
  });

  it('shows Proff and Doffin as free alternatives and LinkedIn as not used', async () => {
    renderWithProviders(<SettingsPage />);
    const heading = await screen.findByRole('heading', { name: 'Source availability' });
    const section = heading.closest('section')!;
    const row = async (name: RegExp) => (await within(section).findByText(name)).closest('li')!;
    expect(within(await row(/^Proff\.no$/)).getByText('Free alternative')).toBeInTheDocument();
    expect(within(await row(/^Doffin/)).getByText('Free alternative')).toBeInTheDocument();
    expect(within(await row(/^LinkedIn$/)).getByText('Not used')).toBeInTheDocument();
    expect(within(await row(/^NAV Arbeidsplassen/)).getByText('Available')).toBeInTheDocument();
  });

  it('lists the hiring sources as they really work: Fakt.no is not used, never available', async () => {
    renderWithProviders(<SettingsPage />);
    const heading = await screen.findByRole('heading', { name: 'Source availability' });
    const section = heading.closest('section')!;
    const row = async (name: RegExp) => (await within(section).findByText(name)).closest('li')!;
    expect(within(await row(/^Fakt\.no$/)).getByText('Not used')).toBeInTheDocument();
    expect(within(await row(/^Fakt\.no$/)).queryByText('Available')).not.toBeInTheDocument();
    expect(within(await row(/^Company careers pages and linked job boards/)).getByText('Available')).toBeInTheDocument();
    expect(within(section).getByText(/Discovery only: every page is fetched, identity-checked and re-verified/)).toBeInTheDocument();
    expect(within(section).getByText(/never "no openings"/)).toBeInTheDocument();
  });
});

describe('hiring outcome', () => {
  const base: HiringSection = { status: 'partial', totalCurrent: null, locations: [], categories: [], jobs: [], history: [] };
  const checks = [
    { id: 'careers', name: 'Company careers pages', state: 'checked' as const, note: 'Careers page read.', required: true },
    { id: 'nav', name: 'NAV Arbeidsplassen', state: 'unavailable' as const, note: 'NAV did not answer within 25 s.', required: true },
  ];

  it('says "source unavailable" for a NAV timeout and never "no openings"', () => {
    const { container } = renderWithProviders(
      <HiringNotice h={{ ...base, outcome: 'source_unavailable', message: 'NAV Arbeidsplassen could not be checked. This is not evidence that the company has no openings.', checks }} />,
    );
    expect(screen.getByText('Hiring source unavailable')).toBeInTheDocument();
    expect(screen.getByText(/NAV Arbeidsplassen: unavailable — NAV did not answer/)).toBeInTheDocument();
    expect(container.querySelector('[data-outcome="source_unavailable"]')).not.toBeNull();
    expect(screen.queryByText(/No verified openings found/)).not.toBeInTheDocument();
  });

  it('distinguishes none found, incomplete and verified', () => {
    const none = renderWithProviders(<HiringNotice h={{ ...base, status: 'not_available', outcome: 'none_found', message: 'No verified openings found in the sources checked. This does not mean the company is not hiring.' }} />);
    expect(screen.getByText('No verified openings found')).toBeInTheDocument();
    none.unmount();
    const inc = renderWithProviders(<HiringNotice h={{ ...base, outcome: 'incomplete', message: 'Hiring research is incomplete.' }} />);
    expect(screen.getByText('Hiring research incomplete')).toBeInTheDocument();
    inc.unmount();
    const ok = renderWithProviders(<HiringNotice h={{ ...base, status: 'available', totalCurrent: 2, outcome: 'verified' }} />);
    expect(ok.container.querySelector('[data-testid="hiring-outcome"]')).toBeNull();
  });
});
