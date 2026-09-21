import type { ControlGraph, FmiVariable } from '../../api/client';

export type SensorBindingDraft = { output: string; scale: string; offset: string; initial: string };
export type CommandBindingDraft = { input: string; scale: string; offset: string; minimum: string; maximum: string; echo: string };
export type AlfalfaOracleSignalKind = 'graph_input' | 'graph_output' | 'fmu_input' | 'fmu_output';
export type AlfalfaOracleDraft = {
  id: string;
  signalKind: AlfalfaOracleSignalKind;
  signal: string;
  referenceValues: string;
  timeTolerance: string;
  valueTolerance: string;
};
export type AlfalfaOracle = {
  id: string;
  signal_kind: AlfalfaOracleSignalKind;
  signal: string;
  reference_times: number[];
  reference_values: number[];
  absolute_time_tolerance: number;
  absolute_value_tolerance: number;
};

export function signalLabel(variable: FmiVariable): string {
  const bounds = variable.minimum !== null || variable.maximum !== null ? `${variable.minimum ?? '−∞'}…${variable.maximum ?? '∞'}` : null;
  const metadata = [variable.data_type, variable.unit, bounds].filter(Boolean).join(' · ');
  return `${variable.name}${metadata ? ` — ${metadata}` : ''}`;
}

function normalizedSignal(value: string): string {
  return value.toLowerCase().replaceAll(/[^a-z0-9]/g, '');
}

export function exactSignalMatch(id: string, label: string, variables: FmiVariable[]): string {
  const desired = new Set([normalizedSignal(id), normalizedSignal(label)]);
  const matches = variables.filter((variable) => desired.has(normalizedSignal(variable.name)));
  return matches.length === 1 ? matches[0].name : '';
}

function numericDraft(value: string, label: string, optional = false): number | undefined {
  if (optional && value.trim() === '') return undefined;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new Error(`${label} must be a finite number`);
  return parsed;
}

function initialDraft(value: string): number | boolean | undefined {
  const normalized = value.trim().toLowerCase();
  if (!normalized) return undefined;
  if (normalized === 'true') return true;
  if (normalized === 'false') return false;
  return numericDraft(value, 'Tick-zero fallback');
}

export function buildAlfalfaMapping(
  graphInputs: ControlGraph['blocks'],
  graphOutputs: ControlGraph['blocks'],
  sensors: Record<string, SensorBindingDraft>,
  commands: Record<string, CommandBindingDraft>,
  observedOutputs: string[],
): unknown {
  const inputs = graphOutputs.map((block) => {
    const draft = commands[block.id];
    if (!draft?.input) throw new Error(`Graph output ${block.id} has no reviewed FMU input`);
    return {
      graph_output: block.id,
      input: draft.input,
      scale: numericDraft(draft.scale, `${block.id} scale`),
      offset: numericDraft(draft.offset, `${block.id} offset`),
      minimum: numericDraft(draft.minimum, `${block.id} minimum`, true),
      maximum: numericDraft(draft.maximum, `${block.id} maximum`, true),
    };
  });
  const outputs = graphInputs.map((block) => {
    const draft = sensors[block.id];
    if (!draft?.output) throw new Error(`Graph input ${block.id} has no reviewed FMU output`);
    return {
      graph_input: block.id,
      output: draft.output,
      scale: numericDraft(draft.scale, `${block.id} scale`),
      offset: numericDraft(draft.offset, `${block.id} offset`),
      initial_output_value: initialDraft(draft.initial),
    };
  });
  const command_echoes = Object.fromEntries(graphOutputs.flatMap((block) => {
    const draft = commands[block.id];
    return draft?.input && draft.echo ? [[draft.input, draft.echo]] : [];
  }));
  return { outputs, inputs, observed_outputs: observedOutputs, command_echoes, echo_tolerance: 1e-6 };
}

export function buildAlfalfaOracles(
  drafts: AlfalfaOracleDraft[],
  steps: number,
  stepSeconds: number,
): AlfalfaOracle[] {
  if (!Number.isInteger(steps) || steps < 1) throw new Error('Oracle steps must be a positive integer');
  if (!Number.isFinite(stepSeconds) || stepSeconds <= 0) throw new Error('Oracle step seconds must be positive');
  if (!drafts.length) throw new Error('At least one independent trajectory oracle is required');
  const ids = drafts.map((draft) => draft.id.trim());
  if (new Set(ids).size !== ids.length) throw new Error('Trajectory oracle IDs must be unique');
  return drafts.map((draft) => {
    const id = draft.id.trim();
    if (!/^[A-Za-z][A-Za-z0-9_.-]{0,119}$/.test(id)) throw new Error(`Oracle ID ${id || '(blank)'} is invalid`);
    if (!draft.signal) throw new Error(`Oracle ${id} has no reviewed signal`);
    const parsed = draft.referenceValues.trim().split(/[\s,]+/).filter(Boolean).map(Number);
    if (!parsed.length || parsed.some((value) => !Number.isFinite(value))) throw new Error(`Oracle ${id} expected values must be finite numbers`);
    const referenceValues = parsed.length === 1 ? Array.from({ length: steps }, () => parsed[0]) : parsed;
    if (referenceValues.length !== steps) throw new Error(`Oracle ${id} requires one value or exactly ${steps} trajectory values`);
    const absoluteTimeTolerance = numericDraft(draft.timeTolerance, `${id} time tolerance`);
    const absoluteValueTolerance = numericDraft(draft.valueTolerance, `${id} value tolerance`);
    if (absoluteTimeTolerance! < 0 || absoluteValueTolerance! < 0) throw new Error(`Oracle ${id} tolerances cannot be negative`);
    return {
      id,
      signal_kind: draft.signalKind,
      signal: draft.signal,
      reference_times: Array.from({ length: steps }, (_, index) => (index + 1) * stepSeconds),
      reference_values: referenceValues,
      absolute_time_tolerance: absoluteTimeTolerance!,
      absolute_value_tolerance: absoluteValueTolerance!,
    };
  });
}
