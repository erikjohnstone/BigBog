import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { LineChart } from 'echarts/charts';
import { AriaComponent, GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import type { EChartsCoreOption, EChartsType } from 'echarts/core';
import {
  Activity,
  Building2,
  CheckCircle2,
  CircleAlert,
  Cpu,
  FlaskConical,
  FileUp,
  Gauge,
  Network,
  Play,
  ShieldCheck,
  Waves,
} from 'lucide-react';
import { toast } from 'sonner';

import { api, type AlfalfaEvidence, type ArtifactState, type BacnetLab, type BoptestEvidence, type ControlGraph, type FmiModel, type FmiVariable, type QualificationJob, type RunDetail } from '../../api/client';
import { buildAlfalfaMapping, buildAlfalfaOracles, exactSignalMatch, signalLabel, type AlfalfaOracleDraft, type AlfalfaOracleSignalKind, type CommandBindingDraft, type SensorBindingDraft } from './alfalfa-mapping';

echarts.use([AriaComponent, GridComponent, LegendComponent, TooltipComponent, LineChart, CanvasRenderer]);

export function SimulationLab({ run }: { run: RunDetail }) {
  const queryClient = useQueryClient();
  const boptest = useQuery({ queryKey: ['boptest', run.id], queryFn: () => api.boptest(run.id) });
  const bacnet = useQuery({ queryKey: ['bacnet-lab', run.id], queryFn: () => api.bacnetLab(run.id) });
  const alfalfa = useQuery({ queryKey: ['alfalfa', run.id], queryFn: () => api.alfalfa(run.id) });
  const qualificationJob = useQuery({
    queryKey: ['qualification-job', run.id],
    queryFn: () => api.latestQualificationJob(run.id),
    refetchInterval: (query) => {
      const value = query.state.data;
      return value?.state === 'available' && ['queued', 'running', 'cancel_requested'].includes(value.data.status) ? 1_000 : false;
    },
  });
  const graph = useQuery({ queryKey: ['graph', run.id], queryFn: () => api.graph(run.id) });
  const probe = useMutation({
    mutationFn: () => api.probeBacnetLab(run.id),
    onSuccess: (result) => toast.success(`BAC0 independently read ${result.point_count} virtual points`),
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Loopback proof failed'),
  });
  const qualifyAlfalfa = useMutation({
    mutationFn: ({ model, qualification }: { model: File; qualification: AlfalfaQualification }) => api.enqueueAlfalfaQualification(run.id, model, qualification),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['qualification-job', run.id] });
      toast.success('Qualification queued. It will continue if this page closes.');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Alfalfa qualification failed'),
  });
  const qualifyBoptest = useMutation({
    mutationFn: (qualification: BoptestQualification) => api.enqueueBoptestQualification(run.id, qualification),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['qualification-job', run.id] });
      toast.success('BOPTEST qualification queued. It will continue if this page closes.');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'BOPTEST qualification failed'),
  });
  const cancelQualification = useMutation({
    mutationFn: (jobId: string) => api.cancelQualificationJob(jobId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['qualification-job', run.id] });
      toast.info('Qualification cancellation requested');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not cancel qualification'),
  });
  const reportedTerminalJob = useRef<string | null>(null);
  useEffect(() => {
    const state = qualificationJob.data;
    if (state?.state !== 'available' || !['succeeded', 'failed', 'canceled'].includes(state.data.status)) return;
    const notification = `${state.data.id}:${state.data.status}`;
    if (reportedTerminalJob.current === notification) return;
    reportedTerminalJob.current = notification;
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: ['alfalfa', run.id] }),
      queryClient.invalidateQueries({ queryKey: ['boptest', run.id] }),
      queryClient.invalidateQueries({ queryKey: ['runs'] }),
      queryClient.invalidateQueries({ queryKey: ['run', run.id] }),
    ]);
    const runtime = state.data.kind === 'alfalfa' ? 'Alfalfa exact-FMU' : 'BOPTEST';
    if (state.data.status === 'succeeded' && state.data.qualification_passed) toast.success(`${runtime} qualification passed and entered the approval boundary`);
    else if (state.data.status === 'succeeded') toast.error(`${runtime} execution completed, but its trajectory oracle failed. Approval is blocked.`);
    else if (state.data.status === 'failed') toast.error(state.data.error ?? 'Qualification worker failed');
  }, [qualificationJob.data, queryClient, run.id]);

  const latestJob = qualificationJob.data?.state === 'available' ? qualificationJob.data.data : undefined;
  const qualificationActive = Boolean(latestJob && ['queued', 'running', 'cancel_requested'].includes(latestJob.status));

  if (boptest.isLoading || bacnet.isLoading || alfalfa.isLoading || qualificationJob.isLoading || graph.isLoading) return <div className="simulation-state"><div className="studio-state-spinner" /><strong>Loading retained simulation evidence…</strong></div>;
  return (
    <div className="simulation-lab">
      <section className="simulation-hero">
        <div className="simulation-hero-icon"><FlaskConical size={25} /></div>
        <div><span className="eyebrow">MULTI-FIDELITY VALIDATION</span><h2>Prove the control program against behavior and protocol</h2><p>Evidence is retained with this exact candidate. Missing tiers stay visibly unqualified.</p></div>
        <div className="simulation-boundary"><ShieldCheck size={18} /><span><strong>Offline only</strong>No live routes or writes</span></div>
      </section>

      <FidelityRail run={run} boptest={boptest.data} bacnet={bacnet.data} alfalfa={alfalfa.data} />

      {boptest.data?.state === 'invalid' && <IntegrityWarning label="BOPTEST evidence failed integrity validation" message={boptest.data.message} />}
      {bacnet.data?.state === 'invalid' && <IntegrityWarning label="Virtual BACnet evidence could not be validated" message={bacnet.data.message} />}
      {alfalfa.data?.state === 'invalid' && <IntegrityWarning label="Alfalfa FMU evidence failed validation" message={alfalfa.data.message} />}

      <AlfalfaPanel evidence={alfalfa.data} job={latestJob?.kind === 'alfalfa' ? latestJob : undefined} graph={graph.data} bacnetAvailable={bacnet.data?.state === 'available'} canQualify={run.status === 'ready_for_review'} otherQualificationActive={qualificationActive && latestJob?.kind !== 'alfalfa'} onQualify={(model, qualification) => qualifyAlfalfa.mutateAsync({ model, qualification })} qualifying={qualifyAlfalfa.isPending} onCancel={(jobId) => cancelQualification.mutate(jobId)} canceling={cancelQualification.isPending} />

      <div className="simulation-grid">
        <BoptestPanel evidence={boptest.data} job={latestJob?.kind === 'boptest' ? latestJob : undefined} graph={graph.data} canQualify={run.status === 'ready_for_review'} otherQualificationActive={qualificationActive && latestJob?.kind !== 'boptest'} onQualify={(qualification) => qualifyBoptest.mutateAsync(qualification)} qualifying={qualifyBoptest.isPending} onCancel={(jobId) => cancelQualification.mutate(jobId)} canceling={cancelQualification.isPending} />
        <BacnetPanel lab={bacnet.data} onProbe={() => probe.mutate()} probing={probe.isPending} probe={probe.data} />
      </div>
    </div>
  );
}

