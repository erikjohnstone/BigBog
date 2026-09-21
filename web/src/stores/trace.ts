/**
 * Trace store: simulation data as column-major typed arrays, outside React.
 *
 * A trace is one scenario's worth of samples turned into per-signal columns
 * with a shared time axis. Thousands of values change every scan during
 * playback; pushing those through React state would re-render the wiresheet
 * sixty times a second. Instead the arrays live here, the clock advances an
 * index, and subscribers read `values[index]` in one animation frame via
 * `useSignalRef`, writing straight to DOM text and CSS custom properties.
 *
 * `useSignalValue` is the React-friendly alternative for inspectors and
 * tables: a value that updates at most ~10 Hz.
 */

import { useCallback, useEffect, useRef, useSyncExternalStore } from 'react';
import type { RefObject } from 'react';

import { useTimeCursor } from './timeCursor';

export type SignalKind = 'numeric' | 'boolean';
export type SignalSource =
  | 'input'
  | 'block'
  | 'slot'
  | 'fault'
  | 'effective'
  | 'measurement'
  | 'command'
  | 'override'
  | 'echo'
  | 'bacnet'
  | 'actuator'
  | 'reference'
  | 'kpi';

export interface Signal {
  id: string;
  label: string;
  kind: SignalKind;
  source: SignalSource;
  unit?: string;
  blockId?: string;
  slot?: string;
  /** For grouping in the signal rail: equipment name, fault id, oracle id. */
  group?: string;
  values: Float64Array | Uint8Array;
  min: number;
  max: number;
}

export interface FaultDecl {
  id: string;
  kind: string;
  target: string;
  qualityTarget: string | null;
  scenario: string;
  phase: string;
}

export interface Phase {
  index: number;
  name: string;
  startIdx: number;
  /** Inclusive. */
  endIdx: number;
  t0: number;
  t1: number;
  stepSeconds: number;
  faults: FaultDecl[];
}

export interface TraceAssertion {
  id: string;
  name: string;
  passed: boolean;
  observed: string;
  expected: string;
  /** Sample index the assertion was evaluated at (end of its phase). */
  index: number;
  phaseIndex: number;
  /** Block ids this assertion observes, when derivable. */
  blockIds: string[];
  /** Signal id of the observed output, when derivable. */
  signalId?: string;
}

export interface FaultWindow {
  id: string;
  kind: string;
  target: string;
  qualityTarget: string | null;
  startIdx: number;
  endIdx: number;
}

export interface OracleBand {
  id: string;
  signalId: string;
  referenceSignalId: string;
  tolerance: number;
  passed: boolean;
  maxError: number | null;
  /** Counterexample window in sample indices when the oracle failed. */
  window: { startIdx: number; endIdx: number; peakIdx: number; peakError: number } | null;
}

export type TraceEngine = 'generic' | 'g36-legacy' | 'boptest' | 'alfalfa' | 'project' | 'bacnet-lab';

export interface Trace {
  id: string;
  label: string;
  engine: TraceEngine;
  /** Seconds from the start of the scenario; monotonic non-decreasing. */
  time: Float64Array;
  phases: Phase[];
  signals: Map<string, Signal>;
  assertions: TraceAssertion[];
  faultWindows: FaultWindow[];
  oracles: OracleBand[];
  /** True when the seconds axis was reconstructed rather than declared. */
  axisReconstructed: boolean;
  passed: boolean;
}

type Listener = () => void;

class TraceStore {
  private traces = new Map<string, Trace>();
  private listeners = new Set<Listener>();

  get(id: string): Trace | undefined {
    return this.traces.get(id);
  }

  has(id: string): boolean {
    return this.traces.has(id);
  }

  put(trace: Trace): void {
    this.traces.set(trace.id, trace);
    this.emit();
  }

  remove(id: string): void {
    if (this.traces.delete(id)) this.emit();
  }

  ids(): string[] {
    return [...this.traces.keys()];
  }

  signal(traceId: string, signalId: string): Signal | undefined {
    return this.traces.get(traceId)?.signals.get(signalId);
  }

