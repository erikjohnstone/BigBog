import type { BoptestSignal, BoptestTestCaseContract, ControlGraph } from '../../api/client';

export type BoptestMeasurementBindingDraft = { measurement: string; scale: string; offset: string };
export type BoptestActuatorBindingDraft = { actuator: string; activation: string; scale: string; offset: string };
export type BoptestOracleSignalKind = 'graph_output' | 'measurement';
export type BoptestOracleDraft = {
  id: string;
  signalKind: BoptestOracleSignalKind;
  signal: string;
  referenceValues: string;
  timeTolerance: string;
  valueTolerance: string;
};
export type BoptestScenarioDraft = {
  timePeriod: string;
  electricityPrice: '' | 'constant' | 'dynamic' | 'highly_dynamic';
  temperatureUncertainty: '' | 'none' | 'low' | 'medium' | 'high';
  solarUncertainty: '' | 'none' | 'low' | 'medium' | 'high';
  seed: string;
};
export type BoptestScenario = {
  time_period?: string;
  electricity_price?: 'constant' | 'dynamic' | 'highly_dynamic';
  temperature_uncertainty?: 'none' | 'low' | 'medium' | 'high';
  solar_uncertainty?: 'none' | 'low' | 'medium' | 'high';
  seed?: number;
};

export type BoptestMapping = {
  test_case: string;
  measurements: Array<{ graph_input: string; measurement: string; scale: number; offset: number }>;
  actuators: Array<{ graph_output: string; actuator: string; activation_actuator: string | null; scale: number; offset: number }>;
};

export type BoptestOracle = {
  id: string;
  signal_kind: BoptestOracleSignalKind;
  signal: string;
  reference_times: number[];
  reference_values: number[];
  absolute_time_tolerance: number;
  absolute_value_tolerance: number;
};

export type BoptestSingleQualification = {
  mapping: BoptestMapping;
  oracles: BoptestOracle[];
  steps: number;
  step_seconds: number;
  start_time: number;
  warmup_period: number;
  scenario?: BoptestScenario;
};

export type BoptestQualificationCase = Omit<BoptestSingleQualification, 'mapping'> & {
  id: string;
};

export type BoptestQualificationSuite = {
  mapping: BoptestMapping;
  cases: BoptestQualificationCase[];
};

export type BoptestQualification = BoptestSingleQualification | BoptestQualificationSuite;

export function boptestSignalLabel(signal: BoptestSignal): string {
  const bounds = signal.minimum !== null || signal.maximum !== null ? `${signal.minimum ?? '−∞'}…${signal.maximum ?? '∞'}` : null;
  const detail = [signal.unit, bounds, signal.description].filter(Boolean).join(' · ');
  return `${signal.name}${detail ? ` — ${detail}` : ''}`;
}

function normalizedSignal(value: string): string {
  return value.toLowerCase().replaceAll(/[^a-z0-9]/g, '');
}

export function exactBoptestSignalMatch(id: string, label: string, signals: BoptestSignal[]): string {
  const desired = new Set([normalizedSignal(id), normalizedSignal(label)]);
  const matches = signals.filter((signal) => desired.has(normalizedSignal(signal.name)));
  return matches.length === 1 ? matches[0].name : '';
}

function numericDraft(value: string, label: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new Error(`${label} must be a finite number`);
  return parsed;
}

function unique(values: string[], label: string): void {
  if (new Set(values).size !== values.length) throw new Error(`BOPTEST mapping contains duplicate ${label}`);
}

export function buildBoptestScenario(draft?: BoptestScenarioDraft): BoptestScenario | undefined {
  if (!draft) return undefined;
  const scenario: BoptestScenario = {};
  const timePeriod = draft.timePeriod.trim();
  if (timePeriod) {
    if (!/^[a-z][a-z0-9_]{0,119}$/.test(timePeriod)) throw new Error('BOPTEST time period is invalid');
    scenario.time_period = timePeriod;
  }
  const prices = new Set(['constant', 'dynamic', 'highly_dynamic']);
  if (draft.electricityPrice) {
    if (!prices.has(draft.electricityPrice)) throw new Error('BOPTEST electricity price scenario is invalid');
    scenario.electricity_price = draft.electricityPrice;
  }
  const uncertaintyLevels = new Set(['none', 'low', 'medium', 'high']);
  if (draft.temperatureUncertainty) {
    if (!uncertaintyLevels.has(draft.temperatureUncertainty)) throw new Error('BOPTEST temperature uncertainty is invalid');
    scenario.temperature_uncertainty = draft.temperatureUncertainty;
  }
  if (draft.solarUncertainty) {
    if (!uncertaintyLevels.has(draft.solarUncertainty)) throw new Error('BOPTEST solar uncertainty is invalid');
    scenario.solar_uncertainty = draft.solarUncertainty;
  }
  if (draft.seed.trim()) {
    const seed = Number(draft.seed);
    if (!Number.isInteger(seed) || seed < 0 || seed > 2_147_483_647) throw new Error('BOPTEST uncertainty seed must be a nonnegative integer');
    if (![scenario.temperature_uncertainty, scenario.solar_uncertainty].some((value) => value && value !== 'none')) throw new Error('BOPTEST uncertainty seed requires weather uncertainty');
    scenario.seed = seed;
  }
  return Object.keys(scenario).length ? scenario : undefined;
}

