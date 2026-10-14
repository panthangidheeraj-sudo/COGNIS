/**
 * Data Sheets cards open the right sheet, and no filter is ever selected for the user.
 *  - /sheets lists the sheets on load and opens one only after its card is clicked
 *  - the stretched card link is styled by a global stylesheet (it used to ship only with the Discover page)
 *  - filters (hiring, location, industry …) are all offered but none starts selected; what the interpreter reads out of free text
 *    is a suggestion; only selected filters restrict results; creating a sheet is never emptied by unselected filters
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes, useLocation } from 'react-router-dom';
import { renderWithProviders } from './utils';
import { mockApi } from '@/data/mock/mockApi';
import SheetsIndexPage from '@/pages/DataSheets/SheetsIndexPage';
import SheetPage from '@/pages/DataSheets/SheetPage';
import DiscoverPage from '@/pages/Discover/DiscoverPage';
import { FilterPanel } from '@/components/search/FilterPanel';
import { filtersToChips, paramsToFilters } from '@/utils/filters';
import type { DiscoverFilters, FilterCapability } from '@/types';

const SLOW = { timeout: 6000 };
// Vitest runs with `css: false` (stylesheets are stubbed empty even with ?raw), so the stylesheet checks read the files themselves.
async function stylesheet(rel: string): Promise<string> {
  const node = (m: string) => import(/* @vite-ignore */ `node:${m}`);
  const [{ readFileSync }, { fileURLToPath }] = await Promise.all([node('fs'), node('url')]);
  return readFileSync(fileURLToPath(new URL(rel, import.meta.url).href), 'utf8') as string;
}
const HIRING_TEXT = 'Build a sheet of Norwegian technology companies in Oslo with over 100 employees and current hiring.';

beforeEach(() => {
  // jsdom has no canvas: the globes simply have nothing to draw into
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
});
afterEach(() => vi.restoreAllMocks());

function Where() {
  const l = useLocation();
  return <output data-testid="where">{l.pathname + l.search}</output>;
}
const sheetRoutes = (
  <>
    <Routes>
      <Route path="/sheets" element={<SheetsIndexPage />} />
      <Route path="/sheets/:sheetId" element={<SheetPage />} />
    </Routes>
    <Where />
  </>
);
const where = () => screen.getByTestId('where').textContent;

