/**
 * UI/UX correction pass: Discover filters are a secondary drawer (no permanent rail), Compare is a true
 * side-by-side board (one aligned row per metric, one column per company), About is a scroll story
 * that degrades to a static page under reduced motion.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { renderWithProviders } from './utils';
import DiscoverPage from '@/pages/Discover/DiscoverPage';
import ComparePage from '@/pages/Compare/ComparePage';
import AboutPage from '@/pages/Settings/AboutPage';
import { usePreferences } from '@/stores/preferences';

afterEach(() => usePreferences.getState().set({ motion: 'system' }));

describe('Discover', () => {
  it('has no permanent filter rail; filters open in a drawer and keep their controls', async () => {
    renderWithProviders(
      <Routes>
        <Route path="/discover" element={<DiscoverPage />} />
      </Routes>,
      { route: '/discover?q=software%20companies%20in%20Oslo' },
    );
    const button = await screen.findByRole('button', { name: /^Filters/ }, { timeout: 4000 });
    expect(screen.queryByRole('complementary', { name: 'Filters' })).not.toBeInTheDocument();
    await waitFor(() => expect(button).toHaveTextContent(/2/), { timeout: 4000 }); // Location + Industry from the query
    fireEvent.click(button);
    const drawer = await screen.findByRole('dialog', { name: 'Filters' });
    await waitFor(() => expect(within(drawer).getByLabelText(/Location/)).toBeInTheDocument(), { timeout: 4000 });
    expect(within(drawer).getByLabelText(/Industry/)).toBeInTheDocument();
    expect(within(drawer).getByRole('button', { name: /Show \d+ compan/ })).toBeInTheDocument();
  });
});

describe('Compare', () => {
  it('lays companies out as peer columns with every metric on one aligned row', async () => {
    renderWithProviders(
      <Routes>
        <Route path="/compare" element={<ComparePage />} />
      </Routes>,
      { route: '/compare?orgs=921604337,918877231,976812873' },
    );
    const table = await screen.findByRole('table', { name: /Side-by-side comparison/ }, { timeout: 4000 });
    const heads = within(table).getAllByRole('columnheader');
    expect(heads).toHaveLength(4); // label column + 3 companies
    expect(heads[1]).toHaveTextContent('Nordvik Helseteknologi AS');
    expect(heads[1]).toHaveTextContent('Org. 921 604 337');
    expect(heads[1]).toHaveTextContent(/areas/);
    const revenueRows = within(table).getAllByRole('row').filter((r) => within(r).queryByRole('rowheader', { name: 'Revenue' }));
    expect(revenueRows.length).toBeGreaterThan(0);
    for (const r of revenueRows) expect(within(r).getAllByRole('cell')).toHaveLength(3); // one value per company, same row
    for (const label of ['At a glance', 'Overview', 'Financials', 'People']) expect(within(table).getByRole('rowheader', { name: label })).toBeInTheDocument();
  });
});

describe('About', () => {
  it('tells the story in seven chapters', () => {
    renderWithProviders(<AboutPage />);
    const index = screen.getByRole('navigation', { name: 'About chapters' });
    expect(within(index).getAllByRole('button')).toHaveLength(7);
    for (const h of [/Company intelligence/, /Find the/, /A dossier/, /Every fact shows/, /Sources have/, /A research run/, /Precision over recall/]) expect(screen.getByRole('heading', { name: h })).toBeInTheDocument();
    expect(document.querySelectorAll('[data-act]')).toHaveLength(6);
  });
  it('becomes a static page under reduced motion, with every chapter fully shown', () => {
    usePreferences.getState().set({ motion: 'reduced' });
    const { container } = renderWithProviders(<AboutPage />);
    expect(container.querySelector('.story')).toHaveClass('story--static');
    container.querySelectorAll<HTMLElement>('[data-act]').forEach((a) => expect(a.style.getPropertyValue('--p')).toBe('1'));
  });
});
