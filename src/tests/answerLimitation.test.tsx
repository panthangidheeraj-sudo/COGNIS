/** A question that public evidence cannot answer shows the limit itself — not saved facts and not a blank answer. */
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from './utils';
import { AnswerView } from '@/components/research/AnswerView';
import type { ResearchAnswer } from '@/types';

const base: ResearchAnswer = { id: 'a1', question: 'What confidential future contracts will it win?', origin: 'saved_evidence', blocks: [], generatedAt: '2026-10-12T10:00:00Z' };

describe('AnswerView limitations', () => {
  it('states the limitation when no evidence can answer the question', () => {
    renderWithProviders(<AnswerView answer={{ ...base, limitation: 'This cannot be answered from public sources. Confidential matters are not published.' }} sourceIndex={{}} />);
    expect(screen.getByRole('note')).toHaveTextContent('This cannot be answered from public sources');
    expect(screen.queryByText('The available evidence does not answer this question.')).not.toBeInTheDocument();
  });

  it('shows the dated announcement with a link to its source', () => {
    const answer: ResearchAnswer = {
      ...base,
      question: 'Which contracts were announced in the last 12 months?',
      blocks: [{ id: 'b1', text: '1 Sep 2026 — Signs framework agreement. Source: the company newsroom.', detail: 'https://www.firma.no/nyheter/c1', citations: [] }],
      gaps: ['No discoveries announcement dated within the last 12 months was found in the evidence on record.'],
    };
    renderWithProviders(<AnswerView answer={answer} sourceIndex={{}} />);
    expect(screen.getByRole('link', { name: 'Open source' })).toHaveAttribute('href', 'https://www.firma.no/nyheter/c1');
    expect(screen.getByText(/No discoveries announcement/)).toBeInTheDocument();
  });
});
