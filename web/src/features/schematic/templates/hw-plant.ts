import type { SchematicElement, SchematicFlow, SlotBindings, Template } from '../types';

export const hwPlantTemplate: Template = {
  id: 'hw-plant',
  title: 'Heating water plant',
  brick: ['Boiler', 'Hot_Water_System', 'Hot_Water_Plant', 'Heat_Exchanger'],
  slots: [
    { id: 'boilerEnable', label: 'Boiler enable', kind: 'boolean', brick: ['Boiler_Command', 'Enable_Command'], names: [/boiler.*(enable|cmd|command)|enable/i] },
    { id: 'boilerStatus', label: 'Boiler status', kind: 'boolean', brick: ['Boiler_Status', 'Run_Status'], names: [/boiler.*status|status/i] },
    { id: 'hwPump', label: 'HW pump', kind: 'boolean', brick: ['Hot_Water_Pump_Command', 'Pump_Command'], names: [/pump/i] },
    { id: 'supplyTemp', label: 'HW supply temperature', kind: 'numeric', brick: ['Hot_Water_Supply_Temperature_Sensor', 'Supply_Water_Temperature_Sensor'], names: [/hws|supply.*temp/i] },
    { id: 'returnTemp', label: 'HW return temperature', kind: 'numeric', brick: ['Hot_Water_Return_Temperature_Sensor', 'Return_Water_Temperature_Sensor'], names: [/hwr|return.*temp/i] },
    { id: 'supplySetpoint', label: 'HW setpoint', kind: 'numeric', brick: ['Hot_Water_Supply_Temperature_Setpoint', 'Supply_Water_Temperature_Setpoint'], names: [/setpoint|sp/i] },
    { id: 'outsideTemp', label: 'Outside air temperature', kind: 'numeric', brick: ['Outside_Air_Temperature_Sensor'], names: [/outside|oat/i] },
    { id: 'firing', label: 'Firing rate', kind: 'numeric', names: [/firing|modulat|rate/i] },
    { id: 'alarm', label: 'Alarm', kind: 'boolean', names: [/alarm|fail/i] },
  ],
  build(b: SlotBindings) {
    const running = b.boilerStatus ?? b.boilerEnable;
    const flows: SchematicFlow[] = [
      { id: 'hws', points: [[230, 120], [520, 120]], medium: 'hw', flow: b.hwPump ?? running, temp: b.supplyTemp, width: 8 },
      { id: 'hwr', points: [[520, 200], [230, 200]], medium: 'hw', flow: b.hwPump ?? running, temp: b.returnTemp, width: 8 },
    ];
    const elements: SchematicElement[] = [
      { id: 'boiler', type: 'boiler', x: 110, y: 80, w: 120, h: 140, slot: 'boilerEnable', label: 'Boiler', unit: '%', bindings: { on: running, value: b.firing, speed: b.firing ?? running } },
      { id: 'hwPump', type: 'pump', x: 330, y: 90, w: 60, h: 50, medium: 'hw', slot: 'hwPump', label: 'HWP', bindings: { on: b.hwPump ?? running, speed: b.hwPump ?? running } },
      { id: 'supplyTemp', type: 'sensor', x: 440, y: 60, w: 48, h: 48, tag: 'TT', label: 'HWS', slot: 'supplyTemp', unit: '°F', bindings: { value: b.supplyTemp } },
      { id: 'returnTemp', type: 'sensor', x: 440, y: 210, w: 48, h: 48, tag: 'TT', label: 'HWR', slot: 'returnTemp', unit: '°F', bindings: { value: b.returnTemp } },
      { id: 'sp', type: 'readout', x: 320, y: 40, w: 100, h: 20, label: 'HWS SP', slot: 'supplySetpoint', unit: '°F', bindings: { value: b.supplySetpoint } },
      { id: 'oat', type: 'sensor', x: 20, y: 40, w: 48, h: 48, tag: 'TT', label: 'Outside', slot: 'outsideTemp', unit: '°F', bindings: { value: b.outsideTemp } },
      { id: 'enable', type: 'lamp', x: 20, y: 240, w: 90, h: 22, label: 'Enable', slot: 'boilerEnable', bindings: { on: b.boilerEnable } },
      { id: 'status', type: 'lamp', x: 115, y: 240, w: 90, h: 22, label: 'Firing', slot: 'boilerStatus', bindings: { on: b.boilerStatus } },
      { id: 'alarm', type: 'lamp', x: 400, y: 240, w: 110, h: 22, label: 'Alarm', slot: 'alarm', medium: 'status', bindings: { on: b.alarm } },
      { id: 'loadLabel', type: 'label', x: 520, y: 140, w: 60, h: 16, label: 'To load', bindings: {} },
    ];
    return { title: 'Heating water plant', width: 600, height: 280, elements, flows };
  },
};
