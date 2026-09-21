/**
 * Traces from high-fidelity evidence. BOPTEST and Alfalfa retain a
 * trajectory per step with the graph's inputs and outputs, the runtime's
 * measurements, and pyfunnel oracle results; this puts them on the same
 * seconds axis as the deterministic trace so every view can play them.
 *
 * Signal ids are namespaced so a graph input and a runtime measurement with
 * the same name never collide: `in.<name>`, `out.<name>`, `meas.<name>`,
 * `ovr.<name>`, `fmu.<name>`, `echo.<output>.<command|feedback|matched>`,
 * `oracle.<id>.ref`.
 */

import type { AlfalfaEvidence, BoptestEvidence } from '../api/client';
import type { OracleBand, Phase, Signal, SignalSource, Trace, TraceAssertion } from '../stores/trace';

type NumericMap = Record<string, number | boolean | null>;

interface Column {
  id: string;
  label: string;
  source: SignalSource;
  group?: string;
  blockId?: string;
  values: number[];
}

function nearestIndex(time: Float64Array, t: number): number {
  let lo = 0;
  let hi = time.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (time[mid] < t) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && Math.abs(time[lo - 1] - t) <= Math.abs(time[lo] - t)) return lo - 1;
  return lo;
}

function peakIndex(item: OracleLike, time: Float64Array, offsetSeconds: number, timeOffsetIdx: number, total: number): number {
  const peakTime = item.counterexample!.peak_error_time;
  const position = item.test_times.indexOf(peakTime);
  if (position >= 0) return Math.min(total - 1, timeOffsetIdx + position);
  return Math.min(total - 1, Math.max(0, nearestIndex(time, peakTime + offsetSeconds)));
}

function toSignal(column: Column, total: number): Signal {
  const values = new Float64Array(total);
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  let allBoolean = column.values.length > 0;
  for (let i = 0; i < total; i += 1) {
    const value = column.values[i];
    values[i] = value === undefined || value === null ? Number.NaN : value;
    if (Number.isFinite(values[i])) {
      min = Math.min(min, values[i]);
      max = Math.max(max, values[i]);
      if (values[i] !== 0 && values[i] !== 1) allBoolean = false;
    }
  }
  if (!Number.isFinite(min)) {
    min = 0;
    max = 0;
    allBoolean = false;
  }
  if (allBoolean && column.id.startsWith('echo.') && column.id.endsWith('.matched')) {
    const bytes = new Uint8Array(total);
    for (let i = 0; i < total; i += 1) bytes[i] = Number.isNaN(values[i]) ? 255 : values[i] ? 1 : 0;
    return { id: column.id, label: column.label, kind: 'boolean', source: column.source, group: column.group, blockId: column.blockId, values: bytes, min, max };
  }
  return { id: column.id, label: column.label, kind: 'numeric', source: column.source, group: column.group, blockId: column.blockId, values, min, max };
}

function collect(columns: Map<string, Column>, prefix: string, label: (name: string) => string, source: SignalSource, index: number, map: NumericMap | undefined, total: number, blockIdFor?: (name: string) => string | undefined, group?: string): void {
  if (!map) return;
  for (const [name, raw] of Object.entries(map)) {
    const id = `${prefix}.${name}`;
    let column = columns.get(id);
    if (!column) {
      column = { id, label: label(name), source, group, blockId: blockIdFor?.(name), values: new Array<number>(total).fill(Number.NaN) };
      columns.set(id, column);
    }
    column.values[index] = raw === null || raw === undefined ? Number.NaN : typeof raw === 'boolean' ? (raw ? 1 : 0) : raw;
  }
}

interface OracleLike {
  passed: boolean;
  max_error: number | null;
  test_times: number[];
  test_values: number[];
  counterexample?: { window: { start_index: number; end_index: number }; peak_error_time: number; peak_error: number } | null;
  oracle: { id: string; signal: string; signal_kind: string; reference_times: number[]; reference_values: number[]; absolute_value_tolerance: number };
}