function FidelityRail({ run, boptest, bacnet, alfalfa }: { run: RunDetail; boptest?: ArtifactState<BoptestEvidence>; bacnet?: ArtifactState<BacnetLab>; alfalfa?: ArtifactState<AlfalfaEvidence> }) {
  const levels = [
    { name: 'Typed simulator', detail: 'Deterministic acceptance', state: run.status === 'failed' ? 'failed' : 'passed', icon: Cpu },
    { name: 'Virtual BACnet', detail: 'Real BACnet/IP loopback', state: bacnet?.state === 'available' ? 'passed' : 'missing', icon: Network },
    { name: 'BOPTEST', detail: 'Dynamic building physics', state: boptest?.state === 'available' ? boptest.data.status === 'pass' ? 'passed' : 'failed' : boptest?.state === 'invalid' ? 'failed' : 'missing', icon: Waves },
    { name: 'Alfalfa FMU', detail: 'Exact graph + building model', state: alfalfa?.state === 'available' ? alfalfa.data.status === 'pass' ? 'passed' : 'failed' : alfalfa?.state === 'invalid' ? 'failed' : 'missing', icon: Building2 },
    { name: 'Licensed Niagara', detail: 'Workbench/runtime readback', state: 'missing', icon: ShieldCheck },
  ];
  return <section className="fidelity-rail" aria-label="Validation fidelity ladder">{levels.map(({ name, detail, state, icon: Icon }, index) => <div className={`fidelity-step ${state}`} key={name}><span className="fidelity-index">{index + 1}</span><Icon size={17} /><div><strong>{name}</strong><small>{detail}</small></div><b>{state === 'passed' ? 'Qualified' : state === 'failed' ? 'Blocked' : 'Not run'}</b></div>)}</section>;
}

type AlfalfaQualification = { mapping: unknown; oracles: unknown[]; steps: number; step_seconds: number; start: string; transport: 'direct' | 'bacnet_ip_loopback' };
type BoptestQualification = { mapping: unknown; oracles: unknown[]; steps: number; step_seconds: number; start_time?: number; warmup_period?: number };

function AlfalfaPanel({ evidence, job, graph, bacnetAvailable, canQualify, otherQualificationActive, onQualify, qualifying, onCancel, canceling }: { evidence?: ArtifactState<AlfalfaEvidence>; job?: QualificationJob; graph?: ControlGraph; bacnetAvailable: boolean; canQualify: boolean; otherQualificationActive: boolean; onQualify: (model: File, qualification: AlfalfaQualification) => Promise<unknown>; qualifying: boolean; onCancel: (jobId: string) => void; canceling: boolean }) {
  if (!evidence || evidence.state === 'missing') return <AlfalfaQualificationPanel job={job} graph={graph} bacnetAvailable={bacnetAvailable} canQualify={canQualify} otherQualificationActive={otherQualificationActive} onQualify={onQualify} qualifying={qualifying} onCancel={onCancel} canceling={canceling} />;
  if (evidence.state === 'invalid') return <section className="simulation-panel empty-tier failed alfalfa-panel"><CircleAlert size={28} /><span className="eyebrow">ALFALFA FMU CLOSED LOOP</span><h2>Evidence is not trustworthy</h2><p>{evidence.message}</p><span className="qualification-chip failed">Release blocked</span></section>;
  const data = evidence.data;
  const samples = data.trajectory;
  const series = alfalfaTraceSeries(data);
  const echoCount = samples.reduce((count, sample) => count + Object.keys(sample.command_echoes).length, 0);
  const initialValueCount = samples.reduce((count, sample) => count + Object.keys(sample.initial_output_values).length, 0);
  return (
    <section className="simulation-panel alfalfa-panel">
      <div className="simulation-panel-head"><div><span className="eyebrow">ALFALFA EXACT-FMU CLOSED LOOP</span><h2>{data.model_name}</h2><p>{data.graph_name} · graph {data.graph_sha256.slice(0, 10)} · model {data.model_sha256.slice(0, 10)}</p></div><span className={`qualification-chip ${data.status}`}>{data.status === 'pass' ? <CheckCircle2 size={13} /> : <CircleAlert size={13} />}{data.status === 'pass' ? 'FMU + oracle passed' : 'Oracle failed'}</span></div>
      <div className="alfalfa-metrics" aria-label="Alfalfa runtime facts"><div><span>Simulation steps</span><strong>{data.steps}</strong><small>{formatDuration(data.step_seconds)} each</small></div><div><span>FMU boundary</span><strong>{data.runtime_input_count} / {data.runtime_output_count}</strong><small>inputs / outputs</small></div><div><span>Command echoes</span><strong>{echoCount}</strong><small>all matched</small></div><div><span>Runtime stop</span><strong>{data.clean_stop ? 'Clean' : 'Failed'}</strong><small>{data.status_after_stop}</small></div></div>
      <div className="alfalfa-safety"><ShieldCheck size={18} /><div><strong>{data.control_transport ? 'Signed BACnet/IP + building-physics evidence' : 'Signed offline evidence'}</strong><span>{data.control_transport ? `${data.control_transport.read_transaction_count} real UDP reads and ${data.control_transport.write_transaction_count} priority-${data.control_transport.write_priority} writes passed exact readback checks on ${data.control_transport.bind_scope}. The controller runtime is ${data.control_transport.controller_runtime}; this does not claim licensed Niagara execution.` : 'The uploaded FMU, exact graph, signal map, complete trajectory, and hashes are inside the approval boundary. Live-building writes remained disabled.'}</span></div></div>
      <div className="trace-card"><div className="trace-card-head"><span><Activity size={15} />Graph-to-FMU trajectory</span><small>Inputs, controller outputs, and building response</small></div><TraceChart timeLabels={samples.map((sample) => formatTimestamp(sample.end_time))} series={series} description="Alfalfa exact-FMU graph and building response trajectory." /></div>
      <div className="oracle-section"><div className="trace-card-head"><span><Gauge size={15} />Independent trajectory oracles</span><small>pyfunnel acceptance scoring</small></div>{data.oracles.map((result) => <article className={result.passed ? 'pass' : 'fail'} key={result.oracle.id}><span>{result.passed ? <CheckCircle2 size={16} /> : <CircleAlert size={16} />}</span><div><strong>{result.oracle.id}</strong><small>{result.oracle.signal_kind.replaceAll('_', ' ')} · {result.oracle.signal}</small></div><dl><div><dt>Max error</dt><dd>{result.max_error === null ? '—' : formatNumber(result.max_error)}</dd></div><div><dt>Value tolerance</dt><dd>{result.oracle.absolute_value_tolerance}</dd></div><div><dt>Status</dt><dd>{result.passed ? 'Pass' : 'Fail'}</dd></div></dl></article>)}</div>
      <details className="simulation-data-table"><summary>Inspect command echoes and step evidence</summary><div><table><thead><tr><th>Step</th><th>FMU time</th><th>Controller command</th><th>FMU feedback</th><th>Echo</th><th>Initial substitute</th></tr></thead><tbody>{samples.flatMap((sample) => { const echoes = Object.entries(sample.command_echoes); return (echoes.length ? echoes : [["—", null] as const]).map(([input, echo], echoIndex) => <tr key={`${sample.index}-${input}`}><th>{sample.index + 1}{echoIndex ? '' : ''}</th><td>{formatTimestamp(sample.end_time)}</td><td>{echo ? `${input} = ${formatNumber(echo.command)}` : '—'}</td><td>{echo ? `${echo.output} = ${formatNumber(echo.feedback)}` : '—'}</td><td>{echo ? echo.matched ? 'Matched' : 'Mismatch' : 'No echo mapped'}</td><td>{Object.keys(sample.initial_output_values).length ? Object.entries(sample.initial_output_values).map(([name, value]) => `${name}=${formatNumber(value)}`).join(', ') : 'None'}</td></tr>); })}</tbody></table></div></details>
      <div className="alfalfa-footer"><span><CheckCircle2 size={15} /><strong>External-clock timing exact</strong>{data.start} → {data.end}</span><span><ShieldCheck size={15} /><strong>No hidden startup data</strong>{initialValueCount ? `${initialValueCount} reviewed tick-zero substitute${initialValueCount === 1 ? '' : 's'}` : 'All outputs supplied by FMU'}</span></div>
    </section>
  );
}

