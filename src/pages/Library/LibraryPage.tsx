import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import { Archive, Columns3, Download, Ellipsis, LayoutGrid, List, Pencil, Pin, PinOff, RefreshCw, Search, Table, Tag } from 'lucide-react';
import { api } from '@/api';
import type { ArtifactSummary, ArtifactType, LibrarySort } from '@/types';
import { usePreferences } from '@/stores/preferences';
import { useCompare, useUi } from '@/stores/ui';
import { useDebounce } from '@/hooks/useDebounce';
import { useIsMobile } from '@/hooks/useMediaQuery';
import { Segmented } from '@/components/common/Tabs';
import { Menu, type MenuItem } from '@/components/common/Menu';
import { Modal } from '@/components/common/Overlay';
import { Skeleton } from '@/components/common/Skeleton';
import { EmptyState } from '@/components/common/EmptyState';
import { ErrorState } from '@/components/common/ErrorState';
import { ExportModal } from '@/components/common/ExportModal';
import { CoverageMeter } from '@/components/company/Coverage';
import { ArtifactThumb } from '@/components/library/ArtifactThumb';
import { ArtifactIcon, artifactHref } from '@/components/library/artifactNav';
import { formatDate, formatOrgNumber, formatRelative } from '@/utils/format';
import { ARTIFACT_TYPE_LABEL } from '@/utils/status';
import { cn } from '@/utils/cn';
import './library.css';

const TYPES: { id: ArtifactType | 'all'; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'company', label: 'Companies' },
  { id: 'report', label: 'Reports' },
  { id: 'data_sheet', label: 'Data Sheets' },
  { id: 'comparison', label: 'Comparisons' },
  { id: 'watchlist', label: 'Watchlists' },
  { id: 'saved_search', label: 'Saved searches' },
];
const SUGGESTED_TAGS = ['SaaS', 'Healthcare', 'Prospect', 'Research', 'Watch', 'Competitor'];
const PAGE = 18;

