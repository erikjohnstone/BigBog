import { describe, expect, it } from 'vitest';

import type { ProjectRecord, TestReport } from '../api/client';
import { buildProjectTrace, projectCasesAsAcceptance } from './project-trace';

const project = {
  id: 'p1',
  status: 'ready_for_review',
  artifact_sha256: 'x',
  project: {
    name: 'Office',
    site: 'Campus',
    equipment: [
      {
        equipment_name: 'AHU_1',
        points: [{ name: 'Occupied', label: 'Occupied', data_type: 'boolean', role: 'status' }, { name: 'SupplyFanCommand', label: 'Supply fan', data_type: 'boolean', role: 'command' }],
        control_graph: { name: 'AHU_1', blocks: [{ id: 'Occupied', kind: 'boolean_input', label: 'Occupied', x: 0, y: 0, config: {} }, { id: 'SupplyFanCommand', kind: 'boolean_output', label: 'Supply fan', x: 0, y: 0, config: {} }], links: [] },
      },
      {
        equipment_name: 'EF_1',
        points: [{ name: 'Enable', label: 'Enable', data_type: 'boolean', role: 'status' }, { name: 'FanCommand', label: 'Fan', data_type: 'boolean', role: 'command' }],
        control_graph: { name: 'EF_1', blocks: [{ id: 'Enable', kind: 'boolean_input', label: 'Enable', x: 0, y: 0, config: {} }, { id: 'FanCommand', kind: 'boolean_output', label: 'Fan', x: 0, y: 0, config: {} }], links: [] },
      },
    ],
    relationships: [],
    signal_bindings: [{ source_equipment: 'AHU_1', source_point: 'SupplyFanCommand', target_equipment: 'EF_1', target_point: 'Enable' }],
    acceptance_tests: [
      {
        name: 'Occupancy propagates',
        phases: [
          { name: 'off', inputs: { 'AHU_1.Occupied': false }, repeat: 2, step_seconds: 1, expectations: [{ equipment: 'EF_1', point: 'FanCommand', operator: 'eq', value: false }] },
          { name: 'on', inputs: { 'AHU_1.Occupied': true }, repeat: 2, step_seconds: 1, expectations: [{ equipment: 'EF_1', point: 'FanCommand', operator: 'eq', value: true }] },
        ],
      },
    ],
    station_assembly_mode: 'none',
  },
  equipment_runs: [],
} as unknown as ProjectRecord;

const report = {
  engine: 'project',
  passed: true,
  coverage: null,
  scenarios: [
    {
      name: 'Occupancy propagates',
      passed: true,
      assertions: [
        { name: 'Occupancy propagates / off: EF_1.FanCommand', passed: true, observed: 'false', expected: 'false' },
        { name: 'Occupancy propagates / on: EF_1.FanCommand', passed: true, observed: 'true', expected: 'true' },
      ],
      samples: [0, 1, 2, 3].map((i) => ({ step: i, phase: i < 2 ? 'off' : 'on', phase_step: i % 2, 'AHU_1.Occupied': i >= 2, 'AHU_1.SupplyFanCommand': i >= 2, 'AHU_1.SupplyFanCommand.out': i >= 2, 'EF_1.Enable': i >= 2, 'EF_1.FanCommand': i >= 2 })),
    },
  ],
} as unknown as TestReport;

describe('buildProjectTrace', () => {
  it('maps project phases onto the generic timeline shape', () => {
    expect(projectCasesAsAcceptance(project.project.acceptance_tests)[0]).toEqual({
      name: 'Occupancy propagates',
      expectations: [{ target: 'EF_1.FanCommand' }, { target: 'EF_1.FanCommand' }],
      timeline: [
        { name: 'off', repeat: 2, step_seconds: 1 },
        { name: 'on', repeat: 2, step_seconds: 1 },
      ],
    });
  });

  it('keeps qualified Equip.Point ids so bindings and the system map resolve them', () => {
    const trace = buildProjectTrace(project, report);
    expect(trace.id).toBe('project:p1');
    expect(trace.engine).toBe('project');
    expect(trace.signals.get('AHU_1.SupplyFanCommand')?.source).toBe('command');
    expect(trace.signals.get('EF_1.Enable')?.source).toBe('input');
    // A qualified block's slot is a slot of that block, not a block called "AHU_1".
    expect(trace.signals.get('AHU_1.SupplyFanCommand.out')).toMatchObject({ source: 'slot', blockId: 'AHU_1.SupplyFanCommand', slot: 'out' });
    expect(trace.phases.map((phase) => [phase.name, phase.startIdx, phase.endIdx])).toEqual([
      ['Occupancy propagates · off', 0, 1],
      ['Occupancy propagates · on', 2, 3],
    ]);
    expect(trace.assertions.map((item) => item.blockIds)).toEqual([['EF_1.FanCommand'], ['EF_1.FanCommand']]);
  });
});
