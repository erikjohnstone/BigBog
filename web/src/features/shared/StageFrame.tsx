import type { ReactNode } from 'react';

import { cn } from '../../design-system/cn';

/**
 * Scrollable stage body with a max-width column. Stages with canvases skip
 * it. The scroll region is focusable so keyboard users can scroll it.
 */
export function StageFrame({
  children,
  wide,
  className,
  label = 'Stage content',
}: {
  children: ReactNode;
  wide?: boolean;
  className?: string;
  label?: string;
}) {
  return (
    <div className="h-full overflow-auto outline-none focus-visible:[box-shadow:inset_0_0_0_2px_var(--accent)]" tabIndex={0} role="region" aria-label={label}>
      <div className={cn('mx-auto px-6 py-6 flex flex-col gap-4', wide ? 'max-w-7xl' : 'max-w-5xl', className)}>{children}</div>
    </div>
  );
}

export function SectionCard({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel">
      <header className="flex items-center justify-between gap-3 px-4 h-11 hairline-b">
        <h2 className="text-sm font-medium">{title}</h2>
        {aside}
      </header>
      {children}
    </section>
  );
}

export function KeyValue({ items }: { items: Array<{ label: string; value: ReactNode }> }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1.5 px-4 py-3 text-sm">
      {items.map((item) => (
        <div key={item.label} className="contents">
          <dt className="text-fg-2">{item.label}</dt>
          <dd className="text-fg-0 min-w-0 break-words">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
