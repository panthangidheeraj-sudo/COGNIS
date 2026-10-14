import { ApiError } from './http';

/**
 * What the backend says about *why* a request failed (`ApiError.details`). Set for the Enhetsregisteret search failures: the cause in plain words,
 * the register's HTTP status, how many attempts were made, whether trying again could help, and whether COGNIS can continue from companies it has
 * already verified. Every field is optional: an error without them is shown by its message alone.
 */
export interface FailureDetails {
  source?: string;
  /** Machine-readable class: timeout, network, server_error, rate_limited, client_error, blocked, unsafe_url, invalid_content, unexpected_response… */
  reason?: string;
  cause?: string;
  /** The underlying error text (redacted by the backend). */
  detail?: string;
  httpStatus?: number;
  attempts?: number;
  /** false when repeating the same request cannot succeed (the register rejected it, or refused access). */
  retryable?: boolean;
  fallback?: { available: boolean; count: number; kind?: string; note?: string };
}

export function failureDetails(error: unknown): FailureDetails | null {
  if (!(error instanceof ApiError) || typeof error.details !== 'object' || error.details === null) return null;
  const d = error.details as Record<string, unknown>;
  if (typeof d.reason !== 'string' && typeof d.cause !== 'string') return null;
  return d as FailureDetails;
}

const REASON_LABEL: Record<string, string> = {
  timeout: 'Timed out',
  network: 'Network error',
  server_error: 'Server error',
  rate_limited: 'Rate limited',
  client_error: 'Request rejected',
  blocked: 'Access refused',
  unsafe_url: 'Blocked by network safety check',
  invalid_content: 'Not valid JSON',
  unexpected_response: 'Unexpected response',
  budget_exhausted: 'Request budget used up',
  too_large: 'Response too large',
};

/** One line of facts for people who need to diagnose it: "Server error · HTTP 503 · 4 attempts · fixture failure". */
export function failureFacts(d: FailureDetails): string {
  const parts: string[] = [];
  if (d.reason) parts.push(REASON_LABEL[d.reason] ?? d.reason);
  if (d.httpStatus) parts.push(`HTTP ${d.httpStatus}`);
  if (d.attempts) parts.push(`${d.attempts} ${d.attempts === 1 ? 'attempt' : 'attempts'}`);
  if (d.detail) parts.push(d.detail);
  return parts.join(' · ');
}
