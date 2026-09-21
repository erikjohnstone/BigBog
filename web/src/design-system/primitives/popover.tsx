import { Popover as BasePopover } from '@base-ui/react/popover';
import type { ReactNode } from 'react';

import { cn } from '../cn';

export function Popover({
  trigger,
  children,
  side = 'bottom',
  align = 'start',
  className,
  open,
  onOpenChange,
}: {
  trigger: ReactNode;
  children: ReactNode;
  side?: 'top' | 'bottom' | 'left' | 'right';
  align?: 'start' | 'center' | 'end';
  className?: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  return (
    <BasePopover.Root open={open} onOpenChange={onOpenChange}>
      <BasePopover.Trigger render={<span className="inline-flex" />}>{trigger}</BasePopover.Trigger>
      <BasePopover.Portal>
        <BasePopover.Positioner side={side} align={align} sideOffset={6}>
          <BasePopover.Popup
            className={cn(
              'floating z-30 p-3 text-sm min-w-48 outline-none',
              'data-[starting-style]:opacity-0 data-[starting-style]:scale-[0.98] data-[ending-style]:opacity-0',
              'transition-[opacity,transform] duration-[var(--duration-micro)] ease-[var(--ease-out)]',
              className,
            )}
          >
            {children}
          </BasePopover.Popup>
        </BasePopover.Positioner>
      </BasePopover.Portal>
    </BasePopover.Root>
  );
}
