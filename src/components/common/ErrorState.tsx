import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Ban, CircleAlert, RotateCcw } from 'lucide-react';
import { ApiError } from '@/api/http';
import { failureDetails, failureFacts } from '@/api/errorDetails';

/** Friendly error panel. Never shows stack traces. When the backend reports why a request failed it shows that cause, and offers Retry only if trying again can help. */
export function ErrorState({ error, title, onRetry, compact }: { error?: unknown; title?: string; onRetry?: () => void; compact?: boolean }) {
  const e = error instanceof ApiError ? error : null;
  const blocked = e?.code === 'blocked';
  const why = failureDetails(error);
  const registry = why?.source === 'enhetsregisteret';
  const heading =
    title ?? (registry ? 'Company search in Enhetsregisteret failed' : blocked ? 'Source access blocked' : e?.code === 'not_found' ? 'Not found' : e?.code === 'network' ? 'Backend unreachable' : 'Something went wrong');
  const msg = (registry ? why?.cause : undefined) ?? e?.message ?? (blocked ? 'We could not verify this information through this source.' : 'This part of the page could not be loaded. Other sections are unaffected.');
  const facts = why ? failureFacts(why) : '';
  const futile = why?.retryable === false; // the same request would fail the same way
  return (
    <div className={`notice ${blocked ? 'notice--err' : 'notice--warn'}`} role="alert" style={compact ? { padding: '10px 12px' } : undefined}>
      {blocked ? <Ban aria-hidden /> : <CircleAlert aria-hidden />}
      <div className="stack" style={{ gap: 6 }}>
        <strong>{heading}</strong>
        <span>{msg}</span>
        {facts && (
          <span className="t-xs t-muted" data-testid="error-facts">
            {facts}
          </span>
        )}
        {onRetry && !futile && (
          <div>
            <button className="btn btn--sm" onClick={onRetry}>
              <RotateCcw aria-hidden /> Retry
            </button>
          </div>
        )}
        {onRetry && futile && <span className="t-xs t-muted">Trying again will not help until something changes — adjust the filters and try again.</span>}
      </div>
    </div>
  );
}

/** Component-level boundary so one broken chart or panel can't take down the page. */
export class ErrorBoundary extends Component<{ children: ReactNode; label?: string; fallback?: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    // Technical details stay in the console only.
    console.error(`[COGNIS] ${this.props.label ?? 'component'} failed`, error, info.componentStack);
  }
  render() {
    if (this.state.error)
      return (
        this.props.fallback ?? (
          <ErrorState
            title={`${this.props.label ?? 'This section'} could not be displayed`}
            error={null}
            onRetry={() => this.setState({ error: null })}
            compact
          />
        )
      );
    return this.props.children;
  }
}
