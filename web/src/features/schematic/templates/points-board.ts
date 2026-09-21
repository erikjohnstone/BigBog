import type { SchematicElement, SignalSource, SlotBindings, Template } from '../types';

/**
 * Fallback for equipment without a drawn template: every point as a sensor
 * bubble or a lamp on a grid. Honest, and still on the shared clock.
 */
export const pointsBoardTemplate: Template = {
  id: 'points-board',
  title: 'Points',
  brick: [],
  slots: [],
  build(_bindings: SlotBindings, sources: SignalSource[]) {
    const columns = 4;
    const cellW = 150;
    const cellH = 84;
    const items = sources.slice(0, 24);
    const elements: SchematicElement[] = items.map((source, index) => {
      const col = index % columns;
      const row = Math.floor(index / columns);
      const x = 16 + col * cellW;
      const y = 16 + row * cellH;
      if (source.kind === 'boolean') {
        return { id: source.id, type: 'lamp', x, y: y + 20, w: cellW - 24, h: 22, label: source.label, bindings: { on: source.signalId } };
      }
      return { id: source.id, type: 'sensor', x: x + 8, y, w: 48, h: 48, tag: source.role === 'setpoint' ? 'SP' : 'XT', label: source.label, unit: source.unit, bindings: { value: source.signalId } };
    });
    const rows = Math.max(1, Math.ceil(items.length / columns));
    return { title: 'Points', width: 16 + columns * cellW, height: 16 + rows * cellH, elements, flows: [] };
  },
};
