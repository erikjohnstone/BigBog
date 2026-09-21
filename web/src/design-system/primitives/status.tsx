/**
 * Status pills and badges. Color is never the only signal: every status
 * carries an icon and a label, and simulated evidence is always violet.
 */

import { AlertTriangle, Check, CircleDashed, CircleOff, FlaskConical, X } from 'lucide-react';
import type { ReactNode } from 'react';

import { cn } from '../cn';

export type Tone = 'ok' | 'fail' | 'warn' | 'info' | 'neutral' | 'offline' | 'sim';

const tones: Record<Tone, string> = {
  ok: 'bg-ok-soft text-ok border-ok/30',
  fail: 'bg-fail-soft text-fail border-fail/30',
  warn: 'bg-warn-soft text-warn border-warn/30',
  info: 'bg-accent-soft text-accent border-accent/30',
  neutral: 'bg-bg-2 text-fg-1 border-line-1',
  offline: 'bg-bg-2 text-offline border-line-1 border-dashed',
  sim: 'bg-sim-soft text-sim border-sim/30',
};

const toneIcons: Record<Tone, ReactNode> = {
  ok: <Check size={12} strokeWidth={2.5} />,
  fail: <X size={12} strokeWidth={2.5} />,
  warn: <AlertTriangle size={12} strokeWidth={2.5} />,
  info: <CircleDashed size={12} strokeWidth={2.5} />,
  neutral: null,
  offline: <CircleOff size={12} strokeWidth={2.5} />,
  sim: <FlaskConical size={12} strokeWidth={2.5} />,
};

export function StatusPill({
  tone,
  children,
  icon,
  className,
  title,
}: {
  tone: Tone;
  children: ReactNode;
  icon?: ReactNode | null;
  className?: string;
  title?: string;
}) {
  const resolvedIcon = icon === undefined ? toneIcons[tone] : icon;
  return (
    <span
      title={title}
      className={cn(
        'inline-flex items-center gap-1 h-5 px-1.5 rounded-pill border text-2xs font-semibold whitespace-nowrap',
        tones[tone],
        className,
      )}
    >
      {resolvedIcon}
      {children}
    </span>
  );
}

/** Map a run status string onto a tone and label. */
export function runStatusTone(status: string): { tone: Tone; label: string } {
  switch (status) {
    case 'approved':
      return { tone: 'ok', label: 'Approved' };
    case 'ready_for_review':
      return { tone: 'info', label: 'Ready for review' };
    case 'failed':
      return { tone: 'fail', label: 'Failed' };
    case 'rejected':
      return { tone: 'warn', label: 'Rejected' };
    default:
      return { tone: 'neutral', label: status.replaceAll('_', ' ') };
  }
}

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        'inline-flex items-center h-5 min-w-5 px-1 rounded-chip border border-line-2 bg-bg-2 text-2xs font-mono text-fg-1',
        className,
      )}
    >
      {children}
    </kbd>
  );
}

export function Dot({ tone, className }: { tone: Tone; className?: string }) {
  const colors: Record<Tone, string> = {
    ok: 'bg-ok',
    fail: 'bg-fail',
    warn: 'bg-warn',
    info: 'bg-accent',
    neutral: 'bg-fg-2',
    offline: 'bg-offline',
    sim: 'bg-sim',
  };
  return <span aria-hidden className={cn('inline-block size-1.5 rounded-full', colors[tone], className)} />;
}
