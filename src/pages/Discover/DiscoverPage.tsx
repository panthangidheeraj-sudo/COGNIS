import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { ArrowRight, ChartScatter, LayoutGrid, LoaderCircle, Search, SlidersHorizontal, Sparkle, Table, X } from 'lucide-react';
import { api } from '@/api';
import type { CompanySummary, DiscoverFilters, DiscoverSort, InterpretedFilter } from '@/types';
import { usePreferences } from '@/stores/preferences';
import { CompanyCard, CompareToggle, ResearchStateLabel } from '@/components/company/CompanyCard';
import { CoverageMeter } from '@/components/company/Coverage';
import { FilterPanel } from '@/components/search/FilterPanel';
import { Segmented } from '@/components/common/Tabs';
import { Skeleton } from '@/components/common/Skeleton';
import { EmptyState } from '@/components/common/EmptyState';
import { ErrorState } from '@/components/common/ErrorState';
import { Drawer } from '@/components/common/Overlay';
import { LandscapeChart } from '@/components/charts/LazyCharts';
import type { LandscapeMetric } from '@/components/charts/LandscapeChart';
import { useIsMobile } from '@/hooks/useMediaQuery';
import { useGlobe } from '@/stores/ui';
import { GlobeStage } from '@/components/globe/GlobeStage';
import { chipsToFilters, filtersToChips, filtersToParams, paramsToFilters } from '@/utils/filters';
import { formatInteger, formatMoneyCompact, formatOrgNumber } from '@/utils/format';
import './discover.css';

const EXAMPLES = [
  'Norwegian SaaS companies with over 100 employees',
  'Companies in Oslo currently hiring engineers',
  'Healthcare companies with revenue above 200M NOK',
  'Norwegian companies with new offices in the last year',
];
const PAGE_SIZE = 24;