function AlfalfaQualificationPanel({ job, graph, bacnetAvailable, canQualify, otherQualificationActive, onQualify, qualifying, onCancel, canceling }: { job?: QualificationJob; graph?: ControlGraph; bacnetAvailable: boolean; canQualify: boolean; otherQualificationActive: boolean; onQualify: (model: File, qualification: AlfalfaQualification) => Promise<unknown>; qualifying: boolean; onCancel: (jobId: string) => void; canceling: boolean }) {
  const [model, setModel] = useState<File | null>(null);
  const [mappingFile, setMappingFile] = useState<File | null>(null);
  const [sensorBindings, setSensorBindings] = useState<Record<string, SensorBindingDraft>>({});
  const [commandBindings, setCommandBindings] = useState<Record<string, CommandBindingDraft>>({});
  const [observedOutputs, setObservedOutputs] = useState<string[]>([]);
  const [steps, setSteps] = useState(12);
  const [stepSeconds, setStepSeconds] = useState(60);
  const [start, setStart] = useState('2019-01-01T00:00');
  const [transport, setTransport] = useState<'direct' | 'bacnet_ip_loopback'>(bacnetAvailable ? 'bacnet_ip_loopback' : 'direct');
  const [oracleDrafts, setOracleDrafts] = useState<AlfalfaOracleDraft[]>([]);
  const [error, setError] = useState<string | null>(null);
  const jobActive = job ? ['queued', 'running', 'cancel_requested'].includes(job.status) : false;
  const busy = qualifying || jobActive || otherQualificationActive;
  const graphInputs = useMemo(() => graph?.blocks.filter((block) => block.kind === 'numeric_input' || block.kind === 'boolean_input') ?? [], [graph]);
  const graphOutputs = useMemo(() => graph?.blocks.filter((block) => block.kind === 'numeric_output' || block.kind === 'boolean_output') ?? [], [graph]);
  const inspectFmu = useMutation({
    mutationFn: api.inspectAlfalfaFmu,
    onSuccess: (contract) => {
      setSensorBindings(Object.fromEntries(graphInputs.map((block) => [block.id, { output: exactSignalMatch(block.id, block.label, contract.outputs), scale: '1', offset: '0', initial: '' }])));
      setCommandBindings(Object.fromEntries(graphOutputs.map((block) => {
        const input = exactSignalMatch(block.id, block.label, contract.inputs);
        const variable = contract.inputs.find((item) => item.name === input);
        return [block.id, { input, scale: '1', offset: '0', minimum: variable?.minimum ?? '', maximum: variable?.maximum ?? '', echo: '' }];
      })));
      setObservedOutputs([]);
      setOracleDrafts([{
        id: 'behavior-1',
        signalKind: graphOutputs.length ? 'graph_output' : 'fmu_output',
        signal: graphOutputs[0]?.id ?? contract.outputs[0]?.name ?? '',
        referenceValues: '',
        timeTolerance: '0',
        valueTolerance: '0.1',
      }]);
    },
  });
  const contract = inspectFmu.data;
  const mappingReady = Boolean(contract)
    && graphInputs.every((block) => sensorBindings[block.id]?.output)
    && graphOutputs.every((block) => commandBindings[block.id]?.input);
  const selectedMappingCount = graphInputs.filter((block) => sensorBindings[block.id]?.output).length + graphOutputs.filter((block) => commandBindings[block.id]?.input).length;
  const requiredMappingCount = graphInputs.length + graphOutputs.length;
  const oracleSignals = (kind: AlfalfaOracleSignalKind) => {
    if (kind === 'graph_input') return graphInputs.map((block) => ({ value: block.id, label: `${block.label} (${block.id})` }));
    if (kind === 'graph_output') return graphOutputs.map((block) => ({ value: block.id, label: `${block.label} (${block.id})` }));
    if (kind === 'fmu_input') return Array.from(new Set(Object.values(commandBindings).map((draft) => draft.input).filter(Boolean))).map((value) => ({ value, label: value }));
    return contract?.outputs.map((variable) => ({ value: variable.name, label: signalLabel(variable) })) ?? [];
  };
  const oracleReady = useMemo(() => {
    try { buildAlfalfaOracles(oracleDrafts, steps, stepSeconds); return true; } catch { return false; }
  }, [oracleDrafts, stepSeconds, steps]);
  const selectModel = (file: File | null) => {
    setModel(file);
    setMappingFile(null);
    setError(null);
    inspectFmu.reset();
    if (file) inspectFmu.mutate(file);
  };
  const submit = async () => {
    if (!model || !contract) return;
    setError(null);
    try {
      const oracles = buildAlfalfaOracles(oracleDrafts, steps, stepSeconds);
      const requiredOracleOutputs = oracles.filter((oracle) => oracle.signal_kind === 'fmu_output').map((oracle) => oracle.signal);
      const mappingValue: unknown = mappingFile
        ? JSON.parse(await mappingFile.text())
        : buildAlfalfaMapping(graphInputs, graphOutputs, sensorBindings, commandBindings, Array.from(new Set([...observedOutputs, ...requiredOracleOutputs])));
      await onQualify(model, { mapping: mappingValue, oracles, steps, step_seconds: stepSeconds, start: `${start}:00`, transport });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The reviewed mapping is invalid');
    }
  };
  return (
    <section className="simulation-panel alfalfa-panel alfalfa-qualification">
      <div className="simulation-panel-head"><div><span className="eyebrow">ALFALFA EXACT-FMU CLOSED LOOP</span><h2>Qualify this exact candidate against a building model</h2><p>The FMU and reviewed signal map become signed artifacts. This operation never connects to a live building.</p></div><span className={`qualification-chip ${job?.status ?? 'missing'}`}>{job ? job.status.replaceAll('_', ' ') : 'Not run'}</span></div>
      {job && <QualificationJobCard job={job} onCancel={onCancel} canceling={canceling} />}
      <div className="alfalfa-qualification-grid">
        <label className={model ? 'selected' : ''}><FileUp size={20} /><span><strong>{model?.name ?? 'Building model (.fmu)'}</strong><small>{inspectFmu.isPending ? 'Inspecting FMI contract…' : model ? `${(model.size / 1024 / 1024).toFixed(1)} MiB · ${contract ? `${contract.inputs.length} inputs · ${contract.outputs.length} outputs` : 'inspection failed'}` : 'FMI archive, maximum 512 MiB'}</small></span><input accept=".fmu,application/zip" disabled={!canQualify || busy} onChange={(event) => selectModel(event.target.files?.[0] ?? null)} type="file" /></label>
        <label className={mappingFile ? 'selected' : ''}><Network size={20} /><span><strong>{mappingFile?.name ?? 'Optional reviewed map (.json)'}</strong><small>{mappingFile ? 'Imported map will be validated at execution' : 'Or build the map visually below'}</small></span><input accept=".json,application/json" disabled={!canQualify || busy || !contract} onChange={(event) => setMappingFile(event.target.files?.[0] ?? null)} type="file" /></label>
      </div>
      {contract && <FmiContractSummary contract={contract} />}
      {contract && <div className="alfalfa-mapper">
        <header><div><span className="eyebrow">REVIEWED SIGNAL CONTRACT</span><h3>Bind every typed graph boundary</h3><p>{mappingFile ? `${mappingFile.name} is active; the visual mapping remains visible as a reference while trajectory oracles are authored below.` : 'Exact-name suggestions are preselected only when unique. Every row remains a human-reviewed choice.'}</p></div><span className={mappingFile || mappingReady ? 'complete' : ''}>{mappingFile ? 'Imported map' : `${selectedMappingCount} / ${requiredMappingCount} required`}</span></header>
        <section>
          <div className="alfalfa-mapper-heading"><strong>FMU outputs → graph inputs</strong><small>Measurements read from the building model</small></div>
          <div className="alfalfa-map-table"><table><thead><tr><th>Graph input</th><th>FMU output</th><th>Scale</th><th>Offset</th><th>Tick-zero fallback</th></tr></thead><tbody>{graphInputs.map((block) => { const draft = sensorBindings[block.id] ?? { output: '', scale: '1', offset: '0', initial: '' }; return <tr key={block.id}><th><strong>{block.label}</strong><code>{block.id}</code></th><td><SignalSelect value={draft.output} variables={contract.outputs} onChange={(output) => setSensorBindings((current) => ({ ...current, [block.id]: { ...draft, output } }))} /></td><td><input aria-label={`${block.id} scale`} onChange={(event) => setSensorBindings((current) => ({ ...current, [block.id]: { ...draft, scale: event.target.value } }))} type="number" value={draft.scale} /></td><td><input aria-label={`${block.id} offset`} onChange={(event) => setSensorBindings((current) => ({ ...current, [block.id]: { ...draft, offset: event.target.value } }))} type="number" value={draft.offset} /></td><td><input aria-label={`${block.id} initial output value`} onChange={(event) => setSensorBindings((current) => ({ ...current, [block.id]: { ...draft, initial: event.target.value } }))} placeholder="Only if FMU starts null" value={draft.initial} /></td></tr>; })}</tbody></table></div>
        </section>
        <section>
          <div className="alfalfa-mapper-heading"><strong>Graph outputs → FMU inputs</strong><small>Bounded commands written only inside the simulation</small></div>
          <div className="alfalfa-map-table"><table><thead><tr><th>Graph output</th><th>FMU input</th><th>Scale</th><th>Offset</th><th>Minimum</th><th>Maximum</th><th>Echo output</th></tr></thead><tbody>{graphOutputs.map((block) => { const draft = commandBindings[block.id] ?? { input: '', scale: '1', offset: '0', minimum: '', maximum: '', echo: '' }; return <tr key={block.id}><th><strong>{block.label}</strong><code>{block.id}</code></th><td><SignalSelect value={draft.input} variables={contract.inputs} onChange={(input) => { const variable = contract.inputs.find((item) => item.name === input); setCommandBindings((current) => ({ ...current, [block.id]: { ...draft, input, minimum: variable?.minimum ?? '', maximum: variable?.maximum ?? '' } })); }} /></td><td><input aria-label={`${block.id} scale`} onChange={(event) => setCommandBindings((current) => ({ ...current, [block.id]: { ...draft, scale: event.target.value } }))} type="number" value={draft.scale} /></td><td><input aria-label={`${block.id} offset`} onChange={(event) => setCommandBindings((current) => ({ ...current, [block.id]: { ...draft, offset: event.target.value } }))} type="number" value={draft.offset} /></td><td><input aria-label={`${block.id} minimum`} onChange={(event) => setCommandBindings((current) => ({ ...current, [block.id]: { ...draft, minimum: event.target.value } }))} type="number" value={draft.minimum} /></td><td><input aria-label={`${block.id} maximum`} onChange={(event) => setCommandBindings((current) => ({ ...current, [block.id]: { ...draft, maximum: event.target.value } }))} type="number" value={draft.maximum} /></td><td><SignalSelect optional value={draft.echo} variables={contract.outputs} onChange={(echo) => setCommandBindings((current) => ({ ...current, [block.id]: { ...draft, echo } }))} /></td></tr>; })}</tbody></table></div>
        </section>
        <label className="alfalfa-observed"><span><strong>Additional observed outputs</strong><small>Optional building-response signals to retain in every trajectory step</small></span><select multiple onChange={(event) => setObservedOutputs(Array.from(event.target.selectedOptions, (option) => option.value))} value={observedOutputs}>{contract.outputs.map((variable) => <option key={variable.name} value={variable.name}>{signalLabel(variable)}</option>)}</select></label>
        <section className="alfalfa-oracle-builder"><div className="alfalfa-mapper-heading"><strong>Independent pass/fail trajectory</strong><small>One value repeats for every step; otherwise enter exactly {steps} comma-separated values</small></div><div className="alfalfa-map-table"><table><thead><tr><th>Oracle ID</th><th>Signal kind</th><th>Reviewed signal</th><th>Expected values</th><th>Value tolerance</th><th /></tr></thead><tbody>{oracleDrafts.map((draft, index) => <tr key={`${index}-${draft.id}`}><td><input aria-label={`Oracle ${index + 1} ID`} onChange={(event) => setOracleDrafts((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, id: event.target.value } : item))} value={draft.id} /></td><td><select aria-label={`Oracle ${index + 1} signal kind`} onChange={(event) => { const signalKind = event.target.value as AlfalfaOracleSignalKind; const signal = oracleSignals(signalKind)[0]?.value ?? ''; setOracleDrafts((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, signalKind, signal } : item)); }} value={draft.signalKind}><option value="graph_output">Graph output</option><option value="graph_input">Graph input</option><option value="fmu_output">FMU output</option><option value="fmu_input">FMU input</option></select></td><td><select aria-label={`Oracle ${index + 1} signal`} onChange={(event) => setOracleDrafts((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, signal: event.target.value } : item))} value={draft.signal}><option value="">Select signal…</option>{oracleSignals(draft.signalKind).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></td><td><input aria-label={`Oracle ${index + 1} expected values`} onChange={(event) => setOracleDrafts((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, referenceValues: event.target.value } : item))} placeholder={`1 value or ${steps} values`} value={draft.referenceValues} /></td><td><input aria-label={`Oracle ${index + 1} value tolerance`} min={0} onChange={(event) => setOracleDrafts((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, valueTolerance: event.target.value } : item))} type="number" value={draft.valueTolerance} /></td><td><button aria-label={`Remove oracle ${index + 1}`} disabled={oracleDrafts.length === 1} onClick={() => setOracleDrafts((current) => current.filter((_, itemIndex) => itemIndex !== index))} type="button">Remove</button></td></tr>)}</tbody></table></div><button onClick={() => setOracleDrafts((current) => [...current, { id: `behavior-${current.length + 1}`, signalKind: 'graph_output', signal: graphOutputs[0]?.id ?? '', referenceValues: '', timeTolerance: '0', valueTolerance: '0.1' }])} type="button">Add trajectory oracle</button></section>
      </div>}
      <div className="alfalfa-run-settings"><label><span>Control transport</span><select disabled={!canQualify || busy} onChange={(event) => setTransport(event.target.value as 'direct' | 'bacnet_ip_loopback')} value={transport}><option value="direct">Direct typed graph</option>{bacnetAvailable && <option value="bacnet_ip_loopback">BACnet/IP loopback</option>}</select></label><label><span>Model start</span><input disabled={!canQualify || busy} onChange={(event) => setStart(event.target.value)} type="datetime-local" value={start} /></label><label><span>Steps</span><input disabled={!canQualify || busy} min={1} max={100000} onChange={(event) => setSteps(Number(event.target.value))} type="number" value={steps} /></label><label><span>Seconds / step</span><input disabled={!canQualify || busy} min={0.001} onChange={(event) => setStepSeconds(Number(event.target.value))} type="number" value={stepSeconds} /></label><button disabled={!canQualify || !model || !contract || (!mappingFile && !mappingReady) || !oracleReady || busy || steps < 1 || stepSeconds <= 0} onClick={submit} type="button"><Play size={15} />{jobActive ? job?.status === 'cancel_requested' ? 'Stopping safely…' : 'Qualification running…' : qualifying ? 'Queueing qualification…' : 'Queue and sign qualification'}</button></div>
      {bacnetAvailable && transport === 'bacnet_ip_loopback' && <div className="alfalfa-form-message"><Network size={16} />Every graph sensor and command must have an exact BACnet object. Qualification performs real loopback UDP reads, priority writes, and readbacks between each FMU step.</div>}
      {otherQualificationActive && <div className="alfalfa-form-message"><CircleAlert size={16} />Another building-physics qualification is active for this candidate. Wait for it to finish or cancel it before starting Alfalfa.</div>}
      {!canQualify && <div className="alfalfa-form-message"><CircleAlert size={16} />Only a passing candidate awaiting review can start a new qualification.</div>}
      {inspectFmu.isError && <div className="alfalfa-form-message error"><CircleAlert size={16} />{inspectFmu.error instanceof Error ? inspectFmu.error.message : 'FMU inspection failed'}</div>}
      {error && <div className="alfalfa-form-message error"><CircleAlert size={16} />{error}</div>}
    </section>
  );
}

