import { z } from 'zod';

import type { Catalog } from '../../api/client';

export interface FamilyOption {
  id: string;
  label: string;
  detail: string;
  /** Library lane: needs an exact controller id from this catalog. */
  library?: 'g36' | 'plant_controls';
  requiresSequence?: boolean;
  requiresTests?: boolean;
}

export const families: FamilyOption[] = [
  { id: 'AUTO', label: 'Detect from the sequence document', detail: 'BACTalk suggests a family from the narrative; ambiguous suggestions block until you choose.', requiresSequence: true },
  { id: 'G36_VAV_REHEAT', label: 'Standard VAV with reheat (BACTalk pack)', detail: 'Bounded proportional zone program with the VAV plant simulator. Not Guideline 36; choose the LBNL controller lane for that.' },
  { id: 'CUSTOM_AHU_SAFETY_COOLING', label: 'AHU safety and discharge cooling', detail: 'Supply fan interlock, duct high-limit, discharge cooling loop.' },
  { id: 'AHU_DUCT_STATIC_PI', label: 'AHU duct-static PI loop', detail: 'Static pressure PI control with fault-injected pressure trajectories.' },
  { id: 'EXHAUST_FAN_PROOF', label: 'Exhaust fan command and proof', detail: 'Command, proof timer, and proof-failure alarm.' },
  { id: 'TWO_PUMP_AVAILABILITY_SELECTOR', label: 'Two-pump duty / standby selector', detail: 'Lead selection, failover, and no-pump-available alarm.' },
  { id: 'LBNL_G36_CONTROLLER', label: 'LBNL Guideline 36 controller', detail: 'Exact translation of a pinned Modelica G36 controller; choose the controller id.', library: 'g36' },
  { id: 'LBNL_PLANT_CONTROLLER', label: 'LBNL plant controller', detail: 'Pinned plant-control models with proven IR generation; choose the controller id.', library: 'plant_controls' },
  { id: 'AI_CUSTOM', label: 'AI custom · engineer-tested', detail: 'The coding model proposes a typed graph from the sequence; your acceptance tests grade it.', requiresSequence: true, requiresTests: true },
];

export function familyById(id: string): FamilyOption | undefined {
  return families.find((item) => item.id === id);
}

const controllerRowSchema = z.object({ id: z.string(), name: z.string().optional(), family: z.string().optional(), validation_fixture: z.boolean().optional(), product_status: z.string().optional() }).passthrough();

/** Controller rows from a catalog payload (g36 or plant controls). */
export function controllerRows(catalog: Catalog | undefined): Array<{ id: string; name: string; family: string; fixture: boolean }> {
  const raw = (catalog as { controllers?: unknown } | undefined)?.controllers;
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item) => controllerRowSchema.safeParse(item))
    .filter((result): result is { success: true; data: z.infer<typeof controllerRowSchema> } => result.success)
    .map((result) => ({ id: result.data.id, name: result.data.name ?? result.data.id, family: result.data.family ?? '', fixture: Boolean(result.data.validation_fixture) }));
}
