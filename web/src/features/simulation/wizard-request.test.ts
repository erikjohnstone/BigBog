import { describe, expect, it } from 'vitest';

import type { BoptestTestCaseContract, ControlGraph, FmiModel } from '../../api/client';
import { buildRequest, initialState } from './wizard-request';

const graph = {
  blocks: [
    { id: 'zone_temperature', kind: 'numeric_input', label: 'Zone Temperature', x: 0, y: 0, config: {} },
    { id: 'fan_command', kind: 'numeric_output', label: 'Fan Command', x: 0, y: 0, config: {} },
    { id: 'gain', kind: 'numeric_gain', label: 'Gain', x: 0, y: 0, config: {} },
  ],
  links: [],
} as unknown as ControlGraph;

const contract: BoptestTestCaseContract = {
  schema: 'bactalk.boptest-test-case-contract/v1',
  version: '0.7',
  test_case: 'bestest_air',
  measurements: [{ name: 'reaTZon_y', unit: 'K', description: null, minimum: null, maximum: null, activation_signal: false }],
  inputs: [
    { name: 'oveFan_u', unit: '1', description: null, minimum: 0, maximum: 1, activation_signal: false },
    { name: 'oveFan_activate', unit: null, description: null, minimum: null, maximum: null, activation_signal: true },
  ],
  measurement_count: 1,
  input_count: 2,
  clean_stop: true,
  initialized: false,
  live_building_writes: false,
};

describe('buildRequest', () => {
  it('refuses to build before the source is inspected', () => {
    expect(buildRequest(initialState('boptest'), graph).error).toMatch(/inspect a boptest/i);
    expect(buildRequest(initialState('alfalfa'), graph).error).toMatch(/inspect an fmu/i);
  });

  it('assembles and boundary-checks a BOPTEST qualification', () => {
    const state = {
      ...initialState('boptest'),
      testCase: 'bestest_air',
      contract,
      measurements: { zone_temperature: { measurement: 'reaTZon_y', scale: '1', offset: '0' } },
      actuators: { fan_command: { actuator: 'oveFan_u', activation: 'oveFan_activate', scale: '1', offset: '0' } },
      oracles: [{ id: 'fan', signalKind: 'graph_output', signal: 'fan_command', referenceValues: '1', timeTolerance: '0', valueTolerance: '0.1' }],
      steps: '3',
      stepSeconds: '60',
    };
    const built = buildRequest(state, graph);
    expect(built.error).toBeNull();
    expect(built.request).toMatchObject({
      mapping: { test_case: 'bestest_air', measurements: [{ graph_input: 'zone_temperature', measurement: 'reaTZon_y' }], actuators: [{ graph_output: 'fan_command', actuator: 'oveFan_u', activation_actuator: 'oveFan_activate' }] },
      oracles: [{ id: 'fan', reference_times: [60, 120, 180], reference_values: [1, 1, 1] }],
      steps: 3,
      step_seconds: 60,
    });
    // A measurement the case does not advertise is rejected before it is sent.
    const wrong = buildRequest({ ...state, measurements: { zone_temperature: { measurement: 'reaTOut_y', scale: '1', offset: '0' } } }, graph);
    expect(wrong.error).toMatch(/not advertised as a measurement/);
  });

  it('assembles an Alfalfa request with bound outputs always observed', () => {
    const model = {
      schema: 'bactalk.fmi-model-description/v1',
      filename: 'b.fmu',
      sha256: 'x',
      bytes: 1,
      fmi_version: '2.0',
      model_name: 'B',
      guid: null,
      instantiation_token: null,
      generation_tool: null,
      model_identifiers: [],
      platforms: [],
      inputs: [{ name: 'fan', value_reference: null, causality: 'input', variability: null, initial: null, data_type: 'Real', unit: null, minimum: null, maximum: null, start: null, description: null }],
      outputs: [{ name: 'TZone', value_reference: null, causality: 'output', variability: null, initial: null, data_type: 'Real', unit: 'K', minimum: null, maximum: null, start: null, description: null }],
      parameter_count: 0,
      local_variable_count: 0,
      variable_count: 2,
      live_building_writes: false,
    } satisfies FmiModel;
    const state = {
      ...initialState('alfalfa'),
      file: new File(['x'], 'b.fmu'),
      model,
      sensors: { zone_temperature: { output: 'TZone', scale: '1', offset: '0', initial: '' } },
      commands: { fan_command: { input: 'fan', scale: '1', offset: '0', minimum: '', maximum: '', echo: '' } },
      observed: ['TZone'],
      oracles: [{ id: 'fan', signalKind: 'graph_output', signal: 'fan_command', referenceValues: '0.5', timeTolerance: '0', valueTolerance: '0.1' }],
      steps: '2',
      stepSeconds: '30',
      start: '2026-01-01T00:00:00',
      transport: 'bacnet_ip_loopback' as const,
    };
    const built = buildRequest(state, graph);
    expect(built.error).toBeNull();
    expect(built.request).toMatchObject({ mapping: { observed_outputs: ['TZone'] }, steps: 2, step_seconds: 30, start: '2026-01-01T00:00:00', transport: 'bacnet_ip_loopback' });
  });
});
