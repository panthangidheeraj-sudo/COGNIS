import { ArrowUpRight } from 'lucide-react';
import { cn } from '@/utils/cn';

/** Safe external link: new tab, noopener, visible external marker + SR hint. */
export function ExternalLink({ href, children, className, button }: { href?: string; children: React.ReactNode; className?: string; button?: boolean }) {
  if (!href) return <span className={className}>{children}</span>;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow" className={cn(button ? 'btn btn--sm' : 'link-btn', className)}>
      {children}
      <ArrowUpRight aria-hidden />
      <span className="sr-only">(opens external site in a new tab)</span>
    </a>
  );
}
