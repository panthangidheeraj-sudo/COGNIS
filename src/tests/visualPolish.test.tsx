/**
 * Final visual polish: DARK = INVESTIGATE, IVORY = UNDERSTAND.
 * Reading surfaces carry `.paper` (ivory); the investigation workspace around them stays dark.
 */
import { describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { renderWithProviders } from './utils';
import ComparePage from '@/pages/Compare/ComparePage';
import AboutPage from '@/pages/Settings/AboutPage';

describe('Compare', () => {
  it('sets the company headers and the at-a-glance rows on ivory, and keeps detail sections in the workspace', async () => {
    renderWithProviders(
      <Routes>
        <Route path="/compare" element={<ComparePage />} />
      </Routes>,
      { route: '/compare?orgs=921604337,918877231' },
    );
    const table = await screen.findByRole('table', { name: /Side-by-side comparison/ }, { timeout: 4000 });
    const heads = within(table).getAllByRole('columnheader').slice(1);
    for (const h of heads) expect(h).toHaveClass('paper');
    const glance = table.querySelector('#cmp-sec-glance')!;
    const glanceCells = glance.querySelectorAll('.cmp-cell');
    expect(glanceCells.length).toBeGreaterThan(0);
    glanceCells.forEach((c) => expect(c).toHaveClass('paper'));
    const financials = table.querySelector('#cmp-sec-financials')!;
    expect(financials.querySelectorAll('.cmp-cell').length).toBeGreaterThan(0);
    financials.querySelectorAll('.cmp-cell').forEach((c) => expect(c).not.toHaveClass('paper'));
  });
});

describe('About', () => {
  it('gives the evidence chapter and the closing notes ivory reading surfaces', () => {
    const { container } = renderWithProviders(<AboutPage />);
    expect(container.querySelector('#act-evidence')).toHaveClass('paper');
    expect(container.querySelector('.final-notes')).toHaveClass('paper');
    expect(container.querySelector('#act-verify')).not.toHaveClass('paper');
  });
});
