/**
 * Build a Trace (typed arrays on one seconds axis) from a run's retained
 * deterministic report. Two sample shapes exist:
 *
 * - Generic interpreter: `{step, phase?, phase_step?, <block>, <block>.<slot>,
 *   fault.<id>.<field>, effective.<target>}` per scan.
 * - Legacy G36 VAV simulator: `{minute, <point>...}` per minute.
 *
 * Scenarios are concatenated in report order, one phase each (timeline
 * scenarios split into sub-phases). The seconds axis comes from the
 * acceptance case's `step_seconds`; when a scenario cannot be matched to its
 * case the axis is reconstructed and the trace says so.
 */

import { z } from 'zod';

import type { BlockCatalog, ControlGraph, RunDetail, TestReport } from '../api/client';
import type { FaultWindow, Phase, Signal, SignalKind, SignalSource, Trace, TraceAssertion } from '../stores/trace';

const acceptanceCaseSchema = z
  .object({
    name: z.string(),
    repeat: z.number().default(1),
    step_seconds: z.number().default(1),
    expectations: z
      .array(z.object({ target: z.string() }).passthrough())
      .default([]),
    timeline: z
      .array(
        z
          .object({
            name: z.string().optional(),
            phase: z.string().optional(),
            repeat: z.number().optional(),
            step_seconds: z.number().optional(),
          })
          .passthrough(),
      )
      .default([]),
  })
  .passthrough();

type AcceptanceCase = z.infer<typeof acceptanceCaseSchema>;
type SampleValue = number | boolean | string | null;
type Sample = Record<string, SampleValue>;

const META_KEYS = new Set(['step', 'phase', 'phase_step', 'minute', 'scenario']);

function readCases(run: RunDetail): AcceptanceCase[] {
  const raw = (run.job as { acceptance_tests?: unknown }).acceptance_tests;
  if (!Array.isArray(raw)) return [];
  const cases: AcceptanceCase[] = [];
  for (const item of raw) {
    const parsed = acceptanceCaseSchema.safeParse(item);
    if (parsed.success) cases.push(parsed.data);
  }
  return cases;
}

function isBooleanColumn(scenarios: TestReport['scenarios'], key: string): boolean {
  let seen = false;
  for (const scenario of scenarios) {
    for (const sample of scenario.samples) {
      const value = sample[key];
      if (value === null || value === undefined) continue;
      if (typeof value !== 'boolean') return false;
      seen = true;
    }
  }
  return seen;
}

function toNumber(value: SampleValue | undefined): number {
  if (typeof value === 'number') return value;
  if (typeof value === 'boolean') return value ? 1 : 0;
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : Number.NaN;
  }
  return Number.NaN;
}

interface Classified {
  source: SignalSource;
  blockId?: string;
  slot?: string;
  group?: string;
  label: string;
}

function classify(key: string, blockIds: Set<string>, run: RunDetail, graph?: ControlGraph): Classified {
  const point = run.job.points.find((item) => item.name === key);
  const block = graph?.blocks.find((item) => item.id === key);
  if (key.startsWith('fault.')) {
    const [, id, field] = key.split('.');
    return { source: 'fault', group: id, label: `${id} ${field ?? ''}`.trim() };
  }
  if (key.startsWith('effective.')) {
    const target = key.slice('effective.'.length);
    return { source: 'effective', blockId: target, label: `${target} (effective)` };
  }
  if (block) {
    const source: SignalSource = block.kind.endsWith('_input') ? 'input' : block.kind.endsWith('_output') ? 'command' : 'block';
    return { source, blockId: key, label: point?.label ?? block.label };
  }
  // `block.slot`, or `Equip.block.slot` in a project trace whose block ids are qualified.
  for (const dot of [key.indexOf('.'), key.lastIndexOf('.')]) {
    if (dot <= 0) continue;
    const blockId = key.slice(0, dot);
    const slot = key.slice(dot + 1);
    if (blockIds.has(blockId)) {
      const owner = graph?.blocks.find((item) => item.id === blockId);
      return { source: 'slot', blockId, slot, label: `${owner?.label ?? blockId} · ${slot}` };
    }
  }
  if (point) {
    const sensor = point.role === 'sensor' || point.role === 'status';
    return { source: sensor ? 'input' : 'command', blockId: key, label: point.label };
  }
  return { source: 'block', blockId: key, label: key };
}

