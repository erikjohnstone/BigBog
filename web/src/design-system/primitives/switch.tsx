import { Switch as BaseSwitch } from '@base-ui/react/switch';

import { cn } from '../cn';

export function Switch({
  checked,
  onCheckedChange,
  ariaLabel,
  className,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  ariaLabel: string;
  className?: string;
}) {
  return (
    <BaseSwitch.Root
      checked={checked}
      onCheckedChange={onCheckedChange}
      aria-label={ariaLabel}
      className={cn(
        'relative inline-flex h-5 w-9 items-center rounded-pill border border-line-2 bg-bg-2 p-0.5',
        'data-[checked]:bg-accent data-[checked]:border-accent transition-colors duration-[var(--duration-micro)]',
        'outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
        className,
      )}
    >
      <BaseSwitch.Thumb
        className={cn(
          'size-3.5 rounded-pill bg-fg-1 transition-transform duration-[var(--duration-micro)] ease-[var(--ease-out)]',
          'data-[checked]:translate-x-4 data-[checked]:bg-accent-fg',
        )}
      />
    </BaseSwitch.Root>
  );
}
