import type { SchematicElement, SchematicFlow, SlotBindings, Template } from '../types';

export const exhaustFanTemplate: Template = {
  id: 'exhaust-fan',
  title: 'Exhaust fan with proof',
  brick: ['Exhaust_Fan', 'Fan'],
  slots: [
    { id: 'enable', label: 'Enable / interlock', kind: 'boolean', brick: ['Enable_Command', 'Enable_Status'], names: [/enable|interlock/i] },
    { id: 'fanCommand', label: 'Fan command', kind: 'boolean', brick: ['Exhaust_Fan_Command', 'Fan_Command', 'Start_Stop_Command'], roles: ['command'], names: [/fan.*(cmd|command|start)/i, /command/i] },
    { id: 'fanStatus', label: 'Fan proof / status', kind: 'boolean', brick: ['Exhaust_Fan_Status', 'Fan_Status'], roles: ['status', 'sensor'], names: [/status|proof/i] },
    { id: 'proofAlarm', label: 'Proof alarm', kind: 'boolean', names: [/alarm/i] },
    { id: 'speed', label: 'Fan speed', kind: 'numeric', brick: ['Fan_Speed_Command', 'Speed_Command'], names: [/speed|vfd/i] },
  ],
  build(b: SlotBindings) {
    const on = b.fanStatus ?? b.fanCommand;
    const flows: SchematicFlow[] = [
      { id: 'inlet', points: [[20, 150], [200, 150]], medium: 'air-return', flow: on, width: 24 },
      { id: 'outlet', points: [[320, 150], [480, 150], [480, 60]], medium: 'air-outside', flow: on, width: 24 },
    ];
    const elements: SchematicElement[] = [
      { id: 'fan', type: 'fan', x: 200, y: 100, w: 120, h: 100, slot: 'fanCommand', label: 'Exhaust fan', unit: '%', bindings: { on, speed: b.speed ?? on, value: b.speed } },
      { id: 'enable', type: 'lamp', x: 40, y: 220, w: 110, h: 22, label: 'Enable', slot: 'enable', bindings: { on: b.enable } },
      { id: 'command', type: 'lamp', x: 160, y: 220, w: 110, h: 22, label: 'Command', slot: 'fanCommand', bindings: { on: b.fanCommand } },
      { id: 'status', type: 'lamp', x: 280, y: 220, w: 110, h: 22, label: 'Proof', slot: 'fanStatus', bindings: { on: b.fanStatus } },
      { id: 'alarm', type: 'lamp', x: 400, y: 220, w: 110, h: 22, label: 'Proof alarm', slot: 'proofAlarm', medium: 'status', bindings: { on: b.proofAlarm } },
      { id: 'inletLabel', type: 'label', x: 20, y: 122, w: 120, h: 16, label: 'From space', bindings: {} },
      { id: 'outletLabel', type: 'label', x: 420, y: 40, w: 120, h: 16, label: 'To outdoors', bindings: {} },
    ];
    return { title: 'Exhaust fan with proof', width: 540, height: 260, elements, flows };
  },
};