function oracleSignalId(kind: string, signal: string): string {
  switch (kind) {
    case 'graph_output':
      return `out.${signal}`;
    case 'graph_input':
      return `in.${signal}`;
    case 'measurement':
    case 'fmu_output':
      return `meas.${signal}`;
    case 'fmu_input':
      return `fmu.${signal}`;
    default:
      return signal;
  }
}

function addOracles(oracles: OracleLike[], time: Float64Array, offsetSeconds: number, timeOffsetIdx: number, columns: Map<string, Column>, bands: OracleBand[], assertions: TraceAssertion[], phaseIndex: number, casePrefix: string): void {
  const total = time.length;
  for (const item of oracles) {
    const id = `${casePrefix}${item.oracle.id}`;
    const signalId = oracleSignalId(item.oracle.signal_kind, item.oracle.signal);
    const referenceId = `oracle.${id}.ref`;
    const reference = new Array<number>(total).fill(Number.NaN);
    // Oracle samples are positional: reference_times[i] and test_times[i] are
    // the i-th trajectory step of the case, so the reference is placed by index
    // and the counterexample peak is looked up by the test_times position.
    item.oracle.reference_values.forEach((value, i) => {
      const index = timeOffsetIdx + i;
      if (index >= 0 && index < total) reference[index] = value;
    });
    columns.set(referenceId, { id: referenceId, label: `${item.oracle.id} reference`, source: 'reference', group: item.oracle.id, values: reference });
    const window = item.counterexample
      ? {
          startIdx: Math.min(total - 1, timeOffsetIdx + item.counterexample.window.start_index),
          endIdx: Math.min(total - 1, timeOffsetIdx + item.counterexample.window.end_index),
          peakIdx: peakIndex(item, time, offsetSeconds, timeOffsetIdx, total),
          peakError: item.counterexample.peak_error,
        }
      : null;
    bands.push({ id, signalId, referenceSignalId: referenceId, tolerance: item.oracle.absolute_value_tolerance, passed: item.passed, maxError: item.max_error, window });
    const at = window ? window.peakIdx : Math.min(total - 1, timeOffsetIdx + Math.max(0, item.test_times.length - 1));
    assertions.push({
      id,
      name: `${item.oracle.id} within ±${item.oracle.absolute_value_tolerance} of reference`,
      passed: item.passed,
      observed: item.max_error === null ? 'incomplete' : `max error ${item.max_error.toFixed(3)}`,
      expected: `≤ ${item.oracle.absolute_value_tolerance}`,
      index: at,
      phaseIndex,
      blockIds: item.oracle.signal_kind === 'graph_output' || item.oracle.signal_kind === 'graph_input' ? [item.oracle.signal] : [],
      signalId,
    });
  }
}

export function boptestTraceId(runId: string): string {
  return `boptest:${runId}`;
}

