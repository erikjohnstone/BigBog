/**
 * Which signals are on which trend pane, per trace. Panes are a viewer
 * preference; the evidence itself never changes. Persisted per trace in
 * sessionStorage so a reload keeps the engineer's arrangement.
 */

import { create } from 'zustand';

export interface Pane {
  id: string;
  title: string;
  unit?: string;
  signalIds: string[];
}

export interface TraceTrends {
  panes: Pane[];
  /** Boolean signals shown as lanes in the state ribbon. */
  ribbon: string[];
}

interface TrendsState {
  byTrace: Record<string, TraceTrends>;
  ensure: (traceId: string, defaults: () => TraceTrends) => TraceTrends;
  toggleSignal: (traceId: string, signalId: string, options: { kind: 'numeric' | 'boolean'; unit?: string; paneId?: string }) => void;
  removePane: (traceId: string, paneId: string) => void;
  reset: (traceId: string, defaults: () => TraceTrends) => void;
}

const KEY = 'bactalk.trends.v1';

function readAll(): Record<string, TraceTrends> {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Record<string, TraceTrends>) : {};
  } catch {
    return {};
  }
}

function persist(byTrace: Record<string, TraceTrends>): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(byTrace));
  } catch {
    // Session storage can be unavailable; the arrangement just does not persist.
  }
}

let paneCounter = 0;
export function newPaneId(): string {
  paneCounter += 1;
  return `pane-${Date.now().toString(36)}-${paneCounter}`;
}

export const useTrends = create<TrendsState>((set, get) => ({
  byTrace: readAll(),

  ensure(traceId, defaults) {
    const existing = get().byTrace[traceId];
    if (existing) return existing;
    const created = defaults();
    const byTrace = { ...get().byTrace, [traceId]: created };
    set({ byTrace });
    persist(byTrace);
    return created;
  },

  toggleSignal(traceId, signalId, options) {
    const current = get().byTrace[traceId];
    if (!current) return;
    let next: TraceTrends;
    if (options.kind === 'boolean') {
      const on = current.ribbon.includes(signalId);
      next = { ...current, ribbon: on ? current.ribbon.filter((id) => id !== signalId) : [...current.ribbon, signalId] };
    } else {
      const owner = current.panes.find((pane) => pane.signalIds.includes(signalId));
      if (owner) {
        next = {
          ...current,
          panes: current.panes
            .map((pane) => (pane.id === owner.id ? { ...pane, signalIds: pane.signalIds.filter((id) => id !== signalId) } : pane))
            .filter((pane) => pane.signalIds.length > 0),
        };
      } else {
        const target =
          (options.paneId && current.panes.find((pane) => pane.id === options.paneId)) ||
          current.panes.find((pane) => (pane.unit ?? '') === (options.unit ?? '') && pane.signalIds.length < 8);
        if (target) {
          next = { ...current, panes: current.panes.map((pane) => (pane.id === target.id ? { ...pane, signalIds: [...pane.signalIds, signalId] } : pane)) };
        } else {
          next = { ...current, panes: [...current.panes, { id: newPaneId(), title: options.unit ?? 'Values', unit: options.unit, signalIds: [signalId] }] };
        }
      }
    }
    const byTrace = { ...get().byTrace, [traceId]: next };
    set({ byTrace });
    persist(byTrace);
  },

  removePane(traceId, paneId) {
    const current = get().byTrace[traceId];
    if (!current) return;
    const byTrace = { ...get().byTrace, [traceId]: { ...current, panes: current.panes.filter((pane) => pane.id !== paneId) } };
    set({ byTrace });
    persist(byTrace);
  },

  reset(traceId, defaults) {
    const byTrace = { ...get().byTrace, [traceId]: defaults() };
    set({ byTrace });
    persist(byTrace);
  },
}));
