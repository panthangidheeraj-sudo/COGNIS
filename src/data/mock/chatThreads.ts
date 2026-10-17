/**
 * MOCK BACKEND — AI Chat conversations for demo mode.
 * Threads are kept in this browser's localStorage (honestly: demo data, not a server). The behaviour mirrors the real backend:
 * the thread's company is fixed once known, another company starts a NEW thread with a notice, an unknown company asks for clarification,
 * and sending the same message id twice never creates a second message.
 */
import { ApiError } from '@/api/http';
import type { ChatCandidate, ChatProgress, ChatReply, ChatThread, ChatThreadSummary, ThreadAskInput, ThreadAskResult, ThreadMessage } from '@/types';

const KEY = 'cognis.mock.chat.threads.v1';
const MAX_THREADS = 300;

export interface MockCompany {
  orgNumber: string;
  legalName: string;
}
export interface MockChatDeps {
  /** Every company the demo knows. */
  companies: () => MockCompany[];
  reply: (orgNumber: string, question: string) => ChatReply | null;
  wait: (ms: number, signal?: AbortSignal) => Promise<void>;
  now: () => string;
}

type Store = Record<string, ChatThread>;
let memory: Store | null = null;

function read(): Store {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as Store;
  } catch {
    /* storage blocked: fall back to memory */
  }
  return memory ?? {};
}
function write(s: Store) {
  memory = s;
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* kept in memory for this tab */
  }
}

