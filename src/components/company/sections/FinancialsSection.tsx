import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChartColumn, ChartLine, ExternalLink, Eye, Lightbulb, Table2, TrendingDown, TrendingUp } from 'lucide-react';
import type { CompanyProfile, Evidence, ExplainSubject, FinancialMetricKey, FinancialSeries, Source } from '@/types';
import { FinancialChart } from '@/components/charts/LazyCharts';
import { FactValue } from '@/components/evidence/FactValue';
import { useOpenEvidence } from '@/components/evidence/useEvidence';
import { Segmented } from '@/components/common/Tabs';
import { EmptyState } from '@/components/common/EmptyState';
import { SectionState } from '../SectionState';
import { useCompact } from '@/stores/preferences';
import { factChange, formatDate, formatInteger, formatMoneyCompact, formatPercent, isCurrencyUnit, isMoneyUnit, MIXED_CURRENCIES } from '@/utils/format';

const GROUPS: { id: string; label: string; keys: FinancialMetricKey[] }[] = [
  { id: 'revenue', label: 'Revenue', keys: ['revenue'] },
  { id: 'results', label: 'Results', keys: ['operating_result', 'annual_result'] },
  { id: 'balance', label: 'Assets & equity', keys: ['total_assets', 'equity'] },
  { id: 'fte', label: 'Average FTEs', keys: ['employees'] },
];
const CASH_KEYS: FinancialMetricKey[] = ['cash', 'debt', 'equity'];

type View = 'trend' | 'annual' | 'ratios' | 'cash' | 'sources';
const VIEW_LABEL: Record<View, string> = { trend: 'Trend', annual: 'Annual values', ratios: 'Ratios', cash: 'Cash / debt', sources: 'Sources' };

/** Each amount carries the currency its own filing states; a change is only computed between amounts in the same currency (no conversion is ever applied). */
const fmtShort = (s: Pick<FinancialSeries, 'unit'>, v: number | null, currency?: string) =>
  v == null ? 'n/a' : isMoneyUnit(s.unit) || s.unit === 'currency not stated' ? formatMoneyCompact(v, currency ?? (isCurrencyUnit(s.unit) ? s.unit : undefined)) : s.unit === '%' ? formatPercent(v) : formatInteger(v);
/** A series that spans a change of reporting currency is charted in its latest currency only; earlier filings stay in the annual-values table, unconverted. */
const plotted = (s: FinancialSeries): FinancialSeries => {
  if (s.unit !== MIXED_CURRENCIES) return s;
  const cur = s.points.at(-1)?.fact.currency;
  return cur ? { ...s, unit: cur, points: s.points.filter((p) => p.fact.currency === cur) } : s;
};

/**
 * Financials. One view at a time — Trend, Annual values, Ratios, Cash / debt,
 * Sources — and only the views the filed data actually supports. Every chart
 * has a "View table" beneath it with exact values, periods, changes and the
 * source for each point.
 */
