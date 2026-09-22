/**
 * Trace from Niagara Shadow Runtime evidence. The Shadow Runtime is a Python
 * model that executes the exported `.bog` (tier `bog-simulated`); it produces
 * a TestReport in the same shape as the deterministic interpreter, so the
 * scenarios and samples go through `buildTrace` unchanged and the three-way
 * differential is layered on top:
 *
 * - `ref.<signal>`: the reference engine's trajectory, resampled onto the
 *   trace's own axis inside each scenario's phase (nearest earlier sample,
 *   NaN outside), when the evidence retains a reference.
 * - one `OracleBand` per compared signal so the trend pane draws the band.
 * - one `TraceAssertion` per differential comparison so "jump to failure"
 *   lands on the first divergence.
 *
 * Nothing here is a Niagara runtime qualification.
 */

import type { RunDetail, ShadowDifferentialCase, ShadowEvidence } from '../api/client';
import type { OracleBand, Phase, Signal, Trace, TraceAssertion } from '../stores/trace';
import { buildTrace, signalIdForOutput } from './build-trace';
import type { BuildTraceOptions } from './build-trace';

export const SHADOW_TRACE_LABEL = 'Shadow Runtime · bog-simulated';

export function shadowTraceId(runId: string): string {
  return `shadow:${runId}`;
}

/** Index range of a scenario in the trace: its phase, or its sub-phases joined. */
function scenarioRange(phases: Phase[], name: string): { startIdx: number; endIdx: number } | null {
  const owned = phases.filter((phase) => phase.name === name || phase.name.startsWith(`${name} · `));
  if (owned.length === 0) return null;
  return { startIdx: Math.min(...owned.map((phase) => phase.startIdx)), endIdx: Math.max(...owned.map((phase) => phase.endIdx)) };
}

/** Largest k with times[k] <= t, or -1 when t precedes the first sample. */
function earlierSample(times: number[], t: number): number {
  let lo = 0;
  let hi = times.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid] <= t) {
      found = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return found;
}

/** Trace index inside [startIdx, endIdx] whose time is the latest at or before t0 + seconds. */
function indexAtOffset(time: Float64Array, startIdx: number, endIdx: number, seconds: number): number {
  const target = time[startIdx] + seconds;
  let at = startIdx;
  for (let i = startIdx; i <= endIdx; i += 1) {
    if (time[i] <= target) at = i;
    else break;
  }
  return at;
}

function resample(time: Float64Array, startIdx: number, endIdx: number, trajectory: { times: number[]; values: number[] }, into: Float64Array): void {
  const t0 = time[startIdx];
  for (let i = startIdx; i <= endIdx; i += 1) {
    const k = earlierSample(trajectory.times, time[i] - t0);
    into[i] = k < 0 ? Number.NaN : trajectory.values[k];
  }
}

function finishSignal(id: string, label: string, values: Float64Array): Signal {
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (const value of values) {
    if (Number.isFinite(value)) {
      min = Math.min(min, value);
      max = Math.max(max, value);
    }
  }
  if (!Number.isFinite(min)) {
    min = 0;
    max = 0;
  }
  return { id, label, kind: 'numeric', source: 'reference', group: 'Shadow Runtime', values, min, max };
}

function legSummary(comparison: ShadowDifferentialCase['signals'][number]): { maxError: number | null; firstViolation: number | null } {
  let maxError: number | null = null;
  let firstViolation: number | null = null;
  for (const leg of Object.values(comparison.legs)) {
    if (typeof leg.max_error === 'number') maxError = maxError === null ? leg.max_error : Math.max(maxError, leg.max_error);
    if (!leg.passed && typeof leg.first_violation_time === 'number') firstViolation = firstViolation === null ? leg.first_violation_time : Math.min(firstViolation, leg.first_violation_time);
  }
  return { maxError, firstViolation };
}

export function buildShadowTrace(run: RunDetail, evidence: ShadowEvidence, options: BuildTraceOptions = {}): Trace {
  const base = buildTrace(run, evidence.report, options);
  const total = base.time.length;
  const signals = new Map(base.signals);
  const oracles: OracleBand[] = [];
  const assertions: TraceAssertion[] = [...base.assertions];
  const references = new Map<string, Float64Array>();
  const lastPhase = base.phases[base.phases.length - 1];

  for (const item of evidence.differential.cases) {
    const range = scenarioRange(base.phases, item.name) ?? (lastPhase ? { startIdx: lastPhase.startIdx, endIdx: lastPhase.endIdx } : { startIdx: 0, endIdx: Math.max(0, total - 1) });
    const trajectories = evidence.reference?.[item.name];
    for (const comparison of item.signals) {
      const signalId = signalIdForOutput(base, comparison.signal, 'out', undefined) ?? comparison.signal;
      const tolerance = comparison.band.atoly ?? 0;
      const { maxError, firstViolation } = legSummary(comparison);
      const divergence = item.first_divergence && item.first_divergence.block === comparison.signal ? item.first_divergence.time_seconds : null;
      const violationSeconds = comparison.passed ? null : (firstViolation ?? divergence);

      const trajectory = trajectories?.[comparison.signal];
      const referenceId = `ref.${comparison.signal}`;
      if (trajectory && total > 0) {
        let column = references.get(referenceId);
        if (!column) {
          column = new Float64Array(total).fill(Number.NaN);
          references.set(referenceId, column);
        }
        resample(base.time, range.startIdx, range.endIdx, trajectory, column);
      }

      let window: OracleBand['window'] = null;
      if (violationSeconds !== null && total > 0) {
        const peakIdx = indexAtOffset(base.time, range.startIdx, range.endIdx, violationSeconds);
        window = { startIdx: Math.max(range.startIdx, peakIdx - 2), endIdx: Math.min(range.endIdx, peakIdx + 2), peakIdx, peakError: maxError ?? 0 };
      }
      const bandId = `shadow:${item.name}:${comparison.signal}`;
      if (trajectory && total > 0) {
        oracles.push({ id: bandId, signalId, referenceSignalId: referenceId, tolerance, passed: comparison.passed, maxError, window });
      }
      const at = window ? window.peakIdx : range.endIdx;
      const phase = base.phases.find((candidate) => at >= candidate.startIdx && at <= candidate.endIdx) ?? lastPhase;
      const known = base.signals.has(signalId) || options.graph?.blocks.some((block) => block.id === comparison.signal);
      assertions.push({
        id: bandId,
        name: `${item.name}: ${comparison.signal} within band`,
        passed: comparison.passed,
        observed: maxError === null ? (comparison.passed ? 'within band' : 'diverged') : `max error ${maxError.toFixed(3)}`,
        expected: `≤ ${tolerance}`,
        index: at,
        phaseIndex: phase?.index ?? 0,
        blockIds: known ? [comparison.signal] : [],
        signalId: known ? signalId : undefined,
      });
    }
  }

  for (const [id, values] of references) signals.set(id, finishSignal(id, `${id.slice('ref.'.length)} reference`, values));

  return {
    ...base,
    id: shadowTraceId(run.id),
    engine: 'shadow',
    label: SHADOW_TRACE_LABEL,
    signals,
    assertions,
    oracles,
    passed: evidence.status === 'pass',
  };
}