export default function DiscoverPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get('q') ?? '';
  const kw = params.get('kw') ?? '';
  const sort = (params.get('sort') as DiscoverSort) ?? 'relevance';
  const page = Number(params.get('page') ?? 1);
  const explicit = useMemo(() => paramsToFilters(params), [params]);
  const edited = params.get('edited') === '1';
  const view = usePreferences((s) => s.discoverView);
  const setPref = usePreferences((s) => s.set);
  const [text, setText] = useState(q);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const mobile = useIsMobile();
  const nav = useNavigate();
  useEffect(() => setText(q), [q]);

  const status = useQuery({ queryKey: ['status'], queryFn: api.system.status });
  const caps = status.data?.capabilities.discoverFilters ?? [];

  const query = useQuery({
    queryKey: ['discover', q, kw, explicit, edited, sort, page, view],
    queryFn: ({ signal }) =>
      api.companies.discover(
        edited ? { text: kw || undefined, filters: explicit, sort, page, pageSize: view === 'landscape' ? 500 : PAGE_SIZE, interpret: false } : { text: q || undefined, filters: explicit, sort, page, pageSize: view === 'landscape' ? 500 : PAGE_SIZE, interpret: !!q },
        signal,
      ),
    placeholderData: keepPreviousData,
  });
  const res = query.data;

  const update = (mut: (p: URLSearchParams) => void) => {
    const p = new URLSearchParams(params);
    mut(p);
    p.delete('page');
    setParams(p);
  };
  const submit = (t: string) =>
    update((p) => {
      for (const k of [...p.keys()]) if (k.startsWith('f.')) p.delete(k);
      p.delete('edited');
      p.delete('kw');
      if (t.trim()) p.set('q', t.trim());
      else p.delete('q');
    });
  const applyFilters = (f: DiscoverFilters, keywords?: string) =>
    update((p) => {
      for (const k of [...p.keys()]) if (k.startsWith('f.')) p.delete(k);
      filtersToParams(f, p);
      p.set('edited', '1');
      if (keywords) p.set('kw', keywords);
      else p.delete('kw');
    });

  const activeFilters: DiscoverFilters = edited ? explicit : (res?.appliedFilters ?? explicit);
  const chips: InterpretedFilter[] = !edited && res?.interpretation ? res.interpretation.filters : filtersToChips(activeFilters, caps);
  const removeChip = (key: InterpretedFilter['key']) => {
    const next = chipsToFilters(chips.filter((c) => c.key !== key));
    applyFilters(next, edited ? kw : res?.interpretation?.keywords);
  };
  const hasQuery = !!q || chips.length > 0;
  const activeCount = Object.values(activeFilters).filter((v) => v !== undefined && v !== null && v !== '' && v !== false).length;
  const clearFilters = () => applyFilters({}, edited ? kw : undefined);

  // Globe: one node per result with a backend geo point; it turns toward the results.
  const setPoints = useGlobe((g) => g.setPoints);
  const setFocus = useGlobe((g) => g.setFocus);
  const geoItems = useMemo(() => (res?.items ?? []).filter((c) => c.geo), [res?.items]);
  const centroid = useMemo(
    () => (geoItems.length ? { id: 'disc-centroid', lat: geoItems.reduce((a, c) => a + c.geo!.lat, 0) / geoItems.length, lon: geoItems.reduce((a, c) => a + c.geo!.lon, 0) / geoItems.length } : null),
    [geoItems],
  );
  useEffect(() => {
    setPoints(geoItems.map((c) => ({ id: c.orgNumber, lat: c.geo!.lat, lon: c.geo!.lon })));
    setFocus(centroid);
  }, [geoItems, centroid, setPoints, setFocus]);
  useEffect(
    () => () => {
      setPoints([]);
      setFocus(null);
    },
    [setPoints, setFocus],
  );
  const hoverCompany = (c: CompanySummary | null) => setFocus(c?.geo ? { id: c.orgNumber, lat: c.geo.lat, lon: c.geo.lon, label: `${c.legalName} · ${c.municipality}` } : centroid);

  return (
    <div className="page page--wide discover">
      <div className="disc-top">
      {!mobile && (
        <div className="disc-globe" aria-hidden>
          <GlobeStage className="disc-globe-stage" />
          {res && <span className="disc-globe-cap t-xs t-muted">{geoItems.length ? `${geoItems.length} of ${res.items.length} results on this page have a verified location` : 'No mapped locations for these results'}</span>}
        </div>
      )}
      <div className="page-head">
        <div>
          <h1>Discover</h1>
          <p>Search by company, industry, location or organization number — or describe the companies you need.</p>
        </div>
      </div>

      <form
        className="disc-search surface"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          submit(text);
        }}
      >
        {query.isFetching ? <LoaderCircle className="spin" aria-hidden /> : <Search aria-hidden />}
        <label htmlFor="disc-q" className="sr-only">
          Search companies
        </label>
        <input id="disc-q" value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Norwegian technology companies in Oslo with more than 100 employees and current hiring" autoComplete="off" />
        {text && (
          <button type="button" className="btn btn--ghost btn--icon btn--sm" onClick={() => (setText(''), submit(''))} aria-label="Clear search">
            <X aria-hidden />
          </button>
        )}
        <button className="btn btn--primary" type="submit">
          Search
        </button>
      </form>

      {!hasQuery && (
        <div className="disc-examples">
          <span className="t-xs t-muted">Try a natural-language query</span>
          <div className="row-wrap">
            {EXAMPLES.map((e) => (
              <button key={e} className="chip" onClick={() => (setText(e), submit(e))}>
                <Sparkle aria-hidden /> {e}
              </button>
            ))}
          </div>
        </div>
      )}

      {hasQuery && (
        <section className="interp" aria-label="Interpreted filters">
          <div className="row-wrap" style={{ gap: 8 }}>
            <span className="interp-label">
              <Sparkle aria-hidden /> {edited ? 'Filters' : res?.interpretation?.filters.length ? 'Interpreted as' : 'Keyword search'}
            </span>
            {chips.map((c) => (
              <span key={c.key} className="chip is-active">
                <span className="t-muted">{c.label}:</span> {c.display}
                <button className="chip-x" onClick={() => removeChip(c.key)} aria-label={`Remove ${c.label} filter`}>
                  <X width={12} height={12} aria-hidden />
                </button>
              </span>
            ))}
            {(edited ? kw : res?.interpretation?.keywords ?? (!res?.interpretation?.filters.length ? q : '')) && (
              <span className="chip">
                <span className="t-muted">Keywords:</span> {edited ? kw : (res?.interpretation?.keywords ?? q)}
              </span>
            )}
            <button className="btn btn--sm" onClick={() => setFiltersOpen(true)}>
              <SlidersHorizontal aria-hidden /> Edit
            </button>
          </div>
          {!edited && res?.interpretation?.notes?.map((n) => (
            <p key={n} className="t-xs t-muted">
              {n}
            </p>
          ))}
          {edited && q && <p className="t-xs t-muted">Edited from: “{q}”</p>}
        </section>
      )}
      </div>

      {/* Results take the full width: filters are a secondary control (drawer), not a permanent rail. */}
      <div className="disc-body">
        <section className="disc-results" aria-label="Results" aria-busy={query.isFetching}>
          <div className="disc-bar">
            <span className="t-sm" role="status">
              {res ? (
                <>
                  <strong className="t-num">{formatInteger(res.total)}</strong> {res.total === 1 ? 'company' : 'companies'}
                  {!hasQuery && <span className="t-muted"> · all companies</span>}
                </>
              ) : (
                'Searching…'
              )}
            </span>
            <button className={`btn btn--sm disc-filter-btn${activeCount ? ' is-active' : ''}`} onClick={() => setFiltersOpen(true)} aria-haspopup="dialog" aria-expanded={filtersOpen}>
              <SlidersHorizontal aria-hidden /> Filters
              {activeCount > 0 && (
                <span className="disc-filter-count" aria-label={`${activeCount} active`}>
                  {activeCount}
                </span>
              )}
            </button>
            {activeCount > 0 && (
              <button className="link-btn t-xs" onClick={clearFilters}>
                Clear filters
              </button>
            )}
            <span className="spacer" />
            <label className="row t-xs t-muted" style={{ gap: 6 }}>
              <span className="nowrap">Sort</span>
              <select className="select" style={{ height: 32, width: 150 }} value={sort} onChange={(e) => update((p) => p.set('sort', e.target.value))}>
                <option value="relevance">Relevance</option>
                <option value="revenue">Revenue</option>
                <option value="employees">Employees</option>
                <option value="hiring">Open positions</option>
                <option value="researched">Recently researched</option>
                <option value="name">Name</option>
              </select>
            </label>
            <Segmented
              label="View"
              value={view}
              onChange={(v) => setPref({ discoverView: v })}
              options={[
                { value: 'cards', label: <span className="sr-only">Cards</span>, icon: <LayoutGrid aria-hidden />, title: 'Cards' },
                { value: 'table', label: <span className="sr-only">Table</span>, icon: <Table aria-hidden />, title: 'Table' },
                { value: 'landscape', label: <span className="sr-only">Landscape</span>, icon: <ChartScatter aria-hidden />, title: 'Landscape' },
              ]}
            />
          </div>

          {query.isError ? (
            <ErrorState error={query.error} onRetry={() => query.refetch()} />
          ) : !res ? (
            <div className="co-grid">
              {Array.from({ length: 9 }, (_, i) => (
                <Skeleton key={i} h={200} r={12} />
              ))}
            </div>
          ) : res.items.length === 0 ? (
            <EmptyState title="No companies match these criteria." text="Try removing a filter. Filters like hiring only include companies with verified evidence, so unresearched companies may be excluded." />
          ) : view === 'landscape' ? (
            <Landscape companies={res.items} onSelect={(org) => nav(`/company/${org}`)} />
          ) : view === 'table' && !mobile ? (
            <ResultsTable items={res.items} />
          ) : (
            <div className="co-grid" onMouseLeave={() => hoverCompany(null)}>
              {res.items.map((c) => (
                <div key={c.orgNumber} className="disc-card" onMouseEnter={() => hoverCompany(c)} onFocusCapture={() => hoverCompany(c)}>
                  <CompanyCard c={c} />
                </div>
              ))}
            </div>
          )}

          {res && view !== 'landscape' && res.total > PAGE_SIZE && (
            <nav className="pager" aria-label="Pagination">
              <button className="btn btn--sm" disabled={page <= 1} onClick={() => setParams((p) => (p.set('page', String(page - 1)), p))}>
                Previous
              </button>
              <span className="t-sm t-muted t-num">
                Page {page} of {Math.ceil(res.total / PAGE_SIZE)}
              </span>
              <button className="btn btn--sm" disabled={page >= Math.ceil(res.total / PAGE_SIZE)} onClick={() => setParams((p) => (p.set('page', String(page + 1)), p))}>
                Next
              </button>
            </nav>
          )}
        </section>
      </div>

      <Drawer
        open={filtersOpen}
        onClose={() => setFiltersOpen(false)}
        label="Filters"
        className="disc-filter-drawer"
        subtitle={<span className="eyebrow">Refine results</span>}
        title="Filters"
        footer={
          <div className="row" style={{ gap: 8, width: '100%' }}>
            <button className="btn btn--ghost" onClick={clearFilters} disabled={activeCount === 0}>
              Clear all
            </button>
            <span className="spacer" />
            <button className="btn btn--primary" onClick={() => setFiltersOpen(false)}>
              {res ? `Show ${formatInteger(res.total)} ${res.total === 1 ? 'company' : 'companies'}` : 'Show results'}
            </button>
          </div>
        }
      >
        {caps.length ? <FilterPanel caps={caps} value={activeFilters} onChange={(f) => applyFilters(f, edited ? kw : res?.interpretation?.keywords)} /> : <Skeleton h={300} />}
        <p className="t-xs t-muted" style={{ marginTop: 16 }}>
          Results update as you change a filter. Only filters the backend can apply are shown.
        </p>
      </Drawer>
    </div>
  );
}

