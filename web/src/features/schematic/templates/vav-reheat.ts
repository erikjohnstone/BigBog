import type { SchematicElement, SchematicFlow, SlotBindings, Template } from '../types';

export const vavReheatTemplate: Template = {
  id: 'vav-reheat',
  title: 'VAV terminal with hot-water reheat',
  brick: ['VAV', 'Variable_Air_Volume_Box', 'Variable_Air_Volume_Box_With_Reheat', 'RVAV'],
  slots: [
    { id: 'zoneTemp', label: 'Zone temperature', kind: 'numeric', brick: ['Zone_Air_Temperature_Sensor'], roles: ['sensor'], units: ['degF', '°F', 'degC', '°C'], names: [/zone.*temp/i] },
    { id: 'coolingSetpoint', label: 'Cooling setpoint', kind: 'numeric', brick: ['Zone_Air_Cooling_Temperature_Setpoint', 'Cooling_Temperature_Setpoint'], names: [/cool.*(setpoint|sp)/i] },
    { id: 'heatingSetpoint', label: 'Heating setpoint', kind: 'numeric', brick: ['Zone_Air_Heating_Temperature_Setpoint', 'Heating_Temperature_Setpoint'], names: [/heat.*(setpoint|sp)/i] },
    { id: 'occupied', label: 'Occupied', kind: 'boolean', brick: ['Occupancy_Status', 'Occupancy_Command'], names: [/occup/i] },
    { id: 'damperCommand', label: 'Damper command', kind: 'numeric', brick: ['Damper_Position_Command', 'Damper_Command'], roles: ['command'], units: ['%'], names: [/damper/i] },
    { id: 'valveCommand', label: 'Reheat valve command', kind: 'numeric', brick: ['Reheat_Valve_Command', 'Valve_Command'], names: [/reheat|valve/i] },
    { id: 'airflow', label: 'Supply airflow', kind: 'numeric', brick: ['Supply_Air_Flow_Sensor', 'Air_Flow_Sensor'], names: [/airflow|cfm|flow/i] },
    { id: 'dischargeTemp', label: 'Discharge air temperature', kind: 'numeric', brick: ['Discharge_Air_Temperature_Sensor', 'Supply_Air_Temperature_Sensor'], names: [/discharge.*temp|supply.*temp/i] },
    { id: 'coolingDemand', label: 'Cooling demand', kind: 'numeric', names: [/cool.*demand/i] },
    { id: 'heatingDemand', label: 'Heating demand', kind: 'numeric', names: [/heat.*demand/i] },
    { id: 'highTempAlarm', label: 'High temperature alarm', kind: 'boolean', names: [/alarm/i] },
  ],
  build(b: SlotBindings) {
    const flows: SchematicFlow[] = [
      { id: 'primary', points: [[20, 150], [150, 150]], medium: 'air-supply', flow: b.damperCommand, width: 22 },
      { id: 'discharge', points: [[420, 150], [560, 150], [560, 190]], medium: 'air-supply', flow: b.damperCommand, temp: b.dischargeTemp, width: 22 },
      { id: 'hw-supply', points: [[330, 300], [330, 212]], medium: 'hw', flow: b.valveCommand, width: 6 },
      { id: 'hw-return', points: [[370, 212], [370, 300]], medium: 'hw', flow: b.valveCommand, width: 6 },
    ];
    const elements: SchematicElement[] = [
      { id: 'box', type: 'casing', x: 150, y: 110, w: 270, h: 80, label: 'VAV', bindings: {} },
      { id: 'damper', type: 'damper', x: 180, y: 118, w: 60, h: 64, slot: 'damperCommand', label: 'Damper', unit: '%', bindings: { position: b.damperCommand, value: b.damperCommand } },
      { id: 'coil', type: 'coil', x: 300, y: 118, w: 100, h: 64, medium: 'hw', slot: 'valveCommand', label: 'Reheat', bindings: { on: undefined, temp: undefined } },
      { id: 'valve', type: 'valve', x: 316, y: 232, w: 28, h: 44, medium: 'hw', slot: 'valveCommand', unit: '%', bindings: { position: b.valveCommand, value: b.valveCommand } },
      { id: 'zone', type: 'zone', x: 480, y: 190, w: 200, h: 140, label: 'Zone', slot: 'zoneTemp', bindings: { temp: b.zoneTemp } },
      { id: 'zoneTemp', type: 'sensor', x: 560, y: 240, w: 52, h: 52, tag: 'TT', label: 'Zone temp', slot: 'zoneTemp', unit: '°F', bindings: { value: b.zoneTemp } },
      { id: 'coolingSp', type: 'readout', x: 484, y: 196, w: 92, h: 20, label: 'Cool SP', slot: 'coolingSetpoint', bindings: { value: b.coolingSetpoint } },
      { id: 'heatingSp', type: 'readout', x: 584, y: 196, w: 92, h: 20, label: 'Heat SP', slot: 'heatingSetpoint', bindings: { value: b.heatingSetpoint } },
      { id: 'occupied', type: 'lamp', x: 484, y: 300, w: 92, h: 22, label: 'Occupied', slot: 'occupied', bindings: { on: b.occupied } },
      { id: 'alarm', type: 'lamp', x: 584, y: 300, w: 92, h: 22, label: 'High temp', slot: 'highTempAlarm', medium: 'status', bindings: { on: b.highTempAlarm } },
      { id: 'airflow', type: 'sensor', x: 66, y: 66, w: 48, h: 48, tag: 'FT', label: 'Airflow', slot: 'airflow', unit: 'cfm', bindings: { value: b.airflow } },
      { id: 'dischargeTemp', type: 'sensor', x: 470, y: 62, w: 48, h: 48, tag: 'TT', label: 'Discharge', slot: 'dischargeTemp', unit: '°F', bindings: { value: b.dischargeTemp } },
      { id: 'coolingDemand', type: 'readout', x: 150, y: 212, w: 160, h: 20, label: 'Cooling demand', slot: 'coolingDemand', unit: '%', bindings: { value: b.coolingDemand } },
      { id: 'heatingDemand', type: 'readout', x: 150, y: 238, w: 160, h: 20, label: 'Heating demand', slot: 'heatingDemand', unit: '%', bindings: { value: b.heatingDemand } },
      { id: 'primaryLabel', type: 'label', x: 20, y: 120, w: 120, h: 16, label: 'Primary air from AHU', bindings: {} },
    ];
    return { title: 'VAV terminal with hot-water reheat', width: 700, height: 340, elements, flows };
  },
};
