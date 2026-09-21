import { forwardRef } from 'react';
import type { InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from 'react';

import { cn } from '../cn';

export function Field({
  label,
  hint,
  error,
  children,
  className,
  htmlFor,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  className?: string;
  htmlFor?: string;
}) {
  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <label htmlFor={htmlFor} className="text-xs font-medium text-fg-1">
        {label}
      </label>
      {children}
      {error ? (
        <span role="alert" className="text-2xs text-fail">
          {error}
        </span>
      ) : hint ? (
        <span className="text-2xs text-fg-2">{hint}</span>
      ) : null}
    </div>
  );
}

const inputBase =
  'raised w-full text-sm text-fg-0 placeholder:text-fg-2 outline-none focus-visible:border-accent disabled:opacity-50 transition-colors duration-[var(--duration-micro)]';

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { mono?: boolean }>(
  function Input({ className, mono, ...props }, ref) {
    return <input ref={ref} className={cn(inputBase, 'h-8 px-2.5', mono && 'font-mono text-xs', className)} {...props} />;
  },
);

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & { mono?: boolean }>(
  function Textarea({ className, mono, ...props }, ref) {
    return (
      <textarea
        ref={ref}
        className={cn(inputBase, 'px-2.5 py-2 min-h-24 resize-y', mono && 'font-mono text-xs', className)}
        {...props}
      />
    );
  },
);