const NotAvailable = () => <span className="t-xs t-muted">Not available</span>;

function ResultsTable({ items }: { items: CompanySummary[] }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="sr-only">Companies</caption>
        <thead>
          <tr>
            <th className="sticky-col" scope="col">
              Company
            </th>
            <th scope="col">Location</th>
            <th scope="col">Industry</th>
            <th scope="col" className="num">
              Revenue
            </th>
            <th scope="col" className="num">
              Employees
            </th>
            <th scope="col" className="num">
              Openings
            </th>
            <th scope="col">Coverage</th>
            <th scope="col">Research</th>
            <th scope="col">
              <span className="sr-only">Compare</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((c) => (
            <tr key={c.orgNumber}>
              <td className="sticky-col">
                <Link to={`/company/${c.orgNumber}`} className="stack" style={{ gap: 0 }}>
                  <span style={{ fontWeight: 500 }}>{c.legalName}</span>
                  <span className="t-xs t-muted t-mono">{formatOrgNumber(c.orgNumber)}</span>
                </Link>
              </td>
              <td>{c.municipality}</td>
              <td className="truncate" style={{ maxWidth: 220 }}>
                {c.industry?.description}
              </td>
              <td className="num">{c.revenue ? formatMoneyCompact(c.revenue.value, c.revenue.currency) : <NotAvailable />}</td>
              <td className="num">{c.employees != null ? formatInteger(c.employees) : <NotAvailable />}</td>
              <td className="num">{c.openPositions ?? <NotAvailable />}</td>
              <td>
                <CoverageMeter coverage={c.coverage} size="sm" interactive={false} />
              </td>
              <td>
                <ResearchStateLabel c={c} />
              </td>
              <td>
                <CompareToggle c={c} small />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Landscape({ companies, onSelect }: { companies: CompanySummary[]; onSelect: (org: string) => void }) {
  const [x, setX] = useState<LandscapeMetric>('employees');
  const [y, setY] = useState<LandscapeMetric>('revenue');
  const opts: { value: LandscapeMetric; label: string }[] = [
    { value: 'revenue', label: 'Revenue' },
    { value: 'employees', label: 'Employees' },
    { value: 'openPositions', label: 'Open positions' },
  ];
  return (
    <div className="card">
      <div className="row-wrap" style={{ gap: 12, marginBottom: 12 }}>
        <h2 className="t-h3">Company landscape</h2>
        <span className="spacer" />
        <label className="row t-xs t-muted" style={{ gap: 6 }}>
          X
          <select className="select" style={{ height: 32, width: 150 }} value={x} onChange={(e) => setX(e.target.value as LandscapeMetric)}>
            {opts.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="row t-xs t-muted" style={{ gap: 6 }}>
          Y
          <select className="select" style={{ height: 32, width: 150 }} value={y} onChange={(e) => setY(e.target.value as LandscapeMetric)}>
            {opts.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <LandscapeChart companies={companies} x={x} y={y} onSelect={onSelect} />
      <p className="t-xs t-muted" style={{ marginTop: 6 }}>
        Positions show reported values only — no scores or rankings. <ArrowRight width={12} height={12} style={{ display: 'inline' }} aria-hidden /> Use Compare for side-by-side facts.
      </p>
    </div>
  );
}