function FmiContractSummary({ contract }: { contract: FmiModel }) {
  return <div className="fmi-contract"><div><span>Model</span><strong>{contract.model_name}</strong><small>FMI {contract.fmi_version} · {contract.model_identifiers.join(', ') || 'identifier not declared'}</small></div><div><span>Declared boundary</span><strong>{contract.inputs.length} in / {contract.outputs.length} out</strong><small>{contract.variable_count.toLocaleString()} total variables</small></div><div><span>Binary platforms</span><strong>{contract.platforms.join(', ') || 'None declared'}</strong><small>{contract.generation_tool ?? 'Generation tool not declared'}</small></div><div><span>Model digest</span><strong>{contract.sha256.slice(0, 12)}</strong><small>No model code executed during inspection</small></div></div>;
}

function SignalSelect({ variables, value, onChange, optional = false }: { variables: FmiVariable[]; value: string; onChange: (value: string) => void; optional?: boolean }) {
  return <select onChange={(event) => onChange(event.target.value)} value={value}><option value="">{optional ? 'No echo required' : 'Select exact signal…'}</option>{variables.map((variable) => <option key={variable.name} value={variable.name}>{signalLabel(variable)}</option>)}</select>;
}

function QualificationJobCard({ job, onCancel, canceling }: { job: QualificationJob; onCancel: (jobId: string) => void; canceling: boolean }) {
  const active = ['queued', 'running', 'cancel_requested'].includes(job.status);
  const label = job.model_filename ?? (job.kind === 'boptest' ? 'BOPTEST building-physics run' : 'Building FMU');
  return <div className={`qualification-job-card ${job.status}`}><div><strong>{label}</strong><span>{job.progress.phase.replaceAll('_', ' ')} · {job.progress.completed_steps}/{job.progress.total_steps} steps</span><small>Worker {job.worker_id ?? 'awaiting assignment'} · candidate {job.candidate_artifact_sha256?.slice(0, 12) ?? 'legacy-unbound'} · input {job.input_sha256.slice(0, 12)}</small></div><div className="qualification-job-progress"><i style={{ width: `${job.progress.percent}%` }} /></div><b>{job.progress.percent.toFixed(0)}%</b>{active && <button disabled={canceling || job.status === 'cancel_requested'} onClick={() => onCancel(job.id)} type="button">{job.status === 'cancel_requested' ? 'Stopping safely…' : canceling ? 'Requesting…' : 'Cancel run'}</button>}{job.error && <p>{job.error}</p>}</div>;
}

