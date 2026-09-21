/**
 * Layout and colour rules for the zone massing view, kept apart from the
 * three.js scene so they are unit tested without a WebGL context.
 */

import type { ProjectRecord } from '../../api/client';
import type { Trace } from '../../stores/trace';

export interface Massing {
  name: string;
  brick: string | null;
  x: number;
  z: number;
  w: number;
  d: number;
  h: number;
  status: string;
  tempSignal: string | null;
  tempUnit: string | undefined;
}

/** Equipment as extruded blocks on a grid: air handlers wide and low, terminals small, plants tall. */
export function layoutMassing(project: ProjectRecord, trace: Trace | undefined): Massing[] {
  const statusByEquipment = new Map(project.equipment_runs.map((item) => [item.equipment_name, item.status]));
  const columns = Math.max(2, Math.ceil(Math.sqrt(project.project.equipment.length)));
  return project.project.equipment.map((equipment, index) => {
    const brick = (equipment.equipment_brick_class ?? '').toLowerCase();
    const kind = brick.includes('vav') || brick.includes('terminal') ? 'terminal' : brick.includes('ahu') || brick.includes('air_handl') || brick.includes('fan') ? 'air' : brick.includes('pump') || brick.includes('chiller') || brick.includes('boiler') || brick.includes('plant') ? 'plant' : 'other';
    const size = kind === 'terminal' ? { w: 1.2, d: 1.2, h: 0.8 } : kind === 'air' ? { w: 2.6, d: 1.6, h: 1.2 } : kind === 'plant' ? { w: 1.6, d: 1.6, h: 2.2 } : { w: 1.5, d: 1.5, h: 1 };
    const temp = equipment.points.find((point) => /°f|°c|degf|degc|\bk\b/i.test(point.units ?? '') && (point.role === 'sensor' || point.role === 'status'));
    const tempSignal = temp && trace?.signals.has(`${equipment.equipment_name}.${temp.name}`) ? `${equipment.equipment_name}.${temp.name}` : null;
    return {
      name: equipment.equipment_name,
      brick: equipment.equipment_brick_class ?? null,
      x: (index % columns) * 3.4 - ((columns - 1) * 3.4) / 2,
      z: Math.floor(index / columns) * 3.2,
      ...size,
      status: statusByEquipment.get(equipment.equipment_name) ?? 'unknown',
      tempSignal,
      tempUnit: temp?.units ?? undefined,
    };
  });
}

/** Cool-to-warm hue over a plausible zone range, in the units the point declares. */
export function temperatureHue(value: number, unit: string | undefined): number {
  const f = /°c|degc/i.test(unit ?? '') ? value * 1.8 + 32 : /\bk\b/i.test(unit ?? '') ? (value - 273.15) * 1.8 + 32 : value;
  const t = Math.min(1, Math.max(0, (f - 60) / 25));
  return 210 - t * 190;
}
