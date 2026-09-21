import { describe, expect, it } from 'vitest';

import type { ProjectRecord } from '../../api/client';
import type { Trace } from '../../stores/trace';
import { layoutMassing, temperatureHue } from './layout';

const project = {
  equipment_runs: [{ equipment_name: 'AHU_1', status: 'approved' }],
  project: {
    equipment: [
      { equipment_name: 'AHU_1', equipment_brick_class: 'Air_Handling_Unit', points: [{ name: 'DischargeAirTemp', label: 'DAT', data_type: 'numeric', role: 'sensor', units: '°F' }] },
      { equipment_name: 'VAV_1', equipment_brick_class: 'VAV', points: [] },
      { equipment_name: 'BLR_1', equipment_brick_class: 'Boiler', points: [] },
    ],
  },
} as unknown as ProjectRecord;

describe('layoutMassing', () => {
  it('sizes blocks by equipment kind and binds a temperature signal when the trace has one', () => {
    const trace = { signals: new Map([['AHU_1.DischargeAirTemp', {}]]) } as unknown as Trace;
    const items = layoutMassing(project, trace);
    expect(items.map((item) => [item.name, item.w, item.h])).toEqual([
      ['AHU_1', 2.6, 1.2],
      ['VAV_1', 1.2, 0.8],
      ['BLR_1', 1.6, 2.2],
    ]);
    expect(items[0]).toMatchObject({ status: 'approved', tempSignal: 'AHU_1.DischargeAirTemp', tempUnit: '°F' });
    expect(items[1].tempSignal).toBeNull();
    // Distinct grid cells.
    expect(new Set(items.map((item) => `${item.x},${item.z}`)).size).toBe(3);
  });
});

describe('temperatureHue', () => {
  it('runs cool to warm across a zone range in any declared unit', () => {
    expect(temperatureHue(60, '°F')).toBe(210);
    expect(temperatureHue(85, '°F')).toBe(20);
    expect(temperatureHue(22, '°C')).toBeCloseTo(temperatureHue(71.6, '°F'), 5);
    expect(temperatureHue(295.15, 'K')).toBeCloseTo(temperatureHue(22, '°C'), 5);
  });
});
