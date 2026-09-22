/**
 * Pure helpers between the guided intake draft and the /api/runs/import
 * form: validation per step and the FormData the server expects.
 */

import type { ConfirmedBinding, IntakeDraft, IntakeFiles, IntakeStep } from '../../stores/intake';
import { familyById } from './families';

export const EQUIPMENT_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;

export function parametersToJson(parameters: IntakeDraft['parameters']): string {
  const out: Record<string, unknown> = {};
  for (const { key, value } of parameters) {
    const name = key.trim();
    if (!name) continue;
    const trimmed = value.trim();
    if (trimmed === 'true' || trimmed === 'false') out[name] = trimmed === 'true';
    else if (trimmed !== '' && Number.isFinite(Number(trimmed))) out[name] = Number(trimmed);
    else {
      try {
        out[name] = JSON.parse(trimmed);
      } catch {
        out[name] = trimmed;
      }
    }
  }
  return JSON.stringify(out);
}

export function parametersFromJson(json: string): IntakeDraft['parameters'] {
  try {
    const parsed = JSON.parse(json) as Record<string, unknown>;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return [];
    return Object.entries(parsed).map(([key, value]) => [key, typeof value === 'string' ? value : JSON.stringify(value)] as const).map(([key, value]) => ({ key, value }));
  } catch {
    return [];
  }
}

export function validateStep(step: IntakeStep, draft: IntakeDraft, files: IntakeFiles): Record<string, string> {
  const errors: Record<string, string> = {};
  const family = familyById(draft.sequenceFamily);
  if (step === 'job' || step === 'create') {
    if (!draft.name.trim()) errors.name = 'Give the job a name.';
    if (!draft.site.trim()) errors.site = 'Name the site.';
    if (!EQUIPMENT_PATTERN.test(draft.equipmentName)) errors.equipmentName = 'Equipment identifier: letters, digits, underscores; must not start with a digit.';
  }
  if (step === 'sources' || step === 'create') {
    if (!files.points) errors.points = 'A points list (.csv or .xlsx) is required.';
    if (family?.requiresSequence && !files.sequence) errors.sequence = `${family.label} needs the sequence document.`;
  }
  if (step === 'strategy' || step === 'create') {
    if (family?.library && !draft.controllerId.trim()) errors.controllerId = 'Choose the exact library controller id.';
    if (family?.requiresTests && draft.acceptanceTests.length === 0) errors.acceptanceTests = 'AI custom programming needs engineer-authored acceptance tests; the model may not grade its own work.';
    try {
      const parsed = JSON.parse(draft.deliverableRequirements || '{}');
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) errors.deliverableRequirements = 'Deliverable requirements must be a JSON object.';
    } catch {
      errors.deliverableRequirements = 'Deliverable requirements must be valid JSON.';
    }
    for (const [index, testCase] of draft.acceptanceTests.entries()) {
      if (!testCase.name.trim()) errors[`acceptanceTests.${index}`] = 'Every acceptance case needs a name.';
      else if (testCase.expectations.length === 0) errors[`acceptanceTests.${index}`] = `"${testCase.name}" needs at least one expectation.`;
    }
  }
  return errors;
}

export function buildImportForm(draft: IntakeDraft, files: IntakeFiles, bindings: Record<string, ConfirmedBinding> = {}): FormData {
  const body = new FormData();
  const family = familyById(draft.sequenceFamily);
  body.append('name', draft.name.trim());
  body.append('site', draft.site.trim());
  body.append('equipment_name', draft.equipmentName.trim());
  body.append('sequence_family', draft.sequenceFamily);
  body.append('sequence_version', draft.sequenceVersion.trim() || 'Contractor sequence of operations');
  body.append('sequence_parameters', parametersToJson(draft.parameters));
  body.append('deliverable_requirements', draft.deliverableRequirements.trim() || '{}');
  body.append('acceptance_tests', JSON.stringify(draft.acceptanceTests));
  body.append('execution_profile', draft.executionProfile);
  if (draft.notes.trim()) body.append('notes', draft.notes.trim());
  if (family?.library) {
    body.append('sequence_library', family.library);
    body.append('controller_id', draft.controllerId.trim());
  }
  if (files.points) body.append('points_file', files.points);
  if (files.sequence) body.append('sequence_document', files.sequence);
  if (files.bacnet) body.append('bacnet_scan', files.bacnet);
  if (files.template) body.append('template_bog', files.template);
  if (files.environment) body.append('environment_pack', files.environment);
  // Only bindings the engineer confirmed travel with the job; the server
  // refuses priority 1 and implicit priorities on command points.
  if (Object.keys(bindings).length > 0) body.append('point_bindings', JSON.stringify(bindings));
  return body;
}

export function buildStationBindingsForm(draft: IntakeDraft, files: IntakeFiles): FormData {
  const body = new FormData();
  if (files.template) body.append('station_bog', files.template);
  if (files.points) body.append('points_file', files.points);
  body.append('sequence_family', draft.sequenceFamily);
  return body;
}

export function buildInspectForm(draft: IntakeDraft, files: IntakeFiles): FormData {
  const body = new FormData();
  if (files.points) body.append('points_file', files.points);
  if (files.sequence) body.append('sequence_document', files.sequence);
  body.append('sequence_family', draft.sequenceFamily);
  return body;
}
