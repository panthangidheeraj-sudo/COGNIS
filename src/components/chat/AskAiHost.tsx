import { useRef, useState } from 'react';
import { AskAiPanel } from './AskAiPanel';

/**
 * Opens the Ask AI panel from a button elsewhere on the page and keeps the conversation: once opened, the panel stays mounted and is only
 * hidden when closed, so closing and reopening it continues the same chat. A different company (a different org number) starts a new one.
 * Focus goes into the question box on open and back to the opener on close.
 */
export function useAskAiHost() {
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState(false);
  const opener = useRef<HTMLElement | null>(null);
  const close = () => {
    setOpen(false);
    opener.current?.focus();
  };
  const toggle = () => {
    if (open) return close();
    opener.current = document.activeElement as HTMLElement | null;
    setSeen(true);
    setOpen(true);
    requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('#ask-ai textarea')?.focus());
  };
  return { open, seen, toggle, close };
}

export function AskAiHost({ host, orgNumber, legalName, logoUrl, origin, suggestions }: { host: ReturnType<typeof useAskAiHost>; orgNumber: string; legalName: string; logoUrl?: string; origin?: string; suggestions?: string[] }) {
  if (!host.seen) return null;
  return (
    <div hidden={!host.open} data-testid="ask-ai-host">
      <AskAiPanel key={orgNumber} orgNumber={orgNumber} legalName={legalName} logoUrl={logoUrl} onClose={host.close} origin={origin} suggestions={suggestions} />
    </div>
  );
}