  /** NaN when the trace, signal, or index is missing. */
  valueAt(traceId: string, signalId: string, index: number): number {
    const signal = this.signal(traceId, signalId);
    if (!signal || index < 0 || index >= signal.values.length) return Number.NaN;
    const raw = signal.values[index];
    if (signal.kind === 'boolean') return raw === 255 ? Number.NaN : raw;
    return raw;
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(): void {
    for (const listener of this.listeners) listener();
  }
}

export const traceStore = new TraceStore();

/* ------------------------------------------------------------------ */
/* Frame fan-out: one subscription to the clock, many DOM writes.       */
/* ------------------------------------------------------------------ */

export interface SignalBinding {
  element: HTMLElement | SVGElement;
  signalId: string;
  /** Called every frame with the current value; default writes textContent. */
  apply?: (element: HTMLElement | SVGElement, value: number, signal: Signal | undefined) => void;
  /**
   * Level-of-detail group. A view pauses a whole group (for example every
   * wiresheet chip while zoomed out past legibility) so the frame skips
   * DOM writes nobody can read.
   */
  group?: string;
}

const bindings = new Set<SignalBinding>();
const pausedGroups = new Set<string>();
let frameScheduled = false;
let lastIndex = -1;
let lastTraceId: string | null = null;

/** Pause or resume every binding in a group; resuming repaints the group. */
export function setBindingGroupActive(group: string, active: boolean): void {
  const paused = pausedGroups.has(group);
  if (active && paused) {
    pausedGroups.delete(group);
    lastIndex = -1;
    scheduleFlush();
  } else if (!active && !paused) {
    pausedGroups.add(group);
  }
}

export function isBindingGroupActive(group: string): boolean {
  return !pausedGroups.has(group);
}

export function formatSignalValue(value: number, signal: Signal | undefined): string {
  if (Number.isNaN(value)) return '—';
  if (signal?.kind === 'boolean') return value ? 'true' : 'false';
  const abs = Math.abs(value);
  const digits = abs >= 1000 ? 0 : abs >= 100 ? 1 : abs >= 10 ? 2 : 3;
  return value.toFixed(digits);
}

function defaultApply(element: HTMLElement | SVGElement, value: number, signal: Signal | undefined): void {
  const text = formatSignalValue(value, signal);
  if (element.textContent !== text) element.textContent = text;
}

function flush(): void {
  frameScheduled = false;
  const { traceId, index } = useTimeCursor.getState();
  if (traceId === lastTraceId && index === lastIndex) return;
  lastTraceId = traceId;
  lastIndex = index;
  if (!traceId) return;
  for (const binding of bindings) {
    if (binding.group && pausedGroups.has(binding.group)) continue;
    const signal = traceStore.signal(traceId, binding.signalId);
    const value = traceStore.valueAt(traceId, binding.signalId, index);
    (binding.apply ?? defaultApply)(binding.element, value, signal);
  }
}

function scheduleFlush(): void {
  if (frameScheduled) return;
  frameScheduled = true;
  requestAnimationFrame(flush);
}

let clockSubscribed = false;
function ensureClockSubscription(): void {
  if (clockSubscribed) return;
  clockSubscribed = true;
  useTimeCursor.subscribe(scheduleFlush);
  traceStore.subscribe(() => {
    lastIndex = -1;
    scheduleFlush();
  });
}

/** Register a DOM element to receive a signal's value every frame. */
export function bindSignal(binding: SignalBinding): () => void {
  ensureClockSubscription();
  bindings.add(binding);
  // Paint immediately so a freshly mounted chip does not show a stale value.
  lastIndex = -1;
  scheduleFlush();
  return () => {
    bindings.delete(binding);
  };
}

/**
 * Ref hook for value chips and schematic symbols. The element's content or
 * CSS variables are updated in the animation frame; React never re-renders.
 */
export function useSignalRef<T extends HTMLElement | SVGElement = HTMLElement>(
  signalId: string | null | undefined,
  apply?: SignalBinding['apply'],
  group?: string,
): RefObject<T | null> {
  const ref = useRef<T | null>(null);
  useEffect(() => {
    const element = ref.current;
    if (!element || !signalId) return;
    return bindSignal({ element, signalId, apply, group });
  }, [signalId, apply, group]);
  return ref;
}

/** Throttled React value for inspectors; re-renders at most every 100 ms. */
export function useSignalValue(signalId: string | null | undefined): number {
  const subscribe = useCallback(
    (notify: () => void) => {
      if (!signalId) return () => {};
      let last = 0;
      let pending: number | null = null;
      const push = () => {
        const now = performance.now();
        if (now - last >= 100) {
          last = now;
          notify();
        } else if (pending === null) {
          pending = window.setTimeout(() => {
            pending = null;
            last = performance.now();
            notify();
          }, 100 - (now - last));
        }
      };
      const unsubscribe = useTimeCursor.subscribe(push);
      const unsubscribeTrace = traceStore.subscribe(push);
      return () => {
        unsubscribe();
        unsubscribeTrace();
        if (pending !== null) window.clearTimeout(pending);
      };
    },
    [signalId],
  );
  const read = useCallback(() => {
    if (!signalId) return Number.NaN;
    const { traceId, index } = useTimeCursor.getState();
    return traceId ? traceStore.valueAt(traceId, signalId, index) : Number.NaN;
  }, [signalId]);
  // Object.is(NaN, NaN) is true, so a missing value never loops.
  return useSyncExternalStore(subscribe, read, read);
}

/** React value of the current trace object; updates when traces change. */
export function useTrace(traceId: string | null | undefined): Trace | undefined {
  const subscribe = useCallback((notify: () => void) => traceStore.subscribe(notify), []);
  const read = useCallback(() => (traceId ? traceStore.get(traceId) : undefined), [traceId]);
  return useSyncExternalStore(subscribe, read, read);
}
