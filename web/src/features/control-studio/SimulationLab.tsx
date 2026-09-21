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

import { api, type AlfalfaEvidence, type ArtifactState, type BacnetLab, type BoptestEvidence, type RunDetail } from '../../api/client';

echarts.use([AriaComponent, GridComponent, LegendComponent, TooltipComponent, LineChart, CanvasRenderer]);

export function SimulationLab({ run }: { run: RunDetail }) {
  const queryClient = useQueryClient();
  const boptest = useQuery({ queryKey: ['boptest', run.id], queryFn: () => api.boptest(run.id) });
  const bacnet = useQuery({ queryKey: ['bacnet-lab', run.id], queryFn: () => api.bacnetLab(run.id) });
  const alfalfa = useQuery({ queryKey: ['alfalfa', run.id], queryFn: () => api.alfalfa(run.id) });
  const probe = useMutation({
    mutationFn: () => api.probeBacnetLab(run.id),
    onSuccess: (result) => toast.success(`BAC0 independently read ${result.point_count} virtual points`),
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Loopback proof failed'),
  });
  const qualifyAlfalfa = useMutation({
    mutationFn: ({ model, qualification }: { model: File; qualification: { mapping: unknown; steps: number; step_seconds: number; start: string } }) => api.qualifyAlfalfa(run.id, model, qualification),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['alfalfa', run.id] }),
        queryClient.invalidateQueries({ queryKey: ['runs'] }),
        queryClient.invalidateQueries({ queryKey: ['run', run.id] }),
      ]);
      toast.success('Exact-FMU qualification passed and entered the approval boundary');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Alfalfa qualification failed'),
  });

  if (boptest.isLoading || bacnet.isLoading || alfalfa.isLoading) return <div className="simulation-state"><div className="studio-state-spinner" /><strong>Loading retained simulation evidence…</strong></div>;
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

      <AlfalfaPanel evidence={alfalfa.data} canQualify={run.status === 'ready_for_review'} onQualify={(model, qualification) => qualifyAlfalfa.mutateAsync({ model, qualification })} qualifying={qualifyAlfalfa.isPending} />

      <div className="simulation-grid">
        <BoptestPanel evidence={boptest.data} />
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
    { name: 'Alfalfa FMU', detail: 'Exact graph + building model', state: alfalfa?.state === 'available' ? 'passed' : alfalfa?.state === 'invalid' ? 'failed' : 'missing', icon: Building2 },
    { name: 'Licensed Niagara', detail: 'Workbench/runtime readback', state: 'missing', icon: ShieldCheck },
  ];
  return <section className="fidelity-rail" aria-label="Validation fidelity ladder">{levels.map(({ name, detail, state, icon: Icon }, index) => <div className={`fidelity-step ${state}`} key={name}><span className="fidelity-index">{index + 1}</span><Icon size={17} /><div><strong>{name}</strong><small>{detail}</small></div><b>{state === 'passed' ? 'Qualified' : state === 'failed' ? 'Blocked' : 'Not run'}</b></div>)}</section>;
}

type AlfalfaQualification = { mapping: unknown; steps: number; step_seconds: number; start: string };

function AlfalfaPanel({ evidence, canQualify, onQualify, qualifying }: { evidence?: ArtifactState<AlfalfaEvidence>; canQualify: boolean; onQualify: (model: File, qualification: AlfalfaQualification) => Promise<unknown>; qualifying: boolean }) {
  if (!evidence || evidence.state === 'missing') return <AlfalfaQualificationPanel canQualify={canQualify} onQualify={onQualify} qualifying={qualifying} />;
  if (evidence.state === 'invalid') return <section className="simulation-panel empty-tier failed alfalfa-panel"><CircleAlert size={28} /><span className="eyebrow">ALFALFA FMU CLOSED LOOP</span><h2>Evidence is not trustworthy</h2><p>{evidence.message}</p><span className="qualification-chip failed">Release blocked</span></section>;
  const data = evidence.data;
  const samples = data.trajectory;
  const series = alfalfaTraceSeries(data);
  const echoCount = samples.reduce((count, sample) => count + Object.keys(sample.command_echoes).length, 0);
  const initialValueCount = samples.reduce((count, sample) => count + Object.keys(sample.initial_output_values).length, 0);
  return (
    <section className="simulation-panel alfalfa-panel">
      <div className="simulation-panel-head"><div><span className="eyebrow">ALFALFA EXACT-FMU CLOSED LOOP</span><h2>{data.model_name}</h2><p>{data.graph_name} · graph {data.graph_sha256.slice(0, 10)} · model {data.model_sha256.slice(0, 10)}</p></div><span className="qualification-chip pass"><CheckCircle2 size={13} />FMU passed</span></div>
      <div className="alfalfa-metrics" aria-label="Alfalfa runtime facts"><div><span>Simulation steps</span><strong>{data.steps}</strong><small>{formatDuration(data.step_seconds)} each</small></div><div><span>FMU boundary</span><strong>{data.runtime_input_count} / {data.runtime_output_count}</strong><small>inputs / outputs</small></div><div><span>Command echoes</span><strong>{echoCount}</strong><small>all matched</small></div><div><span>Runtime stop</span><strong>{data.clean_stop ? 'Clean' : 'Failed'}</strong><small>{data.status_after_stop}</small></div></div>
      <div className="alfalfa-safety"><ShieldCheck size={18} /><div><strong>Signed offline evidence</strong><span>The uploaded FMU, exact graph, signal map, complete trajectory, and hashes are inside the approval boundary. Live-building writes remained disabled.</span></div></div>
      <div className="trace-card"><div className="trace-card-head"><span><Activity size={15} />Graph-to-FMU trajectory</span><small>Inputs, controller outputs, and building response</small></div><TraceChart timeLabels={samples.map((sample) => formatTimestamp(sample.end_time))} series={series} description="Alfalfa exact-FMU graph and building response trajectory." /></div>
      <details className="simulation-data-table"><summary>Inspect command echoes and step evidence</summary><div><table><thead><tr><th>Step</th><th>FMU time</th><th>Controller command</th><th>FMU feedback</th><th>Echo</th><th>Initial substitute</th></tr></thead><tbody>{samples.flatMap((sample) => { const echoes = Object.entries(sample.command_echoes); return (echoes.length ? echoes : [["—", null] as const]).map(([input, echo], echoIndex) => <tr key={`${sample.index}-${input}`}><th>{sample.index + 1}{echoIndex ? '' : ''}</th><td>{formatTimestamp(sample.end_time)}</td><td>{echo ? `${input} = ${formatNumber(echo.command)}` : '—'}</td><td>{echo ? `${echo.output} = ${formatNumber(echo.feedback)}` : '—'}</td><td>{echo ? echo.matched ? 'Matched' : 'Mismatch' : 'No echo mapped'}</td><td>{Object.keys(sample.initial_output_values).length ? Object.entries(sample.initial_output_values).map(([name, value]) => `${name}=${formatNumber(value)}`).join(', ') : 'None'}</td></tr>); })}</tbody></table></div></details>
      <div className="alfalfa-footer"><span><CheckCircle2 size={15} /><strong>External-clock timing exact</strong>{data.start} → {data.end}</span><span><ShieldCheck size={15} /><strong>No hidden startup data</strong>{initialValueCount ? `${initialValueCount} reviewed tick-zero substitute${initialValueCount === 1 ? '' : 's'}` : 'All outputs supplied by FMU'}</span></div>
    </section>
  );
}

