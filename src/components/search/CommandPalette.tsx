import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowRight,
  Building2,
  Clock,
  Columns3,
  Compass,
  Download,
  FileText,
  History,
  Library,
  LoaderCircle,
  Moon,
  Radar,
  Rows3,
  Rows4,
  Search,
  SearchCode,
  Sun,
  Table2,
  Telescope,
} from 'lucide-react';
import { api } from '@/api';
import { useUi } from '@/stores/ui';
import { usePreferences } from '@/stores/preferences';
import { useDebounce } from '@/hooks/useDebounce';
import { useModHotkey, modKeyLabel } from '@/hooks/useHotkey';
import { formatOrgNumber } from '@/utils/format';
import { fireCommand } from '@/hooks/useCommand';

interface Item {
  id: string;
  group: string;
  icon: ReactNode;
  label: ReactNode;
  sub?: ReactNode;
  hint?: string;
  /** Extra words that should match this command (e.g. "dark", "density"). */
  keywords?: string;
  run: () => void | Promise<void>;
}

/** ⌘K / Ctrl+K command center: commands, companies, research, sheets, reports. */
export function CommandPalette() {
  const { paletteOpen, paletteQuery, openPalette, closePalette } = useUi();
  const toggle = useCallback(() => (useUi.getState().paletteOpen ? closePalette() : openPalette()), [openPalette, closePalette]);
  useModHotkey('k', toggle);
  if (!paletteOpen) return null;
  return createPortal(<PaletteBody initial={paletteQuery} onClose={closePalette} />, document.body);
}