function boptestContractTemplate(graph?: ControlGraph): string {
  const inputs = graph?.blocks.filter((block) => block.kind === 'numeric_input' || block.kind === 'boolean_input') ?? [];
  const outputs = graph?.blocks.filter((block) => block.kind === 'numeric_output' || block.kind === 'boolean_output') ?? [];
  return JSON.stringify({
    mapping: {
      test_case: 'REVIEW_REQUIRED',
      measurements: inputs.map((block) => ({ graph_input: block.id, measurement: 'REVIEW_REQUIRED', scale: 1, offset: 0 })),
      actuators: outputs.map((block) => ({ graph_output: block.id, actuator: 'REVIEW_REQUIRED', activation_actuator: null, scale: 1, offset: 0 })),
    },
    oracles: [{ id: 'behavior-1', signal_kind: 'graph_output', signal: outputs[0]?.id ?? 'REVIEW_REQUIRED', reference_times: [300], reference_values: [null], absolute_time_tolerance: 0, absolute_value_tolerance: 0.1 }],
    steps: 1,
    step_seconds: 300,
    start_time: 0,
    warmup_period: 0,
  }, null, 2);
}

function BoptestQualificationPanel({ job, graph, canQualify, otherQualificationActive, onQualify, qualifying, onCancel, canceling }: { job?: QualificationJob; graph?: ControlGraph; canQualify: boolean; otherQualificationActive: boolean; onQualify: (qualification: BoptestQualification) => Promise<unknown>; qualifying: boolean; onCancel: (jobId: string) => void; canceling: boolean }) {
  const [contract, setContract] = useState(() => boptestContractTemplate(graph));
  const [error, setError] = useState<string | null>(null);
  const jobActive = Boolean(job && ['queued', 'running', 'cancel_requested'].includes(job.status));
  const busy = qualifying || jobActive || otherQualificationActive;
  const contractReady = useMemo(() => {
    try {
      const value = JSON.parse(contract) as { mapping?: { test_case?: unknown; measurements?: Array<{ measurement?: unknown }>; actuators?: Array<{ actuator?: unknown }> }; oracles?: Array<{ reference_values?: unknown[] }> };
      return value.mapping?.test_case !== 'REVIEW_REQUIRED'
        && value.mapping?.measurements?.every((item) => item.measurement !== 'REVIEW_REQUIRED') === true
        && value.mapping?.actuators?.every((item) => item.actuator !== 'REVIEW_REQUIRED') === true
        && Boolean(value.oracles?.length)
        && value.oracles?.every((oracle) => oracle.reference_values?.every((item) => typeof item === 'number')) === true;
    } catch {
      return false;
    }
  }, [contract]);
  const submit = async () => {
    setError(null);
    try {
      await onQualify(JSON.parse(contract) as BoptestQualification);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The BOPTEST contract is invalid');
    }
  };
  const importContract = async (file: File | null) => {
    if (!file) return;
    setError(null);
    try { setContract(await file.text()); } catch { setError('The BOPTEST contract could not be read'); }
  };
  return <section className="simulation-panel boptest-qualification"><div className="simulation-panel-head"><div><span className="eyebrow">BOPTEST CLOSED LOOP</span><h2>Qualify against a reviewed BOPTEST case</h2><p>Map every graph boundary and supply an independent expected trajectory. Signal names are never guessed.</p></div><span className={`qualification-chip ${job?.status ?? 'missing'}`}>{job ? job.status.replaceAll('_', ' ') : 'Not run'}</span></div>{job && <QualificationJobCard job={job} onCancel={onCancel} canceling={canceling} />}<div className="boptest-contract-editor"><header><div><strong>Reviewed mapping + oracle contract</strong><small>The generated skeleton contains every typed graph boundary. Replace every REVIEW_REQUIRED value and null reference before queueing.</small></div><label><FileUp size={14} />Import JSON<input accept=".json,application/json" disabled={busy || !canQualify} onChange={(event) => void importContract(event.target.files?.[0] ?? null)} type="file" /></label></header><textarea aria-label="BOPTEST qualification contract" disabled={busy || !canQualify} onChange={(event) => setContract(event.target.value)} spellCheck={false} value={contract} /><footer><span className={contractReady ? 'ready' : ''}>{contractReady ? 'Contract ready for server validation' : 'Complete all reviewed mappings and numeric oracle values'}</span><button disabled={!canQualify || busy || !contractReady} onClick={() => void submit()} type="button"><Play size={14} />{jobActive ? 'Qualification running…' : qualifying ? 'Queueing…' : 'Queue BOPTEST qualification'}</button></footer></div>{otherQualificationActive && <div className="alfalfa-form-message"><CircleAlert size={16} />Another building-physics qualification is active for this candidate.</div>}{!canQualify && <div className="alfalfa-form-message"><CircleAlert size={16} />Only a passing candidate awaiting review can start qualification.</div>}{error && <div className="alfalfa-form-message error"><CircleAlert size={16} />{error}</div>}</section>;
}

