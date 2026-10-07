import { Link } from 'react-router-dom';
import { CircleAlert, CircleCheck, Info, X } from 'lucide-react';
import { useUi } from '@/stores/ui';

export function Toaster() {
  const toasts = useUi((s) => s.toasts);
  const dismiss = useUi((s) => s.dismissToast);
  return (
    <div className="toasts" aria-live="polite" aria-atomic="false">
      {toasts.map((t) => (
        <div key={t.id} className="toast" role="status">
          {t.tone === 'ok' ? <CircleCheck style={{ color: 'var(--ok)' }} aria-hidden /> : t.tone === 'info' ? <Info style={{ color: 'var(--accent-soft)' }} aria-hidden /> : <CircleAlert style={{ color: t.tone === 'err' ? 'var(--err)' : 'var(--warn)' }} aria-hidden />}
          <span style={{ flex: 1 }}>{t.text}</span>
          {t.action && (
            <Link to={t.action.href} className="link-btn" onClick={() => dismiss(t.id)}>
              {t.action.label}
            </Link>
          )}
          <button className="btn btn--ghost btn--icon btn--sm" onClick={() => dismiss(t.id)} aria-label="Dismiss notification">
            <X aria-hidden />
          </button>
        </div>
      ))}
    </div>
  );
}