export function buildBoptestTrace(runId: string, evidence: BoptestEvidence): Trace {
  const cases = evidence.schema === 'bactalk.boptest-qualification-suite/v1' ? evidence.cases.map((item) => ({ id: item.id, runtime: item.runtime, oracles: item.oracles, origin: item.oracle_clock.runtime_time_origin })) : [{ id: evidence.runtime.test_case, runtime: evidence.runtime, oracles: evidence.oracles, origin: evidence.runtime.trajectory[0]?.start_time ?? 0 }];
  const total = cases.reduce((sum, item) => sum + item.runtime.trajectory.length, 0);
  const time = new Float64Array(total);
  const columns = new Map<string, Column>();
  const phases: Phase[] = [];
  const bands: OracleBand[] = [];
  const assertions: TraceAssertion[] = [];
  let cursor = 0;
  let elapsed = 0;
  cases.forEach((item, caseIndex) => {
    const start = cursor;
    const origin = item.runtime.trajectory[0]?.start_time ?? 0;
    for (const step of item.runtime.trajectory) {
      time[cursor] = elapsed + (step.start_time - origin);
      collect(columns, 'in', (name) => name, 'input', cursor, step.graph_inputs, total, (name) => name);
      collect(columns, 'out', (name) => name, 'command', cursor, step.controller_outputs, total, (name) => name);
      collect(columns, 'meas', (name) => name, 'measurement', cursor, step.measurements, total, undefined, 'BOPTEST');
      collect(columns, 'ovr', (name) => `${name} override`, 'override', cursor, step.overrides, total, undefined, 'BOPTEST');
      cursor += 1;
    }
    const end = Math.max(start, cursor - 1);
    const last = item.runtime.trajectory[item.runtime.trajectory.length - 1];
    const stepSeconds = item.runtime.step_seconds;
    phases.push({ index: caseIndex, name: cases.length > 1 ? `${item.id}` : item.runtime.test_case, startIdx: start, endIdx: end, t0: time[start] ?? 0, t1: time[end] ?? 0, stepSeconds, faults: [] });
    // Oracle test_times are elapsed seconds from the case's runtime origin.
    addOracles(item.oracles, time, elapsed - (item.origin - origin), start, columns, bands, assertions, caseIndex, cases.length > 1 ? `${item.id}/` : '');
    elapsed = (last ? time[end] : elapsed) + stepSeconds;
  });
  const signals = new Map<string, Signal>();
  for (const column of columns.values()) signals.set(column.id, toSignal(column, total));
  return { id: boptestTraceId(runId), label: `BOPTEST · ${cases.map((item) => item.id).join(', ')}`, engine: 'boptest', time, phases, signals, assertions, faultWindows: [], oracles: bands, axisReconstructed: false, passed: evidence.status === 'pass' };
}

export function alfalfaTraceId(runId: string): string {
  return `alfalfa:${runId}`;
}

export function buildAlfalfaTrace(runId: string, evidence: AlfalfaEvidence): Trace {
  const total = evidence.trajectory.length;
  const time = new Float64Array(total);
  const columns = new Map<string, Column>();
  const origin = evidence.trajectory[0] ? Date.parse(evidence.trajectory[0].start_time) : 0;
  evidence.trajectory.forEach((step, index) => {
    const parsed = Date.parse(step.start_time);
    time[index] = Number.isFinite(parsed) && Number.isFinite(origin) ? (parsed - origin) / 1000 : index * evidence.step_seconds;
    collect(columns, 'in', (name) => name, 'input', index, step.graph_inputs, total, (name) => name);
    collect(columns, 'out', (name) => name, 'command', index, step.controller_outputs, total, (name) => name);
    collect(columns, 'fmu', (name) => `${name} (to FMU)`, 'command', index, step.fmu_inputs, total, undefined, 'FMU');
    collect(columns, 'meas', (name) => name, 'measurement', index, step.observed_outputs, total, undefined, 'FMU');
    for (const [output, echo] of Object.entries(step.command_echoes ?? {})) {
      collect(columns, `echo.${output}`, (name) => `${output} ${name}`, 'echo', index, { command: echo.command, feedback: echo.feedback, matched: echo.matched }, total, () => echo.output, 'BACnet echoes');
    }
  });
  const phases: Phase[] = [{ index: 0, name: evidence.model_name, startIdx: 0, endIdx: Math.max(0, total - 1), t0: time[0] ?? 0, t1: time[total - 1] ?? 0, stepSeconds: evidence.step_seconds, faults: [] }];
  const bands: OracleBand[] = [];
  const assertions: TraceAssertion[] = [];
  addOracles(evidence.oracles, time, 0, 0, columns, bands, assertions, 0, '');
  const signals = new Map<string, Signal>();
  for (const column of columns.values()) signals.set(column.id, toSignal(column, total));
  return { id: alfalfaTraceId(runId), label: `Alfalfa · ${evidence.model_name}`, engine: 'alfalfa', time, phases, signals, assertions, faultWindows: [], oracles: bands, axisReconstructed: false, passed: evidence.status === 'pass' };
}
