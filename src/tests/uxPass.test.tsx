/**
 * UX pass found by clicking through the running app:
 *  - choosing "Compare" on a profile or card said nothing and showed no way on (the tray only lives on /compare): it now toasts and the rail counts the selection;
 *  - a company that is not in the register offered "Retry" (which cannot help): it now offers a new search;
 *  - a failing global search left the command palette looking like "no results": it now says the search is unavailable.
 */
// @ts-expect-error -- this project has no @types/node; vitest runs in Node, so the module exists at runtime
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { renderWithProviders } from './utils';
import { api } from '@/api';
import { ApiError } from '@/api/http';
import { useCompare, useUi } from '@/stores/ui';
import { Rail } from '@/components/navigation/Rail';
import { Toaster } from '@/components/common/Toaster';
import { CommandPalette } from '@/components/search/CommandPalette';
import CompanyPage from '@/pages/Company/CompanyPage';
import { WebsiteSection } from '@/components/company/sections/OnlineHiring';
import { fullProfile, specsByOrg } from '@/data/mock/store';

const withSocial = () => [...specsByOrg.keys()].map((o) => fullProfile(o)).find((p) => p.website.social.length > 0)!;

const compareCss = readFileSync('src/pages/Compare/compare.css', 'utf8') as string;
const A = { orgNumber: '810359862', legalName: 'AUTOBJØRN A/S' };
const B = { orgNumber: '810034882', legalName: 'SANDNES ELEKTRISKE AS' };

beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  useCompare.getState().clear();
  useUi.setState({ toasts: [], paletteOpen: false, paletteQuery: '' });
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe('compare selection feedback', () => {
  it('says what happened after the first company and offers the comparison after the second', () => {
    useCompare.getState().toggle(A);
    expect(useUi.getState().toasts.at(-1)).toMatchObject({ tone: 'ok', text: expect.stringContaining('Pick one more company') });
    expect(useUi.getState().toasts.at(-1)?.action).toBeUndefined();

    useCompare.getState().toggle(B);
    const t = useUi.getState().toasts.at(-1)!;
    expect(t.text).toContain('2/5');
    expect(t.action).toEqual({ label: 'Open comparison', href: '/compare?orgs=810359862,810034882' });
  });

  it('stays silent when a company is removed again, and when the selection is full', () => {
    useCompare.getState().toggle(A);
    const before = useUi.getState().toasts.length;
    useCompare.getState().toggle(A); // removed
    expect(useUi.getState().toasts).toHaveLength(before);
    expect(useCompare.getState().selected).toHaveLength(0);

    for (let i = 0; i < 5; i++) useCompare.getState().toggle({ orgNumber: `81000000${i}`, legalName: `C${i}` });
    const full = useUi.getState().toasts.length;
    useCompare.getState().toggle({ orgNumber: '810000009', legalName: 'Sixth' });
    expect(useUi.getState().toasts).toHaveLength(full); // nothing added, nothing announced
    expect(useCompare.getState().selected).toHaveLength(5);
  });

  it('renders the toast with a working link to the comparison', () => {
    renderWithProviders(<Toaster />);
    act(() => {
      useCompare.getState().toggle(A);
      useCompare.getState().toggle(B);
    });
    expect(screen.getByRole('link', { name: 'Open comparison' })).toHaveAttribute('href', '/compare?orgs=810359862,810034882');
  });

  it('counts the selection on the Compare item of the rail', () => {
    renderWithProviders(<Rail />);
    expect(screen.queryByLabelText(/selected for comparison/)).not.toBeInTheDocument();
    act(() => useCompare.getState().toggle(A));
    expect(screen.getByLabelText('1 company selected for comparison')).toHaveTextContent('1');
    act(() => useCompare.getState().toggle(B));
    expect(screen.getByLabelText('2 companies selected for comparison')).toHaveTextContent('2');
  });
});

