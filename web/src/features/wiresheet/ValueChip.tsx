import { useCallback } from 'react';

import { cn } from '../../design-system/cn';
import { formatSignalValue, useSignalRef } from '../../stores/trace';
import type { Signal } from '../../stores/trace';

/**
 * A live value that updates in the animation frame without re-rendering.
 * `data-state` carries true/false/nan so CSS can tone it.
 */
export function ValueChip({
  signalId,
  kind,
  unit,
  className,
  title,
  group,
}: {
  signalId?: string;
  kind: 'numeric' | 'boolean';
  unit?: string;
  className?: string;
  title?: string;
  /** Level-of-detail group; see setBindingGroupActive. */
  group?: string;
}) {
  const apply = useCallback(
    (element: HTMLElement | SVGElement, value: number, signal: Signal | undefined) => {
      const text = formatSignalValue(value, signal ?? undefined);
      const next = unit && !Number.isNaN(value) && kind === 'numeric' ? `${text} ${unit}` : text;
      if (element.textContent !== next) element.textContent = next;
      const state = Number.isNaN(value) ? 'nan' : kind === 'boolean' ? (value ? 'true' : 'false') : 'num';
      if ((element as HTMLElement).dataset.state !== state) (element as HTMLElement).dataset.state = state;
    },
    [kind, unit],
  );
  const ref = useSignalRef<HTMLSpanElement>(signalId, apply, group);
  return (
    <span ref={ref} className={cn('chip', className)} data-state={signalId ? 'nan' : 'none'} title={title} aria-live="off">
      —
    </span>
  );
}
