import type { SchematicElement, SchematicFlow, SlotBindings, Template } from '../types';

export const chwPlantTemplate: Template = {
  id: 'chw-plant',
  title: 'Chilled water plant',
  brick: ['Chiller', 'Chilled_Water_System', 'Chilled_Water_Plant', 'Cooling_Tower'],
  slots: [
    { id: 'chillerEnable', label: 'Chiller enable', kind: 'boolean', brick: ['Chiller_Enable_Command', 'Enable_Command'], names: [/chiller.*(enable|cmd|command)|enable/i] },
    { id: 'chillerStatus', label: 'Chiller status', kind: 'boolean', brick: ['Chiller_Status', 'Run_Status'], names: [/chiller.*status|status/i] },
    { id: 'chwPump', label: 'CHW pump', kind: 'boolean', brick: ['Chilled_Water_Pump_Command', 'Pump_Command'], names: [/chw.*pump|pump/i] },
    { id: 'cwPump', label: 'Condenser pump', kind: 'boolean', brick: ['Condenser_Water_Pump_Command'], names: [/cond.*pump|cw.*pump/i] },
    { id: 'towerFan', label: 'Tower fan', kind: 'boolean', brick: ['Cooling_Tower_Fan_Command'], names: [/tower/i] },
    { id: 'supplyTemp', label: 'CHW supply temperature', kind: 'numeric', brick: ['Chilled_Water_Supply_Temperature_Sensor', 'Supply_Water_Temperature_Sensor'], names: [/chws|supply.*temp/i] },
    { id: 'returnTemp', label: 'CHW return temperature', kind: 'numeric', brick: ['Chilled_Water_Return_Temperature_Sensor', 'Return_Water_Temperature_Sensor'], names: [/chwr|return.*temp/i] },
    { id: 'supplySetpoint', label: 'CHW setpoint', kind: 'numeric', brick: ['Chilled_Water_Supply_Temperature_Setpoint', 'Supply_Water_Temperature_Setpoint'], names: [/setpoint|sp/i] },
    { id: 'stage', label: 'Stage', kind: 'numeric', names: [/stage/i] },
    { id: 'alarm', label: 'Alarm', kind: 'boolean', names: [/alarm|fail/i] },
  ],
  build(b: SlotBindings) {
    const running = b.chillerStatus ?? b.chillerEnable;
    const flows: SchematicFlow[] = [
      { id: 'chws', points: [[330, 130], [560, 130]], medium: 'chw', flow: b.chwPump ?? running, temp: b.supplyTemp, width: 8 },
      { id: 'chwr', points: [[560, 200], [330, 200]], medium: 'chw', flow: b.chwPump ?? running, temp: b.returnTemp, width: 8 },
      { id: 'cws', points: [[210, 130], [110, 130], [110, 80]], medium: 'refrig', flow: b.cwPump ?? running, width: 8 },
      { id: 'cwr', points: [[110, 40], [110, 20], [60, 20], [60, 200], [210, 200]], medium: 'refrig', flow: b.cwPump ?? running, width: 8 },
    ];
    const elements: SchematicElement[] = [
      { id: 'chiller', type: 'chiller', x: 210, y: 90, w: 120, h: 140, slot: 'chillerEnable', label: 'Chiller', bindings: { on: running } },
      { id: 'tower', type: 'tower', x: 70, y: 40, w: 80, h: 60, slot: 'towerFan', label: 'Tower', bindings: { on: b.towerFan ?? running, speed: b.towerFan ?? running } },
      { id: 'chwPump', type: 'pump', x: 400, y: 100, w: 60, h: 50, medium: 'chw', slot: 'chwPump', label: 'CHWP', bindings: { on: b.chwPump ?? running, speed: b.chwPump ?? running } },
      { id: 'supplyTemp', type: 'sensor', x: 490, y: 70, w: 48, h: 48, tag: 'TT', label: 'CHWS', slot: 'supplyTemp', unit: '°F', bindings: { value: b.supplyTemp } },
      { id: 'returnTemp', type: 'sensor', x: 490, y: 220, w: 48, h: 48, tag: 'TT', label: 'CHWR', slot: 'returnTemp', unit: '°F', bindings: { value: b.returnTemp } },
      { id: 'sp', type: 'readout', x: 380, y: 40, w: 100, h: 20, label: 'CHWS SP', slot: 'supplySetpoint', unit: '°F', bindings: { value: b.supplySetpoint } },
      { id: 'stage', type: 'readout', x: 210, y: 250, w: 120, h: 20, label: 'Stage', slot: 'stage', bindings: { value: b.stage } },
      { id: 'enable', type: 'lamp', x: 20, y: 250, w: 90, h: 22, label: 'Enable', slot: 'chillerEnable', bindings: { on: b.chillerEnable } },
      { id: 'status', type: 'lamp', x: 115, y: 250, w: 90, h: 22, label: 'Running', slot: 'chillerStatus', bindings: { on: b.chillerStatus } },
      { id: 'alarm', type: 'lamp', x: 400, y: 250, w: 110, h: 22, label: 'Alarm', slot: 'alarm', medium: 'status', bindings: { on: b.alarm } },
      { id: 'loadLabel', type: 'label', x: 560, y: 150, w: 60, h: 16, label: 'To load', bindings: {} },
    ];
    return { title: 'Chilled water plant', width: 640, height: 290, elements, flows };
  },
};