/** Test helper: forget every demo thread. */
export function resetMockThreads() {
  memory = null;
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

const clean = (t: string) => t.replace(/\s+/g, ' ').trim();
const STOP = /^(what|how|who|when|where|why|is|are|does|do|did|can|could|please|show|tell|give|compare|check|which|hi|hello|hey|ask)\b/i;

/** A title from the first meaningful message, never a greeting or an empty string. */
export function makeTitle(question: string, legalName?: string | null): string {
  let t = clean(question).replace(/^(hi|hello|hey)[,!. ]+/i, '').replace(/[?!.]+$/, '');
  t = t.charAt(0).toUpperCase() + t.slice(1);
  if (t.length < 3 || (STOP.test(t) && t.split(' ').length < 2)) return legalName ? `About ${legalName}` : 'New chat';
  if (t.length > 56) t = t.slice(0, 55).replace(/\s+\S*$/, '').replace(/[,;:]+$/, '') + '…';
  return t;
}

function summary(t: ChatThread): ChatThreadSummary {
  const { messages, ...rest } = t;
  const last = [...messages].reverse().find((m) => m.kind !== 'context_notice');
  return { ...rest, messageCount: messages.length, preview: last ? clean(last.content).slice(0, 90) : '' };
}

let counter = 0;
const uid = () => `m${Date.now().toString(36)}${(counter++).toString(36)}${Math.random().toString(36).slice(2, 8)}`;

export function createMockThreads(deps: MockChatDeps) {
  const find = (question: string, hint?: string): { found?: MockCompany; candidates: ChatCandidate[] } => {
    const all = deps.companies();
    const digits = (hint ?? question.replace(/\s/g, '').match(/\d{9}/)?.[0]) ?? '';
    if (/^\d{9}$/.test(digits)) {
      const c = all.find((x) => x.orgNumber === digits);
      return c ? { found: c, candidates: [] } : { candidates: [] };
    }
    const q = question.toLowerCase();
    const hits = all.filter((c) => {
      const base = c.legalName.toLowerCase().replace(/\b(asa|as)\b/g, '').trim();
      return base.length > 2 && q.includes(base);
    });
    if (hits.length === 1) return { found: hits[0], candidates: [] };
    return { candidates: hits.slice(0, 6).map((c) => ({ orgNumber: c.orgNumber, legalName: c.legalName })) };
  };

  const progress = async (input: ThreadAskInput, steps: ChatProgress[]) => {
    for (const s of steps) {
      input.onProgress?.(s);
      await deps.wait(140, input.signal);
    }
  };

  return {
    async list(): Promise<ChatThreadSummary[]> {
      return Object.values(read())
        .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
        .map(summary);
    },
    async get(id: string): Promise<ChatThread> {
      const t = read()[id];
      if (!t) throw new ApiError('not_found', 'That conversation does not exist (it may have been deleted).', 404);
      return structuredClone(t);
    },
    async create(input: { id: string; orgNumber?: string; title?: string }): Promise<ChatThreadSummary> {
      const s = read();
      if (s[input.id]) return summary(s[input.id]);
      const now = deps.now();
      const company = input.orgNumber ? deps.companies().find((c) => c.orgNumber === input.orgNumber) : undefined;
      const ids = Object.keys(s);
      if (ids.length >= MAX_THREADS) delete s[ids.sort((a, b) => s[a].updatedAt.localeCompare(s[b].updatedAt))[0]];
      s[input.id] = {
        id: input.id,
        title: input.title ?? 'New chat',
        titleEdited: !!input.title,
        createdAt: now,
        updatedAt: now,
        company: company ?? null,
        messageCount: 0,
        preview: '',
        messages: [],
      };
      write(s);
      return summary(s[input.id]);
    },
    async rename(id: string, title: string): Promise<ChatThreadSummary> {
      const s = read();
      const t = s[id];
      if (!t) throw new ApiError('not_found', 'That conversation does not exist (it may have been deleted).', 404);
      const next = clean(title).slice(0, 80);
      if (!next) throw new ApiError('invalid', 'A conversation needs a title.', 400);
      t.title = next;
      t.titleEdited = true;
      write(s);
      return summary(t);
    },
    async remove(id: string): Promise<void> {
      const s = read();
      if (!s[id]) throw new ApiError('not_found', 'That conversation does not exist (it may already be deleted).', 404);
      delete s[id];
      write(s);
    },
    async ask(input: ThreadAskInput): Promise<ThreadAskResult> {
      const s = read();
      const t = s[input.threadId];
      if (!t) throw new ApiError('not_found', 'That conversation does not exist (it may have been deleted).', 404);
      const question = clean(input.question);
      if (!question && !input.retryOf) throw new ApiError('invalid', 'Ask a question.', 400);

      // the same message id answered before: return the stored answer
      const at = t.messages.findIndex((m) => m.id === input.messageId);
      if (at >= 0 && !input.retryOf && t.messages[at + 1]?.role === 'assistant' && t.messages[at + 1].kind !== 'error') {
        return { threadId: t.id, thread: summary(t), userMessage: t.messages[at], assistantMessage: t.messages[at + 1] };
      }
      let userMsg: ThreadMessage;
      let q = question;
      if (input.retryOf) {
        const prior = t.messages.find((m) => m.id === input.retryOf && m.role === 'user');
        if (!prior) throw new ApiError('not_found', 'That message is not part of this conversation.', 404);
        userMsg = prior;
        q = prior.content;
        t.messages = t.messages.filter((m) => !(m.kind === 'clarification' && m.payload?.waitingFor === prior.id));
      } else {
        t.messages = at >= 0 ? t.messages.slice(0, at) : t.messages;
        userMsg = { id: input.messageId, role: 'user', content: question, createdAt: deps.now() };
        if (!t.messages.some((m) => m.role === 'user') && !t.titleEdited) t.title = makeTitle(question, t.company?.legalName);
        t.messages.push(userMsg);
      }
      write(s);

      const named = find(q, input.orgNumber);
      let org = t.company?.orgNumber;
      let target = t;
      let switched: string | undefined;
      if (!org) {
        if (!named.found) {
          const text = named.candidates.length
            ? 'More than one company matches that name. Pick the exact company — COGNIS never guesses.'
            : 'Which company do you mean? Name it exactly, give its 9-digit organisation number, or pick it below. Answers are always about one verified company.';
          const msg: ThreadMessage = {
            id: uid(), role: 'assistant', kind: 'clarification', content: text, createdAt: deps.now(),
            payload: { kind: 'clarification', answer: text, candidates: named.candidates, citations: [], sources: [], coverage: [], search: { state: 'not_used', note: 'No search was made.' }, waitingFor: userMsg.id },
          };
          t.messages.push(msg);
          t.updatedAt = deps.now();
          write(s);
          return { threadId: t.id, thread: summary(t), userMessage: userMsg, assistantMessage: msg };
        }
        t.company = named.found;
        org = named.found.orgNumber;
      } else if (named.found && named.found.orgNumber !== org) {
        // another company: a NEW thread for it; this one gets a notice and stays clean
        const nid = `${t.id.slice(0, 40)}-${uid()}`.slice(0, 64);
        const now = deps.now();
        target = { id: nid, title: makeTitle(q, named.found.legalName), titleEdited: false, createdAt: now, updatedAt: now, company: named.found, messageCount: 0, preview: '', messages: [] };
        s[nid] = target;
        const moved: ThreadMessage = {
          id: uid(), role: 'assistant', kind: 'context_notice', createdAt: now,
          content: `Continued in a new chat about ${named.found.legalName} (organisation number ${named.found.orgNumber}). This conversation stays about its own company.`,
          payload: { kind: 'context_notice', movedTo: nid, citations: [], sources: [] },
        };
        userMsg.payload = { movedTo: nid } as ThreadMessage['payload'];
        t.messages.push(moved);
        t.updatedAt = now;
        switched = t.id;
        org = named.found.orgNumber;
        target.messages.push({ id: uid(), role: 'user', content: q, createdAt: now });
        userMsg = target.messages[0];
      }

      await progress(input, [
        { stage: 'identity', label: `Confirming the company (${org})` },
        { stage: 'evidence', label: 'Reading the saved demo profile' },
        { stage: 'answer', label: 'Writing an answer from that evidence' },
      ]);
      const reply = deps.reply(org!, q);
      if (!reply) throw new ApiError('not_found', 'Company not found.', 404);
      const followUps = reply.followUps ?? ['Compare this with the previous reporting period', 'Which claims could not be verified?', 'Check the latest company announcements'].slice(0, 3);
      const payload: ChatReply = { ...reply, followUps };
      if (switched) {
        payload.contextSwitch = {
          from: { orgNumber: t.company?.orgNumber ?? null, legalName: t.company?.legalName ?? null },
          to: { orgNumber: named.found!.orgNumber, legalName: named.found!.legalName },
          message: `Active company changed from ${t.company?.legalName} to ${named.found!.legalName} (organisation number ${named.found!.orgNumber}). Everything below was retrieved for ${named.found!.legalName}; nothing from ${t.company?.legalName} was used.`,
        };
      }
      const bot: ThreadMessage = { id: uid(), role: 'assistant', kind: payload.kind, content: payload.answer, createdAt: deps.now(), payload };
      target.messages.push(bot);
      target.updatedAt = deps.now();
      write(s);
      return { threadId: target.id, thread: summary(target), userMessage: userMsg, assistantMessage: bot, ...(switched ? { switchedFromThreadId: switched } : {}) };
    },
  };
}
