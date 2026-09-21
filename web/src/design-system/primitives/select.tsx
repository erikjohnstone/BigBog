import { Select as BaseSelect } from '@base-ui/react/select';
import { Check, ChevronDown } from 'lucide-react';

import { cn } from '../cn';

export interface SelectOption {
  value: string;
  label: string;
  hint?: string;
  disabled?: boolean;
}

export function Select({
  value,
  onValueChange,
  options,
  placeholder = 'Select…',
  className,
  ariaLabel,
  size = 'md',
}: {
  value: string | null;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  className?: string;
  ariaLabel?: string;
  size?: 'sm' | 'md';
}) {
  return (
    <BaseSelect.Root value={value} onValueChange={(next) => next !== null && onValueChange(String(next))}>
      <BaseSelect.Trigger
        aria-label={ariaLabel}
        className={cn(
          'raised inline-flex items-center justify-between gap-2 text-sm text-fg-0 hover:bg-bg-3 outline-none focus-visible:border-accent',
          size === 'sm' ? 'h-7 px-2 text-xs' : 'h-8 px-2.5',
          className,
        )}
      >
        <BaseSelect.Value placeholder={placeholder} className="truncate" />
        <BaseSelect.Icon className="text-fg-2">
          <ChevronDown size={14} />
        </BaseSelect.Icon>
      </BaseSelect.Trigger>
      <BaseSelect.Portal>
        <BaseSelect.Positioner sideOffset={4} className="z-30">
          <BaseSelect.Popup className="floating p-1 min-w-[var(--anchor-width)] max-h-80 overflow-auto outline-none">
            <BaseSelect.List>
              {options.map((option) => (
                <BaseSelect.Item
                  key={option.value}
                  value={option.value}
                  disabled={option.disabled}
                  className={cn(
                    'flex items-center gap-2 px-2 h-8 rounded-control text-sm text-fg-0 cursor-default',
                    'data-[highlighted]:bg-bg-2 data-[disabled]:opacity-50',
                  )}
                >
                  <BaseSelect.ItemIndicator className="w-3.5 text-accent">
                    <Check size={14} />
                  </BaseSelect.ItemIndicator>
                  <BaseSelect.ItemText className="flex-1 truncate">{option.label}</BaseSelect.ItemText>
                  {option.hint && <span className="text-2xs text-fg-2">{option.hint}</span>}
                </BaseSelect.Item>
              ))}
            </BaseSelect.List>
          </BaseSelect.Popup>
        </BaseSelect.Positioner>
      </BaseSelect.Portal>
    </BaseSelect.Root>
  );
}
