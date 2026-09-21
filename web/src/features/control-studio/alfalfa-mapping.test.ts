import { describe, expect, it } from 'vitest';

import type { ControlGraph, FmiVariable } from '../../api/client';
import { buildAlfalfaMapping, exactSignalMatch, signalLabel } from './alfalfa-mapping';

const variable = (name: string, overrides: Partial<FmiVariable> = {}): FmiVariable => ({
  name,
  value_reference: '1',
  causality: 'output',
  variability: 'continuous',
  initial: null,
  data_type: 'Real',
  unit: null,
  minimum: null,
  maximum: null,
  start: null,
  description: null,
  ...overrides,
});

const graphInputs: ControlGraph['blocks'] = [{ id: 'zone_temperature', kind: 'numeric_input', label: 'Zone Temperature', x: 0, y: 0, config: {} }];
const graphOutputs: ControlGraph['blocks'] = [{ id: 'fan_command', kind: 'numeric_output', label: 'Fan Command', x: 0, y: 0, config: {} }];

describe('Alfalfa mapping authoring', () => {
  it('suggests only one exact normalized signal', () => {
    const outputs = [variable('zone-temperature'), variable('unrelated')];
    expect(exactSignalMatch('zone_temperature', 'Zone Temperature', outputs)).toBe('zone-temperature');
    expect(exactSignalMatch('supply_temperature', 'Supply Temperature', outputs)).toBe('');
    expect(exactSignalMatch('zone_temperature', 'Zone Temperature', [...outputs, variable('zone temperature')])).toBe('');
  });

  it('builds explicit transforms, bounds, startup values, observations, and echoes', () => {
    expect(buildAlfalfaMapping(
      graphInputs,
      graphOutputs,
      { zone_temperature: { output: 'zone_T', scale: '1.8', offset: '-459.67', initial: 'true' } },
      { fan_command: { input: 'fan_u', scale: '0.01', offset: '0', minimum: '0', maximum: '1', echo: 'fan_y' } },
      ['supply_T'],
    )).toEqual({
      outputs: [{ graph_input: 'zone_temperature', output: 'zone_T', scale: 1.8, offset: -459.67, initial_output_value: true }],
      inputs: [{ graph_output: 'fan_command', input: 'fan_u', scale: 0.01, offset: 0, minimum: 0, maximum: 1 }],
      observed_outputs: ['supply_T'],
      command_echoes: { fan_u: 'fan_y' },
      echo_tolerance: 1e-6,
    });
  });

  it('blocks incomplete or nonfinite reviewed mappings', () => {
    expect(() => buildAlfalfaMapping(graphInputs, graphOutputs, {}, {}, [])).toThrow(/fan_command has no reviewed FMU input/);
    expect(() => buildAlfalfaMapping(
      graphInputs,
      graphOutputs,
      { zone_temperature: { output: 'zone_T', scale: 'NaN', offset: '0', initial: '' } },
      { fan_command: { input: 'fan_u', scale: '1', offset: '0', minimum: '', maximum: '', echo: '' } },
      [],
    )).toThrow(/zone_temperature scale must be a finite number/);
  });

  it('renders units and reviewed bounds in signal labels', () => {
    expect(signalLabel(variable('fan_u', { data_type: 'Float64', unit: '1', minimum: '0', maximum: '1' }))).toBe('fan_u — Float64 · 1 · 0…1');
  });
});
