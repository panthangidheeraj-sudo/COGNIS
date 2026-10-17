/** The launch tour. Every slide describes a feature that exists in this build (routes in app/router.tsx, Ask AI panel on the company page). */
export interface TourSlide {
  id: string;
  file: string;
  title: string;
  subtitle: string;
  alt: string;
}

export const TOUR_SLIDES: TourSlide[] = [
  { id: 'discover', file: 'discover.svg', title: 'Discover', subtitle: 'Search by name or number, then confirm the legal entity.', alt: 'Search results listing Norwegian companies, with one selected to confirm its identity' },
  { id: 'research', file: 'research.svg', title: 'Research', subtitle: 'Open a profile: registered facts, people and financial trend.', alt: 'A company profile with key figures and a revenue chart' },
  { id: 'evidence', file: 'evidence.svg', title: 'Evidence', subtitle: 'Each fact shows its source, dates and verification.', alt: 'Company facts listed beside the original source extract with dates' },
  { id: 'ask-ai', file: 'ask-ai.svg', title: 'Ask AI', subtitle: 'Ask a follow-up and get answers with numbered sources.', alt: 'A chat panel answering a question about revenue with numbered source citations' },
  { id: 'workspace', file: 'workspace.svg', title: 'Your workspace', subtitle: 'Return to saved research, your watchlist and comparisons.', alt: 'Library, watchlist and compare cards above a recent activity list' },
];
