import { Dialog as BaseDialog } from '@base-ui/react/dialog';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';

import { cn } from '../cn';
import { Button } from './button';

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  size = 'md',
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
}) {
  const widths = { sm: 'max-w-sm', md: 'max-w-lg', lg: 'max-w-2xl', xl: 'max-w-4xl' };
  return (
    <BaseDialog.Root open={open} onOpenChange={onOpenChange}>
      <BaseDialog.Portal>
        <BaseDialog.Backdrop
          className={cn(
            'fixed inset-0 z-40 bg-black/50 backdrop-blur-[2px]',
            'data-[starting-style]:opacity-0 data-[ending-style]:opacity-0 transition-opacity duration-[var(--duration-state)]',
          )}
        />
        <BaseDialog.Popup
          className={cn(
            'fixed z-40 left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[calc(100vw-32px)]',
            widths[size],
            'floating p-0 outline-none',
            'data-[starting-style]:opacity-0 data-[starting-style]:scale-[0.98] data-[ending-style]:opacity-0',
            'transition-[opacity,transform] duration-[var(--duration-state)] ease-[var(--ease-out)]',
          )}
        >
          <header className="flex items-start gap-3 px-5 pt-4 pb-3 hairline-b">
            <div className="flex-1 min-w-0">
              <BaseDialog.Title className="text-lg font-semibold text-fg-0">{title}</BaseDialog.Title>
              {description && (
                <BaseDialog.Description className="mt-0.5 text-sm text-fg-1">{description}</BaseDialog.Description>
              )}
            </div>
            <BaseDialog.Close render={<Button variant="ghost" size="icon" aria-label="Close" />}>
              <X size={16} />
            </BaseDialog.Close>
          </header>
          {children && <div className="px-5 py-4 text-sm">{children}</div>}
          {footer && <footer className="flex justify-end gap-2 px-5 py-3 border-t border-line-1">{footer}</footer>}
        </BaseDialog.Popup>
      </BaseDialog.Portal>
    </BaseDialog.Root>
  );
}
