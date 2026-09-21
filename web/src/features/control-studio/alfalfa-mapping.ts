import type { ControlGraph, FmiVariable } from '../../api/client';

export type SensorBindingDraft = { output: string; scale: string; offset: string; initial: string };
export type CommandBindingDraft = { input: string; scale: string; offset: string; minimum: string; maximum: string; echo: string };

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
