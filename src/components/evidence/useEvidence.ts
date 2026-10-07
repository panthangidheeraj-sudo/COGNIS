import { useCallback } from 'react';
import type { Evidence, Fact, Source } from '@/types';
import { useUi } from '@/stores/ui';

/** Opens the global evidence drawer for a fact or loose evidence list. */
export function useOpenEvidence(sourceIndex: Record<string, Source>, context?: string) {
  const open = useUi((s) => s.openEvidence);
  return useCallback(
    (target: Fact | { title: string; value?: string; evidence: Evidence[] }) =>
      'field' in target ? open({ fact: target, sourceIndex, context }) : open({ title: target.title, value: target.value, evidence: target.evidence, sourceIndex, context }),
    [open, sourceIndex, context],
  );
}
