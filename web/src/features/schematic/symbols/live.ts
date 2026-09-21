/**
 * Bind a symbol's signals to CSS variables and data attributes on its SVG
 * group, in the animation frame. Values normalize to 0..1 (percent inputs
 * divide by 100); temperatures map to a hue from cool to warm across the
 * signal's observed range.
 */

import { useEffect, useRef } from 'react';
import type { RefObject } from 'react';

import { bindSignal, formatSignalValue } from '../../../stores/trace';
import type { Signal } from '../../../stores/trace';
import type { SymbolBindings } from '../types';

export const LOD_SCHEMATIC = 'schematic';

export function unit01(value: number, signal: Signal | undefined): number {
  if (Number.isNaN(value)) return 0;
  if (signal?.kind === 'boolean') return value ? 1 : 0;
  const max = Math.max(1, Math.abs(signal?.max ?? 1));
  const scale = max > 1.5 ? 100 : 1;
  return Math.min(1, Math.max(0, value / scale));
}

export function tempHue(value: number, signal: Signal | undefined): number {
  if (Number.isNaN(value) || !signal) return 200;
  const span = Math.max(1e-6, signal.max - signal.min);
  const ratio = Math.min(1, Math.max(0, (value - signal.min) / span));
  return 250 - ratio * 225;
}

export function useLiveSymbol<T extends SVGElement = SVGGElement>(bindings: SymbolBindings, unit?: string): RefObject<T | null> {
  const ref = useRef<T | null>(null);
  const key = JSON.stringify(bindings);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const unbinders: Array<() => void> = [];
    const setVar = (name: string, value: string) => {
      if (element.style.getPropertyValue(name) !== value) element.style.setProperty(name, value);
    };
    if (bindings.value) {
      const text = element.querySelector<SVGTextElement>('[data-live-value]');
      unbinders.push(
        bindSignal({
          element,
          signalId: bindings.value,
          group: LOD_SCHEMATIC,
          apply: (_element, value, signal) => {
            if (!text) return;
            const base = formatSignalValue(value, signal);
            const next = unit && !Number.isNaN(value) && signal?.kind !== 'boolean' ? `${base} ${unit}` : base;
            if (text.textContent !== next) text.textContent = next;
          },
        }),
      );
    }
    if (bindings.on) {
      unbinders.push(
        bindSignal({
          element,
          signalId: bindings.on,
          group: LOD_SCHEMATIC,
          apply: (_element, value) => {
            const on = Number.isNaN(value) ? 'unknown' : value >= 0.5 ? 'true' : 'false';
            if (element.dataset.on !== on) element.dataset.on = on;
          },
        }),
      );
    }
    if (bindings.position) {
      unbinders.push(
        bindSignal({
          element,
          signalId: bindings.position,
          group: LOD_SCHEMATIC,
          apply: (_element, value, signal) => setVar('--position', unit01(value, signal).toFixed(3)),
        }),
      );
    }
    if (bindings.speed) {
      unbinders.push(
        bindSignal({
          element,
          signalId: bindings.speed,
          group: LOD_SCHEMATIC,
          apply: (_element, value, signal) => {
            const speed = unit01(value, signal);
            setVar('--speed', speed.toFixed(3));
            const running = speed > 0 ? 'true' : 'false';
            if (element.dataset.running !== running) element.dataset.running = running;
          },
        }),
      );
    }
    if (bindings.temp) {
      unbinders.push(
        bindSignal({
          element,
          signalId: bindings.temp,
          group: LOD_SCHEMATIC,
          apply: (_element, value, signal) => setVar('--temp-h', tempHue(value, signal).toFixed(0)),
        }),
      );
    }
    for (const fault of bindings.faults ?? []) {
      const active = new Set<string>();
      unbinders.push(
        bindSignal({
          element,
          signalId: fault,
          group: LOD_SCHEMATIC,
          apply: (_element, value) => {
            if (value === 1) active.add(fault);
            else active.delete(fault);
            element.classList.toggle('fault-halo', active.size > 0);
          },
        }),
      );
    }
    return () => {
      unbinders.forEach((unbind) => unbind());
      element.classList.remove('fault-halo');
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, unit]);
  return ref;
}
