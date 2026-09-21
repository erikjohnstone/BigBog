import { ahuTemplate } from './ahu';
import { chwPlantTemplate } from './chw-plant';
import { exhaustFanTemplate } from './exhaust-fan';
import { hwPlantTemplate } from './hw-plant';
import { pointsBoardTemplate } from './points-board';
import { pumpPairTemplate } from './pump-pair';
import type { Template } from '../types';
import { vavReheatTemplate } from './vav-reheat';

export const templates: Template[] = [vavReheatTemplate, ahuTemplate, exhaustFanTemplate, pumpPairTemplate, chwPlantTemplate, hwPlantTemplate, pointsBoardTemplate];

/** Pick by Brick class, then by sequence family hints, else the points board. */
export function pickTemplate(brickClass: string | null | undefined, family?: string | null): Template {
  const brick = (brickClass ?? '').toLowerCase();
  if (brick) {
    const hit = templates.find((template) => template.brick.some((suffix) => brick.endsWith(suffix.toLowerCase())));
    if (hit) return hit;
  }
  const fam = (family ?? '').toUpperCase();
  if (fam.includes('VAV')) return vavReheatTemplate;
  if (fam.includes('AHU')) return ahuTemplate;
  if (fam.includes('EXHAUST') || fam.includes('FAN')) return exhaustFanTemplate;
  if (fam.includes('PUMP')) return pumpPairTemplate;
  if (fam.includes('CHILL')) return chwPlantTemplate;
  if (fam.includes('BOILER') || fam.includes('HEATING')) return hwPlantTemplate;
  return pointsBoardTemplate;
}

export { ahuTemplate, chwPlantTemplate, exhaustFanTemplate, hwPlantTemplate, pointsBoardTemplate, pumpPairTemplate, vavReheatTemplate };