function BoptestPanel({ evidence, job, graph, canQualify, otherQualificationActive, onQualify, qualifying, onCancel, canceling }: { evidence?: ArtifactState<BoptestEvidence>; job?: QualificationJob; graph?: ControlGraph; canQualify: boolean; otherQualificationActive: boolean; onQualify: (qualification: BoptestQualification) => Promise<unknown>; qualifying: boolean; onCancel: (jobId: string) => void; canceling: boolean }) {
  if (!evidence || evidence.state === 'missing') return <BoptestQualificationPanel job={job} graph={graph} canQualify={canQualify} otherQualificationActive={otherQualificationActive} onQualify={onQualify} qualifying={qualifying} onCancel={onCancel} canceling={canceling} />;
  if (evidence.state === 'invalid') return <section className="simulation-panel empty-tier failed"><CircleAlert size={28} /><span className="eyebrow">BOPTEST PHYSICS</span><h2>Evidence is not trustworthy</h2><p>{evidence.message}</p><span className="qualification-chip failed">Release blocked</span></section>;
  const data = evidence.data;
  const samples = data.runtime.trajectory;
  const series = traceSeries(data);
  const kpis = Object.entries(data.runtime.kpis).filter(([, value]) => value !== null);
  return (
    <section className="simulation-panel boptest-panel">
      <div className="simulation-panel-head"><div><span className="eyebrow">BOPTEST CLOSED LOOP</span><h2>{data.runtime.test_case}</h2><p>{data.runtime.steps} steps · {formatDuration(data.runtime.step_seconds)} per step · exact graph {data.runtime.graph_sha256.slice(0, 10)}</p></div><span className={`qualification-chip ${data.status}`}>{data.status === 'pass' ? <CheckCircle2 size={13} /> : <CircleAlert size={13} />}{data.status === 'pass' ? 'Physics passed' : 'Physics failed'}</span></div>
      <div className="boptest-kpis" aria-label="BOPTEST KPIs">{kpis.slice(0, 6).map(([name, value]) => <div key={name}><span>{name.replaceAll('_', ' ')}</span><strong>{formatNumber(value)}</strong></div>)}</div>
      <div className="trace-card"><div className="trace-card-head"><span><Activity size={15} />Closed-loop trajectory</span><small>Controller command + building response</small></div><TraceChart timeLabels={samples.map((sample) => formatDuration(sample.end_time))} series={series} /></div>
      <details className="simulation-data-table"><summary>Accessible step-by-step trace</summary><div><table><thead><tr><th>Step</th><th>Time</th>{series.map((item) => <th key={item.name}>{item.name}</th>)}</tr></thead><tbody>{samples.map((sample, index) => <tr key={sample.index}><th>{sample.index + 1}</th><td>{formatDuration(sample.end_time)}</td>{series.map((item) => <td key={item.name}>{formatNumber(item.values[index])}</td>)}</tr>)}</tbody></table></div></details>
      <div className="oracle-section"><div className="trace-card-head"><span><Gauge size={15} />Independent trajectory oracles</span><small>pyfunnel tolerance scoring</small></div>{data.oracles.map((result) => <article className={result.passed ? 'pass' : 'fail'} key={result.oracle.id}><span>{result.passed ? <CheckCircle2 size={16} /> : <CircleAlert size={16} />}</span><div><strong>{result.oracle.id}</strong><small>{result.oracle.signal_kind.replaceAll('_', ' ')} · {result.oracle.signal}</small></div><dl><div><dt>Max error</dt><dd>{result.max_error === null ? '—' : formatNumber(result.max_error)}</dd></div><div><dt>Value tolerance</dt><dd>{result.oracle.absolute_value_tolerance}</dd></div><div><dt>Status</dt><dd>{result.passed ? 'Pass' : 'Fail'}</dd></div></dl></article>)}</div>
    </section>
  );
}