function AlfalfaQualificationPanel({ canQualify, onQualify, qualifying }: { canQualify: boolean; onQualify: (model: File, qualification: AlfalfaQualification) => Promise<unknown>; qualifying: boolean }) {
  const [model, setModel] = useState<File | null>(null);
  const [mapping, setMapping] = useState<File | null>(null);
  const [steps, setSteps] = useState(12);
  const [stepSeconds, setStepSeconds] = useState(60);
  const [start, setStart] = useState('2019-01-01T00:00');
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    if (!model || !mapping) return;
    setError(null);
    try {
      const mappingValue: unknown = JSON.parse(await mapping.text());
      await onQualify(model, { mapping: mappingValue, steps, step_seconds: stepSeconds, start: `${start}:00` });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The mapping file is not valid JSON');
    }
  };
  return (
    <section className="simulation-panel alfalfa-panel alfalfa-qualification">
      <div className="simulation-panel-head"><div><span className="eyebrow">ALFALFA EXACT-FMU CLOSED LOOP</span><h2>Qualify this exact candidate against a building model</h2><p>The FMU and reviewed signal map become signed artifacts. This operation never connects to a live building.</p></div><span className="qualification-chip missing">Not run</span></div>
      <div className="alfalfa-qualification-grid">
        <label className={model ? 'selected' : ''}><FileUp size={20} /><span><strong>{model?.name ?? 'Building model (.fmu)'}</strong><small>{model ? `${(model.size / 1024 / 1024).toFixed(1)} MiB selected` : 'FMI archive, maximum 512 MiB'}</small></span><input accept=".fmu,application/zip" disabled={!canQualify || qualifying} onChange={(event) => setModel(event.target.files?.[0] ?? null)} type="file" /></label>
        <label className={mapping ? 'selected' : ''}><Network size={20} /><span><strong>{mapping?.name ?? 'Reviewed signal map (.json)'}</strong><small>{mapping ? 'Ready to validate exact graph/FMU coverage' : 'Every graph input and output must be mapped'}</small></span><input accept=".json,application/json" disabled={!canQualify || qualifying} onChange={(event) => setMapping(event.target.files?.[0] ?? null)} type="file" /></label>
      </div>
      <div className="alfalfa-run-settings"><label><span>Model start</span><input disabled={!canQualify || qualifying} onChange={(event) => setStart(event.target.value)} type="datetime-local" value={start} /></label><label><span>Steps</span><input disabled={!canQualify || qualifying} min={1} max={100000} onChange={(event) => setSteps(Number(event.target.value))} type="number" value={steps} /></label><label><span>Seconds / step</span><input disabled={!canQualify || qualifying} min={0.001} onChange={(event) => setStepSeconds(Number(event.target.value))} type="number" value={stepSeconds} /></label><button disabled={!canQualify || !model || !mapping || qualifying || steps < 1 || stepSeconds <= 0} onClick={submit} type="button"><Play size={15} />{qualifying ? 'Running exact FMU…' : 'Run and sign qualification'}</button></div>
      {!canQualify && <div className="alfalfa-form-message"><CircleAlert size={16} />Only a passing candidate awaiting review can start a new qualification.</div>}
      {error && <div className="alfalfa-form-message error"><CircleAlert size={16} />{error}</div>}
    </section>
  );
}

function BoptestPanel({ evidence }: { evidence?: ArtifactState<BoptestEvidence> }) {
  if (!evidence || evidence.state === 'missing') return <section className="simulation-panel empty-tier"><Waves size={28} /><span className="eyebrow">BOPTEST PHYSICS</span><h2>No dynamic-physics qualification retained</h2><p>This candidate passed its deterministic checks, but it has not yet been run against a BOPTEST FMU. That tier is not inferred from unit tests.</p><span className="qualification-chip missing">Unqualified tier</span></section>;
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