export default function LibraryPage() {
  const [params, setParams] = useSearchParams();
  const type = (params.get('type') as ArtifactType | 'all') ?? 'all';
  const sort = (params.get('sort') as LibrarySort) ?? 'updated';
  const tag = params.get('tag') ?? undefined;
  const [q, setQ] = useState(params.get('q') ?? '');
  const dq = useDebounce(q.trim(), 250);
  const view = usePreferences((s) => s.libraryView);
  const setPref = usePreferences((s) => s.set);
  const caps = useQuery({ queryKey: ['library-caps'], queryFn: api.library.capabilities, staleTime: Infinity });

  const list = useInfiniteQuery({
    queryKey: ['library', 'list', { type, sort, tag, q: dq }],
    queryFn: ({ pageParam, signal }) => api.library.list({ type, sort, tag, q: dq || undefined, page: pageParam, pageSize: PAGE }, signal),
    initialPageParam: 1,
    getNextPageParam: (last) => (last.page * last.pageSize < last.total ? last.page + 1 : undefined),
  });
  const items = list.data?.pages.flatMap((p) => p.items) ?? [];
  const total = list.data?.pages[0]?.total ?? 0;
  const facets = list.data?.pages[0]?.facets;
  const mobile = useIsMobile();
  // The dense table is a desktop tool; phones get the readable list instead.
  const shownView = mobile && view === 'table' ? 'list' : view;
  const tags = [...new Set(items.flatMap((i) => i.tags))].sort();
  const setParam = (k: string, v?: string) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v);
    else p.delete(k);
    setParams(p, { replace: true });
  };

  return (
    <div className="page library">
      <div className="page-head">
        <div>
          <h1>Library</h1>
          <p>Your research, saved and searchable.</p>
        </div>
        <div className="page-actions">
          <Link to="/research" className="btn btn--primary">
            New research
          </Link>
          <Link to="/sheets?new=1" className="btn">
            New data sheet
          </Link>
        </div>
      </div>

      <div className="lib-search input-wrap">
        <Search aria-hidden />
        <label htmlFor="lib-q" className="sr-only">
          Search your research
        </label>
        <input id="lib-q" className="input" placeholder="Search your research… company, org. number, industry, place, tag" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      <div className="lib-bar">
        <div className="row-wrap" role="group" aria-label="Artifact type">
          {TYPES.map((t) => {
            const n = facets?.[t.id];
            if (facets && t.id !== 'all' && t.id !== type && !n) return null;
            return (
              <button key={t.id} className={cn('chip', t.id !== 'all' && `lib-chip lib-chip--${t.id}`)} aria-pressed={type === t.id} onClick={() => setParam('type', t.id === 'all' ? undefined : t.id)}>
                {t.id !== 'all' && <ArtifactIcon type={t.id} />}
                {t.label}
                {n != null && <span className="chip-count t-num">{n}</span>}
              </button>
            );
          })}
        </div>
        <span className="spacer" />
        <label className="row t-xs t-muted" style={{ gap: 6 }}>
          Sort
          <select className="select" style={{ height: 32, width: 170 }} value={sort} onChange={(e) => setParam('sort', e.target.value)}>
            <option value="updated">Recently updated</option>
            <option value="researched">Recently researched</option>
            <option value="name">Name</option>
            <option value="coverage">Coverage</option>
            <option value="changed">Last changed</option>
          </select>
        </label>
        <Segmented
          label="View"
          value={shownView}
          onChange={(v) => setPref({ libraryView: v })}
          options={[
            { value: 'cards', label: 'Card', icon: <LayoutGrid aria-hidden />, title: 'Cards with previews' },
            { value: 'list', label: 'List', icon: <List aria-hidden />, title: 'One line per item' },
            ...(mobile ? [] : [{ value: 'table' as const, label: 'Dense', icon: <Table aria-hidden />, title: 'Dense table for scanning many items' }]),
          ]}
        />
      </div>
      {(tags.length > 0 || tag) && (
        <div className="row-wrap" style={{ marginBottom: 16 }} role="group" aria-label="Tags">
          <Tag width={14} height={14} className="t-muted" aria-hidden />
          {[...new Set([...(tag ? [tag] : []), ...tags])].map((t) => (
            <button key={t} className="chip" style={{ height: 26, fontSize: 12 }} aria-pressed={tag === t} onClick={() => setParam('tag', tag === t ? undefined : t)}>
              {t}
            </button>
          ))}
        </div>
      )}

      <p className="t-xs t-muted" role="status" style={{ marginBottom: 12 }}>
        {list.isLoading ? 'Loading…' : `${total} item${total === 1 ? '' : 's'}${dq ? ` matching “${dq}”` : ''}`}
      </p>

      {list.isError ? (
        <ErrorState error={list.error} onRetry={() => list.refetch()} />
      ) : list.isLoading ? (
        <div className="lib-grid">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} h={240} r={12} />
          ))}
        </div>
      ) : items.length === 0 ? (
        dq || type !== 'all' || tag ? (
          <EmptyState title="No saved research matches." text="Try a different search or filter." />
        ) : (
          <EmptyState
            title="Your research library is empty."
            text="Start with a company or create a research sheet."
            action={
              <>
                <Link to="/research" className="btn btn--primary">
                  Research a company
                </Link>
                <Link to="/sheets?new=1" className="btn">
                  Create a data sheet
                </Link>
              </>
            }
          />
        )
      ) : shownView === 'table' ? (
        <LibTable items={items} caps={caps.data} />
      ) : (
        <div className={shownView === 'cards' ? 'lib-grid' : 'lib-list'}>
          {items.map((a) => (
            <LibItem key={a.id} a={a} compact={shownView === 'list'} caps={caps.data} />
          ))}
        </div>
      )}

      {list.hasNextPage && (
        <div className="pager">
          <button className="btn" onClick={() => list.fetchNextPage()} disabled={list.isFetchingNextPage}>
            {list.isFetchingNextPage ? 'Loading…' : `Load more (${total - items.length} remaining)`}
          </button>
        </div>
      )}
    </div>
  );
}

function useArtifactActions(a: ArtifactSummary, caps?: Awaited<ReturnType<typeof api.library.capabilities>>) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const toggle = useCompare((s) => s.toggle);
  const toast = useUi((s) => s.toast);
  const [modal, setModal] = useState<null | 'rename' | 'tag' | 'archive' | 'export'>(null);
  const patch = async (p: Parameters<typeof api.library.update>[1], msg?: string) => {
    await api.library.update(a.id, p);
    await qc.invalidateQueries({ queryKey: ['library'] });
    if (msg) toast({ tone: 'ok', text: msg });
  };
  const items: MenuItem[] = [];
  if (caps?.pin) items.push({ label: a.pinned ? 'Unpin' : 'Pin', icon: a.pinned ? <PinOff aria-hidden /> : <Pin aria-hidden />, onSelect: () => patch({ pinned: !a.pinned }) });
  if (caps?.rename) items.push({ label: 'Rename', icon: <Pencil aria-hidden />, onSelect: () => setModal('rename') });
  if (caps?.tag) items.push({ label: 'Add tag', icon: <Tag aria-hidden />, onSelect: () => setModal('tag') });
  if (a.type === 'company' && a.orgNumber) {
    items.push({ label: 'Compare', icon: <Columns3 aria-hidden />, onSelect: () => (toggle({ orgNumber: a.orgNumber!, legalName: a.title }), toast({ tone: 'info', text: `${a.title} added to compare` })) });
    if (caps?.export) items.push({ label: 'Export', icon: <Download aria-hidden />, onSelect: () => setModal('export') });
    if (caps?.refresh) items.push({ label: 'Refresh research', icon: <RefreshCw aria-hidden />, onSelect: () => nav(`/research?org=${a.orgNumber}&autostart=1`) });
  }
  if (caps?.archive) items.push({ label: 'Archive', icon: <Archive aria-hidden />, onSelect: () => setModal('archive'), danger: true, separatorBefore: true });
  return { items, modal, setModal, patch };
}

