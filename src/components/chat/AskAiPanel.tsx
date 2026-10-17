import { Fragment, useCallback, useEffect, useId, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { CircleAlert, RotateCcw, Sparkles, SquarePen, X } from 'lucide-react';
import { api, ApiError } from '@/api';
import type { ChatContext, ChatMessage, ChatProgress, ChatReply } from '@/types';
import { BrandMark } from '@/components/common/BrandMark';
import { ErrorState } from '@/components/common/ErrorState';
import { Skeleton } from '@/components/common/Skeleton';
import { formatOrgNumber } from '@/utils/format';
import { Answer, CoverageList, Composer, COVERAGE_LABEL, Progress, splitCitations } from './ChatParts';
import './ask-ai.css';

export { COVERAGE_LABEL, splitCitations };

interface Turn {
  id: number;
  question: string;
  status: 'pending' | 'done' | 'error';
  reply?: ChatReply;
  error?: unknown;
  fresh?: boolean;
  steps?: ChatProgress[];
}

/** The earlier completed turns, in the shape the backend accepts. Failed or pending turns are never sent. */
export function historyOf(turns: Turn[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  for (const t of turns) {
    if (t.status !== 'done' || !t.reply) continue;
    out.push({ role: 'user', content: t.question }, { role: 'assistant', content: t.reply.answer });
  }
  return out;
}

export function AskAiPanel({
  orgNumber,
  legalName,
  logoUrl,
  onClose,
  origin,
  suggestions: extraSuggestions,
}: {
  orgNumber: string;
  legalName: string;
  logoUrl?: string;
  onClose: () => void;
  /** Where the panel was opened from, said once under the greeting (e.g. "the research run that just finished"). */
  origin?: string;
  /** Extra starter questions shown before the server's own (deduplicated). */
  suggestions?: string[];
}) {
  const uid = useId();
  const ctx = useQuery<ChatContext>({ queryKey: ['chat-context', orgNumber], queryFn: () => api.chat.context(orgNumber), retry: false, staleTime: 60_000 });
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');
  const seq = useRef(0);
  const logRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const busy = turns.some((t) => t.status === 'pending');
  const max = ctx.data?.capabilities.maxQuestionChars ?? 1000;
  const disabled = ctx.data ? !ctx.data.capabilities.chat : false;

  useEffect(() => {
    inputRef.current?.focus();
  }, []);
  useEffect(() => {
    const el = logRef.current;
    if (el && typeof el.scrollTo === 'function') el.scrollTo({ top: el.scrollHeight });
  }, [turns]);

  const run = useCallback(
    async (id: number, question: string, history: ChatMessage[], fresh: boolean) => {
      try {
        const reply = await api.chat.ask({ orgNumber, question, messages: history, expectedName: legalName, fresh }, (p) =>
          setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, steps: [...(t.steps ?? []), p] } : t))),
        );
        setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, status: 'done', reply, error: undefined } : t)));
      } catch (error) {
        setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, status: 'error', error } : t)));
      }
    },
    [orgNumber, legalName],
  );

  const send = (question: string, fresh = false) => {
    const q = question.trim();
    if (!q || busy || disabled || q.length > max) return;
    const id = ++seq.current;
    const history = historyOf(turns);
    setTurns((ts) => [...ts, { id, question: q, status: 'pending', fresh }]);
    setDraft('');
    void run(id, q, history, fresh);
  };
  const retry = (t: Turn) => {
    if (busy) return;
    const history = historyOf(turns.filter((x) => x.id < t.id));
    setTurns((ts) => ts.map((x) => (x.id === t.id ? { ...x, status: 'pending', error: undefined, steps: [] } : x)));
    void run(t.id, t.question, history, !!t.fresh);
  };
  const reset = () => {
    seq.current += 1000; // late replies from the cleared conversation can no longer match a turn
    setTurns([]);
    setDraft('');
    inputRef.current?.focus();
  };

  const onPanelKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onClose();
    }
  };

  const last = turns.filter((t) => t.status === 'done').at(-1);
  const starters = ctx.data ? [...new Set([...(extraSuggestions ?? []), ...ctx.data.suggestions])].slice(0, 6) : [];

  return (
    <aside id="ask-ai" className="askai" role="complementary" aria-label={`Ask AI about ${legalName}`} onKeyDown={onPanelKey} data-testid="ask-ai-panel">
      <header className="askai-head">
        <BrandMark name={legalName} org={orgNumber} logoUrl={logoUrl} size={36} />
        <div className="askai-id">
          <div className="askai-title">
            <Sparkles aria-hidden /> Ask AI
          </div>
          <div className="askai-company" title={legalName}>
            <strong>{legalName}</strong>
            <span className="t-mono t-muted"> · {formatOrgNumber(orgNumber)}</span>
          </div>
        </div>
        <button className="btn btn--sm btn--icon" onClick={reset} disabled={!turns.length} aria-label="Start a new chat" title="New chat">
          <SquarePen aria-hidden />
        </button>
        <button className="btn btn--sm btn--icon" onClick={onClose} aria-label="Close Ask AI" title="Close">
          <X aria-hidden />
        </button>
      </header>

      <div className="askai-log" ref={logRef} role="log" aria-live="polite" aria-relevant="additions text" aria-label="Conversation">
        {ctx.isLoading && (
          <div className="stack" style={{ gap: 10 }} aria-busy="true">
            <Skeleton h={18} w="70%" />
            <Skeleton h={54} r={10} />
            <Skeleton h={34} r={10} />
          </div>
        )}
        {ctx.isError && <ErrorState error={ctx.error} title="Ask AI could not be loaded" onRetry={() => ctx.refetch()} compact />}
        {disabled && (
          <div className="notice notice--warn" role="status">
            <CircleAlert aria-hidden />
            <div className="stack" style={{ gap: 4 }}>
              <strong>Ask AI is unavailable</strong>
              <span>It is switched off on this server. The saved research on this page is still available.</span>
            </div>
          </div>
        )}

        {ctx.data && !disabled && (
          <div className="askai-msg askai-msg--bot">
            <p>
              Hi. I answer questions about <strong>{legalName}</strong> only, from its saved public sources, and I show which source supports each statement. If the sources do not say, I will tell you.
              {origin ? <> Opened from {origin}.</> : null}
            </p>
            {!turns.length && (
              <>
                <div className="askai-suggest" role="group" aria-label="Suggested questions">
                  {starters.map((s) => (
                    <button key={s} className="askai-prompt askai-prompt--compact" onClick={() => send(s)} disabled={busy}>
                      {s}
                    </button>
                  ))}
                </div>
                <CoverageList rows={ctx.data.coverage} id={`${uid}-cov`} />
              </>
            )}
          </div>
        )}

        {turns.map((t) => (
          <Fragment key={t.id}>
            <div className="askai-msg askai-msg--user">{t.question}</div>
            {t.status === 'pending' && <Progress steps={t.steps ?? []} label={t.fresh ? 'Checking for new information…' : 'Reading the sources…'} />}
            {t.status === 'error' && <TurnError turn={t} onRetry={() => retry(t)} />}
            {t.status === 'done' && t.reply && (
              <Answer
                reply={t.reply}
                turnId={`${uid}-${t.id}`}
                canFresh={!!ctx.data?.capabilities.freshResearch && !t.fresh && last?.id === t.id && !busy}
                onFresh={() => send(t.question, true)}
                followUps={last?.id === t.id && !busy ? (t.reply.followUps?.length ? t.reply.followUps : []) : []}
                onFollowUp={(q) => send(q)}
              />
            )}
          </Fragment>
        ))}

      </div>

      <Composer
        id={`${uid}-q`}
        value={draft}
        onChange={setDraft}
        onSend={() => send(draft)}
        placeholder={disabled ? 'Ask AI is unavailable' : `Ask about ${legalName}`}
        max={max}
        busy={busy}
        disabled={disabled}
        label={`Your question about ${legalName}`}
        inputRef={inputRef}
      />
    </aside>
  );
}

function TurnError({ turn, onRetry }: { turn: Turn; onRetry: () => void }) {
  const e = turn.error instanceof ApiError ? turn.error : null;
  const mismatch = e?.code === 'ambiguous';
  return (
    <div className="askai-msg askai-msg--bot">
      <div className="notice notice--warn" role="alert">
        <CircleAlert aria-hidden />
        <div className="stack" style={{ gap: 6 }}>
          <strong>{mismatch ? 'Wrong company' : e?.code === 'rate_limited' ? 'Too many questions' : 'The answer could not be produced'}</strong>
          <span>{e?.message ?? 'Something went wrong. Nothing was invented in its place.'}</span>
          {!mismatch && (
            <div>
              <button className="btn btn--sm" onClick={onRetry}>
                <RotateCcw aria-hidden /> Retry
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
