import type { SchematicElement, SchematicFlow, SlotBindings, Template } from '../types';

export const pumpPairTemplate: Template = {
  id: 'pump-pair',
  title: 'Duty / standby pump pair',
  brick: ['Pump', 'Hot_Water_Pump', 'Chilled_Water_Pump', 'Water_Pump'],
  slots: [
    { id: 'pump1Command', label: 'Pump 1 command', kind: 'boolean', names: [/pump.?1.*(cmd|command|start)|lead.*(cmd|command)|^pump1/i] },
    { id: 'pump1Status', label: 'Pump 1 status', kind: 'boolean', names: [/pump.?1.*(status|proof|available)/i] },
    { id: 'pump2Command', label: 'Pump 2 command', kind: 'boolean', names: [/pump.?2.*(cmd|command|start)|lag.*(cmd|command)|^pump2/i] },
    { id: 'pump2Status', label: 'Pump 2 status', kind: 'boolean', names: [/pump.?2.*(status|proof|available)/i] },
    { id: 'enable', label: 'System enable', kind: 'boolean', names: [/enable|request|demand/i] },
    { id: 'leadSelect', label: 'Lead selection', kind: 'boolean', names: [/lead|select|rotate/i] },
    { id: 'pressure', label: 'Differential pressure', kind: 'numeric', brick: ['Differential_Pressure_Sensor', 'Pressure_Sensor'], names: [/pressure|dp/i] },
    { id: 'alarm', label: 'Alarm', kind: 'boolean', names: [/alarm|fail/i] },
  ],
  build(b: SlotBindings) {
    const any = b.pump1Status ?? b.pump1Command;
    const flows: SchematicFlow[] = [
      { id: 'supply', points: [[20, 150], [120, 150], [120, 100], [200, 100]], medium: 'hw', flow: b.pump1Status ?? b.pump1Command, width: 8 },
      { id: 'supply2', points: [[120, 150], [120, 200], [200, 200]], medium: 'hw', flow: b.pump2Status ?? b.pump2Command, width: 8 },
      { id: 'header', points: [[280, 100], [360, 100], [360, 200], [280, 200]], medium: 'hw', flow: any, width: 8 },
      { id: 'out', points: [[360, 150], [520, 150]], medium: 'hw', flow: any, width: 8 },
    ];
    const elements: SchematicElement[] = [
      { id: 'pump1', type: 'pump', x: 200, y: 70, w: 80, h: 60, medium: 'hw', slot: 'pump1Command', label: 'Pump 1', bindings: { on: b.pump1Status ?? b.pump1Command, speed: b.pump1Status ?? b.pump1Command } },
      { id: 'pump2', type: 'pump', x: 200, y: 170, w: 80, h: 60, medium: 'hw', slot: 'pump2Command', label: 'Pump 2', bindings: { on: b.pump2Status ?? b.pump2Command, speed: b.pump2Status ?? b.pump2Command } },
      { id: 'p1cmd', type: 'lamp', x: 290, y: 60, w: 60, h: 18, label: 'Cmd', slot: 'pump1Command', bindings: { on: b.pump1Command } },
      { id: 'p1st', type: 'lamp', x: 290, y: 80, w: 60, h: 18, label: 'Proof', slot: 'pump1Status', bindings: { on: b.pump1Status } },
      { id: 'p2cmd', type: 'lamp', x: 290, y: 212, w: 60, h: 18, label: 'Cmd', slot: 'pump2Command', bindings: { on: b.pump2Command } },
      { id: 'p2st', type: 'lamp', x: 290, y: 232, w: 60, h: 18, label: 'Proof', slot: 'pump2Status', bindings: { on: b.pump2Status } },
      { id: 'enable', type: 'lamp', x: 20, y: 240, w: 100, h: 22, label: 'Enable', slot: 'enable', bindings: { on: b.enable } },
      { id: 'lead', type: 'lamp', x: 130, y: 240, w: 100, h: 22, label: 'Lead = 2', slot: 'leadSelect', bindings: { on: b.leadSelect } },
      { id: 'pressure', type: 'sensor', x: 420, y: 80, w: 48, h: 48, tag: 'PDT', label: 'DP', slot: 'pressure', unit: 'psi', bindings: { value: b.pressure } },
      { id: 'alarm', type: 'lamp', x: 400, y: 240, w: 110, h: 22, label: 'Alarm', slot: 'alarm', medium: 'status', bindings: { on: b.alarm } },
    ];
    return { title: 'Duty / standby pump pair', width: 540, height: 280, elements, flows };
  },
};
