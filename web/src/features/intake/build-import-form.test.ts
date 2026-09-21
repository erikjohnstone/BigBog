import { describe, expect, it } from 'vitest';

import { emptyDraft } from '../../stores/intake';
import type { IntakeFiles } from '../../stores/intake';
import { buildImportForm, parametersFromJson, parametersToJson, validateStep } from './build-import-form';

const points = new File(['name,label\nZoneTemp,Zone'], 'points.csv', { type: 'text/csv' });
const files: IntakeFiles = { points, sequence: null, bacnet: null, template: null, environment: null };

describe('intake form helpers', () => {
  it('coerces parameter values and round-trips them', () => {
    const json = parametersToJson([
      { key: 'loop_span_f', value: '3' },
      { key: 'enabled', value: 'true' },
      { key: 'label', value: 'North' },
      { key: 'list', value: '[1,2]' },
      { key: '', value: 'ignored' },
    ]);
    expect(JSON.parse(json)).toEqual({ loop_span_f: 3, enabled: true, label: 'North', list: [1, 2] });
    expect(parametersFromJson(json)).toEqual([
      { key: 'loop_span_f', value: '3' },
      { key: 'enabled', value: 'true' },
      { key: 'label', value: 'North' },
      { key: 'list', value: '[1,2]' },
    ]);
    expect(parametersFromJson('not json')).toEqual([]);
  });

  it('validates each step honestly', () => {
    expect(validateStep('job', emptyDraft, files)).toMatchObject({ name: expect.any(String), site: expect.any(String), equipmentName: expect.any(String) });
    expect(validateStep('job', { ...emptyDraft, name: 'A', site: 'B', equipmentName: '1bad' }, files).equipmentName).toBeDefined();
    expect(validateStep('sources', emptyDraft, { ...files, points: null }).points).toBeDefined();
    expect(validateStep('sources', { ...emptyDraft, sequenceFamily: 'AUTO' }, files).sequence).toBeDefined();
    expect(validateStep('sources', { ...emptyDraft, sequenceFamily: 'G36_VAV_REHEAT' }, files)).toEqual({});
    expect(validateStep('strategy', { ...emptyDraft, sequenceFamily: 'LBNL_G36_CONTROLLER' }, files).controllerId).toBeDefined();
    expect(validateStep('strategy', { ...emptyDraft, sequenceFamily: 'AI_CUSTOM' }, files).acceptanceTests).toBeDefined();
    expect(validateStep('strategy', { ...emptyDraft, sequenceFamily: 'G36_VAV_REHEAT', deliverableRequirements: '[1]' }, files).deliverableRequirements).toBeDefined();
    expect(
      validateStep('strategy', { ...emptyDraft, sequenceFamily: 'G36_VAV_REHEAT', acceptanceTests: [{ name: 'x', inputs: {}, expectations: [], repeat: 1, step_seconds: 1 }] }, files)['acceptanceTests.0'],
    ).toBeDefined();
  });

  it('builds the import form the server expects, with the library lane fields', () => {
    const form = buildImportForm(
      {
        ...emptyDraft,
        name: 'VAV-12',
        site: 'Campus',
        equipmentName: 'VAV_12',
        sequenceFamily: 'LBNL_G36_CONTROLLER',
        controllerId: 'AHUs.MultiZone.VAV.Controller',
        parameters: [{ key: 'k', value: '2' }],
        acceptanceTests: [{ name: 'c', inputs: { ZoneTemp: 70 }, expectations: [{ target: 'Damper', operator: 'eq', value: 100, tolerance: 0 }], repeat: 1, step_seconds: 1 }],
        notes: 'note',
      },
      { ...files, sequence: new File(['seq'], 'seq.txt') },
    );
    expect(form.get('sequence_library')).toBe('g36');
    expect(form.get('controller_id')).toBe('AHUs.MultiZone.VAV.Controller');
    expect(form.get('sequence_parameters')).toBe('{"k":2}');
    expect(JSON.parse(form.get('acceptance_tests') as string)[0].expectations[0].target).toBe('Damper');
    expect((form.get('points_file') as File).name).toBe('points.csv');
    expect((form.get('sequence_document') as File).name).toBe('seq.txt');
    expect(form.get('execution_profile')).toBe('modelica_exact');
    expect(form.get('notes')).toBe('note');
    const plain = buildImportForm({ ...emptyDraft, name: 'a', site: 'b', equipmentName: 'c', sequenceFamily: 'G36_VAV_REHEAT' }, files);
    expect(plain.has('sequence_library')).toBe(false);
    expect(plain.has('notes')).toBe(false);
  });
});