type Trace = { name: string; values: Array<number | null>; lane: 'input' | 'output' | 'measurement' };
function traceSeries(evidence: BoptestEvidence): Trace[] {
  const trajectory = evidence.runtime.trajectory;
  if (!trajectory.length) return [];
  const definitions: Array<{ section: 'graph_inputs' | 'controller_outputs' | 'measurements'; lane: Trace['lane'] }> = [
    { section: 'graph_inputs', lane: 'input' },
    { section: 'controller_outputs', lane: 'output' },
    { section: 'measurements', lane: 'measurement' },
  ];
  return definitions.flatMap(({ section, lane }) => Object.keys(trajectory[0][section]).map((name) => ({
    name,
    lane,
    values: trajectory.map((sample) => {
      const value = sample[section][name];
      return typeof value === 'boolean' ? Number(value) : typeof value === 'number' ? value : null;
    }),
  })));
}

function alfalfaTraceSeries(evidence: AlfalfaEvidence): Trace[] {
  const trajectory = evidence.trajectory;
  if (!trajectory.length) return [];
  const definitions: Array<{ section: 'graph_inputs' | 'controller_outputs' | 'observed_outputs'; lane: Trace['lane'] }> = [
    { section: 'graph_inputs', lane: 'input' },
    { section: 'controller_outputs', lane: 'output' },
    { section: 'observed_outputs', lane: 'measurement' },
  ];
  return definitions.flatMap(({ section, lane }) => Object.keys(trajectory[0][section]).map((name) => ({
    name,
    lane,
    values: trajectory.map((sample) => {
      const value = sample[section][name];
      return typeof value === 'boolean' ? Number(value) : typeof value === 'number' ? value : null;
    }),
  })));
}

