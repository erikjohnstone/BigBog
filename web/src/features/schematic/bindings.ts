/**
 * Resolve a template's slots against the available signals: Brick class
 * first, then role and units, then names. Every source binds at most once.
 * Overrides are a viewer preference stored per run; the deliverable stays
 * server-generated.
 */

import type { SignalSource, SlotBindings, SlotSpec, Template } from './types';

export type MatchedBy = 'brick' | 'role' | 'name' | 'override';

export interface Resolution {
  slots: SlotBindings;
  matchedBy: Record<string, MatchedBy>;
  unmatched: SignalSource[];
}

function normalizeUnit(unit: string | undefined | null): string {
  if (!unit) return '';
  return unit.toLowerCase().replace('°', 'deg').replace(/\s+/g, '');
}

function brickMatches(slot: SlotSpec, source: SignalSource): boolean {
  if (!slot.brick || !source.brick) return false;
  const value = source.brick.toLowerCase();
  return slot.brick.some((suffix) => value.endsWith(suffix.toLowerCase()));
}

function roleMatches(slot: SlotSpec, source: SignalSource): boolean {
  if (!slot.roles || !source.role) return false;
  if (!slot.roles.includes(source.role)) return false;
  if (slot.units && slot.units.length > 0) {
    const unit = normalizeUnit(source.unit);
    if (!slot.units.map(normalizeUnit).includes(unit)) return false;
  }
  return slot.kind === source.kind;
}

function nameMatches(slot: SlotSpec, source: SignalSource): boolean {
  if (!slot.names) return false;
  if (slot.kind !== source.kind) return false;
  return slot.names.some((pattern) => pattern.test(source.id) || pattern.test(source.label));
}

export function resolveSlots(template: Template, sources: SignalSource[], overrides: Record<string, string> = {}): Resolution {
  const slots: SlotBindings = {};
  const matchedBy: Record<string, MatchedBy> = {};
  const used = new Set<string>();

  for (const [slotId, sourceId] of Object.entries(overrides)) {
    if (!template.slots.some((slot) => slot.id === slotId)) continue;
    const source = sources.find((item) => item.id === sourceId);
    if (!source) continue;
    slots[slotId] = source.signalId ?? source.id;
    matchedBy[slotId] = 'override';
    used.add(source.id);
  }

  const passes: Array<[MatchedBy, (slot: SlotSpec, source: SignalSource) => boolean]> = [
    ['brick', brickMatches],
    ['role', roleMatches],
    ['name', nameMatches],
  ];
  for (const [how, test] of passes) {
    for (const slot of template.slots) {
      if (slot.id in slots) continue;
      const source = sources.find((item) => !used.has(item.id) && test(slot, item));
      if (!source) continue;
      slots[slot.id] = source.signalId ?? source.id;
      matchedBy[slot.id] = how;
      used.add(source.id);
    }
  }
  for (const slot of template.slots) if (!(slot.id in slots)) slots[slot.id] = undefined;
  return { slots, matchedBy, unmatched: sources.filter((item) => !used.has(item.id)) };
}

const OVERRIDES_KEY = (runId: string) => `bactalk.schematic.bindings.${runId}`;

export function readOverrides(runId: string): Record<string, string> {
  try {
    const raw = localStorage.getItem(OVERRIDES_KEY(runId));
    return raw ? (JSON.parse(raw) as Record<string, string>) : {};
  } catch {
    return {};
  }
}

export function writeOverrides(runId: string, overrides: Record<string, string>): void {
  try {
    if (Object.keys(overrides).length === 0) localStorage.removeItem(OVERRIDES_KEY(runId));
    else localStorage.setItem(OVERRIDES_KEY(runId), JSON.stringify(overrides));
  } catch {
    // Preference only.
  }
}
