import { afterEach, describe, expect, it, vi } from 'vitest';
import { mockApi } from '@/data/mock/mockApi';
import { initialStreamState, reduceResearchEvent } from '@/api/runs';
import type { ResearchEvent, ResearchStreamState } from '@/types';

afterEach(() => vi.useRealTimers());

describe('research streaming (mock transport)', () => {
  it('streams source steps, confirmed facts and completion; tolerates reconnect replay', async () => {
    vi.useFakeTimers();
    const pending = mockApi.research.start({ orgNumber: '914552108', query: 'Havbris', mode: 'quick' });
    await vi.advanceTimersByTimeAsync(1000);
    const run = await pending;
    expect(run.status).toBe('running');

    let state: ResearchStreamState = { ...initialStreamState, run };
    const seen: ResearchEvent[] = [];
    const stop = mockApi.research.stream(run.id, { onEvent: (e) => (seen.push(e), (state = reduceResearchEvent(state, e))) });
    await vi.advanceTimersByTimeAsync(8000);
    stop();
    // reconnect with lastSeq: no duplicates
    const before = state.events.length;
    const stop2 = mockApi.research.stream(run.id, { onEvent: (e) => (state = reduceResearchEvent(state, e)) }, { lastSeq: state.lastSeq });
    await vi.advanceTimersByTimeAsync(30000);
    stop2();

    expect(state.events.length).toBeGreaterThanOrEqual(before);
    expect(new Set(state.events.map((e) => e.seq)).size).toBe(state.events.length);
    expect(state.run?.status).toBe('completed');
    expect(state.facts.length).toBeGreaterThan(2);
    // Havbris scenario: procurement source fails, reported truthfully
    expect(state.run?.plan.steps.find((s) => s.key === 'activity')?.status).toBe('failed');
    expect(state.answer?.blocks.length).toBeGreaterThan(0);
  });
});