function slotKind(catalog: BlockCatalog | undefined, graph: ControlGraph | undefined, blockId: string | undefined, slot: string | undefined): SignalKind | null {
  if (!catalog || !graph || !blockId) return null;
  const block = graph.blocks.find((item) => item.id === blockId);
  if (!block) return null;
  const kind = catalog.kinds.find((item) => item.kind === block.kind);
  if (!kind) return null;
  const outputs = kind.outputs;
  const match = slot ? outputs.find((item) => item.name === slot) : outputs[0];
  if (!match) return null;
  return match.type === 'boolean' ? 'boolean' : 'numeric';
}

/** Target block of an assertion, derived from its case or its name. */
function assertionTargets(
  name: string,
  scenarioCase: AcceptanceCase | undefined,
  assertionIndex: number,
  assertionCount: number,
  blockIds: Set<string>,
): string[] {
  if (scenarioCase && scenarioCase.expectations.length === assertionCount) {
    const target = scenarioCase.expectations[assertionIndex]?.target;
    if (target && blockIds.has(target)) return [target];
  }
  const colon = name.lastIndexOf(': ');
  if (colon >= 0) {
    const suffix = name.slice(colon + 2).trim();
    if (blockIds.has(suffix)) return [suffix];
  }
  const hits = [...blockIds].filter((id) => name.includes(id));
  return hits.slice(0, 1);
}

export interface BuildTraceOptions {
  catalog?: BlockCatalog;
  graph?: ControlGraph;
}

export function traceIdForRun(runId: string): string {
  return `run:${runId}`;
}

