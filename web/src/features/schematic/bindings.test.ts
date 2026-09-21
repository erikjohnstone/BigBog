import { describe, expect, it } from 'vitest';

import { resolveSlots } from './bindings';
import { ahuTemplate, exhaustFanTemplate, pickTemplate, pointsBoardTemplate, vavReheatTemplate } from './templates';
import type { SignalSource } from './types';

const vavWidgets: SignalSource[] = [
  { id: 'ZoneTemp', label: 'Zone temperature', kind: 'numeric', unit: 'degF', brick: 'brick:Zone_Air_Temperature_Sensor', role: 'sensor', signalId: 'ZoneTemp' },
  { id: 'CoolingSetpoint', label: 'Effective cooling setpoint', kind: 'numeric', unit: 'degF', brick: 'brick:Zone_Air_Cooling_Temperature_Setpoint', role: 'setpoint', signalId: 'CoolingSetpoint' },
  { id: 'HeatingSetpoint', label: 'Effective heating setpoint', kind: 'numeric', unit: 'degF', brick: 'brick:Zone_Air_Heating_Temperature_Setpoint', role: 'setpoint' },
  { id: 'Occupied', label: 'Occupied mode', kind: 'boolean', brick: 'brick:Occupancy_Status', role: 'status', signalId: 'Occupied' },
  { id: 'DamperCommand', label: 'VAV damper command', kind: 'numeric', unit: '%', brick: 'brick:Damper_Position_Command', role: 'command', signalId: 'DamperCommand' },
  { id: 'ValveCommand', label: 'Reheat valve command', kind: 'numeric', unit: '%', brick: 'brick:Valve_Command', role: 'command', signalId: 'ValveCommand' },
  { id: 'CoolingDemand', label: 'Zone cooling demand', kind: 'numeric', unit: '%', brick: null, role: 'status', signalId: 'CoolingDemand' },
  { id: 'HeatingDemand', label: 'Zone heating demand', kind: 'numeric', unit: '%', brick: null, role: 'status', signalId: 'HeatingDemand' },
  { id: 'HighZoneTempAlarm', label: 'High zone temperature alarm', kind: 'boolean', brick: null, role: 'alarm', signalId: 'HighZoneTempAlarm' },
];

const ahuPoints: SignalSource[] = [
  { id: 'Occupied', label: 'Occupied mode', kind: 'boolean', role: 'status', brick: 'brick:Occupancy_Status' },
  { id: 'DuctStatic', label: 'Supply duct static pressure', kind: 'numeric', unit: 'inH2O', role: 'sensor', brick: null },
  { id: 'DuctHighLimit', label: 'Duct pressure high limit', kind: 'numeric', unit: 'inH2O', role: 'setpoint', brick: null },
  { id: 'DischargeAirTemp', label: 'Discharge air temperature', kind: 'numeric', unit: '°F', role: 'sensor', brick: null },
  { id: 'DischargeAirTempSetpoint', label: 'Discharge air temperature setpoint', kind: 'numeric', unit: '°F', role: 'setpoint', brick: null },
  { id: 'SupplyFanCommand', label: 'Supply fan command', kind: 'boolean', role: 'command', brick: null },
  { id: 'CoolingValveCommand', label: 'Cooling valve command', kind: 'numeric', unit: '%', role: 'command', brick: null },
  { id: 'DuctPressureAlarm', label: 'Duct high-pressure alarm', kind: 'boolean', role: 'alarm', brick: null },
];

describe('resolveSlots', () => {
  it('binds VAV widgets by Brick class, then names, each source once', () => {
    const result = resolveSlots(vavReheatTemplate, vavWidgets);
    expect(result.slots.zoneTemp).toBe('ZoneTemp');
    expect(result.matchedBy.zoneTemp).toBe('brick');
    expect(result.slots.coolingSetpoint).toBe('CoolingSetpoint');
    // A source without a trace signal still binds by its id.
    expect(result.slots.heatingSetpoint).toBe('HeatingSetpoint');
    expect(result.slots.occupied).toBe('Occupied');
    expect(result.slots.damperCommand).toBe('DamperCommand');
    expect(result.slots.valveCommand).toBe('ValveCommand');
    expect(result.slots.coolingDemand).toBe('CoolingDemand');
    expect(result.matchedBy.coolingDemand).toBe('name');
    expect(result.slots.highTempAlarm).toBe('HighZoneTempAlarm');
    expect(result.slots.airflow).toBeUndefined();
    expect(result.unmatched).toEqual([]);
  });

  it('binds AHU points by role, units, and names when Brick is missing', () => {
    const result = resolveSlots(ahuTemplate, ahuPoints);
    expect(result.slots.ductStatic).toBe('DuctStatic');
    expect(result.matchedBy.ductStatic).toBe('role');
    expect(result.slots.dischargeTemp).toBe('DischargeAirTemp');
    expect(result.slots.dischargeSetpoint).toBe('DischargeAirTempSetpoint');
    expect(result.slots.staticSetpoint).toBe('DuctHighLimit');
    expect(result.slots.fanCommand).toBe('SupplyFanCommand');
    expect(result.slots.coolingValve).toBe('CoolingValveCommand');
    expect(result.slots.alarm).toBe('DuctPressureAlarm');
    expect(result.slots.occupied).toBe('Occupied');
    expect(result.slots.heatingValve).toBeUndefined();
  });

  it('honours overrides before automatic matching', () => {
    const result = resolveSlots(exhaustFanTemplate, ahuPoints, { fanStatus: 'Occupied' });
    expect(result.slots.fanStatus).toBe('Occupied');
    expect(result.matchedBy.fanStatus).toBe('override');
    expect(result.slots.fanCommand).toBe('SupplyFanCommand');
    // The overridden source is not reused for another slot.
    expect(result.slots.enable).not.toBe('Occupied');
  });
});

describe('templates', () => {
  it('pick by Brick class or family, falling back to the points board', () => {
    expect(pickTemplate('brick:VAV').id).toBe('vav-reheat');
    expect(pickTemplate('brick:AHU').id).toBe('ahu');
    expect(pickTemplate('brick:Exhaust_Fan').id).toBe('exhaust-fan');
    expect(pickTemplate('brick:Pump').id).toBe('pump-pair');
    expect(pickTemplate('brick:Equipment', 'G36_VAV_REHEAT').id).toBe('vav-reheat');
    expect(pickTemplate(null, 'SOMETHING_ELSE').id).toBe('points-board');
  });

  it('build deterministic layouts that reference every bound slot', () => {
    for (const template of [vavReheatTemplate, ahuTemplate, exhaustFanTemplate]) {
      const bindings = Object.fromEntries(template.slots.map((slot) => [slot.id, `sig:${slot.id}`]));
      const a = template.build(bindings, []);
      const b = template.build(bindings, []);
      expect(a).toEqual(b);
      const referenced = new Set<string>();
      for (const element of a.elements) for (const value of Object.values(element.bindings)) {
        if (typeof value === 'string') referenced.add(value);
      }
      for (const flow of a.flows) {
        if (flow.flow) referenced.add(flow.flow);
        if (flow.temp) referenced.add(flow.temp);
      }
      for (const slot of template.slots) expect(referenced.has(`sig:${slot.id}`)).toBe(true);
      expect(new Set(a.elements.map((element) => element.id)).size).toBe(a.elements.length);
    }
  });

  it('lays every source on the points board', () => {
    const layout = pointsBoardTemplate.build({}, ahuPoints);
    expect(layout.elements).toHaveLength(ahuPoints.length);
    expect(layout.elements.filter((element) => element.type === 'lamp')).toHaveLength(3);
  });
});
