/**
 * Subscribes to a research run's event stream and reduces it into UI state.
 * De-duplicates by sequence number and reconnects with lastSeq.
 * The UI only ever reflects events the backend actually sent.
 */
import { useCallback, useEffect, useReducer, useRef } from 'react';
import { api } from '@/api';
import { initialStreamState, reduceResearchEvent } from '@/api/runs';
import type { ResearchEvent, ResearchRun, ResearchStreamState } from '@/types';

type Action =
  | { type: 'reset'; run: ResearchRun | null }
  | { type: 'run'; run: ResearchRun }
  | { type: 'event'; event: ResearchEvent }
  | { type: 'connection'; connection: ResearchStreamState['connection']; error?: string };

function reducer(state: ResearchStreamState, a: Action): ResearchStreamState {
  switch (a.type) {
    case 'reset':
      return { ...initialStreamState, run: a.run };
    case 'run':
      return { ...state, run: a.run };
    case 'event':
      return reduceResearchEvent(state, a.event);
    case 'connection':
      return { ...state, connection: a.connection, error: a.error ?? state.error };
  }
}

export function useResearchStream(run: ResearchRun | null) {
  const [state, dispatch] = useReducer(reducer, { ...initialStreamState, run });
  const lastSeq = useRef(0);
  const unsub = useRef<(() => void) | null>(null);
  const runId = run?.id;

  useEffect(() => {
    dispatch({ type: 'reset', run });
    lastSeq.current = 0;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const connect = useCallback(() => {
    if (!runId) return;
    unsub.current?.();
    dispatch({ type: 'connection', connection: 'connecting' });
    unsub.current = api.research.stream(
      runId,
      {
        onOpen: () => dispatch({ type: 'connection', connection: 'open' }),
        onReconnecting: () => dispatch({ type: 'connection', connection: 'reconnecting' }),
        onError: (err) => dispatch({ type: 'connection', connection: 'error', error: err.message }),
        onEvent: (event) => {
          if (event.seq <= lastSeq.current) return;
          lastSeq.current = event.seq;
          dispatch({ type: 'event', event });
          if (event.type === 'run.completed' || event.type === 'run.failed') dispatch({ type: 'connection', connection: 'closed' });
        },
      },
      { lastSeq: lastSeq.current },
    );
  }, [runId]);

  useEffect(() => {
    if (!run || run.status === 'ambiguous' || run.status === 'awaiting_confirmation') return;
    connect();
    return () => unsub.current?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, run?.status === 'running']);

  const setRun = useCallback((r: ResearchRun) => dispatch({ type: 'run', run: r }), []);
  return { state, setRun, reconnect: connect };
}