describe('Data Sheet cards', () => {
  it('keeps the listing visible on load and opens nothing until a card is clicked', async () => {
    renderWithProviders(sheetRoutes, { route: '/sheets' });
    expect(screen.getByRole('heading', { name: 'Data Sheets' })).toBeInTheDocument();
    const links = await screen.findAllByRole('link', { name: /^Open /i }, SLOW);
    expect(links.length).toBeGreaterThanOrEqual(2);
    expect(where()).toBe('/sheets');
    await new Promise((r) => setTimeout(r, 400)); // nothing navigates by itself
    expect(where()).toBe('/sheets');
    expect(screen.queryByRole('toolbar', { name: 'Sheet tools' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Data Sheets' })).toBeInTheDocument();
  });

  it('links every card to its own sheet', async () => {
    renderWithProviders(sheetRoutes, { route: '/sheets' });
    const summaries = await mockApi.sheets.list();
    const links = await screen.findAllByRole('link', { name: /^Open /i }, SLOW);
    expect(links).toHaveLength(summaries.length);
    for (const s of summaries) expect(screen.getByRole('link', { name: `Open ${s.title}` })).toHaveAttribute('href', `/sheets/${s.id}`);
  });

  it('opens the sheet that was clicked, shows it, and goes back to the listing', async () => {
    renderWithProviders(sheetRoutes, { route: '/sheets' });
    const summaries = await mockApi.sheets.list();
    const [first, second] = summaries;
    fireEvent.click(await screen.findByRole('link', { name: `Open ${first.title}` }, SLOW));
    expect(await screen.findByRole('heading', { level: 1, name: first.title }, SLOW)).toBeInTheDocument();
    expect(where()).toBe(`/sheets/${first.id}`);
    expect(screen.getByRole('toolbar', { name: 'Sheet tools' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('link', { name: /Data Sheets/ }));
    fireEvent.click(await screen.findByRole('link', { name: `Open ${second.title}` }, SLOW));
    // a different sheet, never the previous one left on screen
    expect(await screen.findByRole('heading', { level: 1, name: second.title }, SLOW)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 1, name: first.title })).not.toBeInTheDocument();
    expect(where()).toBe(`/sheets/${second.id}`);
  });

  it('shows a way back, not a blank page, for a sheet that does not exist', async () => {
    renderWithProviders(sheetRoutes, { route: '/sheets/does-not-exist' });
    const alert = await screen.findByRole('alert', {}, SLOW);
    expect(alert).toHaveTextContent(/not found/i);
    expect(screen.getByRole('link', { name: /Data Sheets/ })).toHaveAttribute('href', '/sheets');
  });

  it('styles the stretched card link in the global stylesheet, so /sheets does not depend on Discover being loaded', async () => {
    const components = await stylesheet('../styles/components.css');
    const rule = components.match(/\.co-card-link\s*\{([^}]*)\}/);
    expect(rule?.[1]).toMatch(/position:\s*absolute/);
    expect(rule?.[1]).toMatch(/inset:\s*0/);
    // the card's content lets clicks through to that link
    expect(await stylesheet('../pages/Library/library.css')).toMatch(/\.lib-card > \*:not\(\.co-card-link\)\s*\{[^}]*pointer-events:\s*none/);
    // and Discover's own stylesheet no longer owns the only definition
    expect(await stylesheet('../pages/Discover/discover.css')).not.toMatch(/\.co-card-link\s*\{/);
  });
});

describe('filters start unselected', () => {
  const caps: FilterCapability[] = [
    { key: 'location', label: 'Location', type: 'select', options: [{ value: 'Oslo', label: 'Oslo' }] },
    { key: 'industry', label: 'Industry', type: 'select', options: [{ value: 'software', label: 'Software' }] },
    { key: 'hiring', label: 'Has verified current openings', type: 'boolean' },
    { key: 'employeesMin', label: 'Employees, more than', type: 'number' },
  ];

  it('offers hiring, location, industry and the rest with nothing selected', () => {
    const none: DiscoverFilters = {};
    renderWithProviders(<FilterPanel caps={caps} value={none} onChange={() => undefined} />);
    expect(screen.getByLabelText(/Has verified current openings/)).not.toBeChecked();
    expect((screen.getByLabelText('Location') as HTMLSelectElement).value).toBe('');
    expect((screen.getByLabelText('Industry') as HTMLSelectElement).value).toBe('');
    expect((screen.getByLabelText(/Employees, more than/) as HTMLInputElement).value).toBe('');
    expect(filtersToChips(none, caps)).toEqual([]); // no chips without a selection
    expect(paramsToFilters(new URLSearchParams(''))).toEqual({});
  });

  it('shows a chip only after a filter is selected', () => {
    expect(filtersToChips({ hiring: true }, caps).map((c) => c.key)).toEqual(['hiring']);
    expect(filtersToChips({ location: 'Oslo', hiring: false }, caps).map((c) => c.key)).toEqual(['location']);
  });

  it('Discover does not apply what it reads from the search text: suggestions, no chips, no count, all companies', async () => {
    const all = await mockApi.companies.discover({ filters: {}, sort: 'name', page: 1, pageSize: 24 });
    renderWithProviders(
      <Routes>
        <Route path="/discover" element={<DiscoverPage />} />
      </Routes>,
      { route: `/discover?q=${encodeURIComponent('Norwegian technology companies in Oslo with more than 100 employees and current hiring')}` },
    );
    const suggestions = await screen.findByRole('group', { name: 'Suggested filters' }, SLOW);
    for (const label of [/Add Hiring filter/, /Add Location filter/, /Add Industry filter/, /Add Employees filter/]) expect(within(suggestions).getByRole('button', { name: label })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Remove .* filter$/ })).not.toBeInTheDocument(); // no selected-filter chips
    expect(screen.getByRole('button', { name: /^Filters/ })).not.toHaveTextContent(/\d/); // no active count
    expect(screen.queryByText(/Clear filters/)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('status', { name: '' })).toHaveTextContent(String(all.total)), SLOW); // not zero, not narrowed
    expect(all.total).toBeGreaterThan(150);
  });

  it('applies a suggestion only when the user adds it, then shows it as a chip and narrows the results', async () => {
    renderWithProviders(
      <Routes>
        <Route path="/discover" element={<DiscoverPage />} />
      </Routes>,
      { route: `/discover?q=${encodeURIComponent('companies in Oslo')}` },
    );
    fireEvent.click(await screen.findByRole('button', { name: /Add Location filter/ }, SLOW));
    expect(await screen.findByRole('button', { name: 'Remove Location filter' }, SLOW)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: /^Filters/ })).toHaveTextContent('1'), SLOW);
    expect(screen.queryByRole('button', { name: /Add Location filter/ })).not.toBeInTheDocument(); // it is selected now
    fireEvent.click(screen.getByRole('button', { name: 'Remove Location filter' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Remove Location filter' })).not.toBeInTheDocument(), SLOW);
  });

  it('opens the filter drawer with every control present and nothing selected', async () => {
    renderWithProviders(
      <Routes>
        <Route path="/discover" element={<DiscoverPage />} />
      </Routes>,
      { route: '/discover' },
    );
    fireEvent.click(await screen.findByRole('button', { name: /^Filters/ }, SLOW));
    const drawer = await screen.findByRole('dialog', { name: 'Filters' }, SLOW);
    await waitFor(() => expect(within(drawer).getByLabelText(/Location/)).toBeInTheDocument(), SLOW);
    expect(within(drawer).getByLabelText(/Has verified current openings/)).not.toBeChecked();
    expect((within(drawer).getByLabelText(/Location/) as HTMLSelectElement).value).toBe('');
    expect((within(drawer).getByLabelText(/Industry/) as HTMLSelectElement).value).toBe('');
    expect(within(drawer).getByRole('button', { name: 'Clear all' })).toBeDisabled(); // nothing to clear
  });
});

