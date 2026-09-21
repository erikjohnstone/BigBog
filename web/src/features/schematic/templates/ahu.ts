import type { SchematicElement, SchematicFlow, SlotBindings, Template } from '../types';

export const ahuTemplate: Template = {
  id: 'ahu',
  title: 'Air handling unit',
  brick: ['AHU', 'Air_Handling_Unit', 'Air_Handler_Unit', 'RTU', 'Rooftop_Unit'],
  slots: [
    { id: 'fanCommand', label: 'Supply fan command', kind: 'boolean', brick: ['Supply_Fan_Command', 'Fan_Command', 'Start_Stop_Command'], names: [/fan.*(cmd|command|start)/i, /supplyfan/i] },
    { id: 'fanStatus', label: 'Supply fan status', kind: 'boolean', brick: ['Supply_Fan_Status', 'Fan_Status'], names: [/fan.*(status|proof)/i] },
    { id: 'fanSpeed', label: 'Supply fan speed', kind: 'numeric', brick: ['Supply_Fan_Speed_Command', 'Fan_Speed_Command', 'Speed_Command'], names: [/fan.*speed|vfd/i] },
    { id: 'coolingValve', label: 'Cooling valve command', kind: 'numeric', brick: ['Chilled_Water_Valve_Command', 'Cooling_Valve_Command', 'Cooling_Command'], names: [/cool.*(valve|cmd|command)/i] },
    { id: 'heatingValve', label: 'Heating valve command', kind: 'numeric', brick: ['Hot_Water_Valve_Command', 'Heating_Valve_Command', 'Heating_Command'], names: [/heat.*(valve|cmd|command)/i] },
    { id: 'oaDamper', label: 'Outside air damper', kind: 'numeric', brick: ['Outside_Damper_Position_Command', 'Outside_Air_Damper_Command', 'Damper_Position_Command'], names: [/outside.*damper|oa.*damper|damper/i] },
    { id: 'dischargeTemp', label: 'Discharge air temperature', kind: 'numeric', brick: ['Discharge_Air_Temperature_Sensor', 'Supply_Air_Temperature_Sensor'], roles: ['sensor'], units: ['degF', '°F', 'degC', '°C'], names: [/discharge.*temp|supply.*temp/i] },
    { id: 'dischargeSetpoint', label: 'Discharge air setpoint', kind: 'numeric', brick: ['Discharge_Air_Temperature_Setpoint', 'Supply_Air_Temperature_Setpoint'], names: [/discharge.*(setpoint|sp)|supply.*(setpoint|sp)/i] },
    { id: 'ductStatic', label: 'Duct static pressure', kind: 'numeric', brick: ['Supply_Air_Static_Pressure_Sensor', 'Static_Pressure_Sensor'], roles: ['sensor'], units: ['inH2O', 'inwc', 'Pa'], names: [/static/i] },
    { id: 'staticSetpoint', label: 'Static pressure setpoint', kind: 'numeric', brick: ['Supply_Air_Static_Pressure_Setpoint', 'Static_Pressure_Setpoint'], names: [/static.*(setpoint|sp)|high.*limit/i] },
    { id: 'returnTemp', label: 'Return air temperature', kind: 'numeric', brick: ['Return_Air_Temperature_Sensor'], names: [/return.*temp/i] },
    { id: 'outsideTemp', label: 'Outside air temperature', kind: 'numeric', brick: ['Outside_Air_Temperature_Sensor'], names: [/outside.*temp|oat/i] },
    { id: 'occupied', label: 'Occupied', kind: 'boolean', brick: ['Occupancy_Status', 'Occupancy_Command'], names: [/occup/i] },
    { id: 'alarm', label: 'Alarm', kind: 'boolean', names: [/alarm/i] },
  ],
  build(b: SlotBindings) {
    const flows: SchematicFlow[] = [
      { id: 'oa', points: [[20, 150], [110, 150]], medium: 'air-outside', flow: b.oaDamper, width: 24 },
      { id: 'supply', points: [[640, 150], [760, 150]], medium: 'air-supply', flow: b.fanSpeed ?? b.fanCommand, temp: b.dischargeTemp, width: 24 },
      { id: 'return', points: [[760, 250], [200, 250], [200, 190]], medium: 'air-return', flow: b.fanCommand, temp: b.returnTemp, width: 18 },
      { id: 'chw-s', points: [[338, 300], [338, 212]], medium: 'chw', flow: b.coolingValve, width: 6 },
      { id: 'chw-r', points: [[378, 212], [378, 300]], medium: 'chw', flow: b.coolingValve, width: 6 },
      { id: 'hw-s', points: [[438, 300], [438, 212]], medium: 'hw', flow: b.heatingValve, width: 6 },
      { id: 'hw-r', points: [[478, 212], [478, 300]], medium: 'hw', flow: b.heatingValve, width: 6 },
    ];
    const elements: SchematicElement[] = [
      { id: 'casing', type: 'casing', x: 110, y: 100, w: 530, h: 100, label: 'AHU', bindings: {} },
      { id: 'oaDamper', type: 'damper', x: 122, y: 108, w: 56, h: 84, slot: 'oaDamper', label: 'OA damper', unit: '%', bindings: { position: b.oaDamper, value: b.oaDamper } },
      { id: 'filter', type: 'filter', x: 210, y: 108, w: 40, h: 84, label: 'Filter', bindings: {} },
      { id: 'coolingCoil', type: 'coil', x: 300, y: 108, w: 110, h: 84, medium: 'chw', label: 'Cooling coil', slot: 'coolingValve', bindings: {} },
      { id: 'coolingValve', type: 'valve', x: 324, y: 232, w: 28, h: 44, medium: 'chw', slot: 'coolingValve', unit: '%', bindings: { position: b.coolingValve, value: b.coolingValve } },
      { id: 'heatingCoil', type: 'coil', x: 420, y: 108, w: 110, h: 84, medium: 'hw', label: 'Heating coil', slot: 'heatingValve', bindings: {} },
      { id: 'heatingValve', type: 'valve', x: 424, y: 232, w: 28, h: 44, medium: 'hw', slot: 'heatingValve', unit: '%', bindings: { position: b.heatingValve, value: b.heatingValve } },
      { id: 'fan', type: 'fan', x: 552, y: 108, w: 76, h: 84, slot: 'fanCommand', label: 'Supply fan', unit: '%', bindings: { on: b.fanStatus ?? b.fanCommand, speed: b.fanSpeed ?? b.fanCommand, value: b.fanSpeed } },
      { id: 'fanCmd', type: 'lamp', x: 552, y: 206, w: 76, h: 20, label: 'Fan cmd', slot: 'fanCommand', bindings: { on: b.fanCommand } },
      { id: 'dischargeTemp', type: 'sensor', x: 672, y: 62, w: 48, h: 48, tag: 'TT', label: 'Discharge', slot: 'dischargeTemp', unit: '°F', bindings: { value: b.dischargeTemp } },
      { id: 'dischargeSp', type: 'readout', x: 640, y: 30, w: 118, h: 20, label: 'DAT SP', slot: 'dischargeSetpoint', unit: '°F', bindings: { value: b.dischargeSetpoint } },
      { id: 'ductStatic', type: 'sensor', x: 730, y: 178, w: 48, h: 48, tag: 'PT', label: 'Static', slot: 'ductStatic', unit: 'inH2O', bindings: { value: b.ductStatic } },
      { id: 'staticSp', type: 'readout', x: 600, y: 240, w: 110, h: 20, label: 'Static SP', slot: 'staticSetpoint', unit: 'inH2O', bindings: { value: b.staticSetpoint } },
      { id: 'returnTemp', type: 'sensor', x: 520, y: 262, w: 48, h: 48, tag: 'TT', label: 'Return', slot: 'returnTemp', unit: '°F', bindings: { value: b.returnTemp } },
      { id: 'outsideTemp', type: 'sensor', x: 40, y: 62, w: 48, h: 48, tag: 'TT', label: 'Outside', slot: 'outsideTemp', unit: '°F', bindings: { value: b.outsideTemp } },
      { id: 'occupied', type: 'lamp', x: 110, y: 296, w: 92, h: 22, label: 'Occupied', slot: 'occupied', bindings: { on: b.occupied } },
      { id: 'alarm', type: 'lamp', x: 214, y: 296, w: 92, h: 22, label: 'Alarm', slot: 'alarm', medium: 'status', bindings: { on: b.alarm } },
      { id: 'oaLabel', type: 'label', x: 20, y: 122, w: 90, h: 16, label: 'Outside air', bindings: {} },
      { id: 'supplyLabel', type: 'label', x: 652, y: 122, w: 100, h: 16, label: 'Supply air', bindings: {} },
      { id: 'returnLabel', type: 'label', x: 660, y: 268, w: 100, h: 16, label: 'Return air', bindings: {} },
    ];
    return { title: 'Air handling unit', width: 780, height: 330, elements, flows };
  },
};
