/**
 * Where the conversation log should be scrolled after something changed in it — and when to leave it alone.
 *
 * The log follows new content only while the reader is "at the bottom" (within NEAR_BOTTOM_PX of it) or has just sent a message. Someone who
 * scrolled up to read an earlier answer is never pulled back down by progress updates or a new answer. When a new answer is taller than the
 * visible log, the log shows the START of that answer (not its end), so the reader begins at its first line.
 */
export const NEAR_BOTTOM_PX = 96;

export function isNearBottom(el: Pick<HTMLElement, 'scrollHeight' | 'scrollTop' | 'clientHeight'>): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX;
}

/** The scrollTop to move to, or null to stay where the reader is. */
export function nextScrollTop(
  log: Pick<HTMLElement, 'scrollHeight' | 'scrollTop' | 'clientHeight'>,
  opts: { follow: boolean; newAnswer?: { offsetTop: number; offsetHeight: number } | null },
): number | null {
  if (!opts.follow) return null;
  const bottom = Math.max(0, log.scrollHeight - log.clientHeight);
  const a = opts.newAnswer;
  if (a && a.offsetHeight > log.clientHeight - 48) return Math.min(bottom, Math.max(0, a.offsetTop - 12)); // a long answer: show its beginning
  return bottom;
}