describe('the backend contract: only selected filters restrict', () => {
  it('returns the interpretation as suggestions and applies none of it', async () => {
    const res = await mockApi.companies.discover({ text: HIRING_TEXT, interpret: true, filters: {}, sort: 'name', page: 1, pageSize: 24 });
    expect(res.interpretation?.filters.map((f) => f.key)).toEqual(expect.arrayContaining(['hiring', 'location', 'industry', 'employeesMin']));
    expect(res.appliedFilters).toEqual({});
    expect(res.total).toBeGreaterThan(150);
  });

  it('applies exactly the filters that were selected', async () => {
    const res = await mockApi.companies.discover({ text: HIRING_TEXT, interpret: true, filters: { location: 'Oslo' }, sort: 'name', page: 1, pageSize: 500 });
    expect(res.appliedFilters).toEqual({ location: 'Oslo' });
    expect(res.total).toBeGreaterThan(0);
    expect(res.items.every((c) => c.municipality === 'Oslo')).toBe(true);
  });

  it('treats hiring as data on each company, not as a filter that is on by default', async () => {
    const all = await mockApi.companies.discover({ filters: {}, sort: 'hiring', page: 1, pageSize: 500 });
    const hiring = await mockApi.companies.discover({ filters: { hiring: true }, sort: 'hiring', page: 1, pageSize: 500 });
    expect(all.items.some((c) => c.openPositions == null)).toBe(true); // the column exists for every company, known or not
    expect(hiring.total).toBeLessThan(all.total); // the filter only narrows when it is explicitly selected
  });

  it('never creates an empty sheet because of filters nobody selected', async () => {
    const interp = await mockApi.sheets.interpret(HIRING_TEXT);
    expect(interp.filters.some((f) => f.key === 'hiring')).toBe(true); // it is offered ...
    const sheet = await mockApi.sheets.create({ title: 'Tech in Oslo', criteria: [], text: HIRING_TEXT }); // ... but not applied
    expect(sheet.criteria ?? []).toEqual([]);
    expect(sheet.rowCount).toBeGreaterThan(150);
  });
});

describe('creating a Data Sheet', () => {
  it('interprets the description into suggestions, selects nothing, and creates a sheet with companies', async () => {
    renderWithProviders(sheetRoutes, { route: '/sheets?new=1' });
    const before = (await mockApi.sheets.list()).length;
    fireEvent.change(await screen.findByLabelText('Sheet description'), { target: { value: HIRING_TEXT } });
    fireEvent.click(screen.getByRole('button', { name: /Interpret/ }));

    const suggested = await screen.findByRole('group', { name: 'Suggested filters' }, SLOW);
    expect(screen.getByText(/No filters selected/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Remove (Location|Industry|Hiring|Employees)/ })).not.toBeInTheDocument();
    expect(within(suggested).getByRole('button', { name: /Add Location filter: Oslo/ })).toBeInTheDocument();
    // hiring is a column of every sheet, not a filter: it is not offered as one and it is not applied
    expect(within(suggested).queryByRole('button', { name: /Hiring/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Hiring is a column in every sheet/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Create sheet/ }));
    await waitFor(() => expect(where()).toMatch(/^\/sheets\/sheet-new-/), SLOW);
    const created = (await mockApi.sheets.list()).find((s) => where().endsWith(s.id))!;
    expect(created.rowCount).toBeGreaterThan(0);
    expect(created.criteria ?? []).toEqual([]);
    expect((await mockApi.sheets.list()).length).toBe(before + 1);
    // hiring status is a data column of the new sheet, and every company is in it
    const full = await mockApi.sheets.get(created.id);
    expect(full.columns.find((c) => c.id === 'hiring')?.kind).toBe('standard');
    expect(full.rows.length).toBe(created.rowCount);
    // and the new sheet opens with its rows
    expect(await screen.findByRole('toolbar', { name: 'Sheet tools' }, SLOW)).toBeInTheDocument();
  });

  it('narrows the sheet only by a filter the user adds', async () => {
    renderWithProviders(sheetRoutes, { route: '/sheets?new=1' });
    fireEvent.change(await screen.findByLabelText('Sheet description'), { target: { value: 'Logistics companies in Trondheim' } });
    fireEvent.click(screen.getByRole('button', { name: /Interpret/ }));
    fireEvent.click(await screen.findByRole('button', { name: /Add Location filter/ }, SLOW));
    expect(await screen.findByRole('button', { name: 'Remove Location' })).toBeInTheDocument();
    expect(screen.queryByText(/No filters selected/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Create sheet/ }));
    await waitFor(() => expect(where()).toMatch(/^\/sheets\/sheet-new-/), SLOW);
    const created = (await mockApi.sheets.list()).find((s) => where().endsWith(s.id))!;
    expect(created.criteria?.map((c) => c.key)).toEqual(['location']);
    expect(created.rowCount).toBeGreaterThan(0);
    expect(created.rowCount).toBeLessThan(150);
  });
});
