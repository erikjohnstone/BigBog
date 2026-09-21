/**
 * Build the list of bindable sources for a run: graphics-model widgets when
 * the run has a model, else the job's points. Either way the signal id is
 * the trace signal with the same name, when the trace has one.
 */

import type { GraphicsModel, RunDetail } from '../../../api/client';
import type { Trace } from '../../../stores/trace';
import type { SignalSource } from '../types';

function signalFor(trace: Trace | undefined, id: string): string | undefined {
  if (!trace) return undefined;
  // Run traces name points directly; evidence traces namespace them by side.
  for (const candidate of [id, `${id}.out`, `in.${id}`, `out.${id}`, `meas.${id}`]) {
    if (trace.signals.has(candidate)) return candidate;
  }
  return undefined;
}

export function sourcesFromGraphicsModel(model: GraphicsModel, trace: Trace | undefined): SignalSource[] {
  const seen = new Set<string>();
  const sources: SignalSource[] = [];
  for (const view of model.views) {
    for (const widget of view.widgets) {
      if (seen.has(widget.id)) continue;
      seen.add(widget.id);
      sources.push({
        id: widget.id,
        label: widget.label,
        kind: widget.data_type === 'boolean' ? 'boolean' : 'numeric',
        unit: widget.units ?? undefined,
        brick: widget.brick_class ?? null,
        role: widget.kind,
        signalId: signalFor(trace, widget.id),
      });
    }
  }
  return sources;
}

export function sourcesFromJob(run: RunDetail, trace: Trace | undefined): SignalSource[] {
  return run.job.points.map((point) => ({
    id: point.name,
    label: point.label,
    kind: point.data_type === 'boolean' ? 'boolean' : 'numeric',
    unit: point.units ?? undefined,
    brick: point.brick_class ?? null,
    role: point.role,
    signalId: signalFor(trace, point.name),
  }));
}

/** Trace signals that are not points, so a slot can also bind to an internal block value. */
export function sourcesFromTrace(trace: Trace | undefined, exclude: Set<string>): SignalSource[] {
  if (!trace) return [];
  const out: SignalSource[] = [];
  for (const signal of trace.signals.values()) {
    if (exclude.has(signal.id) || signal.source === 'slot' || signal.source === 'fault' || signal.source === 'effective') continue;
    out.push({ id: signal.id, label: signal.label, kind: signal.kind, unit: signal.unit, brick: null, role: signal.source, signalId: signal.id });
  }
  return out;
}
