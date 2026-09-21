import type { ReactNode } from 'react';

import { cn } from '../../design-system/cn';

/**
 * One evidence surface with the reviewer's own acknowledgement. The checkbox
 * is a local checklist; it never reaches the server.
 */
export function SurfaceAck({ id, title, acked, onAck, aside, children }: { id: string; title: string; acked: boolean; onAck: (acked: boolean) => void; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className={cn('panel', acked && 'border-ok/40')} aria-labelledby={`surface-${id}`}>
      <header className="flex items-center gap-3 px-4 h-11 hairline-b">
        <h2 id={`surface-${id}`} className="text-sm font-medium">
          {title}
        </h2>
        {aside}
        <span className="flex-1" />
        <label className="inline-flex items-center gap-2 text-xs text-fg-1 cursor-pointer select-none">
          <input type="checkbox" checked={acked} onChange={(event) => onAck(event.target.checked)} aria-label={`Acknowledge ${title}`} />
          {acked ? 'Reviewed' : 'Mark reviewed'}
        </label>
      </header>
      {children}
    </section>
  );
}