export function buildBoptestMapping(
  testCase: string,
  graphInputs: ControlGraph['blocks'],
  graphOutputs: ControlGraph['blocks'],
  measurementDrafts: Record<string, BoptestMeasurementBindingDraft>,
  actuatorDrafts: Record<string, BoptestActuatorBindingDraft>,
): BoptestMapping {
  const reviewedTestCase = testCase.trim();
  if (!reviewedTestCase || reviewedTestCase === 'REVIEW_REQUIRED') throw new Error('Select and inspect a BOPTEST test case');
  if (!graphInputs.length) throw new Error('The graph has no controller inputs to bind to BOPTEST measurements');
  if (!graphOutputs.length) throw new Error('The graph has no controller outputs to bind to BOPTEST actuators');

  const measurements = graphInputs.map((block) => {
    const draft = measurementDrafts[block.id];
    if (!draft?.measurement) throw new Error(`Graph input ${block.id} has no reviewed BOPTEST measurement`);
    return {
      graph_input: block.id,
      measurement: draft.measurement,
      scale: numericDraft(draft.scale, `${block.id} scale`),
      offset: numericDraft(draft.offset, `${block.id} offset`),
    };
  });
  const actuators = graphOutputs.map((block) => {
    const draft = actuatorDrafts[block.id];
    if (!draft?.actuator) throw new Error(`Graph output ${block.id} has no reviewed BOPTEST actuator`);
    if (draft.activation && draft.activation === draft.actuator) throw new Error(`Activation actuator for ${block.id} must differ from its command actuator`);
    return {
      graph_output: block.id,
      actuator: draft.actuator,
      activation_actuator: draft.activation || null,
      scale: numericDraft(draft.scale, `${block.id} scale`),
      offset: numericDraft(draft.offset, `${block.id} offset`),
    };
  });

  unique(measurements.map((item) => item.measurement), 'measurements');
  unique(actuators.map((item) => item.actuator), 'actuators');
  const activations = actuators.flatMap((item) => item.activation_actuator ? [item.activation_actuator] : []);
  unique(activations, 'activation actuators');
  if (activations.some((activation) => actuators.some((item) => item.actuator === activation))) {
    throw new Error('Activation actuators cannot also be mapped control actuators');
  }
  return { test_case: reviewedTestCase, measurements, actuators };
}

export function buildBoptestOracles(drafts: BoptestOracleDraft[], steps: number, stepSeconds: number): BoptestOracle[] {
  if (!Number.isInteger(steps) || steps < 1) throw new Error('Oracle steps must be a positive integer');
  if (!Number.isFinite(stepSeconds) || stepSeconds <= 0) throw new Error('Oracle step seconds must be positive');
  if (!drafts.length) throw new Error('At least one independent trajectory oracle is required');
  const ids = drafts.map((draft) => draft.id.trim());
  if (new Set(ids).size !== ids.length) throw new Error('Trajectory oracle IDs must be unique');
  return drafts.map((draft) => {
    const id = draft.id.trim();
    if (!/^[A-Za-z][A-Za-z0-9_.-]{0,119}$/.test(id)) throw new Error(`Oracle ID ${id || '(blank)'} is invalid`);
    if (!draft.signal) throw new Error(`Oracle ${id} has no reviewed signal`);
    const parsed = draft.referenceValues.trim().split(/[\s,]+/).filter(Boolean).map(Number);
    if (!parsed.length || parsed.some((value) => !Number.isFinite(value))) throw new Error(`Oracle ${id} expected values must be finite numbers`);
    const referenceValues = parsed.length === 1 ? Array.from({ length: steps }, () => parsed[0]) : parsed;
    if (referenceValues.length !== steps) throw new Error(`Oracle ${id} requires one value or exactly ${steps} trajectory values`);
    const absoluteTimeTolerance = numericDraft(draft.timeTolerance, `${id} time tolerance`);
    const absoluteValueTolerance = numericDraft(draft.valueTolerance, `${id} value tolerance`);
    if (absoluteTimeTolerance < 0 || absoluteValueTolerance < 0) throw new Error(`Oracle ${id} tolerances cannot be negative`);
    return {
      id,
      signal_kind: draft.signalKind,
      signal: draft.signal,
      reference_times: Array.from({ length: steps }, (_, index) => (index + 1) * stepSeconds),
      reference_values: referenceValues,
      absolute_time_tolerance: absoluteTimeTolerance,
      absolute_value_tolerance: absoluteValueTolerance,
    };
  });
}

