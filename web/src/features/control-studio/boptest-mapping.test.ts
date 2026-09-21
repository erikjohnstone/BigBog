import { describe, expect, it } from 'vitest';

import type { BoptestSignal, BoptestTestCaseContract, ControlGraph } from '../../api/client';
import { boptestSignalLabel, buildBoptestMapping, buildBoptestOracles, buildBoptestQualification, exactBoptestSignalMatch, validateBoptestQualificationBoundary } from './boptest-mapping';

const graphInputs: ControlGraph['blocks'] = [{ id: 'zone_temperature', kind: 'numeric_input', label: 'Zone Temperature', x: 0, y: 0, config: {} }];
const graphOutputs: ControlGraph['blocks'] = [{ id: 'fan_command', kind: 'numeric_output', label: 'Fan Command', x: 0, y: 0, config: {} }];
const signal = (name: string, overrides: Partial<BoptestSignal> = {}): BoptestSignal => ({ name, unit: null, description: null, minimum: null, maximum: null, activation_signal: false, ...overrides });

describe('BOPTEST qualification authoring', () => {
  it('suggests only one exact normalized signal and renders model metadata', () => {
    const signals = [signal('zone-temperature'), signal('unrelated')];
    expect(exactBoptestSignalMatch('zone_temperature', 'Zone Temperature', signals)).toBe('zone-temperature');
    expect(exactBoptestSignalMatch('missing', 'Missing', signals)).toBe('');
    expect(exactBoptestSignalMatch('zone_temperature', 'Zone Temperature', [...signals, signal('zone temperature')])).toBe('');
    expect(boptestSignalLabel(signal('fan_u', { unit: '1', minimum: 0, maximum: 1, description: 'Fan override' }))).toBe('fan_u — 1 · 0…1 · Fan override');
  });

  it('builds a complete reviewed mapping with transforms and activation', () => {
    expect(buildBoptestMapping(
      'bestest_air',
      graphInputs,
      graphOutputs,
      { zone_temperature: { measurement: 'reaTZon_y', scale: '1', offset: '-273.15' } },
      { fan_command: { actuator: 'oveFan_u', activation: 'oveFan_activate', scale: '0.01', offset: '0' } },
    )).toEqual({
      test_case: 'bestest_air',
      measurements: [{ graph_input: 'zone_temperature', measurement: 'reaTZon_y', scale: 1, offset: -273.15 }],
      actuators: [{ graph_output: 'fan_command', actuator: 'oveFan_u', activation_actuator: 'oveFan_activate', scale: 0.01, offset: 0 }],
    });
  });

  it('blocks incomplete, nonfinite, duplicate, and overlapping bindings', () => {
    expect(() => buildBoptestMapping('', graphInputs, graphOutputs, {}, {})).toThrow(/select and inspect/i);
    expect(() => buildBoptestMapping('case', graphInputs, graphOutputs, {}, {})).toThrow(/zone_temperature has no reviewed/);
    expect(() => buildBoptestMapping('case', graphInputs, graphOutputs, { zone_temperature: { measurement: 't', scale: 'NaN', offset: '0' } }, { fan_command: { actuator: 'fan', activation: '', scale: '1', offset: '0' } })).toThrow(/finite/);
    const twoOutputs = [...graphOutputs, { ...graphOutputs[0], id: 'pump_command', label: 'Pump Command' }];
    expect(() => buildBoptestMapping('case', graphInputs, twoOutputs, { zone_temperature: { measurement: 't', scale: '1', offset: '0' } }, {
      fan_command: { actuator: 'fan', activation: 'enable', scale: '1', offset: '0' },
      pump_command: { actuator: 'pump', activation: 'enable', scale: '1', offset: '0' },
    })).toThrow(/duplicate activation/);
    expect(() => buildBoptestMapping('case', graphInputs, graphOutputs, { zone_temperature: { measurement: 't', scale: '1', offset: '0' } }, { fan_command: { actuator: 'fan', activation: 'fan', scale: '1', offset: '0' } })).toThrow(/must differ/);
  });

  it('builds a time-indexed oracle and expands one steady expected value', () => {
    expect(buildBoptestOracles([{ id: 'zone-response', signalKind: 'measurement', signal: 'reaTZon_y', referenceValues: '295.15', timeTolerance: '0', valueTolerance: '0.25' }], 3, 300)).toEqual([{
      id: 'zone-response',
      signal_kind: 'measurement',
      signal: 'reaTZon_y',
      reference_times: [300, 600, 900],
      reference_values: [295.15, 295.15, 295.15],
      absolute_time_tolerance: 0,
      absolute_value_tolerance: 0.25,
    }]);
  });

  it('rejects missing, duplicate, invalid, nonfinite, or incomplete oracles', () => {
    const valid = { id: 'fan-command', signalKind: 'graph_output' as const, signal: 'fan_command', referenceValues: '0.2,0.3', timeTolerance: '0', valueTolerance: '0.01' };
    expect(() => buildBoptestOracles([], 2, 300)).toThrow(/at least one/i);
    expect(() => buildBoptestOracles([valid, valid], 2, 300)).toThrow(/unique/);
    expect(() => buildBoptestOracles([{ ...valid, id: 'bad id' }], 2, 300)).toThrow(/invalid/);
    expect(() => buildBoptestOracles([{ ...valid, referenceValues: '0.2,nope' }], 2, 300)).toThrow(/finite/);
    expect(() => buildBoptestOracles([{ ...valid, referenceValues: '0.1,0.2,0.3' }], 2, 300)).toThrow(/exactly 2/);
    expect(() => buildBoptestOracles([{ ...valid, valueTolerance: '-1' }], 2, 300)).toThrow(/cannot be negative/);
  });

  it('builds the canonical qualification and validates run horizon', () => {
    const measurements = { zone_temperature: { measurement: 'zone', scale: '1', offset: '0' } };
    const actuators = { fan_command: { actuator: 'fan', activation: '', scale: '1', offset: '0' } };
    const oracles = [{ id: 'fan', signalKind: 'graph_output' as const, signal: 'fan_command', referenceValues: '1', timeTolerance: '0', valueTolerance: '0.1' }];
    expect(buildBoptestQualification('bestest_air', graphInputs, graphOutputs, measurements, actuators, oracles, 2, 60, '0', '3600')).toMatchObject({ steps: 2, step_seconds: 60, start_time: 0, warmup_period: 3600 });
    expect(() => buildBoptestQualification('bestest_air', graphInputs, graphOutputs, measurements, actuators, oracles, 2, 60, '-1', '0')).toThrow(/start time cannot be negative/i);
    expect(() => buildBoptestQualification('bestest_air', graphInputs, graphOutputs, measurements, actuators, oracles, 2, 60, '0', '-1')).toThrow(/warmup period cannot be negative/i);
  });

  it('requires every mapping and oracle signal to exist on the inspected boundary', () => {
    const qualification = buildBoptestQualification(
      'bestest_air', graphInputs, graphOutputs,
      { zone_temperature: { measurement: 'zone', scale: '1', offset: '0' } },
      { fan_command: { actuator: 'fan', activation: 'fan_activate', scale: '1', offset: '0' } },
      [{ id: 'zone', signalKind: 'measurement', signal: 'zone', referenceValues: '295', timeTolerance: '0', valueTolerance: '1' }],
      1, 300, '0', '0',
    );
    const contract: BoptestTestCaseContract = {
      schema: 'bactalk.boptest-test-case-contract/v1', version: {}, test_case: 'bestest_air',
      measurements: [signal('zone')],
      inputs: [signal('fan'), signal('fan_activate', { activation_signal: true })],
      measurement_count: 1, input_count: 2, clean_stop: true, initialized: false, live_building_writes: false,
    };
    expect(() => validateBoptestQualificationBoundary(qualification, graphOutputs, contract)).not.toThrow();
    expect(() => validateBoptestQualificationBoundary({ ...qualification, mapping: { ...qualification.mapping, test_case: 'other' } }, graphOutputs, contract)).toThrow(/does not match/);
    expect(() => validateBoptestQualificationBoundary({ ...qualification, mapping: { ...qualification.mapping, measurements: [{ ...qualification.mapping.measurements[0], measurement: 'missing' }] } }, graphOutputs, contract)).toThrow(/not advertised as a measurement/);
    expect(() => validateBoptestQualificationBoundary({ ...qualification, mapping: { ...qualification.mapping, actuators: [{ ...qualification.mapping.actuators[0], actuator: 'missing' }] } }, graphOutputs, contract)).toThrow(/not advertised as a command/);
    expect(() => validateBoptestQualificationBoundary({ ...qualification, mapping: { ...qualification.mapping, actuators: [{ ...qualification.mapping.actuators[0], activation_actuator: 'missing' }] } }, graphOutputs, contract)).toThrow(/not advertised as an activation/);
    expect(() => validateBoptestQualificationBoundary({ ...qualification, oracles: [{ ...qualification.oracles[0], signal: 'missing' }] }, graphOutputs, contract)).toThrow(/unreviewed measurement/);
  });
});
