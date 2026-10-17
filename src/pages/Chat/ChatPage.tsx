import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, CircleAlert, MessageSquareText, PanelLeftOpen, RotateCcw } from 'lucide-react';
import { api, ApiError } from '@/api';
import type { ChatCandidate, ChatProgress, ChatReply, ChatThread, ThreadMessage } from '@/types';
import { CognisLogo } from '@/components/common/CognisLogo';
import { ErrorState } from '@/components/common/ErrorState';
import { Skeleton } from '@/components/common/Skeleton';
import { Answer, Composer, ContextNotice, Progress } from '@/components/chat/ChatParts';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import { formatOrgNumber } from '@/utils/format';
import { ChatHistory } from './ChatHistory';
import { isNearBottom, nextScrollTop } from './followScroll';
import '@/components/chat/ask-ai.css';
import './chat.css';

const MAX_QUESTION = 1000;

/** Starter prompts. They fill the composer (so the person names the company) — nothing is sent for them and no company is guessed. */
export const STARTERS: Array<{ title: string; text: string }> = [
  { title: 'Compare results year on year', text: 'Compare the latest annual results of ' },
  { title: 'Latest developments', text: 'What are the most important recent developments at ' },
  { title: 'Who runs it?', text: 'Who runs the company and what is the corporate structure of ' },
  { title: 'Audit the sources', text: 'Which sources were checked for ' },
];