export function buildBoptestQualification(
  testCase: string,
  graphInputs: ControlGraph['blocks'],
  graphOutputs: ControlGraph['blocks'],
  measurementDrafts: Record<string, BoptestMeasurementBindingDraft>,
  actuatorDrafts: Record<string, BoptestActuatorBindingDraft>,
  oracleDrafts: BoptestOracleDraft[],
  steps: number,
  stepSeconds: number,
  startTime: string,
  warmupPeriod: string,
  scenarioDraft?: BoptestScenarioDraft,
): BoptestSingleQualification {
  const start_time = numericDraft(startTime, 'Start time');
  const warmup_period = numericDraft(warmupPeriod, 'Warmup period');
  if (start_time < 0) throw new Error('Start time cannot be negative');
  if (warmup_period < 0) throw new Error('Warmup period cannot be negative');
  const scenario = buildBoptestScenario(scenarioDraft);
  if (scenario?.time_period && (start_time !== 0 || warmup_period !== 0)) throw new Error('Named BOPTEST time periods cannot be combined with explicit start or warmup');
  return {
    mapping: buildBoptestMapping(testCase, graphInputs, graphOutputs, measurementDrafts, actuatorDrafts),
    oracles: buildBoptestOracles(oracleDrafts, steps, stepSeconds),
    steps,
    step_seconds: stepSeconds,
    start_time,
    warmup_period,
    ...(scenario ? { scenario } : {}),
  };
}

export function buildBoptestQualificationCase(
  id: string,
  qualification: BoptestSingleQualification,
): BoptestQualificationCase {
  const reviewedId = id.trim();
  if (!/^[A-Za-z][A-Za-z0-9_.-]{0,119}$/.test(reviewedId)) {
    throw new Error(`Qualification case ID ${reviewedId || '(blank)'} is invalid`);
  }
  return {
    id: reviewedId,
    oracles: qualification.oracles,
    steps: qualification.steps,
    step_seconds: qualification.step_seconds,
    start_time: qualification.start_time,
    warmup_period: qualification.warmup_period,
    ...(qualification.scenario ? { scenario: qualification.scenario } : {}),
  };
}

export function buildBoptestQualificationSuite(
  mapping: BoptestMapping,
  cases: BoptestQualificationCase[],
): BoptestQualificationSuite {
  if (!cases.length) throw new Error('A BOPTEST qualification suite requires at least one operating condition');
  if (cases.length > 50) throw new Error('A BOPTEST qualification suite cannot exceed 50 operating conditions');
  const ids = cases.map((item) => item.id);
  if (new Set(ids).size !== ids.length) throw new Error('BOPTEST qualification case IDs must be unique');
  if (cases.reduce((total, item) => total + item.steps, 0) > 1_000_000) {
    throw new Error('A BOPTEST qualification suite cannot exceed 1,000,000 simulation steps');
  }
  return { mapping, cases };
}

export function validateBoptestQualificationBoundary(
  qualification: BoptestQualification,
  graphOutputs: ControlGraph['blocks'],
  contract: BoptestTestCaseContract,
): void {
  if (contract.test_case !== qualification.mapping.test_case) throw new Error('The inspected BOPTEST case does not match the qualification');
  const measurements = new Set(contract.measurements.map((signal) => signal.name));
  const commands = new Set(contract.inputs.filter((signal) => !signal.activation_signal).map((signal) => signal.name));
  const activations = new Set(contract.inputs.filter((signal) => signal.activation_signal).map((signal) => signal.name));
  for (const binding of qualification.mapping.measurements) {
    if (!measurements.has(binding.measurement)) throw new Error(`${binding.measurement} is not advertised as a measurement by ${contract.test_case}`);
  }
  for (const binding of qualification.mapping.actuators) {
    if (!commands.has(binding.actuator)) throw new Error(`${binding.actuator} is not advertised as a command input by ${contract.test_case}`);
    if (binding.activation_actuator !== null && !activations.has(binding.activation_actuator)) throw new Error(`${binding.activation_actuator} is not advertised as an activation input by ${contract.test_case}`);
  }
  const cases = 'cases' in qualification ? qualification.cases : [qualification];
  for (const qualificationCase of cases) {
    for (const oracle of qualificationCase.oracles) {
      const present = oracle.signal_kind === 'graph_output'
        ? graphOutputs.some((block) => block.id === oracle.signal)
        : measurements.has(oracle.signal);
      if (!present) throw new Error(`Oracle ${oracle.id} references an unreviewed ${oracle.signal_kind.replace('_', ' ')} signal`);
    }
  }
}
