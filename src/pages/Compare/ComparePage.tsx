import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Download, Plus, Search, X } from 'lucide-react';
import { api } from '@/api';
import type { Comparison, CompanySummary } from '@/types';
import { MAX_COMPARE, useCompare } from '@/stores/ui';
import { usePreferences } from '@/stores/preferences';
import { useDebounce } from '@/hooks/useDebounce';
import { BrandMark } from '@/components/common/BrandMark';
import { EmptyState } from '@/components/common/EmptyState';
import { ErrorState } from '@/components/common/ErrorState';
import { Skeleton } from '@/components/common/Skeleton';
import { ExportModal } from '@/components/common/ExportModal';
import { useCommand } from '@/hooks/useCommand';
import { FactValue } from '@/components/evidence/FactValue';
import { CoverageMeter } from '@/components/company/Coverage';
import { CompareChart } from '@/components/charts/LazyCharts';
import { COMPARE_COLORS, COMPARE_COLORS_LIGHT } from '@/components/charts/CompareChart';
import { formatOrgNumber, isCurrencyUnit } from '@/utils/format';
import { COMPANY_STATUS_TONE, toneClass } from '@/utils/status';
import './compare.css';

export default function ComparePage() {
  const [params, setParams] = useSearchParams();
  const orgs = useMemo(() => (params.get('orgs') ?? '').split(',').filter(Boolean).slice(0, MAX_COMPARE), [params]);
  const setAll = useCompare((s) => s.setAll);
  const selected = useCompare((s) => s.selected);
  const [exportOpen, setExportOpen] = useState(false);
  useCommand('export', () => setExportOpen(true));

  // If arriving without params, use the compare tray selection.
  useEffect(() => {
    if (!orgs.length && selected.length) setParams({ orgs: selected.map((s) => s.orgNumber).join(',') }, { replace: true });
  }, [orgs.length, selected, setParams]);

  const cmp = useQuery({ queryKey: ['compare', orgs], queryFn: () => api.compare.get(orgs), enabled: orgs.length >= 2 });
  useEffect(() => {
    if (cmp.data) setAll(cmp.data.companies.map((c) => ({ orgNumber: c.orgNumber, legalName: c.legalName })));
  }, [cmp.data, setAll]);

  const setOrgs = (list: string[]) => setParams(list.length ? { orgs: list.join(',') } : {});
  const names = cmp.data?.companies ?? [];

  return (
    <div className="page page--wide compare">
      <div className="page-head">
        <div>
          <h1>Compare</h1>
          <p>Facts side by side, each with its own evidence. No scores or rankings.</p>
        </div>
        {cmp.data && (
          <div className="page-actions">
            <button className="btn" onClick={() => setExportOpen(true)}>
              <Download aria-hidden /> Export comparison
            </button>
          </div>
        )}
      </div>

      <Picker orgs={orgs} companies={names} onChange={setOrgs} />

      {orgs.length < 2 ? (
        <Suggestions orgs={orgs} onAdd={(o) => setOrgs([...orgs, o])} />
      ) : cmp.isLoading ? (
        <Skeleton h={480} r={12} />
      ) : cmp.isError ? (
        <ErrorState error={cmp.error} onRetry={() => cmp.refetch()} />
      ) : (
        <CompareBody cmp={cmp.data!} />
      )}

      {cmp.data && <ExportModal open={exportOpen} onClose={() => setExportOpen(false)} target={{ type: 'comparison', id: orgs.join(',') }} title={`${names.length} companies`} />}
    </div>
  );
}

