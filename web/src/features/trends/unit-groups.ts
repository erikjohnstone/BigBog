/**
 * Default trend composition: one pane per unit, booleans on the ribbon,
 * and only the signals an engineer looks at first (points, assertion
 * targets, faults) switched on. Everything else stays a click away in the
 * rail. Redundant slot samples are hidden.
 */

import type { Signal, Trace } from '../../stores/trace';
import type { TraceTrends } from '../../stores/trends';
import { isRedundantSlot } from '../../trace/build-trace';

export const MAX_SERIES_PER_PANE = 6;

export function unitLabel(unit: string | undefined): string {
  if (!unit) return 'Values';
  return unit;
}

export function visibleSignals(trace: Trace, outputsOf?: (blockId: string) => string[]): Signal[] {
  return [...trace.signals.values()].filter((signal) => !isRedundantSlot(trace, signal, outputsOf));
}

function priority(signal: Signal, assertionTargets: Set<string>): number {
  if (assertionTargets.has(signal.id)) return 0;
  if (signal.source === 'input' || signal.source === 'command') return 1;
  if (signal.source === 'fault' || signal.source === 'effective') return 2;
  return 3;
}

export function composeDefaultTrends(trace: Trace, outputsOf?: (blockId: string) => string[]): TraceTrends {
  const assertionTargets = new Set(trace.assertions.map((item) => item.signalId).filter((id): id is string => Boolean(id)));
  const signals = visibleSignals(trace, outputsOf);

  const ribbon = signals
    .filter((signal) => signal.kind === 'boolean')
    .filter((signal) => priority(signal, assertionTargets) <= 2 && !(signal.source === 'fault' && !signal.id.endsWith('.active')))
    .sort((a, b) => priority(a, assertionTargets) - priority(b, assertionTargets))
    .slice(0, 12)
    .map((signal) => signal.id);

  const byUnit = new Map<string, Signal[]>();
  for (const signal of signals) {
    if (signal.kind !== 'numeric') continue;
    if (signal.source === 'fault') continue;
    const key = signal.unit ?? '';
    byUnit.set(key, [...(byUnit.get(key) ?? []), signal]);
  }
  const panes: TraceTrends['panes'] = [];
  const order = [...byUnit.keys()].sort((a, b) => (a === '' ? 1 : b === '' ? -1 : a.localeCompare(b)));
  for (const unit of order) {
    const members = (byUnit.get(unit) ?? []).sort((a, b) => priority(a, assertionTargets) - priority(b, assertionTargets) || a.label.localeCompare(b.label));
    const chosen = members.filter((signal) => priority(signal, assertionTargets) <= 1).slice(0, MAX_SERIES_PER_PANE);
    // A unit with nothing "first-look" still gets its top few, so the pane exists.
    const ids = (chosen.length > 0 ? chosen : members.slice(0, Math.min(3, members.length))).map((signal) => signal.id);
    if (ids.length === 0) continue;
    panes.push({ id: `unit:${unit || 'none'}`, title: unitLabel(unit || undefined), unit: unit || undefined, signalIds: ids });
  }
  return { panes, ribbon };
}
