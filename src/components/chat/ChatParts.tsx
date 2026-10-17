/** Presentational pieces shared by the Ask AI side panel and the AI Chat page, so both render an answer exactly the same way. */
import { Fragment, useState } from 'react';
import { ArrowUp, CircleAlert, ExternalLink as ExtIcon, Search, X } from 'lucide-react';
import { ExternalLink } from '@/components/common/ExternalLink';
import type { ChatCandidate, ChatComparison, ChatCoverageRow, ChatProgress, ChatReply, ChatSource, CheckedArea, CoverageStatus, ContextSwitch } from '@/types';
import { formatOrgNumber } from '@/utils/format';
import { cn } from '@/utils/cn';
import { ChatLoader } from './ChatLoader';

/** The five statuses the product uses, worded exactly as the research pages word them. */
export const COVERAGE_LABEL: Record<CoverageStatus, string> = {
  verified: 'Verified',
  no_public_results_found: 'No public results found in checked sources',
  not_reported: 'Not reported',
  not_checked: 'Not checked',
  unavailable: 'Unavailable',
};
export const COVERAGE_TONE: Record<CoverageStatus, string> = {
  verified: 'pill--ok',
  no_public_results_found: 'pill--info',
  not_reported: 'pill--info',
  not_checked: 'pill--warn',
  unavailable: 'pill--err',
};

type Part = { text: string } | { n: number };