function ArtifactModals({ a, ctl }: { a: ArtifactSummary; ctl: ReturnType<typeof useArtifactActions> }) {
  const [title, setTitle] = useState(a.title);
  const [tagInput, setTagInput] = useState('');
  const { modal, setModal, patch } = ctl;
  const close = () => setModal(null);
  return (
    <>
      <Modal
        open={modal === 'rename'}
        onClose={close}
        title="Rename"
        footer={
          <>
            <button className="btn btn--ghost" onClick={close}>
              Cancel
            </button>
            <button className="btn btn--primary" disabled={!title.trim()} onClick={() => (patch({ title: title.trim() }, 'Renamed'), close())}>
              Save
            </button>
          </>
        }
      >
        <div className="field">
          <label htmlFor={`rn-${a.id}`}>Title</label>
          <input id={`rn-${a.id}`} className="input" value={title} onChange={(e) => setTitle(e.target.value)} data-autofocus />
        </div>
      </Modal>
      <Modal open={modal === 'tag'} onClose={close} title="Tags">
        <div className="stack" style={{ gap: 12 }}>
          <div className="row-wrap">
            {[...new Set([...SUGGESTED_TAGS, ...a.tags])].map((t) => (
              <button key={t} className="chip" aria-pressed={a.tags.includes(t)} onClick={() => patch({ tags: a.tags.includes(t) ? a.tags.filter((x) => x !== t) : [...a.tags, t] })}>
                {t}
              </button>
            ))}
          </div>
          <form
            className="row"
            onSubmit={(e) => {
              e.preventDefault();
              if (tagInput.trim()) patch({ tags: [...a.tags, tagInput.trim()] });
              setTagInput('');
            }}
          >
            <input className="input" value={tagInput} onChange={(e) => setTagInput(e.target.value)} placeholder="Custom tag" aria-label="Custom tag" />
            <button className="btn">Add</button>
          </form>
        </div>
      </Modal>
      <Modal
        open={modal === 'archive'}
        onClose={close}
        title="Archive this item?"
        footer={
          <>
            <button className="btn btn--ghost" onClick={close}>
              Cancel
            </button>
            <button className="btn btn--danger" onClick={() => (patch({ archived: true }, 'Archived'), close())}>
              Archive
            </button>
          </>
        }
      >
        <p className="t-sm t-soft">“{a.title}” will be hidden from the Library. Archived research is kept and can be restored; nothing is deleted.</p>
      </Modal>
      {a.orgNumber && <ExportModal open={modal === 'export'} onClose={close} target={{ type: 'company', id: a.orgNumber }} title={a.title} />}
    </>
  );
}