export function FinancialsSection({ profile, compactCharts, onExplain }: { profile: CompanyProfile; compactCharts?: boolean; onExplain?: (subject: ExplainSubject, title: string) => void }) {
  const fin = profile.financials;
  const compact = useCompact() || !!compactCharts;
  const ctx = profile.company.legalName;
  const has = (k: FinancialMetricKey, min = 1) => (fin.series.find((s) => s.key === k)?.points.length ?? 0) >= min;
  const groups = GROUPS.filter((g) => g.keys.some((k) => has(k)));
  const periods = useMemo(() => [...new Set(fin.series.flatMap((s) => s.points.map((p) => p.period)))].sort(), [fin.series]);
  const finSources = useMemo(() => financialSources(profile), [profile]);

  const views: View[] = [];
  if (groups.some((g) => g.keys.some((k) => has(k, 2)))) views.push('trend');
  if (fin.series.length) views.push('annual');
  if (fin.ratios.length || fin.ratioHistory?.some((r) => r.points.length)) views.push('ratios');
  if (CASH_KEYS.some((k) => has(k))) views.push('cash');
  if (finSources.length) views.push('sources');

  const [view, setView] = useState<View>(views[0] ?? 'annual');
  const [group, setGroup] = useState(groups[0]?.id ?? 'revenue');
  const [kind, setKind] = useState<'line' | 'bar'>('line');

  if (fin.status !== 'available' || !fin.series.length)
    return (
      <div className="stack" style={{ gap: 16 }}>
        <SectionState meta={fin} sourceIndex={profile.sourceIndex} />
        <EmptyState
          title="Historical revenue data unavailable."
          text="Charts are only drawn when filed figures exist for at least two reporting periods."
          action={
            <Link className="btn" to={`/research?org=${profile.company.orgNumber}&prompt=${encodeURIComponent('Latest financials')}&autostart=1`}>
              Research financial history
            </Link>
          }
        />
      </div>
    );

  const latest = (k: FinancialMetricKey) => fin.series.find((s) => s.key === k)?.points.at(-1);
  const headline: FinancialMetricKey[] = ['revenue', 'operating_result', 'annual_result', 'total_assets', 'equity', 'debt', 'cash'];
  const selected = (groups.find((g) => g.id === group) ?? groups[0])?.keys.map((k) => fin.series.find((s) => s.key === k)).filter((s): s is FinancialSeries => !!s && s.points.length > 0).map(plotted) ?? [];
  const cashSeries = CASH_KEYS.map((k) => fin.series.find((s) => s.key === k)).filter((s): s is FinancialSeries => !!s && s.points.length > 0).map(plotted);
  const mixed = fin.currency === MIXED_CURRENCIES;
  const chartH = compact ? 200 : 280;
  const active = views.includes(view) ? view : views[0];

  // Material movements the user can ask the backend to explain.
  const movements = (['revenue', 'employees'] as FinancialMetricKey[])
    .map((k) => {
      const s = fin.series.find((x) => x.key === k);
      const [a, b] = s?.points.slice(-2) ?? [];
      if (!s || !a || !b) return null;
      const pct = factChange(a.fact, b.fact);
      return pct == null ? null : { s, a, b, pct };
    })
    .filter((m): m is NonNullable<typeof m> => !!m);

  return (
    <div className="fin">
      <div className="fin-headline" data-search-block="financial-headline">
        {headline.map((k) => {
          const pt = latest(k);
          if (!pt) return null;
          return (
            <div key={k} className="fin-stat">
              <span className="t-xs t-muted">{fin.series.find((s) => s.key === k)!.label}</span>
              <span className="fin-stat-v">
                <FactValue fact={pt.fact} sourceIndex={profile.sourceIndex} context={ctx} />
              </span>
              <span className="freshness">{pt.period}</span>
            </div>
          );
        })}
      </div>

      {movements.length > 0 && (
        <ul className="fin-moves" aria-label="Latest reported movements">
          {movements.map((m) => (
            <li key={m.s.key}>
              {m.pct >= 0 ? <TrendingUp aria-hidden /> : <TrendingDown aria-hidden />}
              <span>
                <span className="t-muted">{m.s.label}</span> {m.a.period} → {m.b.period}:{' '}
                <span className="t-num">
                  {fmtShort(m.s, m.a.fact.value, m.a.fact.currency)} → {fmtShort(m.s, m.b.fact.value, m.b.fact.currency)}
                </span>{' '}
                <span className={m.pct >= 0 ? 'fin-delta is-up' : 'fin-delta is-down'}>
                  ({m.pct >= 0 ? '+' : '−'}
                  {formatPercent(Math.abs(m.pct))})
                </span>
              </span>
              {onExplain && (
                <button className="link-btn" onClick={() => onExplain({ kind: 'metric', metric: m.s.key, fromPeriod: m.a.period, toPeriod: m.b.period }, `${m.s.label} ${m.a.period} → ${m.b.period}`)}>
                  <Lightbulb aria-hidden /> Explain this change
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="fin-views">
        <Segmented label="Financial view" value={active} onChange={setView} options={views.map((v) => ({ value: v, label: VIEW_LABEL[v] }))} />
        <span className="spacer" />
        <span className="t-xs t-muted">
          {mixed ? `Mixed currencies (${(fin.currencies ?? []).join(', ')})` : fin.currency} · filed annual accounts · {periods.length} reporting period{periods.length === 1 ? '' : 's'}
        </span>
      </div>

      {mixed && (
        <p className="t-sm t-muted" role="note" data-testid="mixed-currency-note">
          These filings are stated in different currencies ({(fin.currencies ?? []).join(', ')}). Every amount is shown in the currency it was filed in and is never converted; changes across a currency switch are
          not computed, and charts show the latest reporting currency only.
        </p>
      )}

      {active === 'trend' && (
        <section className="card" aria-labelledby="fin-trend" data-search-block="financial-chart">
          <div className="card-head" style={{ flexWrap: 'wrap' }}>
            <h2 id="fin-trend">Trend</h2>
            <span className="spacer" />
            <Segmented label="Metric" value={group} onChange={setGroup} options={groups.map((g) => ({ value: g.id, label: g.label }))} />
            <Segmented
              label="Chart type"
              value={kind}
              onChange={setKind}
              options={[
                { value: 'line', label: <span className="sr-only">Line</span>, icon: <ChartLine aria-hidden />, title: 'Line' },
                { value: 'bar', label: <span className="sr-only">Bars</span>, icon: <ChartColumn aria-hidden />, title: 'Bars' },
              ]}
            />
          </div>
          {selected.length && selected[0].points.length >= 2 ? (
            <>
              <FinancialChart series={selected} sourceIndex={profile.sourceIndex} kind={kind} height={chartH} />
              <ChartTable series={selected} profile={profile} caption={`${selected.map((s) => s.label).join(', ')} by reporting period`} />
            </>
          ) : (
            <EmptyState compact title="Not enough history for a chart." text={`Only ${selected[0]?.points.length ?? 0} reporting period is available for this metric.`} />
          )}
        </section>
      )}

      {active === 'annual' && <AnnualValues profile={profile} periods={periods} />}

      {active === 'ratios' && (
        <section className="card" aria-labelledby="fin-ratios" data-search-block="financial-ratios">
          <div className="card-head">
            <h2 id="fin-ratios">Ratios</h2>
            <span className="t-xs t-muted">Computed deterministically from filed figures — no estimates</span>
          </div>
          {fin.ratios.length > 0 && (
            <ul className="ratios ratios--grid">
              {fin.ratios.map((r) => (
                <li key={r.key}>
                  <span className="t-sm">{r.label}</span>
                  <span className="t-num ratio-v">{formatPercent(r.value)}</span>
                  <span className="t-xs t-muted">
                    {r.formula} · {r.period}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {fin.ratioHistory && fin.ratioHistory.some((r) => r.points.length >= 2) && <RatioHistory profile={profile} height={compact ? 190 : 240} />}
        </section>
      )}

      {active === 'cash' && (
        <section className="card" aria-labelledby="fin-cash" data-search-block="financial-cash">
          <div className="card-head">
            <h2 id="fin-cash">Cash / debt</h2>
            <span className="t-xs t-muted">Cash, total debt and equity as filed at each year end</span>
          </div>
          {cashSeries[0]?.points.length >= 2 ? (
            <FinancialChart series={cashSeries} sourceIndex={profile.sourceIndex} kind="bar" height={chartH} />
          ) : (
            <p className="t-sm t-muted">Only one reporting period is available, so no chart is drawn.</p>
          )}
          <ChartTable series={cashSeries} profile={profile} caption="Cash, debt and equity by reporting period" open={cashSeries[0]?.points.length < 2} />
        </section>
      )}

      {active === 'sources' && <FinancialSources profile={profile} sources={finSources} />}
    </div>
  );
}

/** "View table" beneath a chart — exact values, period, change vs prior period and the source of each point. */
function ChartTable({ series, profile, caption, open: initial = false }: { series: FinancialSeries[]; profile: CompanyProfile; caption: string; open?: boolean }) {
  const [open, setOpen] = useState(initial);
  const periods = [...new Set(series.flatMap((s) => s.points.map((p) => p.period)))].sort().reverse();
  return (
    <div className="chart-table">
      <button className="link-btn" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <Table2 aria-hidden /> {open ? 'Hide table' : 'View table'}
      </button>
      {open && (
        <div className="table-wrap">
          <table className="table table--tight">
            <caption className="sr-only">{caption}</caption>
            <thead>
              <tr>
                <th scope="col" className="sticky-col">
                  Period
                </th>
                {series.map((s) => (
                  <th key={s.key} scope="col" className="num">
                    {s.label}
                  </th>
                ))}
                {series.map((s) => (
                  <th key={`d-${s.key}`} scope="col" className="num">
                    {series.length > 1 ? `Δ ${s.label}` : 'Change vs prior'}
                  </th>
                ))}
                <th scope="col">Source</th>
              </tr>
            </thead>
            <tbody>
              {periods.map((p) => {
                const srcIds = [...new Set(series.flatMap((s) => s.points.find((x) => x.period === p)?.fact.evidence.map((e) => e.sourceId) ?? []))];
                return (
                  <tr key={p}>
                    <th scope="row" className="sticky-col t-mono" style={{ fontWeight: 400 }}>
                      {p}
                    </th>
                    {series.map((s) => {
                      const pt = s.points.find((x) => x.period === p);
                      return (
                        <td key={s.key} className="num">
                          {pt ? <FactValue fact={pt.fact} sourceIndex={profile.sourceIndex} context={profile.company.legalName} exact /> : <span className="t-muted">—</span>}
                        </td>
                      );
                    })}
                    {series.map((s) => {
                      const i = s.points.findIndex((x) => x.period === p);
                      const pct = i > 0 ? factChange(s.points[i - 1].fact, s.points[i].fact) : null;
                      return (
                        <td key={`d-${s.key}`} className="num t-num">
                          {pct == null ? <span className="t-muted">—</span> : <span className={pct >= 0 ? 'fin-delta is-up' : 'fin-delta is-down'}>{`${pct >= 0 ? '+' : '−'}${formatPercent(Math.abs(pct))}`}</span>}
                        </td>
                      );
                    })}
                    <td className="t-sm t-soft">{srcIds.map((id) => profile.sourceIndex[id]?.name ?? id).join(', ') || '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** Annual values: every filed figure by period, with a year picker and change between the first and last selected year. */
function AnnualValues({ profile, periods }: { profile: CompanyProfile; periods: string[] }) {
  const fin = profile.financials;
  const [years, setYears] = useState<string[]>(periods);
  const shown = periods.filter((p) => years.includes(p));
  const first = shown[0];
  const last = shown.at(-1);
  return (
    <section className="card" aria-labelledby="fin-annual" data-search-block="financial-table">
      <div className="card-head" style={{ flexWrap: 'wrap' }}>
        <h2 id="fin-annual">Annual values</h2>
        <span className="t-xs t-muted">Values as filed; no adjustments. Click a value for evidence.</span>
        <span className="spacer" />
        <div className="row-wrap" role="group" aria-label="Years to show" style={{ gap: 6 }}>
          {periods.map((p) => (
            <button
              key={p}
              className="chip chip--sm"
              aria-pressed={years.includes(p)}
              onClick={() => setYears((ys) => (ys.includes(p) ? (ys.length > 1 ? ys.filter((y) => y !== p) : ys) : [...ys, p].sort()))}
            >
              {p.replace('FY', '')}
            </button>
          ))}
        </div>
      </div>
      <div className="table-wrap">
        <table className="table table--tight">
          <caption className="sr-only">Financial figures by reporting period</caption>
          <thead>
            <tr>
              <th className="sticky-col" scope="col">
                Metric
              </th>
              {shown.map((p) => (
                <th key={p} className="num" scope="col">
                  {p}
                </th>
              ))}
              {shown.length > 1 && (
                <th className="num" scope="col">
                  {first?.replace('FY', '')}→{last?.replace('FY', '')}
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {fin.series.map((s) => {
              const a = s.points.find((x) => x.period === first)?.fact;
              const b = s.points.find((x) => x.period === last)?.fact;
              const pct = factChange(a, b);
              return (
                <tr key={s.key}>
                  <th scope="row" className="sticky-col" style={{ fontWeight: 400 }}>
                    {s.label}
                    {!isCurrencyUnit(s.unit) && <span className="t-xs t-muted"> ({s.unit === 'people' ? 'FTEs' : s.unit})</span>}
                  </th>
                  {shown.map((p) => {
                    const pt = s.points.find((x) => x.period === p);
                    return (
                      <td key={p} className="num">
                        {pt ? <FactValue fact={pt.fact} sourceIndex={profile.sourceIndex} context={profile.company.legalName} /> : <span className="t-muted" aria-label="Not available">—</span>}
                      </td>
                    );
                  })}
                  {shown.length > 1 && (
                    <td className="num t-num">{pct == null ? <span className="t-muted">—</span> : <span className={pct >= 0 ? 'fin-delta is-up' : 'fin-delta is-down'}>{`${pct >= 0 ? '+' : '−'}${formatPercent(Math.abs(pct))}`}</span>}</td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** Ratio history chart + table (backend-computed ratios across periods). */
function RatioHistory({ profile, height }: { profile: CompanyProfile; height: number }) {
  const hist = (profile.financials.ratioHistory ?? []).filter((r) => r.points.length >= 2);
  const [key, setKey] = useState(hist[0]?.key ?? '');
  const r = hist.find((x) => x.key === key) ?? hist[0];
  const [table, setTable] = useState(false);
  if (!r) return null;
  // Adapt to the chart's series shape. Ratios are computed, not sourced, so they carry no evidence of their own.
  const asSeries: FinancialSeries = {
    key: 'revenue',
    label: r.label,
    unit: '%',
    points: r.points.map((p) => ({ period: p.period, year: Number(p.period.replace(/\D/g, '')), fact: { id: `${r.key}-${p.period}`, field: `ratios.${r.key}`, label: r.label, status: 'verified', value: p.value, unit: '%', reportingPeriod: p.period, evidenceState: 'primary', evidence: [] } })),
  };
  return (
    <div className="stack" style={{ gap: 10, marginTop: 14 }}>
      <div className="row-wrap" style={{ gap: 8 }}>
        <span className="t-micro">Across periods</span>
        <span className="spacer" />
        <Segmented label="Ratio" value={r.key} onChange={setKey} options={hist.map((h) => ({ value: h.key, label: h.label }))} />
      </div>
      <FinancialChart series={[asSeries]} sourceIndex={profile.sourceIndex} kind="line" height={height} />
      <p className="t-xs t-muted">Formula: {r.formula}</p>
      <div className="chart-table">
        <button className="link-btn" onClick={() => setTable((t) => !t)} aria-expanded={table}>
          <Table2 aria-hidden /> {table ? 'Hide table' : 'View table'}
        </button>
        {table && (
          <div className="table-wrap">
            <table className="table table--tight">
              <caption className="sr-only">Ratios by reporting period</caption>
              <thead>
                <tr>
                  <th scope="col" className="sticky-col">
                    Ratio
                  </th>
                  {r.points.map((p) => (
                    <th key={p.period} scope="col" className="num">
                      {p.period}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {hist.map((h) => (
                  <tr key={h.key}>
                    <th scope="row" className="sticky-col" style={{ fontWeight: 400 }}>
                      {h.label}
                      <span className="t-xs t-muted"> · {h.formula}</span>
                    </th>
                    {r.points.map((p) => {
                      const v = h.points.find((x) => x.period === p.period)?.value;
                      return (
                        <td key={p.period} className="num t-num">
                          {v == null ? '—' : formatPercent(v)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

interface FinSource {
  source: Source;
  periods: string[];
  figures: number;
  evidence: Evidence[];
  retrievedAt?: string;
  documents: string[];
}

function financialSources(profile: CompanyProfile): FinSource[] {
  const map = new Map<string, FinSource>();
  for (const s of profile.financials.series)
    for (const p of s.points)
      for (const e of p.fact.evidence) {
        const src = profile.sourceIndex[e.sourceId];
        if (!src) continue;
        const cur = map.get(e.sourceId) ?? { source: src, periods: [], figures: 0, evidence: [], documents: [] };
        if (!cur.periods.includes(p.period)) cur.periods.push(p.period);
        cur.figures += 1;
        if (!cur.evidence.some((x) => x.id === e.id)) cur.evidence.push(e);
        if (e.documentTitle && !cur.documents.includes(e.documentTitle)) cur.documents.push(e.documentTitle);
        if (!cur.retrievedAt || e.retrievedAt > cur.retrievedAt) cur.retrievedAt = e.retrievedAt;
        map.set(e.sourceId, cur);
      }
  return [...map.values()].map((s) => ({ ...s, periods: s.periods.sort() })).sort((a, b) => b.figures - a.figures);
}

function FinancialSources({ profile, sources }: { profile: CompanyProfile; sources: FinSource[] }) {
  const open = useOpenEvidence(profile.sourceIndex, profile.company.legalName);
  return (
    <section className="card" aria-labelledby="fin-sources" data-search-block="financial-sources">
      <div className="card-head">
        <h2 id="fin-sources">Sources</h2>
        <span className="t-xs t-muted">Filings and documents behind the figures above</span>
      </div>
      <ul className="fin-src">
        {sources.map((s) => (
          <li key={s.source.id}>
            <div className="stack" style={{ gap: 2, minWidth: 0 }}>
              <strong>{s.source.name}</strong>
              <span className="t-xs t-muted">
                {s.source.tier === 'primary' ? 'Primary source' : s.source.tier === 'secondary' ? 'Secondary source' : 'Source'}
                {s.source.originalTitle ? ` · ${s.source.originalTitle}` : ''}
              </span>
              {s.documents.length > 0 && <span className="t-xs t-soft">{s.documents.slice(0, 3).join(' · ')}</span>}
            </div>
            <span className="t-sm t-num">{s.periods.length > 1 ? `${s.periods[0]}–${s.periods.at(-1)}` : s.periods[0]}</span>
            <span className="t-sm t-muted">
              {s.figures} figure{s.figures === 1 ? '' : 's'}
            </span>
            <span className="t-xs t-muted">{s.retrievedAt ? `Retrieved ${formatDate(s.retrievedAt)}` : ''}</span>
            <span className="row" style={{ gap: 6, justifyContent: 'flex-end' }}>
              <button className="btn btn--ghost btn--sm" onClick={() => open({ title: `${s.source.name} — financial figures`, evidence: s.evidence.slice(0, 12) })}>
                <Eye aria-hidden /> Evidence
              </button>
              {s.source.url && (
                <a className="btn btn--ghost btn--sm" href={s.source.url} target="_blank" rel="noreferrer noopener">
                  <ExternalLink aria-hidden /> Open
                </a>
              )}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