export const newId = (): string => {
  const c = globalThis.crypto as Crypto | undefined;
  if (c?.randomUUID) return c.randomUUID();
  return `c${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
};

interface Seed {
  messageId: string;
  question: string;
  orgNumber?: string;
}
interface Pending {
  messageId: string;
  question: string;
  steps: ChatProgress[];
  error?: unknown;
  orgNumber?: string;
  fresh?: boolean;
  retryOf?: string;
  /** The user message is already stored (retrying a clarification): do not draw it twice. */
  showQuestion: boolean;
}

export function toReply(m: ThreadMessage, company: ChatThread['company']): ChatReply {
  const p = m.payload ?? {};
  return {
    company: { orgNumber: company?.orgNumber ?? '', legalName: company?.legalName ?? '' },
    answer: m.content,
    citations: [],
    sources: [],
    coverage: [],
    search: { state: 'not_used', note: '' },
    origin: 'none',
    generatedAt: m.createdAt,
    ...p,
    kind: (p.kind ?? m.kind ?? 'model') as ChatReply['kind'],
  } as ChatReply;
}

export default function ChatPage() {
  const { threadId } = useParams();
  const wide = useMediaQuery('(min-width: 861px)');
  const [historyOpen, setHistoryOpen] = useState(wide);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ['chat-threads'], queryFn: () => api.chat.threads.list(), staleTime: 5_000 });

  useEffect(() => setHistoryOpen(wide), [wide]);

  const goNew = () => {
    navigate('/chat');
    if (!wide) setHistoryOpen(false);
    requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('.chat-main textarea')?.focus());
  };
  const rename = async (id: string, title: string) => {
    await api.chat.threads.rename(id, title);
    await qc.invalidateQueries({ queryKey: ['chat-threads'] });
    await qc.invalidateQueries({ queryKey: ['chat-thread', id] });
  };
  const remove = async (id: string) => {
    await api.chat.threads.remove(id);
    qc.removeQueries({ queryKey: ['chat-thread', id] });
    await qc.invalidateQueries({ queryKey: ['chat-threads'] });
    if (id === threadId) navigate('/chat', { replace: true });
  };
  const active = list.data?.find((t) => t.id === threadId);

  return (
    <div className="chat-page" data-history={historyOpen ? 'open' : 'closed'} data-testid="chat-page">
      {historyOpen && !wide && <button type="button" className="chat-scrim" aria-label="Close chat history" onClick={() => setHistoryOpen(false)} />}
      <div className="chat-history-wrap" hidden={!historyOpen}>
        <ChatHistory
          threads={list.data ?? []}
          loading={list.isLoading}
          error={list.isError ? 'Conversations could not be loaded.' : null}
          activeId={threadId}
          onNew={goNew}
          onRename={rename}
          onDelete={remove}
          onCollapse={() => setHistoryOpen(false)}
          onNavigate={() => !wide && setHistoryOpen(false)}
        />
      </div>
      <section className="chat-main" aria-label="AI Chat">
        <header className="chat-bar">
          {!historyOpen && (
            <button type="button" className="btn btn--ghost btn--icon btn--sm" onClick={() => setHistoryOpen(true)} aria-label="Show chat history" title="Show history">
              <PanelLeftOpen aria-hidden />
            </button>
          )}
          <div className="chat-bar__title" title={active?.title}>
            {threadId ? (active?.title ?? 'Conversation') : 'New chat'}
          </div>
          {active?.company && (
            <span className="chat-bar__company t-xs" title="Every answer in this conversation is about this company only">
              {active.company.legalName} · <span className="t-mono">{formatOrgNumber(active.company.orgNumber)}</span>
            </span>
          )}
        </header>
        {threadId ? <Conversation key={threadId} threadId={threadId} /> : <Landing onStart={(seed) => navigate(`/chat/${newId()}`, { state: { seed } })} />}
      </section>
    </div>
  );
}

function Landing({ onStart }: { onStart: (seed: Seed) => void }) {
  const uid = useId();
  const [params] = useSearchParams();
  const [draft, setDraft] = useState('');
  const ref = useRef<HTMLTextAreaElement>(null);
  const org = /^\d{9}$/.test(params.get('org') ?? '') ? params.get('org')! : undefined;
  useEffect(() => ref.current?.focus(), []);
  const send = () => {
    const q = draft.trim();
    if (!q || q.length > MAX_QUESTION) return;
    onStart({ messageId: newId(), question: q, orgNumber: org });
  };
  return (
    <div className="chat-landing" data-testid="chat-landing">
      <div className="chat-landing__inner">
        <CognisLogo compact decorative height={112} className="chat-landing__logo" />
        <h1 className="chat-landing__h">Ask COGNIS</h1>
        <p className="chat-landing__sub">Questions about one Norwegian company at a time, answered only from public sources — each statement shows the source it came from.</p>
        <Composer
          id={`${uid}-q`}
          large
          value={draft}
          onChange={setDraft}
          onSend={send}
          inputRef={ref}
          busy={false}
          max={MAX_QUESTION}
          label="Your question"
          placeholder="Name a company or its 9-digit organisation number, then ask…"
          hint="Enter to send, Shift+Enter for a new line. If the name is ambiguous you will be asked to pick the exact company."
        />
        <div className="chat-starters" role="group" aria-label="Starter prompts">
          {STARTERS.map((s) => (
            <button
              key={s.title}
              type="button"
              className="askai-prompt"
              onClick={() => {
                setDraft(s.text);
                ref.current?.focus();
                requestAnimationFrame(() => ref.current?.setSelectionRange(s.text.length, s.text.length));
              }}
            >
              <strong>{s.title}</strong>
              <span className="t-xs">{s.text.trim()} …</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function Conversation({ threadId }: { threadId: string }) {
  const uid = useId();
  const loc = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const seed = (loc.state as { seed?: Seed } | null)?.seed;
  const [fresh, setFresh] = useState(!!seed); // a brand-new id: the server does not know it yet
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState<Pending | null>(null);
  const created = useRef(false); // this conversation already exists on the server: a failed answer and its retry must not create it again
  const logRef = useRef<HTMLDivElement>(null);
  // follow new content only while the reader is at the bottom (or has just sent something); never yank someone who scrolled up to read
  const follow = useRef(true);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const q = useQuery<ChatThread>({ queryKey: ['chat-thread', threadId], queryFn: () => api.chat.threads.get(threadId), enabled: !fresh, retry: false });
  const thread = q.data;
  const busy = !!pending && !pending.error;

  const run = useCallback(
    async (p: Pending) => {
      setPending((cur) => ({ ...p, ...(cur?.messageId === p.messageId ? { steps: cur.steps } : {}), error: undefined }));
      try {
        if (!created.current && !qc.getQueryData(['chat-thread', threadId])) await api.chat.threads.create({ id: threadId, orgNumber: p.orgNumber });
        created.current = true;
        const res = await api.chat.threads.ask({
          threadId,
          messageId: p.messageId,
          question: p.question,
          orgNumber: p.orgNumber,
          fresh: p.fresh,
          retryOf: p.retryOf,
          onProgress: (step) => setPending((cur) => (cur && cur.messageId === p.messageId ? { ...cur, steps: [...cur.steps, step] } : cur)),
        });
        await qc.invalidateQueries({ queryKey: ['chat-threads'] });
        if (res.switchedFromThreadId) {
          // the question belonged to another company: it was answered in its own new conversation, and this one stays clean
          await qc.invalidateQueries({ queryKey: ['chat-thread', res.switchedFromThreadId] });
          setPending(null);
          navigate(`/chat/${res.threadId}`, { replace: false });
          return;
        }
        qc.setQueryData<ChatThread>(['chat-thread', threadId], (old) => {
          const base: ChatThread = old ?? { ...res.thread, messages: [] };
          const keep = base.messages.filter((m) => m.id !== res.assistantMessage.id && !(m.kind === 'clarification' && m.payload?.waitingFor === res.userMessage.id));
          // an answer to a question already in the conversation (a picked company, or "Research more") goes after it; it never moves the question
          const known = keep.some((m) => m.id === res.userMessage.id);
          return { ...base, ...res.thread, messages: known ? [...keep, res.assistantMessage] : [...keep, res.userMessage, res.assistantMessage] };
        });
        setPending(null);
        setFresh(false);
        void qc.invalidateQueries({ queryKey: ['chat-thread', threadId] });
      } catch (error) {
        setPending((cur) => (cur && cur.messageId === p.messageId ? { ...cur, error } : cur));
      }
    },
    [navigate, qc, threadId],
  );

  const send = (question: string, extra: Partial<Pending> = {}) => {
    const text = question.trim();
    if (!text || busy || text.length > MAX_QUESTION) return;
    follow.current = true; // the reader just asked something: show it and what comes back
    setDraft('');
    void run({ messageId: newId(), question: text, steps: [], showQuestion: true, ...extra });
  };

  // a conversation started from the landing page sends its first message once, then forgets the one-off route state
  const started = useRef(false);
  useEffect(() => {
    if (!seed || started.current) return;
    started.current = true;
    void run({ messageId: seed.messageId, question: seed.question, orgNumber: seed.orgNumber, steps: [], showQuestion: true });
    navigate(loc.pathname, { replace: true, state: null });
  }, [seed, run, navigate, loc.pathname]);

  const messages = thread?.messages ?? [];
  const seenCount = useRef(0);
  const onLogScroll = () => {
    const el = logRef.current;
    if (el) follow.current = isNearBottom(el);
  };
  useLayoutEffect(() => {
    const el = logRef.current;
    if (!el) return;
    const added = messages.length > seenCount.current && seenCount.current > 0;
    seenCount.current = messages.length;
    const last = el.querySelector('.chat-log__inner')?.lastElementChild as HTMLElement | null;
    const newAnswer = added && last && !pending && last.classList.contains('askai-msg--bot') ? { offsetTop: last.offsetTop, offsetHeight: last.offsetHeight } : null;
    const top = nextScrollTop(el, { follow: follow.current, newAnswer });
    if (top != null) el.scrollTop = top;
  }, [messages.length, pending?.steps.length, pending?.error, pending]);

  const lastBot = [...messages].reverse().find((m) => m.role === 'assistant' && m.kind !== 'context_notice');
  // "Research more": the same question again with live sources. Offered on the latest answer when current sources were not (or could not be) read for it
  const researchMore = (m: ThreadMessage) => {
    const at = messages.findIndex((x) => x.id === m.id);
    const user = [...messages.slice(0, at)].reverse().find((x) => x.role === 'user');
    if (!user || busy) return;
    void run({ messageId: user.id, question: user.content, retryOf: user.id, fresh: true, steps: [], showQuestion: false });
  };
  const pickCompany = (m: ThreadMessage, c: ChatCandidate) => {
    const waiting = m.payload?.waitingFor;
    const user = messages.find((x) => x.id === waiting);
    if (!waiting || !user) return;
    void run({ messageId: waiting, question: user.content, orgNumber: c.orgNumber, retryOf: waiting, steps: [], showQuestion: false });
  };

  if (q.isError && !pending) {
    const gone = q.error instanceof ApiError && q.error.code === 'not_found';
    return (
      <div className="chat-landing">
        <div className="chat-landing__inner">
          {gone ? (
            <>
              <MessageSquareText aria-hidden className="chat-gone" />
              <h2 className="chat-landing__h chat-landing__h--sm">This conversation is not available</h2>
              <p className="chat-landing__sub">It may have been deleted. Your other conversations are unchanged.</p>
              <Link className="btn btn--primary" to="/chat">
                Start a new chat <ArrowRight aria-hidden />
              </Link>
            </>
          ) : (
            <ErrorState error={q.error} title="This conversation could not be loaded" onRetry={() => q.refetch()} />
          )}
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="chat-log" ref={logRef} onScroll={onLogScroll} role="log" aria-live="polite" aria-relevant="additions text" aria-label="Conversation" data-testid="chat-log">
        <div className="chat-log__inner">
          {q.isLoading && !fresh && (
            <div className="stack" style={{ gap: 10 }} aria-busy="true">
              <Skeleton h={34} w="50%" />
              <Skeleton h={90} r={10} />
            </div>
          )}
          {messages.map((m) => {
            if (m.role === 'user') {
              if (m.payload?.movedTo) return <UserBubble key={m.id} text={m.content} />;
              return <UserBubble key={m.id} text={m.content} />;
            }
            if (m.kind === 'context_notice') {
              return (
                <div key={m.id} className="notice notice--info askai-switch" role="status">
                  <CircleAlert aria-hidden />
                  <div className="stack" style={{ gap: 6 }}>
                    <span>{m.content}</span>
                    {m.payload?.movedTo && (
                      <Link className="btn btn--sm" to={`/chat/${m.payload.movedTo}`}>
                        Open the new chat <ArrowRight aria-hidden />
                      </Link>
                    )}
                  </div>
                </div>
              );
            }
            if (m.kind === 'error') {
              return (
                <div key={m.id} className="askai-msg askai-msg--bot">
                  <div className="notice notice--warn" role="alert">
                    <CircleAlert aria-hidden />
                    <span>{m.content}</span>
                  </div>
                </div>
              );
            }
            const reply = toReply(m, thread?.company ?? null);
            const isLast = lastBot?.id === m.id && !busy;
            return (
              <Answer
                key={m.id}
                reply={reply}
                turnId={`${uid}-${m.id}`}
                canFresh={isLast && !!thread?.company && reply.origin !== 'fresh' && ['answer', 'model', 'model_partial', 'evidence_only', 'limitation'].includes(String(reply.kind)) && ['not_used', 'timeout', 'unavailable'].includes(reply.search?.state ?? '')}
                onFresh={() => researchMore(m)}
                onPick={reply.kind === 'clarification' ? (c) => pickCompany(m, c) : undefined}
                followUps={isLast ? reply.followUps : undefined}
                onFollowUp={(text) => send(text)}
              />
            );
          })}
          {pending?.showQuestion && !messages.some((m) => m.id === pending.messageId) && <UserBubble text={pending.question} />}
          {pending && !pending.error && <Progress steps={pending.steps} label="Resolving the company and reading the sources…" />}
          {pending?.error != null && <TurnError error={pending.error} onRetry={() => void run({ ...pending })} />}
        </div>
      </div>

      <div className="chat-dock">
        <Composer
          id={`${uid}-q`}
          value={draft}
          onChange={setDraft}
          onSend={() => send(draft)}
          inputRef={inputRef}
          busy={busy}
          max={MAX_QUESTION}
          label="Your question"
          placeholder={thread?.company ? `Ask about ${thread.company.legalName}` : 'Ask a follow-up…'}
        />
      </div>
    </>
  );
}

function UserBubble({ text }: { text: string }) {
  return <div className="askai-msg askai-msg--user">{text}</div>;
}

function TurnError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const e = error instanceof ApiError ? error : null;
  return (
    <div className="askai-msg askai-msg--bot">
      <div className="notice notice--warn" role="alert">
        <CircleAlert aria-hidden />
        <div className="stack" style={{ gap: 6 }}>
          <strong>{e?.code === 'rate_limited' ? 'Too many questions' : 'The answer could not be produced'}</strong>
          <span>{e?.message ?? 'Something went wrong. Nothing was invented in its place.'}</span>
          <div>
            <button className="btn btn--sm" onClick={onRetry}>
              <RotateCcw aria-hidden /> Retry
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export { ContextNotice };
