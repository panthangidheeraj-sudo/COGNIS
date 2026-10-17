import { useContext } from 'react';
import { UNSAFE_DataRouterStateContext, useMatches } from 'react-router-dom';

/**
 * Route metadata. A route opts into shell features with `handle` in `router.tsx`, and the shared layout reads it here — instead of
 * pathname checks scattered through components. The handle is read from the active matches, so it changes in the same render as the route
 * does (nothing lingers during a transition).
 */
export interface RouteHandle {
  /** The compare selection tray belongs on this route (the comparison workflow). Every other route hides it. */
  compareTray?: boolean;
}

function Matches(): RouteHandle[] {
  return useMatches().map((m) => (m.handle ?? {}) as RouteHandle);
}

/** Merged handle of the active route (empty outside a data router, e.g. in a bare MemoryRouter test, where no route opts in). */
export function useRouteHandle(): RouteHandle {
  const inDataRouter = useContext(UNSAFE_DataRouterStateContext) != null; // stable for the life of the tree, so the conditional hook call is safe
  const matches = inDataRouter ? Matches() : [];
  return Object.assign({}, ...matches) as RouteHandle;
}
