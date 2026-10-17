/** Company "Ask AI" chat. Mirrors POST /companies/{org}/chat and GET /companies/{org}/chat/context. */

/** What was actually checked for one area. Never "none" when the truth is "not checked" or "unavailable". */
export type CoverageStatus = 'verified' | 'no_public_results_found' | 'not_reported' | 'not_checked' | 'unavailable';

export interface ChatCoverageRow {
  area: string;
  label: string;
  status: CoverageStatus;
  note: string;
}

export interface ChatSource {
  /** The number used in the answer's [n] markers. */
  n: number;
  kind: string;
  title: string;
  url?: string | null;
  publishedAt?: string | null;
  retrievedAt?: string | null;
  sourceClass?: string;
  sourceLabel: string;
  verification?: string;
  reportingPeriod?: string | null;
  uncertainty?: string | null;
  excerpt?: string;
  origin?: 'saved' | 'fresh' | string;
  currency?: string | null;
  accountingScope?: string | null;
  /** Precise status of an event: "Dividend announced (not yet paid)", "Agreement signed (not closed)" … */
  eventStatus?: string | null;
  /** How many separate facts this one source supports (a source is listed once, however many claims use it). */
  claims?: number;
  document?: string | null;
  significance?: string | null;
  /** What the link IS: the filed copy of the annual accounts the register lists, a register data record (not the filing), or an ordinary web page. */
  linkKind?: 'filing_document' | 'register_record' | 'web_page' | string | null;
  /** Where the figures were read, when that is not `url` (the register's data record behind a filed copy). */
  recordUrl?: string | null;
}

/** One row of a period-over-period comparison, computed from the filed accounts (never by a model). */
export interface ChatComparisonRow {
  metric: string;
  label: string;
  scope: 'company' | 'group' | string;
  currency: string;
  previous: { period: string; value: number };
  latest: { period: string; value: number };
  absoluteChange: number;
  percentChange: number | null;
  formula: string;
}
export interface ChatComparison {
  periods: [string, string] | string[];
  rankedBy: 'percent' | 'amount' | string;
  rows: ChatComparisonRow[];
  omitted: string[];
}

/** An area that was relevant to the question, with what was really checked. */
export interface CheckedArea extends ChatCoverageRow {
  relevant?: boolean;
  ranNow?: boolean;
}

export interface ChatCandidate {
  orgNumber: string;
  legalName: string;
  municipality?: string | null;
  status?: string | null;
}

export interface ContextSwitch {
  from: { orgNumber: string | null; legalName: string | null };
  to: { orgNumber: string; legalName: string };
  message: string;
}

export interface ChatContext {
  company: { orgNumber: string; legalName: string; status?: string | null; municipality?: string | null };
  suggestions: string[];
  coverage: ChatCoverageRow[];
  capabilities: { chat: boolean; aiModel: boolean; freshResearch: boolean; maxQuestionChars: number };
  researchedAt?: string | null;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export type ReplyKind =
  | 'model'
  | 'evidence_only'
  | 'clarification'
  | 'comparison'
  | 'comparison_unavailable'
  | 'recent'
  | 'source_audit'
  | 'future_actual'
  | 'forecast'
  | 'limitation'
  | 'context_notice'
  | 'error';

export interface ChatReply {
  company: { orgNumber: string; legalName: string; status?: string | null };
  /** model = grounded AI answer; evidence_only = written from saved evidence without a model; clarification = refused to switch company. */
  kind: ReplyKind;
  answer: string;
  /** Sources actually cited in the answer. */
  citations: ChatSource[];
  /** Every source considered for this answer. */
  sources: ChatSource[];
  coverage: ChatCoverageRow[];
  unsupported?: string[];
  search: {
    /** used | not_used | no_results (checked, nothing usable) | unavailable | timeout | not_configured */
    state: 'not_used' | 'used' | 'no_results' | 'unavailable' | 'timeout' | 'not_configured' | string;
    note: string;
    /** The sources the check of current sources looked at for this answer, and what became of each. */
    checked?: Array<{ name: string; url?: string | null; state: string; reason?: string | null; kind?: string; linkKind?: string | null }>;
    /** The web search behind the check: calls made, results returned, and results never opened (not a permitted source, or not about this company). */
    web?: { searches: number; results: number; notOpened: number; state: string; note?: string | null };
    lookup?: { searches: number; elapsedMs: number; cached: boolean };
  };
  model?: string | null;
  modelNote?: string | null;
  /** One sentence, decided from the cited sources themselves, on what the financial links are and which accounting scope each figure has. */
  provenanceNote?: string | null;
  origin: 'saved' | 'fresh' | 'none' | string;
  generatedAt: string;
  intent?: string;
  /** The areas this question needed, with their real status. */
  checked?: CheckedArea[];
  comparison?: ChatComparison;
  contextSwitch?: ContextSwitch;
  candidates?: ChatCandidate[];
  followUps?: string[];
  consideredSources?: number;
  /** Set on a notice in the previous thread: the question continues in this thread. */
  movedTo?: string;
  /** Set on a clarification: the id of the question that is waiting for the user to pick a company. */
  waitingFor?: string;
}

export interface ChatRequest {
  orgNumber: string;
  question: string;
  messages: ChatMessage[];
  expectedName?: string;
  fresh?: boolean;
}

/** Live progress of one answer: only checks that really started are reported. */
export interface ChatProgress {
  stage: string;
  label: string;
  [extra: string]: unknown;
}

// ---------------------------------------------------------------- AI Chat threads --
export interface ChatThreadSummary {
  id: string;
  title: string;
  titleEdited: boolean;
  createdAt: string;
  updatedAt: string;
  company: { orgNumber: string; legalName: string } | null;
  messageCount: number;
  preview: string;
}

export interface ThreadMessage {
  id: string;
  role: 'user' | 'assistant';
  kind?: ReplyKind | null;
  content: string;
  createdAt: string;
  /** The full structured answer for assistant messages (citations, checks, comparison …). */
  payload?: Partial<ChatReply> & { movedTo?: string; waitingFor?: string; code?: string };
}

export interface ChatThread extends ChatThreadSummary {
  messages: ThreadMessage[];
}

export interface ThreadAskInput {
  threadId: string;
  /** Client-made id: sending the same id twice never creates a second message. */
  messageId: string;
  question: string;
  orgNumber?: string;
  fresh?: boolean;
  /** Answer a question that was waiting for the user to pick a company. */
  retryOf?: string;
  onProgress?: (p: ChatProgress) => void;
  signal?: AbortSignal;
}

export interface ThreadAskResult {
  threadId: string;
  thread: ChatThreadSummary;
  userMessage: ThreadMessage;
  assistantMessage: ThreadMessage;
  switchedFromThreadId?: string;
}
