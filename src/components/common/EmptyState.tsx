import { Motif } from './Motif';
import { cn } from '@/utils/cn';

export function EmptyState({ title, text, action, center, compact }: { title: string; text?: React.ReactNode; action?: React.ReactNode; center?: boolean; compact?: boolean }) {
  return (
    <div className={cn('empty', center && 'empty--center')} style={compact ? { padding: 18 } : undefined}>
      {!compact && <Motif className="empty-motif" />}
      <p className="empty-title">{title}</p>
      {text && <p className="empty-text">{text}</p>}
      {action && <div className="row-wrap" style={{ marginTop: 6 }}>{action}</div>}
    </div>
  );
}