function LibItem({ a, compact, caps }: { a: ArtifactSummary; compact?: boolean; caps?: Awaited<ReturnType<typeof api.library.capabilities>> }) {
  const ctl = useArtifactActions(a, caps);
  const typeTag = (
    <span className={`lib-type lib-type--${a.type}`}>
      <ArtifactIcon type={a.type} />
      {ARTIFACT_TYPE_LABEL[a.type]}
    </span>
  );
  const changes = (a.changeCount ?? 0) > 0 && <span className="pill pill--sm pill--info">{a.type === 'watchlist' ? `${a.changeCount} changed` : `${a.changeCount} change${a.changeCount === 1 ? '' : 's'}`}</span>;
  const subtitle =
    a.type === 'company' ? (
      <>
        {a.municipality}, Norway · <span className="t-mono">{a.orgNumber && formatOrgNumber(a.orgNumber)}</span>
      </>
    ) : (
      (a.subtitle ?? '')
    );
  const when = (
    <span className="t-xs t-muted" title={formatDate(a.updatedAt)}>
      {a.type === 'company' ? 'Researched' : 'Updated'} {formatRelative(a.researchedAt ?? a.updatedAt)}
    </span>
  );
  const menu = (
    <div className="lib-menu">
      <Menu label={`Actions for ${a.title}`} trigger={<Ellipsis aria-hidden />} items={ctl.items} />
    </div>
  );

  if (compact)
    return (
      <article className={cn('lib-card', `lib-card--${a.type}`, 'lib-card--row')}>
        <Link to={artifactHref(a)} className="co-card-link" aria-label={`${ARTIFACT_TYPE_LABEL[a.type]}: ${a.title}. Open.`} />
        <div className="lib-row">
          <span className="lib-row-type">
            {typeTag}
            {a.pinned && <Pin width={13} height={13} className="t-accent" aria-label="Pinned" />}
          </span>
          <span className="lib-title truncate">{a.title}</span>
          <span className="t-xs t-muted truncate">{subtitle}</span>
          <span className="lib-row-facts">
            {a.coverage && <CoverageMeter coverage={a.coverage} size="sm" />}
            {a.type === 'company' && a.openPositions != null && <span className="t-xs t-muted">{a.openPositions} openings</span>}
            {changes}
          </span>
          {when}
          {menu}
        </div>
        <ArtifactModals a={a} ctl={ctl} />
      </article>
    );

  return (
    <article className={cn('lib-card', `lib-card--${a.type}`)}>
      <Link to={artifactHref(a)} className="co-card-link" aria-label={`${ARTIFACT_TYPE_LABEL[a.type]}: ${a.title}. Open.`} />
      <ArtifactThumb a={a} />
      <div className="lib-body">
        <div className="row" style={{ gap: 8 }}>
          {typeTag}
          {a.pinned && <Pin width={13} height={13} className="t-accent" aria-label="Pinned" />}
          <span className="spacer" />
          {changes}
          {menu}
        </div>
        <h3 className="lib-title truncate">{a.title}</h3>
        {a.type !== 'company' && a.itemCount != null && <span className="t-xs t-soft">{a.itemCount} {a.type === 'data_sheet' ? 'rows' : a.type === 'comparison' ? 'companies' : a.type === 'watchlist' ? 'companies watched' : 'items'}</span>}
        <span className="t-xs t-muted truncate">{subtitle}</span>
        <div className="lib-foot">
          {a.coverage && <CoverageMeter coverage={a.coverage} size="sm" />}
          {a.type === 'company' && a.openPositions != null && <span className="t-xs t-muted">{a.openPositions} openings</span>}
          <span className="spacer" />
          {when}
        </div>
        {a.tags.length > 0 && (
          <div className="row-wrap" style={{ gap: 4 }}>
            {a.tags.map((t) => (
              <span key={t} className="pill pill--sm">
                {t}
              </span>
            ))}
          </div>
        )}
      </div>
      <ArtifactModals a={a} ctl={ctl} />
    </article>
  );
}

function LibTable({ items, caps }: { items: ArtifactSummary[]; caps?: Awaited<ReturnType<typeof api.library.capabilities>> }) {
  return (
    <div className="table-wrap">
      <table className="table table--dense">
        <caption className="sr-only">Library items</caption>
        <thead>
          <tr>
            <th className="sticky-col" scope="col">
              Title
            </th>
            <th scope="col">Type</th>
            <th scope="col">Org. no.</th>
            <th scope="col">Location</th>
            <th scope="col">Coverage</th>
            <th scope="col" className="num">
              Changes
            </th>
            <th scope="col" className="num">
              Openings
            </th>
            <th scope="col">Researched</th>
            <th scope="col">Updated</th>
            <th scope="col">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((a) => (
            <LibRow key={a.id} a={a} caps={caps} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LibRow({ a, caps }: { a: ArtifactSummary; caps?: Awaited<ReturnType<typeof api.library.capabilities>> }) {
  const ctl = useArtifactActions(a, caps);
  return (
    <tr>
      <td className="sticky-col">
        <Link to={artifactHref(a)} className="row lib-row-link" style={{ gap: 8 }}>
          <ArtifactIcon type={a.type} />
          <span style={{ fontWeight: 500 }}>{a.title}</span>
        </Link>
      </td>
      <td>
        <span className={`lib-type lib-type--${a.type}`}>{ARTIFACT_TYPE_LABEL[a.type]}</span>
      </td>
      <td className="t-mono">{a.orgNumber ? formatOrgNumber(a.orgNumber) : '—'}</td>
      <td>{a.municipality ?? '—'}</td>
      <td>{a.coverage ? <CoverageMeter coverage={a.coverage} size="sm" interactive={false} /> : '—'}</td>
      <td className="num t-num">{a.changeCount || '—'}</td>
      <td className="num t-num">{a.openPositions ?? '—'}</td>
      <td>{a.researchedAt ? formatDate(a.researchedAt) : '—'}</td>
      <td>{formatDate(a.updatedAt)}</td>
      <td>
        <Menu label={`Actions for ${a.title}`} trigger={<Ellipsis aria-hidden />} items={ctl.items} />
        <ArtifactModals a={a} ctl={ctl} />
      </td>
    </tr>
  );
}