export function buildTrace(run: RunDetail, report: TestReport, options: BuildTraceOptions = {}): Trace {
  const { catalog, graph } = options;
  const scenarios = report.scenarios;
  const cases = readCases(run);
  const blockIds = new Set<string>(graph ? graph.blocks.map((block) => block.id) : []);
  if (!graph) {
    // Without a graph, infer block ids from bare sample keys.
    for (const scenario of scenarios) {
      for (const key of Object.keys(scenario.samples[0] ?? {})) {
        if (!META_KEYS.has(key) && !key.includes('.')) blockIds.add(key);
      }
    }
  }

  const total = scenarios.reduce((sum, scenario) => sum + scenario.samples.length, 0);
  const time = new Float64Array(total);
  const phases: Phase[] = [];
  const assertions: TraceAssertion[] = [];
  let axisReconstructed = false;
  let legacy = false;

  // ---- time axis and phases -------------------------------------------
  let cursor = 0;
  let t = 0;
  scenarios.forEach((scenario, scenarioIndex) => {
    const scenarioCase = cases.find((item) => item.name === scenario.name);
    const samples = scenario.samples as Sample[];
    const n = samples.length;
    if (n === 0) {
      // No retained samples: the assertions still count, pinned to the last
      // sample so far on a zero-length phase the timeline draws as a mark.
      const at = Math.max(0, cursor - 1);
      const phase: Phase = {
        index: phases.length,
        name: scenario.name,
        startIdx: at,
        endIdx: at,
        t0: time[at] ?? 0,
        t1: time[at] ?? 0,
        stepSeconds: 0,
        faults: [],
      };
      phases.push(phase);
      scenario.assertions.forEach((assertion, assertionIndex) => {
        const targets = assertionTargets(assertion.name, scenarioCase, assertionIndex, scenario.assertions.length, blockIds);
        assertions.push({
          id: `${scenarioIndex}:${assertionIndex}`,
          name: assertion.name,
          passed: assertion.passed,
          observed: assertion.observed,
          expected: assertion.expected,
          index: at,
          phaseIndex: phase.index,
          blockIds: targets,
          signalId: targets[0],
        });
      });
      return;
    }
    const hasMinute = typeof samples[0].minute === 'number';
    if (hasMinute) legacy = true;
    const step = scenarioCase?.step_seconds ?? 1;
    if (!scenarioCase) axisReconstructed = true;
    else if (scenarioCase.timeline.length === 0 && scenarioCase.repeat !== n) axisReconstructed = true;

    const start = cursor;
    const phaseStartT = t;
    for (let i = 0; i < n; i += 1) {
      if (hasMinute) {
        time[cursor] = phaseStartT + toNumber(samples[i].minute) * 60;
      } else {
        time[cursor] = i === 0 ? t : time[cursor - 1] + phaseStep(samples[i], scenarioCase, step);
      }
      cursor += 1;
    }
    const end = cursor - 1;
    t = time[end] + (hasMinute ? 60 : step);

    // Sub-phases for timeline scenarios.
    const subPhases: Array<{ name: string; startIdx: number; endIdx: number }> = [];
    if (typeof samples[0].phase === 'string') {
      let current: string | null = null;
      for (let i = 0; i < n; i += 1) {
        const name = String(samples[i].phase);
        if (name !== current) {
          subPhases.push({ name, startIdx: start + i, endIdx: start + i });
          current = name;
        } else {
          subPhases[subPhases.length - 1].endIdx = start + i;
        }
      }
    }
    const firstPhaseIndex = phases.length;
    if (subPhases.length > 1) {
      for (const sub of subPhases) {
        phases.push({
          index: phases.length,
          name: `${scenario.name} · ${sub.name}`,
          startIdx: sub.startIdx,
          endIdx: sub.endIdx,
          t0: time[sub.startIdx],
          t1: time[sub.endIdx],
          stepSeconds: step,
          faults: [],
        });
      }
    } else {
      phases.push({
        index: phases.length,
        name: scenario.name,
        startIdx: start,
        endIdx: end,
        t0: time[start],
        t1: time[end],
        stepSeconds: hasMinute ? 60 : step,
        faults: [],
      });
    }
    const lastPhaseIndex = phases.length - 1;
    const scenarioPhases = phases.slice(firstPhaseIndex);

    scenario.assertions.forEach((assertion, assertionIndex) => {
      const targets = assertionTargets(assertion.name, scenarioCase, assertionIndex, scenario.assertions.length, blockIds);
      // Timeline assertions name their sub-phase; place them at that phase's end.
      const owner =
        scenarioPhases.length > 1
          ? scenarioPhases.find((phase) => assertion.name.includes(phase.name.slice(scenario.name.length + 3)))
          : undefined;
      const phase = owner ?? phases[lastPhaseIndex];
      assertions.push({
        id: `${scenarioIndex}:${assertionIndex}`,
        name: assertion.name,
        passed: assertion.passed,
        observed: assertion.observed,
        expected: assertion.expected,
        index: phase.endIdx,
        phaseIndex: phase.index,
        blockIds: targets,
        signalId: targets[0],
      });
    });
  });

  // ---- signals ----------------------------------------------------------
  const keys = new Set<string>();
  for (const scenario of scenarios) {
    for (const sample of scenario.samples) for (const key of Object.keys(sample)) keys.add(key);
  }
  const signals = new Map<string, Signal>();
  for (const key of keys) {
    if (META_KEYS.has(key)) continue;
    const meta = classify(key, blockIds, run, graph);
    const declared = slotKind(catalog, graph, meta.blockId, meta.slot);
    const kind: SignalKind = declared ?? (isBooleanColumn(scenarios, key) ? 'boolean' : 'numeric');
    const point = run.job.points.find((item) => item.name === (meta.blockId ?? key));
    let min = Number.POSITIVE_INFINITY;
    let max = Number.NEGATIVE_INFINITY;
    let values: Float64Array | Uint8Array;
    if (kind === 'boolean') {
      const array = new Uint8Array(total);
      let i = 0;
      for (const scenario of scenarios) {
        for (const sample of scenario.samples) {
          const value = sample[key];
          array[i] = value === null || value === undefined ? 255 : toNumber(value) ? 1 : 0;
          if (array[i] !== 255) {
            min = Math.min(min, array[i]);
            max = Math.max(max, array[i]);
          }
          i += 1;
        }
      }
      values = array;
    } else {
      const array = new Float64Array(total);
      let i = 0;
      for (const scenario of scenarios) {
        for (const sample of scenario.samples) {
          const value = toNumber(sample[key]);
          array[i] = value;
          if (Number.isFinite(value)) {
            min = Math.min(min, value);
            max = Math.max(max, value);
          }
          i += 1;
        }
      }
      values = array;
    }
    if (!Number.isFinite(min)) {
      min = 0;
      max = 0;
    }
    signals.set(key, {
      id: key,
      label: meta.label,
      kind,
      source: meta.source,
      unit: point?.units ?? undefined,
      blockId: meta.blockId,
      slot: meta.slot,
      group: meta.group,
      values,
      min,
      max,
    });
  }

  // ---- fault windows ----------------------------------------------------
  const declarations = report.coverage?.fault_injection?.declarations ?? [];
  const faultWindows: FaultWindow[] = [];
  for (const signal of signals.values()) {
    if (signal.source !== 'fault' || !signal.id.endsWith('.active')) continue;
    const id = signal.id.split('.')[1];
    const declaration = declarations.find((item) => item.id === id);
    let open: number | null = null;
    for (let i = 0; i <= total; i += 1) {
      const active = i < total && signal.values[i] === 1;
      if (active && open === null) open = i;
      if (!active && open !== null) {
        faultWindows.push({
          id,
          kind: declaration?.kind ?? 'fault',
          target: declaration?.target ?? id,
          qualityTarget: declaration?.quality_target ?? null,
          startIdx: open,
          endIdx: i - 1,
        });
        open = null;
      }
    }
  }
  for (const phase of phases) {
    phase.faults = declarations
      .filter((item) => item.phase === null || phase.name.endsWith(item.phase))
      .filter((item) => item.case === phase.name || phase.name.startsWith(`${item.case} ·`))
      .map((item) => ({
        id: item.id,
        kind: item.kind,
        target: item.target,
        qualityTarget: item.quality_target,
        scenario: item.case,
        phase: item.phase ?? '',
      }));
  }

  return {
    id: traceIdForRun(run.id),
    label: run.job.name,
    engine: legacy ? 'g36-legacy' : 'generic',
    time,
    phases,
    signals,
    assertions,
    faultWindows,
    oracles: [],
    axisReconstructed,
    passed: report.passed,
  };
}

