import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Ban, CircleAlert, RotateCcw } from 'lucide-react';
import { ApiError } from '@/api/http';

/** Friendly error panel. Never shows stack traces. */
export function ErrorState({ error, title, onRetry, compact }: { error?: unknown; title?: string; onRetry?: () => void; compact?: boolean }) {
  const e = error instanceof ApiError ? error : null;
  const blocked = e?.code === 'blocked';
  const heading = title ?? (blocked ? 'Source access blocked' : e?.code === 'not_found' ? 'Not found' : e?.code === 'network' ? 'Backend unreachable' : 'Something went wrong');
  const msg = e?.message ?? (blocked ? 'We could not verify this information through this source.' : 'This part of the page could not be loaded. Other sections are unaffected.');
  return (
    <div className={`notice ${blocked ? 'notice--err' : 'notice--warn'}`} role="alert" style={compact ? { padding: '10px 12px' } : undefined}>
      {blocked ? <Ban aria-hidden /> : <CircleAlert aria-hidden />}
      <div className="stack" style={{ gap: 6 }}>
        <strong>{heading}</strong>
        <span>{msg}</span>
        {onRetry && (
          <div>
            <button className="btn btn--sm" onClick={onRetry}>
              <RotateCcw aria-hidden /> Retry
            </button>
          </div>
        )}
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