describe('company not found', () => {
  it('offers a new search instead of Retry', async () => {
    vi.spyOn(api.companies, 'get').mockRejectedValue(new ApiError('not_found', 'No company with organisation number 000000000 was found in Enhetsregisteret.', 404));
    renderWithProviders(
      <Routes>
        <Route path="/company/:orgNumber" element={<CompanyPage />} />
      </Routes>,
      { route: '/company/000000000' },
    );
    expect(await screen.findByText(/No company with organisation number 000000000/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Retry/ })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Search companies/ })).toHaveAttribute('href', '/discover');
  });

  it('keeps Retry for failures that can pass on a second try', async () => {
    vi.spyOn(api.companies, 'get').mockRejectedValue(new ApiError('network', 'The COGNIS backend could not be reached.'));
    renderWithProviders(
      <Routes>
        <Route path="/company/:orgNumber" element={<CompanyPage />} />
      </Routes>,
      { route: '/company/810359862' },
    );
    expect(await screen.findByRole('button', { name: /Retry/ })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Search companies/ })).not.toBeInTheDocument();
  });
});

describe('command palette when search fails', () => {
  it('says the company search is unavailable instead of looking empty', async () => {
    vi.spyOn(api.search, 'global').mockRejectedValue(new ApiError('unavailable', 'boom', 500));
    renderWithProviders(<CommandPalette />);
    act(() => useUi.getState().openPalette());
    fireEvent.change(await screen.findByRole('combobox'), { target: { value: 'autob' } });
    expect(await screen.findByText('Company search is unavailable right now.')).toBeInTheDocument();
    expect(screen.queryByText(/No matches/)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
  });
});

describe('compare tray and board (mobile polish)', () => {
  it('the tray counts the selection and does not repeat the page chips', async () => {
    const { CompareTray } = await import('@/components/navigation/CompareTray');
    const { createMemoryRouter, RouterProvider } = await import('react-router-dom');
    useCompare.getState().setAll([A, B]);
    const router = createMemoryRouter([{ path: '/compare', element: <CompareTray />, handle: { compareTray: true } }], { initialEntries: ['/compare'] });
    const { render } = await import('@testing-library/react');
    render(<RouterProvider router={router} />);
    const tray = await screen.findByRole('region', { name: /selected for comparison/ });
    expect(tray).toHaveTextContent('2/5 selected');
    expect(tray).not.toHaveTextContent('AUTOBJØRN');
    expect(screen.getByRole('button', { name: 'Clear' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Compare/ })).toBeEnabled();
  });

  it('the board scroller anchors absolutely positioned cell content (else it widens the page on phones)', () => {
    expect(/\.cmp-board\s*{[^}]*position:\s*relative/s.test(compareCss)).toBe(true);
  });
});

describe('command palette focus', () => {
  it('returns focus to the control that was focused before it opened', async () => {
    const { rerender } = renderWithProviders(<button>trigger</button>);
    void rerender;
    const trigger = screen.getByRole('button', { name: 'trigger' });
    trigger.focus();
    renderWithProviders(<CommandPalette />);
    act(() => useUi.getState().openPalette());
    expect(await screen.findByRole('combobox')).toHaveFocus();
    act(() => useUi.getState().closePalette());
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});

describe('social presence wording', () => {
  it('says where each link was found and that the platform itself was not checked; never "verified"', () => {
    const profile = withSocial();
    expect(profile.website.social.length).toBeGreaterThan(0);
    renderWithProviders(<WebsiteSection profile={profile} />);
    const block = document.querySelector('[data-search-block="website-social"]') as HTMLElement;
    expect(block.textContent).toMatch(/Link found via .*not checked on the platform itself/);
    expect(block.textContent).not.toMatch(/verified/i);
    expect(screen.getAllByRole('button', { name: 'View evidence' }).length).toBe(profile.website.social.length);
  });
  it('does not call an empty list "verified"', () => {
    const profile = withSocial();
    renderWithProviders(<WebsiteSection profile={{ ...profile, website: { ...profile.website, social: [] , signals: [{ label: 'x', value: 'y' }] } }} />);
    expect(screen.getByText('No social profiles established from the searched sources.')).toBeInTheDocument();
  });
});
