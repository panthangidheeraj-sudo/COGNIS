import { CircleDashed, Database, Sparkle } from 'lucide-react';
import type { ResearchAnswer, Source } from '@/types';
import { useOpenEvidence } from '@/components/evidence/useEvidence';
import { formatDateTime } from '@/utils/format';

/**
 * Research answer: concise synthesis blocks, each with citations.
 * The origin badge keeps saved evidence and fresh research clearly apart.
 */
export function AnswerView({ answer, sourceIndex, context }: { answer: ResearchAnswer; sourceIndex: Record<string, Source>; context?: string }) {
  const open = useOpenEvidence(sourceIndex, context);
  const fresh = answer.origin === 'fresh_research';
  return (
    <article className="answer" aria-label={`Answer: ${answer.question}`}>
      <div className="row-wrap" style={{ gap: 8 }}>
        <span className={`pill pill--sm ${fresh ? 'pill--info' : ''}`}>
          {fresh ? <Sparkle aria-hidden /> : <Database aria-hidden />}
          {fresh ? 'Fresh research' : 'From saved evidence in this research'}
        </span>
        <span className="t-xs t-muted" title={formatDateTime(answer.generatedAt)}>
          {answer.question}
        </span>
      </div>
      {answer.blocks.length === 0 && (
        <p className="t-sm t-muted" role="note">
          {answer.limitation ?? 'The available evidence does not answer this question.'}
        </p>
      )}
      {answer.blocks.map((b) => (
        <div key={b.id} className="answer-block">
          <p>{b.text}</p>
          <div className="row-wrap" style={{ gap: 6 }}>
            {b.reportingPeriod && <span className="tag">{b.reportingPeriod}</span>}
            {b.detail?.startsWith('http') && (
              <a className="cite" href={b.detail} target="_blank" rel="noreferrer noopener">
                Open source
              </a>
            )}
            {b.citations.length > 0 ? (
              <button className="cite" onClick={() => open({ title: 'Supporting evidence', value: b.text, evidence: b.citations.map((c) => c.evidence) })}>
                {b.citations.length} source{b.citations.length === 1 ? '' : 's'}: {b.citations.map((c) => c.sourceName).join(', ')}
              </button>
            ) : (
              <span className="t-xs t-muted">No citation — derived from the absence of evidence</span>
            )}
          </div>
        </div>
      ))}
      {answer.blocks.length > 0 && answer.limitation && <p className="t-sm t-muted">{answer.limitation}</p>}
      {answer.gaps && answer.gaps.length > 0 && (
        <div className="answer-gaps">
          <span className="t-micro">Not verified</span>
          <ul>
            {answer.gaps.map((g) => (
              <li key={g}>
                <CircleDashed aria-hidden /> {g}
              </li>
            ))}
          </ul>
        </div>
      )}
      {fresh && answer.newSourceIds && (
        <p className="t-xs t-muted">Newly queried: {answer.newSourceIds.map((s) => sourceIndex[s]?.name ?? s).join(', ')}</p>
      )}
    </article>
  );
}