function PaletteBody({ initial, onClose }: { initial: string; onClose: () => void }) {
  const [q, setQ] = useState(initial);
  const [active, setActive] = useState(0);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  const loc = useLocation();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const recent = usePreferences((s) => s.recentSearches);
  const pushRecent = usePreferences((s) => s.pushRecentSearch);
  const dq = useDebounce(q.trim(), 160);
  const orgInRoute = loc.pathname.match(/^\/company\/(\d{9})/)?.[1];
  const artifactInRoute = loc.pathname.match(/^\/library\/([^/]+)/)?.[1];
  const sheetInRoute = loc.pathname.match(/^\/sheets\/([^/]+)/)?.[1];
  const onCompare = loc.pathname === '/compare';
  const density = usePreferences((s) => s.density);
  const theme = usePreferences((s) => s.theme);
  const setPref = usePreferences((s) => s.set);
  const effTheme = theme === 'system' ? (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark') : theme;

  // "open nordvik" → search for "nordvik" (the Open company command).
  const searchQ = dq.replace(/^open\s+/i, '');
  const { data, isFetching } = useQuery({
    queryKey: ['palette-search', searchQ],
    queryFn: ({ signal }) => api.search.global(searchQ, signal),
    enabled: searchQ.length >= 2,
    staleTime: 30_000,
  });

  useEffect(() => {
    inputRef.current?.focus();
    const prev = document.activeElement as HTMLElement | null;
    return () => prev?.focus?.();
  }, []);

  const go = useCallback(
    (to: string) => {
      onClose();
      nav(to);
    },
    [nav, onClose],
  );

  const items = useMemo<Item[]>(() => {
    const out: Item[] = [];
    const text = q.trim();
    const lower = text.toLowerCase();

    // Parsed commands (UI routing only — the backend resolves meaning)
    const research = lower.match(/^research\s+(.+)/);
    const compare = lower.match(/^compare\s+(.+)/);
    const find = lower.match(/^(find|show|list)\s+(.+)/);
    if (research)
      out.push({ id: 'cmd-research', group: 'Commands', icon: <Telescope />, label: <>Research “{text.slice(9)}”</>, sub: 'Start a research run', run: () => go(`/research?q=${encodeURIComponent(text.slice(9))}&autostart=1`) });
    if (compare) {
      const parts = text
        .slice(8)
        .split(/\s*(?:\+|,|\bvs\.?\b|\band\b)\s*/i)
        .filter(Boolean);
      out.push({
        id: 'cmd-compare',
        group: 'Commands',
        icon: <Columns3 />,
        label: <>Compare {parts.map((p) => `“${p}”`).join(' + ')}</>,
        sub: 'Resolves each company, then opens Compare',
        run: async () => {
          setBusy(true);
          const resolved = await Promise.all(parts.map((p) => api.search.global(p).then((r) => r.companies[0]?.orgNumber)));
          setBusy(false);
          const orgs = resolved.filter(Boolean);
          go(`/compare?orgs=${orgs.join(',')}`);
        },
      });
    }
    if (find || (text && data?.intent.kind === 'discover'))
      out.push({ id: 'cmd-find', group: 'Commands', icon: <Compass />, label: <>Find companies: “{find ? text.slice(find[1].length + 1) : text}”</>, sub: 'Natural-language discovery', run: () => go(`/discover?q=${encodeURIComponent(find ? text.slice(find[1].length + 1) : text)}`) });

    // Results
    if (data && searchQ.length >= 2) {
      for (const c of data.companies)
        out.push({
          id: `co-${c.orgNumber}`,
          group: 'Companies',
          icon: <Building2 />,
          label: c.legalName,
          sub: (
            <>
              {c.municipality} · <span className="t-mono">{formatOrgNumber(c.orgNumber)}</span> · {c.coverage.complete}/5 areas
            </>
          ),
          hint: 'Open',
          run: () => {
            pushRecent(text);
            go(`/company/${c.orgNumber}`);
          },
        });
      for (const a of data.artifacts)
        out.push({ id: `ar-${a.id}`, group: 'Research', icon: <History />, label: a.title, sub: a.type === 'comparison' ? 'Comparison' : 'Saved research', run: () => go(a.type === 'comparison' ? `/compare?orgs=${a.targetId}` : `/library/${a.id}`) });
      for (const s of data.sheets) out.push({ id: `sh-${s.id}`, group: 'Data Sheets', icon: <Table2 />, label: s.title, sub: `${s.rowCount} companies`, run: () => go(`/sheets/${s.id}`) });
      for (const r of data.reports) out.push({ id: `rp-${r.id}`, group: 'Reports', icon: <FileText />, label: r.title, run: () => go(`/library/${r.id}`) });
      for (const s of data.savedSearches) out.push({ id: `ss-${s.id}`, group: 'Saved Searches', icon: <Search />, label: s.title, run: () => go(`/discover?q=${encodeURIComponent(s.query)}`) });
    }

    // Commands. Page-specific ones are fired as events the current page handles.
    const run = (fn: () => void) => () => {
      onClose();
      setTimeout(fn, 0);
    };
    const ctx: Item[] = [];
    if (orgInRoute)
      ctx.push(
        { id: 'c-brief', group: 'This company', icon: <FileText />, label: 'Executive brief', keywords: 'summary one screen', run: run(() => fireCommand('brief')) },
        { id: 'c-continue', group: 'This company', icon: <Telescope />, label: 'Continue research', keywords: 'update refresh', run: () => go(`/research?org=${orgInRoute}`) },
        { id: 'c-changes', group: 'This company', icon: <History />, label: 'What changed', keywords: 'changes', run: () => go(`/company/${orgInRoute}?tab=changes`) },
      );
    if (artifactInRoute) ctx.push({ id: 'c-search', group: 'This research', icon: <SearchCode />, label: 'Search this research', keywords: 'find in research evidence', run: run(() => fireCommand('search-research')) });
    if (orgInRoute || artifactInRoute || sheetInRoute || onCompare)
      ctx.push({ id: 'c-export', group: orgInRoute ? 'This company' : artifactInRoute ? 'This research' : sheetInRoute ? 'This data sheet' : 'This comparison', icon: <Download />, label: 'Export', keywords: 'download pdf csv excel', run: run(() => fireCommand('export')) });

    const actions: Item[] = [
      ...ctx,
      { id: 'a-search', group: 'Actions', icon: <Compass />, label: 'Search company', keywords: 'discover find companies', run: () => go(text && !lower.startsWith('search') ? `/discover?q=${encodeURIComponent(text)}` : '/discover') },
      { id: 'a-open', group: 'Actions', icon: <Building2 />, label: 'Open company…', keywords: 'go to profile org number', run: () => (setQ('open '), inputRef.current?.focus()) },
      { id: 'a-research', group: 'Actions', icon: <Telescope />, label: 'Start research', hint: 'R', keywords: 'new run', run: () => go('/research') },
      ...(orgInRoute ? [] : [{ id: 'a-continue', group: 'Actions', icon: <History />, label: 'Continue research', keywords: 'recent researched', run: () => go('/library?type=company&sort=researched') } as Item]),
      { id: 'a-library', group: 'Actions', icon: <Library />, label: text && !/library/.test(lower) ? <>Search Library for “{text}”</> : 'Search Library', keywords: `library saved ${lower}`, run: () => go(text && !/library/.test(lower) ? `/library?q=${encodeURIComponent(text)}` : '/library') },
      { id: 'a-sheet', group: 'Actions', icon: <Table2 />, label: 'Create Data Sheet', keywords: 'table spreadsheet new', run: () => go('/sheets?new=1') },
      { id: 'a-compare', group: 'Actions', icon: <Columns3 />, label: 'Compare companies', keywords: 'side by side', run: () => go('/compare') },
      { id: 'a-watch', group: 'Actions', icon: <Radar />, label: 'Open Watchlist', keywords: 'monitor alerts', run: () => go('/watchlist') },
      { id: 'a-density', group: 'View', icon: density === 'compact' ? <Rows3 /> : <Rows4 />, label: density === 'compact' ? 'Toggle Compact Mode (on)' : 'Toggle Compact Mode', sub: density === 'compact' ? 'Switch to comfortable density' : 'Tighter tables, sheets, compare and research views', keywords: 'density dense comfortable', run: () => (setPref({ density: density === 'compact' ? 'comfortable' : 'compact' }), onClose()) },
      { id: 'a-theme', group: 'View', icon: effTheme === 'dark' ? <Sun /> : <Moon />, label: 'Toggle Theme', sub: effTheme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode', keywords: 'dark light mode appearance', run: () => (setPref({ theme: effTheme === 'dark' ? 'light' : 'dark' }), onClose()) },
    ];
    const words = lower.replace(/^open\s*/, '').split(/\s+/).filter(Boolean);
    const labelText = (a: Item) => `${typeof a.label === 'string' ? a.label : a.id} ${a.keywords ?? ''}`.toLowerCase();
    // Commands match when every typed word appears in the label or keywords; the Library search command always stays available.
    const filtered = text ? actions.filter((a) => a.id === 'a-library' || (!lower.startsWith('open') && words.every((w) => labelText(a).includes(w)))) : actions;
    out.push(...filtered);
    if (!text)
      for (const r of recent) out.unshift({ id: `rs-${r}`, group: 'Recent searches', icon: <Clock />, label: r, run: () => setQ(r) });
    return out;
  }, [q, searchQ, data, recent, orgInRoute, artifactInRoute, sheetInRoute, onCompare, density, effTheme, setPref, onClose, go, pushRecent]);

  useEffect(() => setActive(0), [q, data]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-idx="${active}"]`)?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((a) => Math.min(items.length - 1, a + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((a) => Math.max(0, a - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const it = items[active];
      if (it) void it.run();
      else if (q.trim()) go(`/discover?q=${encodeURIComponent(q.trim())}`);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    }
  };

  let lastGroup = '';
  return (
    <div className="palette-wrap" onKeyDown={onKey}>
      <div className="scrim" onClick={onClose} aria-hidden />
      <div className="palette" role="dialog" aria-modal="true" aria-label="Command palette">
        <div className="palette-input">
          {isFetching || busy ? <LoaderCircle className="spin" aria-hidden /> : <Search aria-hidden />}
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search a company, organization number, industry or place — or type a command"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            aria-activedescendant={items[active] ? `pi-${items[active].id}` : undefined}
            aria-autocomplete="list"
          />
          <span className="kbd">Esc</span>
        </div>
        <div className="palette-list" id="palette-list" role="listbox" ref={listRef} aria-label="Results">
          {items.length === 0 && (
            <div className="empty empty--center" style={{ margin: 10, border: 0 }}>
              <p className="empty-text">{dq.length >= 2 && !isFetching ? 'No matches. Press Enter to run a discovery search.' : 'Search by company, industry, location or organization number.'}</p>
            </div>
          )}
          {items.map((it, i) => {
            const head = it.group !== lastGroup ? it.group : null;
            lastGroup = it.group;
            return (
              <div key={it.id}>
                {head && <div className="palette-group t-micro">{head}</div>}
                <button
                  id={`pi-${it.id}`}
                  data-idx={i}
                  role="option"
                  aria-selected={i === active}
                  className="palette-item"
                  onMouseMove={() => setActive(i)}
                  onClick={() => void it.run()}
                  tabIndex={-1}
                >
                  {it.icon}
                  <span className="stack" style={{ gap: 0, flex: 1, minWidth: 0 }}>
                    <span className="truncate">{it.label}</span>
                    {it.sub && <span className="palette-sub truncate">{it.sub}</span>}
                  </span>
                  {i === active && <ArrowRight width={14} height={14} aria-hidden style={{ color: 'var(--text-3)' }} />}
                </button>
              </div>
            );
          })}
        </div>
        <div className="palette-foot" aria-hidden>
          <span>↑↓ navigate</span>
          <span>↵ open</span>
          <span>{modKeyLabel} K toggle</span>
          <span className="spacer" />
          <span>Try “research Nordvik”, “compare Tindra + Lumen”, “find SaaS companies in Oslo”</span>
        </div>
      </div>
    </div>
  );
}
