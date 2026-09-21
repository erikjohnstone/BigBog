import { ChevronDown } from 'lucide-react';
import { forwardRef } from 'react';
import type { SelectHTMLAttributes } from 'react';

import { cn } from '../cn';

/**
 * A native select styled on the tokens. Used in forms where the options are
 * plain values; it stays a real select so assistive tech and automation
 * drive it directly.
 */
export const NativeSelect = forwardRef<HTMLSelectElement, Omit<SelectHTMLAttributes<HTMLSelectElement>, 'size'> & { size?: 'sm' | 'md' }>(
  function NativeSelect({ className, size = 'md', children, ...props }, ref) {
    return (
      <span className={cn('relative inline-flex w-full', className)}>
        <select
          ref={ref}
          className={cn(
            'raised w-full appearance-none text-fg-0 outline-none focus-visible:border-accent disabled:opacity-50 pr-7',
            size === 'sm' ? 'h-7 px-2 text-xs' : 'h-8 px-2.5 text-sm',
          )}
          {...props}
        >
          {children}
        </select>
        <ChevronDown size={14} className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-fg-2" />
      </span>
    );
  },
);
