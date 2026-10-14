/** Recent activity: Major / Relevant / Routine are kept apart, registrations are never counted as developments, and source limits are shown. */
import { describe, expect, it } from 'vitest';
import { fireEvent, screen, within } from '@testing-library/react';
import { renderWithProviders } from './utils';
import { ActivitySection } from '@/components/company/sections/ActivitySources';
import { mockApi } from '@/data/mock/mockApi';
import type { ActivitySection as Activity, CompanyProfile, TimelineEvent } from '@/types';

const ev = (id: string, title: string, date: string, over: Partial<TimelineEvent> = {}): TimelineEvent => ({
  id,
  date,
  type: 'announcement',
  title,
  significance: 'routine',
  sourceIds: ['web-1'],
  evidence: [{ id: `e-${id}`, sourceId: 'web-1', url: `https://example.test/${id}`, retrievedAt: '2026-10-01T10:00:00Z', excerpt: title }],
  ...over,
});

async function profileWith(activity: Partial<Activity>): Promise<CompanyProfile> {
  const base = await mockApi.companies.get('921604337');
  return {
    ...base,
    sourceIndex: { ...base.sourceIndex, 'web-1': { id: 'web-1', name: 'Official website (example.test)', kind: 'website', tier: 'primary', official: true } },
    activity: { status: 'available', events: [], ...activity },
  };
}

const registrations = Array.from({ length: 12 }, (_, i) => ev(`r${i}`, `Establishment opened: AVD ${i}`, `2025-0${(i % 9) + 1}-10`, { type: 'location', sourceType: 'official_registry' }));
const events = [
  ev('c1', 'Signs framework agreement worth 400 million with the Defence Materiel Agency', '2026-09-20', {
    type: 'contract',
    significance: 'major',
    score: 96,
    rank: 1,
    sourceType: 'company_newsroom',
    reasons: ['Contract or order (decisive wording)', 'Stated amount 400.0 million'],
    url: 'https://example.test/c1',
    sources: [
      { sourceIds: ['web-1'], sourceType: 'company_newsroom', url: 'https://example.test/nyheter' },
      { sourceIds: ['web-1'], sourceType: 'company_newsroom', url: 'https://example.test/feed.xml' },
    ],
  }),
  ev('p1', 'Strategic partnership to develop autonomous vessels', '2026-08-02', { type: 'partnership', significance: 'major', score: 70, rank: 2, sourceType: 'company_newsroom' }),
  ev('o1', 'Opens new office in Bergen', '2026-07-01', { type: 'location', significance: 'relevant', score: 45, rank: 3, sourceType: 'company_newsroom' }),
  ev('w1', 'Invitation to webinar', '2026-09-28', { significance: 'routine', score: 7, rank: 4, sourceType: 'company_newsroom' }),
  ...registrations.map((r, i) => ({ ...r, significance: 'routine' as const, rank: 5 + i })),
];

