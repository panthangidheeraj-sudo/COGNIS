/**
 * The answer's source list and "Sources checked for this answer" show what was really retrieved: a link is labelled as the filed copy only when it is one,
 * standalone and consolidated figures keep their own scope and period, and an empty "Sources checked" section says why it is empty.
 */
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { Answer, CheckedNow } from '@/components/chat/ChatParts';
import type { ChatReply, ChatSource } from '@/types';

const FILING = 'https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/923609016/2024';
const RECORD = 'https://data.brreg.no/regnskapsregisteret/regnskap/923609016';

const src = (over: Partial<ChatSource>): ChatSource => ({
  n: 1,
  kind: 'fact',
  title: 'Annual accounts',
  sourceLabel: 'Official register',
  sourceClass: 'official_register',
  retrievedAt: '2026-10-16T10:00:00Z',
  origin: 'fresh',
  ...over,
});
const base = (over: Partial<ChatReply>): ChatReply =>
  ({
    company: { orgNumber: '923609016', legalName: 'EQUINOR ASA' },
    kind: 'model',
    answer: 'Standalone revenue for FY2024 was NOK 26.5M [1]. Consolidated revenue for FY2025 was NOK 31.0M [2].',
    citations: [],
    sources: [],
    coverage: [],
    search: { state: 'not_used', note: 'Answered from saved, verified research.' },
    origin: 'fresh',
    generatedAt: '2026-10-16T10:00:00Z',
    ...over,
  }) as ChatReply;

describe('source list', () => {
  const sources = [
    src({ n: 1, title: 'Annual accounts FY2024 — filed copy listed by Regnskapsregisteret (standalone company figures)', url: FILING, recordUrl: RECORD, linkKind: 'filing_document', reportingPeriod: 'FY2024', accountingScope: 'standalone company', currency: 'NOK' }),
    src({ n: 2, title: 'Annual accounts FY2025 — consolidated group figures from the Regnskapsregisteret data record', url: RECORD, linkKind: 'register_record', reportingPeriod: 'FY2025', accountingScope: 'consolidated group', currency: 'NOK' }),
  ];

  it('labels the filed copy as the filing, and the register data record as NOT the filing', () => {
    render(<Answer reply={base({ citations: sources, sources, provenanceNote: 'Direct links to the filed annual accounts are given for FY2024 (copies listed by Regnskapsregisteret).' })} turnId="t1" />);
    const list = screen.getByRole('region', { name: 'Sources' }).querySelectorAll('li');
    expect(list[0]).toHaveTextContent('Direct link: the filed copy of the annual accounts');
    expect(list[0].querySelector('[data-link-kind="filing_document"]')).not.toBeNull();
    expect(within(list[0] as HTMLElement).getByRole('link', { name: /the Regnskapsregisteret data record/ })).toHaveAttribute('href', RECORD); // where the figures were read
    expect(list[1]).toHaveTextContent('the register’s data record — not a copy of the filing');
    expect(list[1]).not.toHaveTextContent('Direct link: the filed copy');
  });

  it('keeps each figure’s accounting scope and period next to its source', () => {
    render(<Answer reply={base({ citations: sources, sources })} turnId="t2" />);
    const list = screen.getByRole('region', { name: 'Sources' }).querySelectorAll('li');
    expect(list[0]).toHaveTextContent('period FY2024');
    expect(list[0]).toHaveTextContent('standalone company');
    expect(list[1]).toHaveTextContent('period FY2025');
    expect(list[1]).toHaveTextContent('consolidated group');
  });

  it('shows the provenance note that the server decided from the sources', () => {
    render(<Answer reply={base({ citations: sources, sources, provenanceNote: 'No direct link to a filed copy was established for FY2025.' })} turnId="t3" />);
    expect(screen.getByText('No direct link to a filed copy was established for FY2025.')).toBeInTheDocument();
  });
});

describe('Sources checked for this answer', () => {
  it('lists only sources that were really read; search calls and unopened results are counted, not listed', () => {
    render(
      <CheckedNow
        search={{
          state: 'used',
          note: 'Checked current sources.',
          checked: [
            { name: 'Regnskapsregisteret — data record of the latest filed annual accounts', url: RECORD, state: 'used', kind: 'official' },
            { name: 'Web search (Tavily)', state: 'used', kind: 'search', reason: '3 result(s)' },
            { name: 'example.com', url: 'https://example.com/x', state: 'skipped', reason: 'not a permitted source' },
            { name: 'e24.no', url: 'https://e24.no/a', state: 'unreadable', reason: 'the page did not respond in time' },
          ],
          web: { searches: 1, results: 3, notOpened: 1, state: 'used' },
        }}
      />,
    );
    const box = screen.getByTestId('checked-now');
    fireEvent.click(within(box).getByText(/Sources checked for this answer \(2\)/));
    const rows = box.querySelectorAll('li');
    expect(rows).toHaveLength(2);
    expect(box).toHaveTextContent('data record of the latest filed annual accounts');
    expect(box).toHaveTextContent('could not be read: the page did not respond in time');
    expect(box).not.toHaveTextContent('example.com');
    expect(box).toHaveTextContent('Web search: 1 search, 3 results; 1 not opened');
  });

  it('when nothing was checked it says so, and why, instead of showing an empty list', () => {
    const { unmount } = render(<CheckedNow search={{ state: 'not_used', note: 'Answered from saved, verified research.' }} />);
    expect(screen.getByTestId('checked-now')).toHaveTextContent('Sources checked for this answer (0)');
    expect(screen.getByTestId('checked-now')).toHaveTextContent('No current sources were checked for this answer: it is written from the saved research');
    unmount();
    render(<CheckedNow search={{ state: 'unavailable', note: 'Web search was unavailable (limit) — no paid fallback is used.', checked: [] }} />);
    expect(screen.getByTestId('checked-now')).toHaveTextContent('No source could be read for this answer: the reason is in the note above.');
  });

  it('is shown on every answer, but not on a clarification', () => {
    const { unmount } = render(<Answer reply={base({})} turnId="t4" />);
    expect(screen.getByTestId('checked-now')).toBeInTheDocument();
    unmount();
    render(<Answer reply={base({ kind: 'clarification', answer: 'Which company?' })} turnId="t5" />);
    expect(screen.queryByTestId('checked-now')).not.toBeInTheDocument();
  });
});
