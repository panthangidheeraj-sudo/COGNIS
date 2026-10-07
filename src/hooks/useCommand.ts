import { useEffect, useRef } from 'react';

/**
 * Page-level commands fired from the command center (Cmd/Ctrl+K), e.g.
 * "export", "brief", "search-research". The current page decides what the
 * command means; pages that don't handle a command simply ignore it.
 */
export type CommandName = 'export' | 'brief' | 'search-research';

export function fireCommand(name: CommandName) {
  window.dispatchEvent(new CustomEvent(`cognis:${name}`));
}

export function useCommand(name: CommandName, handler: () => void) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    const on = () => ref.current();
    window.addEventListener(`cognis:${name}`, on);
    return () => window.removeEventListener(`cognis:${name}`, on);
  }, [name]);
}