describe('Recent activity timeline', () => {
  it('opens on the major developments and counts tiers instead of inflating them', async () => {
    const profile = await profileWith({ events });
    renderWithProviders(<ActivitySection profile={profile} />);
    expect(screen.getByTestId('activity-counts')).toHaveTextContent('2 major · 1 relevant · 13 routine');
    const timeline = document.querySelector('.timeline') as HTMLElement;
    expect(within(timeline).getByText(/framework agreement/)).toBeInTheDocument();
    expect(within(timeline).getByText(/autonomous vessels/)).toBeInTheDocument();
    expect(within(timeline).queryByText(/Establishment opened/)).not.toBeInTheDocument(); // register entries do not crowd the major view
    expect(within(timeline).queryByText(/Opens new office/)).not.toBeInTheDocument();
  });

  it('Major + relevant adds relevant events; All events keeps the routine register entries available', async () => {
    const profile = await profileWith({ events });
    renderWithProviders(<ActivitySection profile={profile} />);
    fireEvent.click(screen.getByRole('button', { name: 'Major + relevant' }));
    expect(screen.getByText(/Opens new office/)).toBeInTheDocument();
    expect(screen.queryByText(/Invitation to webinar/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'All events' }));
    expect(screen.getAllByText(/Establishment opened/)).toHaveLength(12);
    expect(screen.getByText(/Invitation to webinar/)).toBeInTheDocument();
  });

  it('a profile without major events opens on the broadest view that has something, and says what is hidden', async () => {
    const profile = await profileWith({ events: registrations.map((r) => ({ ...r, significance: 'routine' as const })) });
    renderWithProviders(<ActivitySection profile={profile} />);
    expect(screen.getAllByText(/Establishment opened/)).toHaveLength(12);
    expect(screen.getByTestId('activity-counts')).toHaveTextContent('0 major · 0 relevant · 12 routine');
  });

  it('shows the tier on every event and, when expanded, why it was ranked that way and where else it was found', async () => {
    const profile = await profileWith({ events });
    renderWithProviders(<ActivitySection profile={profile} />);
    const row = screen.getByText(/framework agreement/).closest('.tl-item') as HTMLElement;
    expect(within(row).getByText('Major')).toBeInTheDocument();
    expect(within(row).getByText('Company newsroom')).toBeInTheDocument();
    expect(within(row).getByText(/Found in 2 places/)).toBeInTheDocument();
    fireEvent.click(within(row).getByRole('button', { name: /framework agreement/ }));
    expect(within(row).getByText('Why major')).toBeInTheDocument();
    expect(within(row).getByText('Contract or order (decisive wording)')).toBeInTheDocument();
    expect(within(row).getByText('Also stated at')).toBeInTheDocument();
    expect(within(row).getByRole('link', { name: /Open source/ })).toHaveAttribute('href', 'https://example.test/c1');
  });

  it('can be sorted by significance across years', async () => {
    const profile = await profileWith({ events });
    renderWithProviders(<ActivitySection profile={profile} />);
    fireEvent.click(screen.getByRole('button', { name: 'All events' }));
    fireEvent.click(screen.getByRole('button', { name: 'Most significant' }));
    const titles = Array.from(document.querySelectorAll('.tl-title')).map((n) => n.textContent ?? '');
    expect(titles[0]).toMatch(/framework agreement/);
    expect(titles[1]).toMatch(/autonomous vessels/);
    expect(titles[2]).toMatch(/Opens new office/);
    expect(document.querySelector('.tl-year')).toBeNull();
  });

  it('legacy saved data that says "minor" is shown as routine', async () => {
    const profile = await profileWith({ events: [ev('m1', 'Board re-elected at annual general meeting', '2026-05-27', { significance: 'minor' })] });
    renderWithProviders(<ActivitySection profile={profile} />);
    expect(screen.getByTestId('activity-counts')).toHaveTextContent('0 major · 0 relevant · 1 routine');
    expect(screen.getByText('Routine')).toBeInTheDocument();
  });

  it('lists the sources that could not be read and never presents an empty result as proof that nothing happened', async () => {
    const profile = await profileWith({
      status: 'partial',
      message: 'No company announcements could be read, so only register and procurement events are shown. Missing announcements are not evidence that none were made.',
      events: registrations.slice(0, 2),
      sourcesChecked: [
        { id: 'n0', kind: 'newsroom', name: 'Company newsroom', status: 'blocked', url: 'https://example.test/nyheter', note: 'robots.txt does not allow this page to be fetched, so it was not read' },
        { id: 'n1', kind: 'news_search', name: 'News coverage search', status: 'not_run', note: 'News coverage search is not configured (TAVILY_API_KEY missing)' },
        { id: 'reg', kind: 'registry', name: 'Enhetsregisteret', status: 'read', note: '' },
      ],
      excluded: { count: 1, items: [{ title: 'Undated press item', reason: 'no valid date' }] },
      consolidated: 3,
    });
    renderWithProviders(<ActivitySection profile={profile} />);
    expect(screen.getByRole('status')).toHaveTextContent('not evidence that none were made');
    const notes = screen.getByTestId('activity-notes');
    expect(within(notes).getByText(/Sources checked \(3\)/)).toHaveTextContent('1 could not be read');
    expect(notes).toHaveTextContent('robots.txt does not allow this page to be fetched');
    expect(notes).toHaveTextContent('TAVILY_API_KEY missing');
    expect(notes).toHaveTextContent('3 duplicate reports of the same announcement were merged');
    expect(notes).toHaveTextContent('1 candidate event not shown');
    expect(notes).toHaveTextContent('It is not evidence that nothing happened');
  });

  it('an empty timeline says that nothing could be found in what was read, not that nothing happened', async () => {
    const profile = await profileWith({ status: 'not_available', events: [] });
    renderWithProviders(<ActivitySection profile={profile} />);
    expect(screen.getByText(/does not mean that nothing happened/)).toBeInTheDocument();
  });
});