function TraceChart({ timeLabels, series, description = 'BOPTEST closed-loop controller and building response trajectory.' }: { timeLabels: string[]; series: Trace[]; description?: string }) {
  const option = useMemo<EChartsCoreOption>(() => ({
    animation: false,
    aria: { enabled: true, decal: { show: true }, description },
    color: ['#607985', '#17785a', '#bb7045', '#5a6db0', '#8e5e99'],
    tooltip: { trigger: 'axis' },
    legend: { bottom: 2, type: 'scroll', textStyle: { color: '#4d5d67', fontSize: 9 } },
    grid: { left: 52, right: 24, top: 30, bottom: 62 },
    xAxis: { type: 'category', data: timeLabels, axisLabel: { color: '#67757e', fontSize: 8 } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: '#67757e', fontSize: 8 }, splitLine: { lineStyle: { color: '#e8ecee' } } },
    series: series.map((item) => ({ name: item.name, type: 'line', data: item.values, symbolSize: 6, lineStyle: { width: item.lane === 'output' ? 3 : 2, type: item.lane === 'measurement' ? 'dashed' : 'solid' }, connectNulls: false })),
  }), [description, series, timeLabels]);
  return <EChart option={option} label={description} />;
}

function EChart({ option, label }: { option: EChartsCoreOption; label: string }) {
  const target = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!target.current) return;
    const chart: EChartsType = echarts.init(target.current, undefined, { renderer: 'canvas' });
    chart.setOption(option);
    const resize = new ResizeObserver(() => chart.resize());
    resize.observe(target.current);
    return () => { resize.disconnect(); chart.dispose(); };
  }, [option]);
  return <div aria-label={label} className="simulation-chart" ref={target} role="img" />;
}

function BacnetPanel({ lab, onProbe, probing, probe }: { lab?: ArtifactState<BacnetLab>; onProbe: () => void; probing: boolean; probe?: Awaited<ReturnType<typeof api.probeBacnetLab>> }) {
  if (!lab || lab.state === 'missing') return <section className="simulation-panel empty-tier"><Network size={28} /><span className="eyebrow">VIRTUAL BACNET</span><h2>No mapped scan was supplied</h2><p>Add a BACnet scan during intake to generate signed loopback devices, point maps, scenario injection, and independent BAC0 readback.</p><span className="qualification-chip missing">No protocol fixture</span></section>;
  if (lab.state === 'invalid') return <section className="simulation-panel empty-tier failed"><CircleAlert size={28} /><span className="eyebrow">VIRTUAL BACNET</span><h2>Lab manifest unavailable</h2><p>{lab.message}</p></section>;
  const data = lab.data;
  const points = Object.entries(data.point_index);
  return (
    <section className="simulation-panel bacnet-panel">
      <div className="simulation-panel-head"><div><span className="eyebrow">VIRTUAL BACNET LAB</span><h2>{data.devices.length} isolated device{data.devices.length === 1 ? '' : 's'}</h2><p>bacpypes3 devices · independent BAC0 client · MIT oracle</p></div><span className="qualification-chip pass"><ShieldCheck size={13} />Loopback only</span></div>
      <div className="bacnet-safety"><ShieldCheck size={18} /><div><strong>Hard network boundary</strong><span>Bound to {data.safety.bind_scope}. Source addresses are never bound, discovery is disabled, and writes affect virtual objects only.</span></div></div>
      <div className="device-list">{data.devices.map((device) => <article key={device.device_instance}><span className="device-led" /><div><strong>{device.device_name}</strong><small>Device {device.device_instance} · {device.network_address}</small></div><dl><div><dt>Objects</dt><dd>{device.object_count}</dd></div><div><dt>Inject</dt><dd>{device.scenario_injectable_objects}</dd></div><div><dt>Capture</dt><dd>{device.command_capture_objects}</dd></div></dl></article>)}</div>
      <div className="point-map-head"><span><Network size={15} />Canonical point map</span><small>{points.length} mapped points</small></div>
      <div className="bacnet-point-table"><table><thead><tr><th>Point</th><th>Device</th><th>Object</th><th>Test role</th><th>Readback</th></tr></thead><tbody>{points.map(([name, point]) => <tr key={name}><th>{name}</th><td>{point.device_instance}</td><td><code>{point.object_identifier}</code></td><td>{point.scenario_injectable ? 'Inject' : point.command_capture ? 'Capture' : 'Observe'}</td><td>{probe ? formatNumber(probe.values[name]) : '—'}</td></tr>)}</tbody></table></div>
      <button className="probe-button" disabled={probing} onClick={onProbe} type="button"><Play size={15} />{probing ? 'Booting devices and reading every point…' : 'Run independent loopback proof'}</button>
      {probe && <div className={probe.passed ? 'probe-result pass' : 'probe-result fail'}>{probe.passed ? <CheckCircle2 size={17} /> : <CircleAlert size={17} />}<span><strong>{probe.passed ? 'Protocol proof passed' : 'Protocol proof failed'}</strong>BAC0 read {probe.point_count} points through real loopback BACnet/IP.</span></div>}
      <details className="oracle-details"><summary>Independent protocol oracle</summary><div><strong>{data.independent_protocol_oracle.implementation}</strong><span>{data.independent_protocol_oracle.license} · {data.independent_protocol_oracle.revision.slice(0, 12)}</span><p>{data.independent_protocol_oracle.limitations}</p><div>{data.independent_protocol_oracle.capabilities.map((capability) => <code key={capability}>{capability.replaceAll('_', ' ')}</code>)}</div></div></details>
    </section>
  );
}

function IntegrityWarning({ label, message }: { label: string; message: string }) {
  return <div className="integrity-warning" role="alert"><CircleAlert size={18} /><span><strong>{label}</strong>{message}</span></div>;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = seconds / 60;
  if (minutes < 60) return `${Number.isInteger(minutes) ? minutes : minutes.toFixed(1)}m`;
  const hours = minutes / 60;
  return `${Number.isInteger(hours) ? hours : hours.toFixed(1)}h`;
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

function formatNumber(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'ON' : 'OFF';
  if (typeof value !== 'number') return value === null || value === undefined ? '—' : String(value);
  if (!Number.isFinite(value)) return '—';
  if (Math.abs(value) >= 1000 || (Math.abs(value) > 0 && Math.abs(value) < 0.001)) return value.toExponential(2);
  return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}
