import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { MessageSquareText, MoreHorizontal, PanelLeftClose, Pencil, Plus, Trash2 } from 'lucide-react';
import type { ChatThreadSummary } from '@/types';
import { Menu } from '@/components/common/Menu';
import { Modal } from '@/components/common/Overlay';
import { cn } from '@/utils/cn';

export type HistoryGroup = 'Today' | 'Previous 7 days' | 'Earlier';

/** Groups conversations by when they were last used, newest first. `now` is injectable for tests. */
export function groupThreads(threads: ChatThreadSummary[], now = new Date()): Array<{ label: HistoryGroup; items: ChatThreadSummary[] }> {
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const week = startOfToday - 6 * 86_400_000;
  const groups: Record<HistoryGroup, ChatThreadSummary[]> = { Today: [], 'Previous 7 days': [], Earlier: [] };
  for (const t of [...threads].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))) {
    const at = new Date(t.updatedAt).getTime();
    (at >= startOfToday ? groups.Today : at >= week ? groups['Previous 7 days'] : groups.Earlier).push(t);
  }
  return (['Today', 'Previous 7 days', 'Earlier'] as const).filter((l) => groups[l].length).map((label) => ({ label, items: groups[label] }));
}

export function ChatHistory({
  threads,
  loading,
  error,
  activeId,
  onNew,
  onRename,
  onDelete,
  onCollapse,
  onNavigate,
}: {
  threads: ChatThreadSummary[];
  loading?: boolean;
  error?: string | null;
  activeId?: string;
  onNew: () => void;
  onRename: (id: string, title: string) => Promise<void> | void;
  onDelete: (id: string) => Promise<void> | void;
  onCollapse: () => void;
  onNavigate?: () => void;
}) {
  const [renaming, setRenaming] = useState<ChatThreadSummary | null>(null);
  const [deleting, setDeleting] = useState<ChatThreadSummary | null>(null);
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false);
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (renaming) setTimeout(() => field.current?.select(), 20);
  }, [renaming]);
  const groups = groupThreads(threads);

  return (
    <aside className="chat-history" aria-label="Chat history">
      <div className="chat-history__head">
        <button type="button" className="chat-new" onClick={onNew}>
          <Plus aria-hidden /> New chat
        </button>
        <button type="button" className="btn btn--ghost btn--icon btn--sm chat-collapse" onClick={onCollapse} aria-label="Hide chat history" title="Hide history">
          <PanelLeftClose aria-hidden />
        </button>
      </div>

      <div className="chat-history__list">
        {loading && <p className="t-xs t-muted chat-history__note">Loading conversations…</p>}
        {error && (
          <p className="t-xs chat-history__note" role="alert">
            {error}
          </p>
        )}
        {!loading && !error && threads.length === 0 && (
          <div className="chat-history__empty" data-testid="history-empty">
            <MessageSquareText aria-hidden />
            <strong>No conversations yet</strong>
            <span className="t-xs t-muted">Ask about a company and it will be saved here, with its sources.</span>
          </div>
        )}
        {groups.map((g) => (
          <section key={g.label} aria-label={g.label}>
            <h3 className="chat-history__group">{g.label}</h3>
            <ul>
              {g.items.map((t) => {
                const active = t.id === activeId;
                return (
                  <li key={t.id} className={cn('chat-item', active && 'is-active')}>
                    <Link to={`/chat/${t.id}`} className="chat-item__link" aria-current={active ? 'page' : undefined} onClick={onNavigate} title={t.title}>
                      <span className="chat-item__title">{t.title}</span>
                      {t.company && <span className="chat-item__sub t-xs">{t.company.legalName}</span>}
                    </Link>
                    <Menu
                      label={`Actions for ${t.title}`}
                      className="chat-item__menu"
                      trigger={<MoreHorizontal aria-hidden />}
                      items={[
                        { label: 'Rename', icon: <Pencil aria-hidden />, onSelect: () => (setTitle(t.title), setRenaming(t)) },
                        { label: 'Delete', icon: <Trash2 aria-hidden />, danger: true, onSelect: () => setDeleting(t) },
                      ]}
                    />
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>

      <Modal
        open={!!renaming}
        onClose={() => setRenaming(null)}
        title="Rename conversation"
        footer={
          <>
            <button className="btn" onClick={() => setRenaming(null)}>
              Cancel
            </button>
            <button
              className="btn btn--primary"
              disabled={busy || !title.trim()}
              onClick={async () => {
                if (!renaming) return;
                setBusy(true);
                try {
                  await onRename(renaming.id, title.trim());
                  setRenaming(null);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Save
            </button>
          </>
        }
      >
        <label className="stack" style={{ gap: 6 }}>
          <span className="t-sm">Title</span>
          <input ref={field} className="input" value={title} maxLength={80} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && title.trim() && (e.currentTarget.closest('.modal')?.querySelector<HTMLButtonElement>('.btn--primary')?.click())} />
        </label>
      </Modal>

      <Modal
        open={!!deleting}
        onClose={() => setDeleting(null)}
        title="Delete this conversation?"
        footer={
          <>
            <button className="btn" onClick={() => setDeleting(null)}>
              Cancel
            </button>
            <button
              className="btn btn--danger"
              disabled={busy}
              onClick={async () => {
                if (!deleting) return;
                setBusy(true);
                try {
                  await onDelete(deleting.id);
                  setDeleting(null);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Delete
            </button>
          </>
        }
      >
        <p>
          “{deleting?.title}” and its saved messages, sources and checks will be permanently removed. This cannot be undone.
        </p>
      </Modal>
    </aside>
  );
}
