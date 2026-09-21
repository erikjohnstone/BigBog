/**
 * Every route and panel has honest states: loading, empty, error, forbidden,
 * offline, and evidence that is missing or invalid. None of them pretends a
 * capability exists when it does not, and every failure names its remedy.
 */

import { AlertTriangle, CircleOff, FileQuestion, Lock, RefreshCw, WifiOff } from 'lucide-react';
import type { ReactNode } from 'react';

import { Button } from './primitives/button';
import { cn } from './cn';

interface StateProps {
  title: string;
  detail?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
  compact?: boolean;
  className?: string;
}

function StateShell({ title, detail, action, icon, compact, className }: StateProps) {
  return (
    <div
      role="status"
      className={cn(
        'flex flex-col items-center justify-center text-center gap-3',
        compact ? 'p-6' : 'p-12 min-h-[280px]',
        className,
      )}
    >
      {icon && <div className="text-fg-2">{icon}</div>}
      <div className="max-w-md">
        <p className="text-base font-medium text-fg-0">{title}</p>
        {detail && <div className="mt-1 text-sm text-fg-1">{detail}</div>}
      </div>
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

export function LoadingState({ label = 'Loading', compact }: { label?: string; compact?: boolean }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn('flex items-center justify-center gap-3 text-fg-2', compact ? 'p-6' : 'p-12 min-h-[280px]')}
    >
      <span className="size-4 rounded-full border-2 border-line-2 border-t-accent animate-spin motion-reduce:animate-none" />
      <span className="text-sm">{label}…</span>
    </div>
  );
}

export function EmptyState(props: StateProps) {
  return <StateShell icon={<FileQuestion size={28} strokeWidth={1.5} />} {...props} />;
}

export function ErrorState({
  error,
  onRetry,
  ...props
}: Partial<StateProps> & { error?: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : typeof error === 'string' ? error : undefined;
  return (
    <StateShell
      icon={<AlertTriangle size={28} strokeWidth={1.5} className="text-fail" />}
      title={props.title ?? 'This could not be loaded'}
      detail={props.detail ?? (message && <code className="text-xs break-all">{message}</code>)}
      action={
        props.action ??
        (onRetry && (
          <Button variant="secondary" size="sm" onClick={onRetry}>
            <RefreshCw size={14} /> Try again
          </Button>
        ))
      }
      compact={props.compact}
      className={props.className}
    />
  );
}

export function ForbiddenState(props: Partial<StateProps>) {
  return (
    <StateShell
      icon={<Lock size={28} strokeWidth={1.5} className="text-warn" />}
      title={props.title ?? 'Not permitted'}
      detail={props.detail ?? 'The server refused this action. Approval and export are decided server-side.'}
      {...props}
    />
  );
}

export function OfflineState(props: Partial<StateProps>) {
  return (
    <StateShell
      icon={<WifiOff size={28} strokeWidth={1.5} className="text-offline" />}
      title={props.title ?? 'BACTalk is unreachable'}
      detail={props.detail ?? 'The API did not answer. Check that the server is running and this browser is online.'}
      {...props}
    />
  );
}

/**
 * Evidence that the server reports as missing or invalid. Used wherever an
 * ArtifactState is not `available`, so the UI never renders a blank chart
 * where evidence should be.
 */
export function MissingEvidence({
  kind,
  state,
  detail,
  compact = true,
}: {
  kind: string;
  state: 'missing' | 'invalid';
  detail?: ReactNode;
  compact?: boolean;
}) {
  return (
    <StateShell
      compact={compact}
      icon={<CircleOff size={22} strokeWidth={1.5} className="text-offline" />}
      title={state === 'missing' ? `No ${kind} evidence retained` : `${kind} evidence is invalid`}
      detail={
        detail ??
        (state === 'missing'
          ? 'This candidate has not been qualified on this tier. Nothing here is inferred.'
          : 'The retained evidence did not pass its integrity check and is not shown.')
      }
    />
  );
}
