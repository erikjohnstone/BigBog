/**
 * Qualification wizard state and the request it produces. Kept apart from
 * the dialog so the request assembly (and its boundary validation) is unit
 * tested without rendering.
 */

import type { BoptestTestCaseContract, ControlGraph, FmiModel } from '../../api/client';
import { buildAlfalfaMapping, buildAlfalfaOracles } from './alfalfa-mapping';
import type { AlfalfaOracleDraft, CommandBindingDraft, SensorBindingDraft } from './alfalfa-mapping';
import { buildBoptestQualification, validateBoptestQualificationBoundary } from './boptest-mapping';
import type { BoptestActuatorBindingDraft, BoptestMeasurementBindingDraft, BoptestOracleDraft, BoptestScenarioDraft } from './boptest-mapping';

export type QualificationKind = 'boptest' | 'alfalfa';
export type Step = 'source' | 'bindings' | 'oracles' | 'review';

export type OracleDraft = { id: string; signalKind: string; signal: string; referenceValues: string; timeTolerance: string; valueTolerance: string };

export interface WizardState {
  kind: QualificationKind;
  step: Step;
  testCase: string;
  contract: BoptestTestCaseContract | null;
  file: File | null;
  model: FmiModel | null;
  measurements: Record<string, BoptestMeasurementBindingDraft>;
  actuators: Record<string, BoptestActuatorBindingDraft>;
  sensors: Record<string, SensorBindingDraft>;
  commands: Record<string, CommandBindingDraft>;
  observed: string[];
  oracles: OracleDraft[];
  steps: string;
  stepSeconds: string;
  startTime: string;
  warmup: string;
  start: string;
  transport: 'direct' | 'bacnet_ip_loopback';
  scenario: BoptestScenarioDraft;
}

export function initialState(kind: QualificationKind): WizardState {
  return {
    kind,
    step: 'source',
    testCase: '',
    contract: null,
    file: null,
    model: null,
    measurements: {},
    actuators: {},
    sensors: {},
    commands: {},
    observed: [],
    oracles: [],
    steps: '12',
    stepSeconds: '300',
    startTime: '0',
    warmup: '0',
    start: new Date(Date.UTC(new Date().getUTCFullYear(), 0, 1)).toISOString().slice(0, 19),
    transport: 'direct',
    scenario: { timePeriod: '', electricityPrice: '', temperatureUncertainty: '', solarUncertainty: '', seed: '' },
  };
}

export function graphIo(graph: ControlGraph | undefined) {
  const blocks = graph?.blocks ?? [];
  return { inputs: blocks.filter((block) => block.kind.endsWith('_input')), outputs: blocks.filter((block) => block.kind.endsWith('_output')) };
}

function toInt(value: string): number {
  return Number.parseInt(value, 10);
}

/** The request as the server will receive it, or the first reason it cannot be built. */
export function buildRequest(state: WizardState, graph: ControlGraph | undefined): { request: unknown; error: string | null } {
  const { inputs, outputs } = graphIo(graph);
  try {
    const steps = toInt(state.steps);
    const stepSeconds = Number(state.stepSeconds);
    if (state.kind === 'boptest') {
      if (!state.contract) throw new Error('Inspect a BOPTEST test case first');
      const qualification = buildBoptestQualification(
        state.testCase,
        inputs,
        outputs,
        state.measurements,
        state.actuators,
        state.oracles as BoptestOracleDraft[],
        steps,
        stepSeconds,
        state.startTime,
        state.warmup,
        state.scenario,
      );
      validateBoptestQualificationBoundary(qualification, outputs, state.contract);
      return { request: qualification, error: null };
    }
    if (!state.model || !state.file) throw new Error('Inspect an FMU first');
    const bound = Object.values(state.sensors).map((draft) => draft.output).filter(Boolean);
    const observed = [...new Set([...bound, ...state.observed])];
    const mapping = buildAlfalfaMapping(inputs, outputs, state.sensors, state.commands, observed);
    const oracles = buildAlfalfaOracles(state.oracles as AlfalfaOracleDraft[], steps, stepSeconds);
    if (!state.start.trim()) throw new Error('A simulation start timestamp is required');
    return { request: { mapping, oracles, steps, step_seconds: stepSeconds, start: state.start, transport: state.transport }, error: null };
  } catch (error) {
    return { request: null, error: error instanceof Error ? error.message : String(error) };
  }
}