/** Splits "text [1][2] more" into text and citation numbers; only numbers that exist in `sources` become citations. */
export function splitCitations(text: string, sources: ChatSource[]): Part[] {
  const known = new Set(sources.map((s) => s.n));
  const out: Part[] = [];
  let last = 0;
  for (const m of text.matchAll(/\[(\d{1,3})\]/g)) {
    const n = Number(m[1]);
    if (!known.has(n)) continue;
    if (m.index! > last) out.push({ text: text.slice(last, m.index) });
    out.push({ n });
    last = m.index! + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  return out;
}

/** A source cited twice in a row ("[1][1]") is shown once. */
export function dedupeAdjacent(parts: Part[]): Part[] {
  const out: Part[] = [];
  for (const p of parts) {
    const prev = out.at(-1);
    if ('n' in p && prev && 'n' in prev && prev.n === p.n) continue;
    out.push(p);
  }
  return out;
}

export function CoverageList({ rows, id, label = 'What was checked' }: { rows: Array<ChatCoverageRow | CheckedArea>; id: string; label?: string }) {
  if (!rows.length) return null;
  return (
    <details className="askai-cov" id={id}>
      <summary>{label}</summary>
      <ul>
        {rows.map((r) => (
          <li key={r.area}>
            <div className="askai-cov-row">
              <span>{r.label}</span>
              <span className={cn('pill pill--sm', COVERAGE_TONE[r.status])}>{COVERAGE_LABEL[r.status] ?? r.status}</span>
            </div>
            <div className="t-xs t-muted">
              {'ranNow' in r && r.ranNow ? 'Checked just now. ' : ''}
              {r.note}
            </div>
          </li>
        ))}
      </ul>
    </details>
  );
}

const fmtNum = (v: number, cur: string) => `${cur} ${new Intl.NumberFormat('en-GB', { maximumFractionDigits: 0 }).format(v)}`;
const signed = (v: number) => `${v < 0 ? '−' : '+'}${new Intl.NumberFormat('en-GB', { maximumFractionDigits: 0 }).format(Math.abs(v))}`;

export function ComparisonTable({ data }: { data: ChatComparison }) {
  if (!data.rows.length) return null;
  return (
    <div className="askai-cmp" role="region" aria-label="Period comparison" tabIndex={0}>
      <table>
        <caption className="t-xs t-muted">
          Ranked by {data.rankedBy === 'amount' ? 'absolute change' : 'percentage change'} · {data.periods.join(' → ')}
        </caption>
        <thead>
          <tr>
            <th scope="col">Metric</th>
            <th scope="col">{data.rows[0].previous.period}</th>
            <th scope="col">{data.rows[0].latest.period}</th>
            <th scope="col">Change</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r) => (
            <tr key={`${r.metric}-${r.scope}`}>
              <th scope="row">
                {r.label}
                {r.scope === 'group' && <span className="t-xs t-muted"> · group</span>}
              </th>
              <td>{fmtNum(r.previous.value, r.currency)}</td>
              <td>{fmtNum(r.latest.value, r.currency)}</td>
              <td title={r.formula}>
                {signed(r.absoluteChange)}
                <span className="t-xs t-muted"> {r.percentChange == null ? '(n/m)' : `(${r.percentChange < 0 ? '−' : '+'}${Math.abs(r.percentChange).toFixed(2)}%)`}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <details className="askai-formulas">
        <summary>How each change was calculated</summary>
        <ul>
          {data.rows.map((r) => (
            <li key={`f-${r.metric}-${r.scope}`} className="t-xs">
              <strong>{r.label}:</strong> {r.formula}
            </li>
          ))}
        </ul>
      </details>
      {data.omitted.length > 0 && (
        <details className="askai-formulas">
          <summary>Left out of the comparison ({data.omitted.length})</summary>
          <ul>
            {data.omitted.map((o) => (
              <li key={o} className="t-xs">
                {o}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export function ContextNotice({ info }: { info: ContextSwitch }) {
  return (
    <div className="notice notice--info askai-switch" role="status" data-testid="context-switch">
      <CircleAlert aria-hidden />
      <div className="stack" style={{ gap: 2 }}>
        <strong>New company: {info.to.legalName}</strong>
        <span>{info.message}</span>
      </div>
    </div>
  );
}

function sourceMeta(s: ChatSource): string {
  const bits = [s.sourceLabel];
  if (s.reportingPeriod) bits.push(`period ${s.reportingPeriod}`);
  if (s.accountingScope) bits.push(s.accountingScope === 'group' ? 'consolidated' : s.accountingScope === 'company' ? 'company-only' : s.accountingScope);
  if (s.publishedAt) bits.push(`published ${s.publishedAt.slice(0, 10)}`);
  if (s.retrievedAt) bits.push(`retrieved ${s.retrievedAt.slice(0, 10)}`);
  bits.push(s.origin === 'fresh' ? 'found just now' : 'saved research');
  return bits.join(' · ');
}

/** What a source link really is — never a register data record presented as the filing. */
export const LINK_KIND: Record<string, string> = {
  filing_document: 'Direct link: the filed copy of the annual accounts (listed by Regnskapsregisteret)',
  register_record: 'Link: the register’s data record — not a copy of the filing',
};

/** The sources are exactly the citations used in this answer, each listed once. */
export function SourceList({ sources, turnId, open, onOpen }: { sources: ChatSource[]; turnId: string; open: number | null; onOpen: (n: number | null) => void }) {
  if (!sources.length) return null;
  const domains = [...new Set(sources.map((s) => hostOf(s.url)).filter(Boolean))] as string[];
  return (
    <section className="askai-sources" aria-label="Sources">
      <h4 className="t-xs t-muted">Sources</h4>
      <ol>
        {sources.map((s) => (
          <li key={s.n} id={`${turnId}-src-${s.n}`} tabIndex={-1} className={cn(open === s.n && 'is-open')}>
            <button type="button" className="askai-src-n" onClick={() => onOpen(open === s.n ? null : s.n)} aria-expanded={open === s.n} aria-label={`Details for source ${s.n}`}>
              {s.n}
            </button>
            <div className="askai-src-body">
              {s.url ? <ExternalLink href={s.url}>{s.title}</ExternalLink> : <span>{s.title}</span>}
              <div className="t-xs t-muted">{sourceMeta(s)}</div>
              {s.eventStatus && <div className="t-xs">Status: {s.eventStatus}</div>}
              {s.significance && <div className="t-xs t-muted">{s.significance}</div>}
              {s.linkKind && LINK_KIND[s.linkKind] && (s.linkKind === 'filing_document' || s.reportingPeriod) && (
                <div className="t-xs askai-linkkind" data-link-kind={s.linkKind}>
                  {LINK_KIND[s.linkKind]}
                </div>
              )}
              {s.recordUrl && (
                <div className="t-xs t-muted">
                  Figures read from: <ExternalLink href={s.recordUrl}>the Regnskapsregisteret data record</ExternalLink>
                </div>
              )}
              {s.uncertainty && <div className="t-xs askai-unc">{s.uncertainty}</div>}
              {open === s.n && s.excerpt && <blockquote className="t-xs">{s.excerpt}</blockquote>}
            </div>
          </li>
        ))}
      </ol>
      {domains.length > 0 && <p className="t-xs t-muted askai-domains">Domains used: {domains.join(', ')}</p>}
    </section>
  );
}

function hostOf(url?: string | null): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return null;
  }
}

export function Answer({
  reply,
  turnId,
  canFresh,
  onFresh,
  onPick,
  onFollowUp,
  followUps,
}: {
  reply: ChatReply;
  turnId: string;
  canFresh?: boolean;
  onFresh?: () => void;
  onPick?: (c: ChatCandidate) => void;
  onFollowUp?: (q: string) => void;
  followUps?: string[];
}) {
  const [open, setOpen] = useState<number | null>(null);
  const cited = reply.citations ?? [];
  const known = reply.sources?.length ? reply.sources : cited;
  const focus = (n: number) => {
    setOpen(n);
    const el = document.getElementById(`${turnId}-src-${n}`);
    if (el) {
      el.scrollIntoView?.({ block: 'nearest' });
      el.focus();
    }
  };
  const paragraphs = (reply.answer ?? '').split(/\n+/).filter((l) => l.trim());
  const checked = reply.checked?.length ? reply.checked : reply.coverage;
  return (
    <div className={cn('askai-msg askai-msg--bot', reply.kind === 'clarification' && 'is-clarify')} data-kind={reply.kind}>
      {reply.contextSwitch && <ContextNotice info={reply.contextSwitch} />}
      <div className="askai-answer">
        {paragraphs.map((para, pi) => (
          <p key={pi}>
            {dedupeAdjacent(splitCitations(para, known)).map((p, i) =>
              'n' in p ? (
                <button key={i} type="button" className="askai-cite" onClick={() => focus(p.n)} aria-label={`Source ${p.n}`} title={`Source ${p.n}: ${known.find((s) => s.n === p.n)?.title ?? ''}`}>
                  {p.n}
                </button>
              ) : (
                <Fragment key={i}>{p.text}</Fragment>
              ),
            )}
          </p>
        ))}
      </div>

      {reply.comparison && <ComparisonTable data={reply.comparison} />}

      {reply.candidates && reply.candidates.length > 0 && (
        <div className="askai-candidates" role="group" aria-label="Matching companies">
          {reply.candidates.map((c) => (
            <button key={c.orgNumber} type="button" className="askai-prompt" onClick={() => onPick?.(c)} disabled={!onPick}>
              <strong>{c.legalName}</strong>
              <span className="t-xs">{formatOrgNumber(c.orgNumber)}{c.municipality ? ` · ${c.municipality}` : ''}</span>
            </button>
          ))}
        </div>
      )}

      {['unavailable', 'timeout', 'no_results', 'not_configured'].includes(reply.search.state) && (
        <div className={cn('notice askai-note', reply.search.state === 'no_results' ? 'notice--info' : 'notice--warn')} role="status">
          <Search aria-hidden />
          <span>{reply.search.note}</span>
        </div>
      )}
      {reply.modelNote && reply.kind !== 'clarification' && <p className="t-xs t-muted askai-meta">{reply.modelNote}</p>}
      {reply.provenanceNote && <p className="t-xs t-muted askai-meta askai-provenance">{reply.provenanceNote}</p>}
      {!!reply.unsupported?.length && reply.kind === 'model' && <p className="t-xs t-muted askai-meta">Not supported by the sources: {reply.unsupported.join(' ')}</p>}

      <SourceList sources={cited} turnId={turnId} open={open} onOpen={setOpen} />
      {reply.kind !== 'clarification' && <CheckedNow search={reply.search} />}

      <div className="askai-foot">
        <CoverageList rows={checked ?? []} id={`${turnId}-cov`} />
        {reply.origin && reply.origin !== 'none' && (
          <span className="t-xs t-muted askai-origin">{reply.origin === 'fresh' ? 'Includes information checked just now.' : 'From saved research (not re-checked for this answer).'}</span>
        )}
        {canFresh && (
          <button className="btn btn--sm" onClick={onFresh}>
            <Search aria-hidden /> Check for new information
          </button>
        )}
      </div>

      {followUps && followUps.length > 0 && onFollowUp && <FollowUps items={followUps} onPick={onFollowUp} />}
    </div>
  );
}

const CHECKED_STATE: Record<string, string> = {
  used: 'used',
  skipped: 'not used (not a permitted source, or not about this company)',
  rejected: 'not used',
  unreadable: 'could not be read',
  nothing_relevant: 'nothing relevant to the question',
  nothing_found: 'nothing found',
  unavailable: 'unavailable',
  not_configured: 'not configured',
};

/**
 * "Sources checked for this answer": only sources that were really read for THIS answer (the register's records and the pages fetched), never search
 * results that were not opened. When nothing was checked, it says why instead of showing an empty list.
 */
export function CheckedNow({ search }: { search: ChatReply['search'] }) {
  const rows = (search.checked ?? []).filter((r) => r.kind !== 'search' && r.state !== 'skipped');
  const web = search.web;
  const empty =
    search.state === 'not_used' || !search.state
      ? 'No current sources were checked for this answer: it is written from the saved research (see “What was checked”).'
      : ['unavailable', 'timeout', 'no_results', 'not_configured'].includes(search.state)
        ? 'No source could be read for this answer: the reason is in the note above.' // the answer already shows the note itself; it is not repeated
        : `No source could be read for this answer. ${search.note ?? ''}`.trim();
  return (
    <details className="askai-checked-now" data-testid="checked-now">
      <summary className="t-xs t-muted">Sources checked for this answer ({rows.length})</summary>
      {rows.length > 0 ? (
        <ul className="t-xs">
          {rows.map((r, i) => (
            <li key={`${r.name}-${r.url ?? i}`} data-state={r.state}>
              {r.url ? <ExternalLink href={r.url}>{r.name}</ExternalLink> : <span>{r.name}</span>}
              <span className="t-muted"> — {CHECKED_STATE[r.state] ?? r.state.replace(/_/g, ' ')}</span>
              {r.reason && <span className="t-muted">: {r.reason}</span>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="t-xs t-muted askai-checked-empty">{empty}</p>
      )}
      {!!web?.searches && (
        <p className="t-xs t-muted">
          Web search: {web.searches} search{web.searches === 1 ? '' : 'es'}, {web.results} result{web.results === 1 ? '' : 's'}
          {web.notOpened ? `; ${web.notOpened} not opened (not a permitted source, or not about this company)` : ''}.
        </p>
      )}
    </details>
  );
}

/** Contextual next questions as compact ivory cards; the whole row can be dismissed and is simply ignored if the user types something else. */
export function FollowUps({ items, onPick }: { items: string[]; onPick: (q: string) => void }) {
  const [hidden, setHidden] = useState(false);
  if (hidden || !items.length) return null;
  return (
    <div className="askai-follow" role="group" aria-label="Suggested follow-up questions">
      <div className="askai-follow-head">
        <span className="t-xs t-muted">Follow up</span>
        <button type="button" className="askai-x" onClick={() => setHidden(true)} aria-label="Dismiss follow-up suggestions" title="Dismiss">
          <X aria-hidden />
        </button>
      </div>
      <div className="askai-follow-list">
        {items.map((q) => (
          <button key={q} type="button" className="askai-prompt askai-prompt--compact" onClick={() => onPick(q)}>
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Truthful progress (see ChatLoader): a few plain-language stages that follow what the server reports, with per-source detail on request. */
export function Progress({ steps, label }: { steps: ChatProgress[]; label: string }) {
  return <ChatLoader steps={steps} label={label} />;
}

export function Composer({
  id,
  value,
  onChange,
  onSend,
  placeholder,
  max,
  busy,
  disabled,
  label,
  inputRef,
  large,
  hint,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  placeholder: string;
  max: number;
  busy: boolean;
  disabled?: boolean;
  label: string;
  inputRef?: React.Ref<HTMLTextAreaElement>;
  large?: boolean;
  hint?: string;
}) {
  const over = value.length > max;
  return (
    <form
      className={cn('askai-form chat-composer', large && 'chat-composer--large', busy && 'is-busy')}
      onSubmit={(e) => {
        e.preventDefault();
        onSend();
      }}
    >
      <label className="sr-only" htmlFor={id}>
        {label}
      </label>
      <textarea
        id={id}
        ref={inputRef}
        className="textarea chat-composer__input"
        rows={large ? 3 : 2}
        value={value}
        maxLength={max + 200}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            onSend();
          }
        }}
        aria-describedby={`${id}-hint`}
        aria-invalid={over}
      />
      <button className="chat-composer__send" type="submit" disabled={busy || disabled || !value.trim() || over} aria-label="Send question" aria-busy={busy}>
        {busy ? <span className="chat-composer__spin" aria-hidden /> : <ArrowUp aria-hidden />}
      </button>
      <p id={`${id}-hint`} className={cn('askai-hint t-xs', over ? 'is-over' : 't-muted')}>
        {over ? `Too long: ${value.length}/${max} characters.` : (hint ?? 'Enter to send, Shift+Enter for a new line. Answers use public sources only.')}
      </p>
    </form>
  );
}

export function ExternalHint() {
  return <ExtIcon aria-hidden />;
}
