import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, Building2, Compass, History, LoaderCircle, Search, Table2 } from 'lucide-react';
import { api } from '@/api';
import { useDebounce } from '@/hooks/useDebounce';
import { modKeyLabel } from '@/hooks/useHotkey';
import { useGlobe, useUi } from '@/stores/ui';
import { usePreferences } from '@/stores/preferences';
import { formatOrgNumber } from '@/utils/format';
import { cn } from '@/utils/cn';

interface Option {
  id: string;
  group: string;
  icon: React.ReactNode;
  label: string;
  sub?: string;
  to: string;
}

/**
 * Large hero search. Routes on the backend's intent (company / discover),
 * never on local keyword guessing. Nudges the globe toward the top match.
 */
export function HeroSearch({ autoFocus }: { autoFocus?: boolean }) {
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const nav = useNavigate();
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const dq = useDebounce(q.trim(), 200);
  const setFocus = useGlobe((s) => s.setFocus);
  const pushRecent = usePreferences((s) => s.pushRecentSearch);
  const openPalette = useUi((s) => s.openPalette);

  const { data, isFetching } = useQuery({
    queryKey: ['hero-search', dq],
    queryFn: ({ signal }) => api.search.global(dq, signal),
    enabled: dq.length >= 2,
    staleTime: 30_000,
  });

  // Globe reacts to real, backend-provided geo of the top company match,
  // and lets go (resumes spinning) when the query is cleared or has no located match.
  useEffect(() => {
    const top = data?.companies[0];
    if (dq.length >= 2 && top?.geo) setFocus({ id: `search-${top.orgNumber}`, lat: top.geo.lat, lon: top.geo.lon, label: `${top.legalName} · ${top.municipality}` });
    else if (dq.length < 2 || data) setFocus(null);
  }, [data, dq, setFocus]);

  useEffect(() => {
    const onDown = (e: MouseEvent) => !wrapRef.current?.contains(e.target as Node) && setOpen(false);
    window.addEventListener('mousedown', onDown);
    return () => window.removeEventListener('mousedown', onDown);
  }, []);

  const options = useMemo<Option[]>(() => {
    if (!data || dq.length < 2) return [];
    const out: Option[] = [];
    if (data.intent.kind === 'discover' || data.companies.length !== 1)
      out.push({ id: 'discover', group: 'Discover', icon: <Compass />, label: `Find companies: “${dq}”`, sub: 'Natural-language discovery with editable filters', to: `/discover?q=${encodeURIComponent(dq)}` });
    for (const c of data.companies.slice(0, 5))
      out.push({ id: c.orgNumber, group: 'Companies', icon: <Building2 />, label: c.legalName, sub: `${c.municipality ?? ''} · Org ${formatOrgNumber(c.orgNumber)} · ${c.coverage.complete}/5 areas`, to: `/company/${c.orgNumber}` });
    for (const a of data.artifacts.slice(0, 3)) out.push({ id: a.id, group: 'Research', icon: <History />, label: a.title, sub: 'Saved research', to: a.type === 'comparison' ? `/compare?orgs=${a.targetId}` : `/library/${a.id}` });
    for (const s of data.sheets.slice(0, 2)) out.push({ id: s.id, group: 'Data Sheets', icon: <Table2 />, label: s.title, sub: `${s.rowCount} companies`, to: `/sheets/${s.id}` });
    return out;
  }, [data, dq]);

  const submit = async () => {
    const text = q.trim();
    if (!text) return;
    pushRecent(text);
    if (active >= 0 && options[active]) return nav(options[active].to);
    const res = data && data.query === text ? data : await api.search.global(text);
    if (res.intent.kind === 'company') nav(`/company/${res.intent.orgNumber}`);
    else nav(`/discover?q=${encodeURIComponent(text)}`);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setOpen(true);
      setActive((a) => Math.min(options.length - 1, a + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((a) => Math.max(-1, a - 1));
    } else if (e.key === 'Escape') setOpen(false);
  };

  let lastGroup = '';
  return (
    <div className="hero-search" ref={wrapRef}>
      <form
        className={cn('hero-search-field glass', open && options.length > 0 && 'is-open')}
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        {isFetching ? <LoaderCircle className="spin" aria-hidden /> : <Search aria-hidden />}
        <label htmlFor="hero-q" className="sr-only">
          Search company, organization number, industry or place
        </label>
        <input
          ref={inputRef}
          id="hero-q"
          value={q}
          autoFocus={autoFocus}
          autoComplete="off"
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
            setActive(-1);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKey}
          placeholder="Search company, organization number, industry or place…"
          role="combobox"
          aria-expanded={open && options.length > 0}
          aria-controls={listId}
          aria-activedescendant={active >= 0 ? `hs-${options[active]?.id}` : undefined}
        />
        <button type="button" className="kbd hero-kbd" onClick={() => openPalette(q)} aria-label="Open command palette">
          {modKeyLabel} K
        </button>
        <button type="submit" className="btn btn--primary hero-go" aria-label="Search">
          <ArrowRight aria-hidden />
        </button>
      </form>
      {open && options.length > 0 && (
        <div className="hero-suggest" id={listId} role="listbox" aria-label="Suggestions">
          {options.map((o, i) => {
            const head = o.group !== lastGroup ? o.group : null;
            lastGroup = o.group;
            return (
              <div key={o.id}>
                {head && <div className="t-micro hero-suggest-group">{head}</div>}
                <button id={`hs-${o.id}`} role="option" aria-selected={i === active} className="palette-item" onMouseEnter={() => setActive(i)} onClick={() => (pushRecent(q.trim()), nav(o.to))}>
                  {o.icon}
                  <span className="stack" style={{ gap: 0, minWidth: 0, flex: 1 }}>
                    <span className="truncate">{o.label}</span>
                    {o.sub && <span className="palette-sub truncate">{o.sub}</span>}
                  </span>
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
