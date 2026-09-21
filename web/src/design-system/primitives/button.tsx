import { forwardRef } from 'react';
import type { ButtonHTMLAttributes } from 'react';

import { cn } from '../cn';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'outline';
export type ButtonSize = 'xs' | 'sm' | 'md' | 'lg' | 'icon';

const variants: Record<ButtonVariant, string> = {
  primary:
    'bg-accent text-accent-fg hover:brightness-110 active:brightness-95 shadow-[var(--inset-hi)] disabled:opacity-50',
  secondary:
    'bg-bg-2 text-fg-0 border border-line-2 hover:bg-bg-3 active:bg-bg-2 disabled:opacity-50',
  outline: 'bg-transparent text-fg-0 border border-line-2 hover:bg-bg-2 disabled:opacity-50',
  ghost: 'bg-transparent text-fg-1 hover:bg-bg-2 hover:text-fg-0 disabled:opacity-50',
  danger: 'bg-fail-soft text-fail border border-fail/30 hover:bg-fail/20 disabled:opacity-50',
};

const sizes: Record<ButtonSize, string> = {
  xs: 'h-6 px-2 text-2xs gap-1 rounded-chip',
  sm: 'h-7 px-2.5 text-xs gap-1.5 rounded-control',
  md: 'h-8 px-3 text-sm gap-2 rounded-control',
  lg: 'h-10 px-4 text-base gap-2 rounded-control',
  icon: 'size-8 text-sm rounded-control',
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

/**
 * The button look as a class string, so a router `<Link>` can wear it without
 * nesting a button inside an anchor.
 */
export function buttonClass(variant: ButtonVariant = 'secondary', size: ButtonSize = 'md', className?: string) {
  return cn(
    'inline-flex items-center justify-center font-medium whitespace-nowrap select-none',
    'transition-[background-color,color,filter] duration-[var(--duration-micro)] ease-[var(--ease-out)]',
    'disabled:cursor-not-allowed',
    variants[variant],
    sizes[size],
    className,
  );
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', className, type = 'button', ...props },
  ref,
) {
  return <button ref={ref} type={type} className={buttonClass(variant, size, className)} {...props} />;
});
