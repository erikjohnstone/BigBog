import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, Plus, Trash2 } from 'lucide-react';
import { useMemo, useState } from 'react';

import { api } from '../../api/client';
import type { ControlGraph } from '../../api/client';
import { keys, useBoptestCatalog } from '../../api/queries';
import { Button, Dialog, Field, Input, NativeSelect, StatusPill } from '../../design-system/primitives';
import { exactSignalMatch, signalLabel } from './alfalfa-mapping';
import type { CommandBindingDraft, SensorBindingDraft } from './alfalfa-mapping';
import { boptestSignalLabel, exactBoptestSignalMatch } from './boptest-mapping';
import type { BoptestActuatorBindingDraft, BoptestMeasurementBindingDraft, BoptestScenarioDraft } from './boptest-mapping';
import { buildRequest, graphIo, initialState } from './wizard-request';
import type { OracleDraft, QualificationKind, WizardState } from './wizard-request';

export type { QualificationKind } from './wizard-request';
type Step = WizardState['step'];
const STEPS: Array<{ id: Step; label: string }> = [
  { id: 'source', label: 'Source' },
  { id: 'bindings', label: 'Bindings' },
  { id: 'oracles', label: 'Oracles' },
  { id: 'review', label: 'Review' },
];

/**
 * Progressive-disclosure wizard for queueing a BOPTEST or Alfalfa
 * qualification. Bindings reuse the same mapping builders the legacy lab
 * shipped with (and their tests); the boundary validation runs before the
 * request leaves the browser, and the exact JSON is shown before enqueue.
 */
