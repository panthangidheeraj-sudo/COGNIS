export const COMPANY_TABS = ['overview', 'financials', 'people', 'locations', 'website', 'hiring', 'activity', 'changes', 'sources'] as const;
export type CompanyTab = (typeof COMPANY_TABS)[number];
export const TAB_LABEL: Record<CompanyTab, string> = {
  overview: 'Overview',
  financials: 'Financials',
  people: 'People',
  locations: 'Locations',
  website: 'Website & Online',
  hiring: 'Hiring',
  activity: 'Activity',
  changes: 'Changes',
  sources: 'Sources',
};
