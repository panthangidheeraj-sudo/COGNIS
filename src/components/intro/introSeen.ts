/** Whether this browser has already seen the launch intro. Stored on the device only (like the theme preference); a browser without storage simply shows the intro on each launch. */
const KEY = 'cognis.intro.seen.v1';
export const REPLAY_INTRO_EVENT = 'cognis:replay-intro';

export function introSeen(): boolean {
  try {
    return window.localStorage.getItem(KEY) === '1';
  } catch {
    return false;
  }
}

export function markIntroSeen(): void {
  try {
    window.localStorage.setItem(KEY, '1');
  } catch {
    /* storage blocked or full: the intro will show again next launch, nothing else is affected */
  }
}

/** Show the intro again on demand (Settings). It is not remembered as unseen: dismissing it records it as seen once more. */
export function replayIntro(): void {
  window.dispatchEvent(new Event(REPLAY_INTRO_EVENT));
}