export function QualificationWizard({ runId, graph, kind, open, onOpenChange }: { runId: string; graph: ControlGraph | undefined; kind: QualificationKind; open: boolean; onOpenChange: (open: boolean) => void }) {
  const [state, setState] = useState<WizardState>(() => initialState(kind));
  // A different kind resets the draft; the dialog is remounted by its parent per kind.
  const patch = (next: Partial<WizardState>) => setState((current) => ({ ...current, ...next }));
  const queryClient = useQueryClient();
  const catalog = useBoptestCatalog(open && kind === 'boptest');
  const { inputs, outputs } = useMemo(() => graphIo(graph), [graph]);

  const inspectCase = useMutation({
    mutationFn: (testCase: string) => api.inspectBoptestTestCase(testCase),
    onSuccess: (contract) => {
      const measurements: Record<string, BoptestMeasurementBindingDraft> = {};
      for (const block of inputs) measurements[block.id] = state.measurements[block.id] ?? { measurement: exactBoptestSignalMatch(block.id, block.label, contract.measurements), scale: '1', offset: '0' };
      const actuators: Record<string, BoptestActuatorBindingDraft> = {};
      const commands = contract.inputs.filter((signal) => !signal.activation_signal);
      for (const block of outputs) actuators[block.id] = state.actuators[block.id] ?? { actuator: exactBoptestSignalMatch(block.id, block.label, commands), activation: '', scale: '1', offset: '0' };
      patch({ contract, testCase: contract.test_case, measurements, actuators });
    },
  });
  const inspectFmu = useMutation({
    mutationFn: (file: File) => api.inspectAlfalfaFmu(file),
    onSuccess: (model) => {
      const sensors: Record<string, SensorBindingDraft> = {};
      for (const block of inputs) sensors[block.id] = state.sensors[block.id] ?? { output: exactSignalMatch(block.id, block.label, model.outputs), scale: '1', offset: '0', initial: '' };
      const commands: Record<string, CommandBindingDraft> = {};
      for (const block of outputs) commands[block.id] = state.commands[block.id] ?? { input: exactSignalMatch(block.id, block.label, model.inputs), scale: '1', offset: '0', minimum: '', maximum: '', echo: '' };
      patch({ model, sensors, commands });
    },
  });
  const enqueue = useMutation({
    mutationFn: async () => {
      const { request, error } = buildRequest(state, graph);
      if (error || !request) throw new Error(error ?? 'Nothing to enqueue');
      if (state.kind === 'boptest') return api.enqueueBoptestQualification(runId, request as Parameters<typeof api.enqueueBoptestQualification>[1]);
      return api.enqueueAlfalfaQualification(runId, state.file!, request as Parameters<typeof api.enqueueAlfalfaQualification>[2]);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.latestJob(runId) });
      onOpenChange(false);
    },
  });

  const review = useMemo(() => (state.step === 'review' ? buildRequest(state, graph) : null), [state, graph]);
  const stepIndex = STEPS.findIndex((item) => item.id === state.step);
  const sourceReady = state.kind === 'boptest' ? Boolean(state.contract) : Boolean(state.model);
  const canAdvance = state.step === 'source' ? sourceReady : state.step === 'review' ? false : true;
  const title = kind === 'boptest' ? 'Qualify against a BOPTEST case' : 'Qualify against an FMU on Alfalfa';

  const oracleSignals: Array<{ kind: string; label: string; options: string[] }> =
    state.kind === 'boptest'
      ? [
          { kind: 'graph_output', label: 'Graph output', options: outputs.map((block) => block.id) },
          { kind: 'measurement', label: 'BOPTEST measurement', options: state.contract?.measurements.map((signal) => signal.name) ?? [] },
        ]
      : [
          { kind: 'graph_output', label: 'Graph output', options: outputs.map((block) => block.id) },
          { kind: 'graph_input', label: 'Graph input', options: inputs.map((block) => block.id) },
          { kind: 'fmu_output', label: 'FMU output', options: state.model?.outputs.map((variable) => variable.name) ?? [] },
          { kind: 'fmu_input', label: 'FMU input', options: state.model?.inputs.map((variable) => variable.name) ?? [] },
        ];

  const setOracle = (index: number, next: Partial<OracleDraft>) => patch({ oracles: state.oracles.map((item, i) => (i === index ? { ...item, ...next } : item)) });

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      size="xl"
      title={title}
      description="Simulated evidence only. Nothing here writes to a live building, and a passing oracle never implies field qualification."
      footer={
        <>
          <Button variant="ghost" onClick={() => patch({ step: STEPS[Math.max(0, stepIndex - 1)].id })} disabled={stepIndex === 0}>
            <ChevronLeft size={14} /> Back
          </Button>
          {state.step === 'review' ? (
            <Button variant="primary" onClick={() => enqueue.mutate()} disabled={enqueue.isPending || Boolean(review?.error)}>
              {enqueue.isPending ? 'Enqueuing…' : 'Enqueue qualification'}
            </Button>
          ) : (
            <Button variant="primary" onClick={() => patch({ step: STEPS[stepIndex + 1].id })} disabled={!canAdvance}>
              Next <ChevronRight size={14} />
            </Button>
          )}
        </>
      }
    >
      <ol className="flex items-center gap-2 mb-4 text-2xs" aria-label="Wizard steps">
        {STEPS.map((item, index) => (
          <li key={item.id} className="flex items-center gap-2" aria-current={item.id === state.step ? 'step' : undefined}>
            <span className={item.id === state.step ? 'text-accent font-medium' : index < stepIndex ? 'text-fg-1' : 'text-fg-2'}>
              {index + 1} {item.label}
            </span>
            {index < STEPS.length - 1 && <span className="text-fg-2">›</span>}
          </li>
        ))}
      </ol>

      {state.step === 'source' && state.kind === 'boptest' && (
        <div className="flex flex-col gap-3">
          <Field label="BOPTEST test case" hint={catalog.isError ? `Catalog unavailable: ${(catalog.error as Error).message}` : 'Cases advertised by the configured BOPTEST service.'}>
            <div className="flex gap-2">
              <NativeSelect value={state.testCase} onChange={(event) => patch({ testCase: event.target.value })} aria-label="BOPTEST test case">
                <option value="">Select a case…</option>
                {(catalog.data?.test_cases ?? []).map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </NativeSelect>
              <Button variant="secondary" onClick={() => inspectCase.mutate(state.testCase)} disabled={!state.testCase || inspectCase.isPending}>
                {inspectCase.isPending ? 'Inspecting…' : 'Inspect contract'}
              </Button>
            </div>
          </Field>
          {inspectCase.isError && (
            <p role="alert" className="text-xs text-fail">
              {(inspectCase.error as Error).message}
            </p>
          )}
          {state.contract && (
            <div className="raised px-3 py-2 text-xs flex items-center gap-3 flex-wrap">
              <StatusPill tone="sim">{state.contract.test_case}</StatusPill>
              <span className="num text-fg-1">{state.contract.measurement_count} measurements</span>
              <span className="num text-fg-1">{state.contract.input_count} inputs</span>
              <span className="text-fg-2">clean stop · not initialized · no live writes</span>
            </div>
          )}
        </div>
      )}

      {state.step === 'source' && state.kind === 'alfalfa' && (
        <div className="flex flex-col gap-3">
          <Field label="FMU model" hint="A co-simulation FMU; inspected in the browser session before anything is queued." htmlFor="fmu-file">
            <div className="flex gap-2 items-center">
              <input id="fmu-file" type="file" accept=".fmu,application/zip" className="text-sm text-fg-1" onChange={(event) => patch({ file: event.target.files?.[0] ?? null, model: null })} />
              <Button variant="secondary" onClick={() => state.file && inspectFmu.mutate(state.file)} disabled={!state.file || inspectFmu.isPending}>
                {inspectFmu.isPending ? 'Inspecting…' : 'Inspect FMU'}
              </Button>
            </div>
          </Field>
          {inspectFmu.isError && (
            <p role="alert" className="text-xs text-fail">
              {(inspectFmu.error as Error).message}
            </p>
          )}
          {state.model && (
            <div className="raised px-3 py-2 text-xs flex items-center gap-3 flex-wrap">
              <StatusPill tone="sim">{state.model.model_name}</StatusPill>
              <span className="text-fg-1">FMI {state.model.fmi_version}</span>
              <span className="num text-fg-1">{state.model.inputs.length} inputs · {state.model.outputs.length} outputs</span>
              <span className="num text-fg-2 truncate" title={state.model.sha256}>
                {state.model.sha256.slice(0, 12)}…
              </span>
            </div>
          )}
        </div>
      )}

      {state.step === 'bindings' && (
        <div className="grid gap-4 md:grid-cols-2">
          <section aria-label="Graph inputs">
            <h3 className="eyebrow mb-2">Graph inputs ← {state.kind === 'boptest' ? 'measurements' : 'FMU outputs'}</h3>
            {inputs.length === 0 && <p className="text-xs text-fg-2">This graph has no controller inputs.</p>}
            <ul className="flex flex-col gap-2">
              {inputs.map((block) => {
                const draft = state.kind === 'boptest' ? state.measurements[block.id] : state.sensors[block.id];
                const value = state.kind === 'boptest' ? (draft as BoptestMeasurementBindingDraft | undefined)?.measurement ?? '' : (draft as SensorBindingDraft | undefined)?.output ?? '';
                const options = state.kind === 'boptest' ? (state.contract?.measurements ?? []).map((signal) => ({ value: signal.name, label: boptestSignalLabel(signal) })) : (state.model?.outputs ?? []).map((variable) => ({ value: variable.name, label: signalLabel(variable) }));
                const update = (next: Record<string, string>) =>
                  state.kind === 'boptest'
                    ? patch({ measurements: { ...state.measurements, [block.id]: { ...(state.measurements[block.id] ?? { measurement: '', scale: '1', offset: '0' }), ...next } } })
                    : patch({ sensors: { ...state.sensors, [block.id]: { ...(state.sensors[block.id] ?? { output: '', scale: '1', offset: '0', initial: '' }), ...next } } });
                return (
                  <li key={block.id} className="raised px-3 py-2 flex flex-col gap-1.5">
                    <div className="flex items-baseline gap-2 min-w-0">
                      <span className="text-sm text-fg-0 truncate">{block.label}</span>
                      <span className="num text-2xs text-fg-2 truncate">{block.id}</span>
                    </div>
                    <NativeSelect size="sm" aria-label={`${block.label} source`} value={value} onChange={(event) => update(state.kind === 'boptest' ? { measurement: event.target.value } : { output: event.target.value })}>
                      <option value="">Unbound</option>
                      {options.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </NativeSelect>
                    <div className="grid grid-cols-3 gap-1.5">
                      <Input aria-label={`${block.label} scale`} value={draft?.scale ?? '1'} onChange={(event) => update({ scale: event.target.value })} mono />
                      <Input aria-label={`${block.label} offset`} value={draft?.offset ?? '0'} onChange={(event) => update({ offset: event.target.value })} mono />
                      {state.kind === 'alfalfa' && <Input aria-label={`${block.label} tick-zero value`} placeholder="tick 0" value={(draft as SensorBindingDraft | undefined)?.initial ?? ''} onChange={(event) => update({ initial: event.target.value })} mono />}
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
          <section aria-label="Graph outputs">
            <h3 className="eyebrow mb-2">Graph outputs → {state.kind === 'boptest' ? 'actuators' : 'FMU inputs'}</h3>
            {outputs.length === 0 && <p className="text-xs text-fg-2">This graph has no controller outputs.</p>}
            <ul className="flex flex-col gap-2">
              {outputs.map((block) => {
                const draft = state.kind === 'boptest' ? state.actuators[block.id] : state.commands[block.id];
                const value = state.kind === 'boptest' ? (draft as BoptestActuatorBindingDraft | undefined)?.actuator ?? '' : (draft as CommandBindingDraft | undefined)?.input ?? '';
                const options = state.kind === 'boptest' ? (state.contract?.inputs ?? []).filter((signal) => !signal.activation_signal).map((signal) => ({ value: signal.name, label: boptestSignalLabel(signal) })) : (state.model?.inputs ?? []).map((variable) => ({ value: variable.name, label: signalLabel(variable) }));
                const activations = state.kind === 'boptest' ? (state.contract?.inputs ?? []).filter((signal) => signal.activation_signal) : [];
                const update = (next: Record<string, string>) =>
                  state.kind === 'boptest'
                    ? patch({ actuators: { ...state.actuators, [block.id]: { ...(state.actuators[block.id] ?? { actuator: '', activation: '', scale: '1', offset: '0' }), ...next } } })
                    : patch({ commands: { ...state.commands, [block.id]: { ...(state.commands[block.id] ?? { input: '', scale: '1', offset: '0', minimum: '', maximum: '', echo: '' }), ...next } } });
                return (
                  <li key={block.id} className="raised px-3 py-2 flex flex-col gap-1.5">
                    <div className="flex items-baseline gap-2 min-w-0">
                      <span className="text-sm text-fg-0 truncate">{block.label}</span>
                      <span className="num text-2xs text-fg-2 truncate">{block.id}</span>
                    </div>
                    <NativeSelect size="sm" aria-label={`${block.label} target`} value={value} onChange={(event) => update(state.kind === 'boptest' ? { actuator: event.target.value } : { input: event.target.value })}>
                      <option value="">Unbound</option>
                      {options.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </NativeSelect>
                    {state.kind === 'boptest' && (
                      <NativeSelect size="sm" aria-label={`${block.label} activation`} value={(draft as BoptestActuatorBindingDraft | undefined)?.activation ?? ''} onChange={(event) => update({ activation: event.target.value })}>
                        <option value="">No activation signal</option>
                        {activations.map((signal) => (
                          <option key={signal.name} value={signal.name}>
                            {boptestSignalLabel(signal)}
                          </option>
                        ))}
                      </NativeSelect>
                    )}
                    <div className="grid grid-cols-2 gap-1.5">
                      <Input aria-label={`${block.label} scale`} value={draft?.scale ?? '1'} onChange={(event) => update({ scale: event.target.value })} mono />
                      <Input aria-label={`${block.label} offset`} value={draft?.offset ?? '0'} onChange={(event) => update({ offset: event.target.value })} mono />
                      {state.kind === 'alfalfa' && (
                        <>
                          <Input aria-label={`${block.label} minimum`} placeholder="min" value={(draft as CommandBindingDraft | undefined)?.minimum ?? ''} onChange={(event) => update({ minimum: event.target.value })} mono />
                          <Input aria-label={`${block.label} maximum`} placeholder="max" value={(draft as CommandBindingDraft | undefined)?.maximum ?? ''} onChange={(event) => update({ maximum: event.target.value })} mono />
                          <NativeSelect size="sm" className="col-span-2" aria-label={`${block.label} echo`} value={(draft as CommandBindingDraft | undefined)?.echo ?? ''} onChange={(event) => update({ echo: event.target.value })}>
                            <option value="">No command echo</option>
                            {(state.model?.outputs ?? []).map((variable) => (
                              <option key={variable.name} value={variable.name}>
                                echo ← {variable.name}
                              </option>
                            ))}
                          </NativeSelect>
                        </>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
          {state.kind === 'alfalfa' && state.model && (
            <section aria-label="Observed outputs" className="md:col-span-2">
              <h3 className="eyebrow mb-2">Also observe</h3>
              <p className="text-2xs text-fg-2 mb-2">Bound outputs are always recorded. Tick extra FMU outputs to keep in the trajectory.</p>
              <ul className="grid gap-x-4 gap-y-1 grid-cols-[repeat(auto-fill,minmax(14rem,1fr))]">
                {state.model.outputs.map((variable) => (
                  <li key={variable.name}>
                    <label className="inline-flex items-center gap-2 text-xs text-fg-1 min-w-0">
                      <input type="checkbox" checked={state.observed.includes(variable.name)} onChange={(event) => patch({ observed: event.target.checked ? [...state.observed, variable.name] : state.observed.filter((name) => name !== variable.name) })} />
                      <span className="truncate">{variable.name}</span>
                    </label>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}

      {state.step === 'oracles' && (
        <div className="flex flex-col gap-4">
          <div className="grid gap-3 grid-cols-2 md:grid-cols-4">
            <Field label="Steps" htmlFor="q-steps">
              <Input id="q-steps" inputMode="numeric" value={state.steps} onChange={(event) => patch({ steps: event.target.value })} mono />
            </Field>
            <Field label="Step seconds" htmlFor="q-step-seconds">
              <Input id="q-step-seconds" inputMode="numeric" value={state.stepSeconds} onChange={(event) => patch({ stepSeconds: event.target.value })} mono />
            </Field>
            {state.kind === 'boptest' ? (
              <>
                <Field label="Start time (s)" htmlFor="q-start-time">
                  <Input id="q-start-time" inputMode="numeric" value={state.startTime} onChange={(event) => patch({ startTime: event.target.value })} mono />
                </Field>
                <Field label="Warmup (s)" htmlFor="q-warmup">
                  <Input id="q-warmup" inputMode="numeric" value={state.warmup} onChange={(event) => patch({ warmup: event.target.value })} mono />
                </Field>
              </>
            ) : (
              <>
                <Field label="Start (ISO)" htmlFor="q-start">
                  <Input id="q-start" value={state.start} onChange={(event) => patch({ start: event.target.value })} mono />
                </Field>
                <Field label="Transport" htmlFor="q-transport">
                  <NativeSelect id="q-transport" value={state.transport} onChange={(event) => patch({ transport: event.target.value as WizardState['transport'] })}>
                    <option value="direct">Direct</option>
                    <option value="bacnet_ip_loopback">BACnet/IP loopback</option>
                  </NativeSelect>
                </Field>
              </>
            )}
          </div>
          {state.kind === 'boptest' && (
            <details className="raised px-3 py-2">
              <summary className="text-xs text-fg-1 cursor-pointer">Scenario (optional)</summary>
              <div className="grid gap-3 grid-cols-2 md:grid-cols-5 mt-2">
                <Field label="Time period" htmlFor="q-period">
                  <Input id="q-period" value={state.scenario.timePeriod} placeholder="peak_heat_day" onChange={(event) => patch({ scenario: { ...state.scenario, timePeriod: event.target.value } })} mono />
                </Field>
                <Field label="Electricity price" htmlFor="q-price">
                  <NativeSelect id="q-price" value={state.scenario.electricityPrice} onChange={(event) => patch({ scenario: { ...state.scenario, electricityPrice: event.target.value as BoptestScenarioDraft['electricityPrice'] } })}>
                    <option value="">Default</option>
                    <option value="constant">Constant</option>
                    <option value="dynamic">Dynamic</option>
                    <option value="highly_dynamic">Highly dynamic</option>
                  </NativeSelect>
                </Field>
                <Field label="Temperature uncertainty" htmlFor="q-temp">
                  <NativeSelect id="q-temp" value={state.scenario.temperatureUncertainty} onChange={(event) => patch({ scenario: { ...state.scenario, temperatureUncertainty: event.target.value as BoptestScenarioDraft['temperatureUncertainty'] } })}>
                    <option value="">Default</option>
                    {['none', 'low', 'medium', 'high'].map((level) => (
                      <option key={level} value={level}>
                        {level}
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
                <Field label="Solar uncertainty" htmlFor="q-solar">
                  <NativeSelect id="q-solar" value={state.scenario.solarUncertainty} onChange={(event) => patch({ scenario: { ...state.scenario, solarUncertainty: event.target.value as BoptestScenarioDraft['solarUncertainty'] } })}>
                    <option value="">Default</option>
                    {['none', 'low', 'medium', 'high'].map((level) => (
                      <option key={level} value={level}>
                        {level}
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
                <Field label="Seed" htmlFor="q-seed">
                  <Input id="q-seed" inputMode="numeric" value={state.scenario.seed} onChange={(event) => patch({ scenario: { ...state.scenario, seed: event.target.value } })} mono />
                </Field>
              </div>
            </details>
          )}
          <section aria-label="Trajectory oracles">
            <div className="flex items-center gap-2 mb-2">
              <h3 className="eyebrow">Independent trajectory oracles</h3>
              <span className="text-2xs text-fg-2">pyfunnel compares the observed trajectory against a reference within tolerance.</span>
              <span className="flex-1" />
              <Button size="xs" variant="outline" onClick={() => patch({ oracles: [...state.oracles, { id: `oracle_${state.oracles.length + 1}`, signalKind: 'graph_output', signal: outputs[0]?.id ?? '', referenceValues: '', timeTolerance: '0', valueTolerance: '0.5' }] })}>
                <Plus size={12} /> Add oracle
              </Button>
            </div>
            {state.oracles.length === 0 && <p className="text-xs text-fg-2">At least one oracle is required; a qualification without one cannot pass or fail.</p>}
            <ul className="flex flex-col gap-2">
              {state.oracles.map((oracle, index) => {
                const signals = oracleSignals.find((item) => item.kind === oracle.signalKind) ?? oracleSignals[0];
                return (
                  <li key={index} className="raised px-3 py-2 grid gap-1.5 grid-cols-2 md:grid-cols-[8rem_9rem_1fr_5rem_5rem_auto] items-end">
                    <Field label="ID" htmlFor={`oracle-id-${index}`}>
                      <Input id={`oracle-id-${index}`} value={oracle.id} onChange={(event) => setOracle(index, { id: event.target.value })} mono />
                    </Field>
                    <Field label="Signal kind" htmlFor={`oracle-kind-${index}`}>
                      <NativeSelect id={`oracle-kind-${index}`} value={oracle.signalKind} onChange={(event) => setOracle(index, { signalKind: event.target.value, signal: '' })}>
                        {oracleSignals.map((item) => (
                          <option key={item.kind} value={item.kind}>
                            {item.label}
                          </option>
                        ))}
                      </NativeSelect>
                    </Field>
                    <Field label="Signal" htmlFor={`oracle-signal-${index}`}>
                      <NativeSelect id={`oracle-signal-${index}`} value={oracle.signal} onChange={(event) => setOracle(index, { signal: event.target.value })}>
                        <option value="">Select…</option>
                        {signals.options.map((name) => (
                          <option key={name} value={name}>
                            {name}
                          </option>
                        ))}
                      </NativeSelect>
                    </Field>
                    <Field label="± time" htmlFor={`oracle-tt-${index}`}>
                      <Input id={`oracle-tt-${index}`} value={oracle.timeTolerance} onChange={(event) => setOracle(index, { timeTolerance: event.target.value })} mono />
                    </Field>
                    <Field label="± value" htmlFor={`oracle-vt-${index}`}>
                      <Input id={`oracle-vt-${index}`} value={oracle.valueTolerance} onChange={(event) => setOracle(index, { valueTolerance: event.target.value })} mono />
                    </Field>
                    <Button size="icon" variant="ghost" aria-label={`Remove oracle ${oracle.id}`} onClick={() => patch({ oracles: state.oracles.filter((_, i) => i !== index) })}>
                      <Trash2 size={13} />
                    </Button>
                    <Field label="Reference values" hint="One value held for every step, or exactly one per step, comma or space separated." className="col-span-2 md:col-span-6" htmlFor={`oracle-ref-${index}`}>
                      <Input id={`oracle-ref-${index}`} value={oracle.referenceValues} placeholder="0.5" onChange={(event) => setOracle(index, { referenceValues: event.target.value })} mono />
                    </Field>
                  </li>
                );
              })}
            </ul>
          </section>
        </div>
      )}

      {state.step === 'review' && review && (
        <div className="flex flex-col gap-3">
          {review.error ? (
            <p role="alert" className="text-sm text-fail">
              {review.error}
            </p>
          ) : (
            <p className="text-sm text-fg-1">
              The request below is exactly what the server receives. It is digested and retained with the job, so the evidence can be traced back to it.
            </p>
          )}
          {review.request !== null && (
            <details open className="raised px-3 py-2">
              <summary className="text-xs text-fg-1 cursor-pointer">Request JSON</summary>
              <pre className="mt-2 text-2xs num text-fg-1 overflow-auto max-h-72 whitespace-pre">{JSON.stringify(review.request, null, 2)}</pre>
            </details>
          )}
          {enqueue.isError && (
            <p role="alert" className="text-sm text-fail">
              {(enqueue.error as Error).message}
            </p>
          )}
        </div>
      )}
    </Dialog>
  );
}