function Picker({ orgs, companies, onChange }: { orgs: string[]; companies: CompanySummary[]; onChange: (o: string[]) => void }) {
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const dq = useDebounce(q.trim(), 180);
  const ref = useRef<HTMLDivElement>(null);
  const res = useQuery({ queryKey: ['cmp-search', dq], queryFn: ({ signal }) => api.search.global(dq, signal), enabled: dq.length >= 2 });
  useEffect(() => {
    const on = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    window.addEventListener('mousedown', on);
    return () => window.removeEventListener('mousedown', on);
  }, []);
  const full = orgs.length >= MAX_COMPARE;
  return (
    <div className="cmp-picker">
      {orgs.map((o) => {
        const c = companies.find((x) => x.orgNumber === o);
        return (
          <span key={o} className="cmp-chip">
            {c && <BrandMark name={c.legalName} org={o} size={24} />}
            <span className="truncate">{c?.legalName ?? formatOrgNumber(o)}</span>
            <button className="chip-x" onClick={() => onChange(orgs.filter((x) => x !== o))} aria-label={`Remove ${c?.legalName ?? o}`}>
              <X width={12} height={12} aria-hidden />
            </button>
          </span>
        );
      })}
      {!full && (
        <div className="cmp-add" ref={ref}>
          <div className="input-wrap">
            <Plus aria-hidden />
            <input className="input" value={q} onChange={(e) => (setQ(e.target.value), setOpen(true))} onFocus={() => setOpen(true)} placeholder={`Add company (${orgs.length}/${MAX_COMPARE})`} aria-label="Add company to comparison" />
          </div>
          {open && res.data && dq.length >= 2 && (
            <ul className="cmp-sugg popover" style={{ position: 'absolute' }}>
              {res.data.companies.filter((c) => !orgs.includes(c.orgNumber)).length === 0 && <li className="t-xs t-muted" style={{ padding: 10 }}>No matching companies</li>}
              {res.data.companies
                .filter((c) => !orgs.includes(c.orgNumber))
                .map((c) => (
                  <li key={c.orgNumber}>
                    <button
                      className="menu-item"
                      style={{ height: 'auto', padding: 8 }}
                      onClick={() => {
                        onChange([...orgs, c.orgNumber]);
                        setQ('');
                        setOpen(false);
                      }}
                    >
                      <Search aria-hidden />
                      <span className="stack" style={{ gap: 0 }}>
                        <span>{c.legalName}</span>
                        <span className="t-xs t-muted">
                          {c.municipality} · {formatOrgNumber(c.orgNumber)}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function Suggestions({ orgs, onAdd }: { orgs: string[]; onAdd: (o: string) => void }) {
  const recent = useQuery({ queryKey: ['companies', 'recent'], queryFn: api.companies.recent });
  return (
    <div className="stack" style={{ gap: 16 }}>
      <EmptyState title="Choose at least two companies to compare." text="Compare 2–5 companies across financials, people, locations, hiring, website and activity. Add companies above, or from Discover and the Library." />
      {recent.data && (
        <div className="row-wrap">
          <span className="t-xs t-muted">Recently researched</span>
          {recent.data
            .filter((c) => !orgs.includes(c.orgNumber))
            .map((c) => (
              <button key={c.orgNumber} className="chip" onClick={() => onAdd(c.orgNumber)}>
                <Plus aria-hidden /> {c.legalName}
              </button>
            ))}
        </div>
      )}
    </div>
  );
}

/**
 * True side-by-side comparison: each company is a peer column (header card → facts), and every metric sits
 * on one shared row so "Revenue → A vs B vs C" reads across without hunting. The narrow, quiet label column
 * stays pinned on the left while the company columns scroll horizontally on narrow screens — companies are
 * never stacked vertically. Values only: no winner badges, rankings or "better/worse" colour.
 */
function CompareBody({ cmp }: { cmp: Comparison }) {
  const theme = usePreferences((s) => s.theme);
  const light = theme === 'light' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: light)').matches);
  const colors = light ? COMPARE_COLORS_LIGHT : COMPARE_COLORS;
  const cs = cmp.companies;
  const names = cs.map((c) => c.legalName);
  const jobs = cmp.sections.find((s) => s.id === 'hiring')?.rows[0].values ?? [];
  const maxJobs = Math.max(1, ...jobs.map((f) => (typeof f?.value === 'number' ? f.value : 0)));
  const sourceIndex = cmp.sourceIndex;
  const groups: { id: string; label: string; rows: Comparison['summary'] }[] = [
    ...(cmp.summary?.length ? [{ id: 'glance', label: 'At a glance', rows: cmp.summary }] : []),
    ...cmp.sections,
  ];
  const hasCharts = cmp.series.some((x) => x.points.length >= 2);
  // The pinned label column only needs a solid backing once the company columns scroll underneath it.
  const boardRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = boardRef.current;
    if (!el) return;
    const on = () => el.toggleAttribute('data-scrolled', el.scrollLeft > 2);
    on();
    el.addEventListener('scroll', on, { passive: true });
    return () => el.removeEventListener('scroll', on);
  }, []);

  const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });

  return (
    <div className="stack" style={{ gap: 20 }}>
      <nav className="cmp-anchors" aria-label="Comparison sections">
        {groups.map((g) => (
          <button key={g.id} className="chip chip--sm" onClick={() => jump(`cmp-sec-${g.id}`)}>
            {g.label}
          </button>
        ))}
        {hasCharts && (
          <button className="chip chip--sm" onClick={() => jump('cmp-charts')}>
            Charts
          </button>
        )}
      </nav>

      <div ref={boardRef} className="cmp-board" style={{ ['--n' as string]: cs.length }} role="region" aria-label="Side-by-side comparison" tabIndex={0}>
        <table className="cmp-grid">
          <caption className="sr-only">Side-by-side comparison of {names.join(', ')}</caption>
          <colgroup>
            <col className="cmp-col-label" />
            {cs.map((c) => (
              <col key={c.orgNumber} className="cmp-col-co" />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th scope="col" className="cmp-label cmp-corner">
                <span className="t-micro">
                  {cs.length} companies
                </span>
                <span className="t-xs t-muted">Values as filed, each with its own evidence</span>
              </th>
              {cs.map((c, i) => (
                <th key={c.orgNumber} scope="col" className="cmp-head" style={{ ['--co' as string]: colors[i] }}>
                  <CompanyHead c={c} />
                </th>
              ))}
            </tr>
          </thead>
          {groups.map((g, gi) => (
            <tbody key={g.id} id={`cmp-sec-${g.id}`} className={`cmp-group cmp-group--${g.id} cmp-anchor-target`}>
              <tr className="cmp-sec">
                <th scope="rowgroup" className="cmp-label">
                  {g.label}
                </th>
                {cs.map((c, i) => (
                  <td key={c.orgNumber} className="cmp-sec-co" aria-hidden>
                    {gi > 0 && (
                      <>
                        <i style={{ background: colors[i] }} />
                        <span className="truncate">{c.legalName}</span>
                      </>
                    )}
                  </td>
                ))}
              </tr>
              {g.rows.map((r) => (
                <tr key={r.key} className="cmp-row">
                  <th scope="row" className="cmp-label">
                    {r.label}
                    {r.unit && !isCurrencyUnit(r.unit) && <span className="cmp-unit"> {r.unit}</span>}
                  </th>
                  {r.values.map((v, i) => (
                    <td key={cs[i].orgNumber} className="cmp-cell">
                      {v ? <FactValue fact={v} sourceIndex={sourceIndex} context={cs[i].legalName} /> : <span className="fact--missing">Not available</span>}
                      {v?.reportingPeriod && <span className="freshness">{v.reportingPeriod}</span>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>

      <div className="cmp-charts cmp-anchor-target" id="cmp-charts">
        {cmp.series.map((s) =>
          s.points.length >= 2 ? (
            <section key={s.key} className="card" aria-labelledby={`cs-${s.key}`}>
              <div className="card-head" style={{ flexWrap: 'wrap' }}>
                <h2 id={`cs-${s.key}`}>{s.label}</h2>
                <span className="t-xs t-muted">{isCurrencyUnit(s.unit) ? `${s.unit} · same scale for all companies` : s.mixedCurrency ? 'Companies file in different currencies' : 'Same scale for all companies'}</span>
              </div>
              {s.mixedCurrency ? (
                <p className="t-sm t-muted" role="note" data-testid="mixed-currency-chart-note">
                  These companies state their accounts in different currencies ({[...new Set((s.currencies ?? []).flat())].join(', ') || 'not all stated'}). COGNIS never converts currencies, so this series is not drawn on one axis —
                  compare the amounts in the table above, each in its own currency.
                </p>
              ) : (
                <CompareChart series={s} names={names} colors={colors} />
              )}
              <div className="chart-legend" style={{ marginTop: 8 }}>
                {names.map((n, i) => (
                  <span key={n}>
                    <i style={{ background: colors[i] }} />
                    {n}
                  </span>
                ))}
              </div>
            </section>
          ) : null,
        )}
        <section className="card" aria-labelledby="cs-jobs">
          <div className="card-head">
            <h2 id="cs-jobs">Open positions</h2>
            <span className="t-xs t-muted">Verified current openings</span>
          </div>
          <ul className="cmp-bars">
            {cs.map((c, i) => {
              const v = jobs[i];
              const n = typeof v?.value === 'number' ? v.value : null;
              return (
                <li key={c.orgNumber}>
                  <span className="truncate t-sm">{c.legalName}</span>
                  <span className="cmp-bar">{n != null && <i style={{ width: `${(n / maxJobs) * 100}%`, background: colors[i] }} />}</span>
                  <span className="t-num t-sm">{n ?? <span className="t-muted t-xs">No verified data</span>}</span>
                </li>
              );
            })}
          </ul>
        </section>
      </div>
    </div>
  );
}

/** The column header that establishes each company before any fact is compared. */
function CompanyHead({ c }: { c: CompanySummary }) {
  return (
    <div className="cmp-head-in">
      <div className="row" style={{ gap: 12, alignItems: 'flex-start' }}>
        <BrandMark name={c.legalName} org={c.orgNumber} logoUrl={c.logoUrl} size={42} />
        <div className="stack" style={{ gap: 3, minWidth: 0, flex: 1 }}>
          <Link to={`/company/${c.orgNumber}`} className="cmp-head-name">
            {c.legalName}
          </Link>
          <span className="t-xs t-muted truncate">{c.municipality ? `${c.municipality}, Norway` : 'Norway'}</span>
          <span className="t-xs t-mono t-muted">Org. {formatOrgNumber(c.orgNumber)}</span>
        </div>
      </div>
      <div className="cmp-head-foot">
        <CoverageMeter coverage={c.coverage} size="sm" />
        <span className={`pill pill--sm ${toneClass(COMPANY_STATUS_TONE[c.status])}`}>{c.statusLabel ?? c.status}</span>
      </div>
    </div>
  );
}