function phaseStep(sample: Sample, scenarioCase: AcceptanceCase | undefined, fallback: number): number {
  if (!scenarioCase || typeof sample.phase !== 'string') return fallback;
  const entry = scenarioCase.timeline.find((item) => (item.name ?? item.phase) === sample.phase);
  return entry?.step_seconds ?? fallback;
}

/** The signal that carries a link's value: the slot sample, else the block sample. */
export function signalIdForOutput(trace: Trace | undefined, blockId: string, slot: string, firstOutput: string | undefined): string | undefined {
  if (!trace) return undefined;
  const slotted = `${blockId}.${slot}`;
  if (trace.signals.has(slotted)) return slotted;
  if ((slot === firstOutput || slot === 'out') && trace.signals.has(blockId)) return blockId;
  return undefined;
}

/** Phase containing a sample index. */
export function phaseAt(trace: Trace | undefined, index: number): Phase | undefined {
  return trace?.phases.find((phase) => index >= phase.startIdx && index <= phase.endIdx);
}

/**
 * Slot samples that duplicate their block sample (`X.out` when `X` exists and
 * is the block's only output) add nothing to a trend; hide them from rails.
 */
export function isRedundantSlot(trace: Trace, signal: Signal, outputsOf?: (blockId: string) => string[]): boolean {
  if (signal.source !== 'slot' || !signal.blockId || !signal.slot) return false;
  if (!trace.signals.has(signal.blockId)) return false;
  const outputs = outputsOf?.(signal.blockId);
  if (outputs && outputs.length > 1) return false;
  return signal.slot === 'out' || (outputs?.[0] ?? 'out') === signal.slot;
}
