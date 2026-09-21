/**
 * A schematic preview from a ctrl-flow programming brief: components in
 * subsystem order on one duct, typed by their component names. It is a
 * preview of the design, not evidence; nothing here has a signal yet.
 */

import type { CtrlFlowBrief } from '../../../api/client';
import type { SchematicElement, SchematicFlow, SchematicLayout, SymbolType } from '../types';

function symbolFor(type: string): SymbolType {
  const value = type.toLowerCase();
  if (value.includes('fan')) return 'fan';
  if (value.includes('damper')) return 'damper';
  if (value.includes('filter')) return 'filter';
  if (value.includes('coil') || value.includes('heat') || value.includes('cool')) return 'coil';
  if (value.includes('valve')) return 'valve';
  if (value.includes('pump')) return 'pump';
  if (value.includes('chiller')) return 'chiller';
  if (value.includes('boiler')) return 'boiler';
  if (value.includes('tower')) return 'tower';
  if (value.includes('sensor')) return 'sensor';
  return 'casing';
}

function shortName(type: string): string {
  const parts = type.split('.');
  return parts[parts.length - 1].replace(/([a-z])([A-Z])/g, '$1 $2');
}

export function layoutFromBrief(brief: CtrlFlowBrief): SchematicLayout {
  const components = brief.components.filter((component) => Number(component.quantity) > 0 || component.quantity === '' || component.quantity === undefined);
  const gap = 24;
  const width = 90;
  let x = 40;
  const elements: SchematicElement[] = [];
  for (const component of components.slice(0, 12)) {
    const type = symbolFor(component.type);
    const h = type === 'sensor' ? 44 : 70;
    const w = type === 'sensor' ? 44 : width;
    elements.push({
      id: component.id,
      type,
      x,
      y: type === 'sensor' ? 46 : 60,
      w,
      h,
      label: shortName(component.type),
      medium: type === 'coil' ? (component.type.toLowerCase().includes('cool') ? 'chw' : 'hw') : undefined,
      bindings: {},
    });
    if (Number(component.quantity) > 1) {
      elements.push({ id: `${component.id}-qty`, type: 'label', x: x + w - 14, y: 44, w: 20, h: 14, label: `×${component.quantity}`, bindings: {} });
    }
    x += w + gap;
  }
  const total = Math.max(320, x + 20);
  const flows: SchematicFlow[] = [{ id: 'duct', points: [[16, 95], [total - 16, 95]], medium: 'air-supply', width: 18 }];
  return { title: `${brief.design_binding.equipment_family} design preview`, width: total, height: 170, elements, flows };
}
