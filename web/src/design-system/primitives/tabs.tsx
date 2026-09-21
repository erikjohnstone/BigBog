import { Tabs as BaseTabs } from '@base-ui/react/tabs';
import type { ReactNode } from 'react';

import { cn } from '../cn';

export function Tabs({
  value,
  onValueChange,
  children,
  className,
}: {
  value: string;
  onValueChange: (value: string) => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <BaseTabs.Root value={value} onValueChange={(next) => onValueChange(String(next))} className={className}>
      {children}
    </BaseTabs.Root>
  );
}

export function TabList({ children, className, ariaLabel }: { children: ReactNode; className?: string; ariaLabel?: string }) {
  return (
    <BaseTabs.List aria-label={ariaLabel} className={cn('relative flex items-end gap-1 hairline-b', className)}>
      {children}
      <BaseTabs.Indicator
        className={cn(
          'absolute bottom-[-1px] h-[2px] bg-accent rounded-pill',
          'left-[var(--active-tab-left)] w-[var(--active-tab-width)]',
          'transition-[left,width] duration-[var(--duration-state)] ease-[var(--ease-out)]',
        )}
      />
    </BaseTabs.List>
  );
}

export function Tab({ value, children, className }: { value: string; children: ReactNode; className?: string }) {
  return (
    <BaseTabs.Tab
      value={value}
      className={cn(
        'h-9 px-3 text-sm text-fg-1 hover:text-fg-0 data-[selected]:text-fg-0 whitespace-nowrap',
        'inline-flex items-center gap-1.5 rounded-t-control outline-none focus-visible:bg-bg-2',
        className,
      )}
    >
      {children}
    </BaseTabs.Tab>
  );
}

export function TabPanel({ value, children, className }: { value: string; children: ReactNode; className?: string }) {
  return (
    <BaseTabs.Panel value={value} className={cn('outline-none', className)}>
      {children}
    </BaseTabs.Panel>
  );
}
