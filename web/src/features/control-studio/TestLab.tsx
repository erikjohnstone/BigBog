import { useEffect, useMemo, useRef } from 'react';
import { LineChart } from 'echarts/charts';
import { AriaComponent, GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import type { EChartsCoreOption, EChartsType } from 'echarts/core';
import { Activity, Check, CheckCircle2, RotateCcw, ShieldCheck, TriangleAlert, XCircle } from 'lucide-react';

import type { RunDetail, TestReport } from '../../api/client';

echarts.use([AriaComponent, GridComponent, LegendComponent, TooltipComponent, LineChart, CanvasRenderer]);

type EvidenceSeries = { name: string; unit: string; values: Array<number | null> };
type ScenarioEvidence = TestReport['scenarios'][number];
type FaultDeclaration = NonNullable<NonNullable<TestReport['coverage']>['fault_injection']>['declarations'][number];

export function TestLab({ report, run }: { report: TestReport; run: RunDetail }) {
  const outputPoints = run.job.points.filter((point) => ['command', 'alarm', 'status'].includes(point.role));
  const analogGroups = new Map<string, EvidenceSeries[]>();
  const binary: EvidenceSeries[] = [];
  outputPoints.forEach((point) => {
    const values = report.scenarios.map((scenario) => {
      const value = scenario.samples.at(-1)?.[point.name];
      if (typeof value === 'boolean') return value ? 1 : 0;
      return typeof value === 'number' ? value : null;
    });
    if (point.data_type === 'boolean') binary.push({ name: point.label, unit: 'state', values });
    else if (values.some((value) => value !== null)) {
      const unit = point.units || 'value';
      analogGroups.set(unit, [...(analogGroups.get(unit) ?? []), { name: point.label, unit, values }]);
    }
  });
  const scenarioNames = report.scenarios.map((scenario) => scenario.name);
  const assertions = report.scenarios.flatMap((scenario) => scenario.assertions);
  const passedAssertions = assertions.filter((assertion) => assertion.passed).length;
  const faultCoverage = report.coverage?.fault_injection;
  const faultDeclarations = faultCoverage?.declarations ?? [];
  return <div className="test-lab">
    <section className={`test-summary ${report.passed ? 'pass' : 'fail'}`}>
      <div className="test-summary-icon">{report.passed ? <CheckCircle2 size={25} /> : <XCircle size={25} />}</div>
      <div><span className="eyebrow">DETERMINISTIC ACCEPTANCE</span><h2>{report.passed ? 'Candidate behavior passed' : 'Candidate behavior failed'}</h2><p>{report.engine}</p></div>
      <div className="test-summary-numbers"><strong>{passedAssertions}/{assertions.length}</strong><span>assertions passed</span></div>
    </section>
    <FaultQualification coverage={faultCoverage} />
    <QualificationMatrix matrix={report.coverage?.qualification_matrix} />
    <div className="evidence-grid">
      <section className="evidence-panel evidence-visuals">
        <div className="panel-title"><div><span className="eyebrow">BEHAVIOR TRACE</span><h2>What the program did</h2></div><Activity size={19} /></div>
        {[...analogGroups.entries()].map(([unit, series]) => <EvidenceChart categories={scenarioNames} key={unit} series={series} unit={unit} />)}
        {binary.length > 0 && <EvidenceChart binary categories={scenarioNames} series={binary} unit="state" />}
        {!analogGroups.size && !binary.length && <div className="evidence-empty">This report does not retain output samples for charting.</div>}
        <EvidenceTable categories={scenarioNames} series={[...analogGroups.values()].flat().concat(binary)} />
      </section>
      <section className="evidence-panel scenario-panel">
        <div className="panel-title"><div><span className="eyebrow">TEST MATRIX</span><h2>Scenario evidence</h2></div><span className={`evidence-status ${report.passed ? 'pass' : 'fail'}`}>{report.passed ? 'All passed' : 'Blocked'}</span></div>
        <div className="scenario-cards">{report.scenarios.map((scenario, index) => <article className={scenario.passed ? 'passed' : 'failed'} key={scenario.name}>
          <header><span>{String(index + 1).padStart(2, '0')}</span><div><h3>{scenario.name}</h3><small>{scenario.assertions.length} assertions</small></div>{scenario.passed ? <CheckCircle2 size={18} /> : <XCircle size={18} />}</header>
          <div>{scenario.assertions.map((assertion) => <div className="assertion-row" key={assertion.name}><span>{assertion.passed ? <Check size={14} /> : <XCircle size={14} />}{assertion.name}</span><code>{assertion.observed}</code></div>)}</div>
          <FaultTrace declarations={faultDeclarations.filter((item) => item.case === scenario.name)} scenario={scenario} />
        </article>)}</div>
      </section>
    </div>
  </div>;
}

function QualificationMatrix({ matrix }: { matrix: NonNullable<TestReport['coverage']>['qualification_matrix'] | undefined }) {
  if (!matrix || !matrix.profile) return <section className="qualification-summary missing"><TriangleAlert size={20} /><div><span className="eyebrow">EQUIPMENT SAFETY PROFILE</span><strong>No qualification profile is bound to this sequence</strong><p>A contractor-approved profile must define which normal, failure, safety, override, restart, and recovery cases apply.</p></div><span>Profile required</span></section>;
  const complete = matrix.engineering_matrix_complete;
  return <section className={`qualification-summary ${complete ? 'complete' : 'incomplete'}`}>
    <div className="qualification-heading"><ShieldCheck size={20} /><div><span className="eyebrow">EQUIPMENT SAFETY PROFILE</span><strong>{matrix.profile.id}</strong><p>{matrix.interpretation}</p></div><span className={complete ? 'complete' : 'incomplete'}>{complete ? 'Matrix complete' : `${matrix.blockers.length} open decisions`}</span></div>
    <div className="qualification-metrics"><div><strong>{matrix.required_passed}/{matrix.required_count}</strong><span>Required evidence</span></div><div><strong>{matrix.conditional_addressed}/{matrix.conditional_count}</strong><span>Conditional resolved</span></div><div><strong>{matrix.profile.version}</strong><span>Profile version</span></div></div>
    <details className="qualification-details"><summary>Review the full safety and failure matrix</summary><div aria-label="Safety and failure requirements" tabIndex={0}>{matrix.requirements.map((item) => {
      const passed = ['passed', 'not_applicable'].includes(item.status);
      return <article className={passed ? 'passed' : 'open'} key={item.category}><span>{passed ? <CheckCircle2 size={14} /> : <TriangleAlert size={14} />}</span><div><header><strong>{item.category.replaceAll('_', ' ')}</strong><small>{item.level.replaceAll('_', ' ')}</small></header><p>{item.description}</p><span>{item.reason}</span>{item.evidence_cases.length > 0 && <code>{item.evidence_cases.join(' · ')}</code>}</div></article>;
    })}</div></details>
  </section>;
}

function FaultQualification({ coverage }: { coverage: NonNullable<TestReport['coverage']>['fault_injection'] | undefined }) {
  if (!coverage || coverage.activation_count === 0) return <section className="fault-qualification missing"><TriangleAlert size={20} /><div><span className="eyebrow">FAULT QUALIFICATION GAP</span><strong>No injected equipment or sensor failures</strong><p>Passing normal scenarios do not prove stale-sensor, communications-loss, actuator-failure, override, or recovery behavior.</p></div><span>Not fault-qualified</span></section>;
  const passed = coverage.fault_cases_passed === coverage.fault_case_count;
  return <section className={`fault-qualification ${passed ? 'pass' : 'fail'}`}><ShieldCheck size={20} /><div><span className="eyebrow">FAULT QUALIFICATION</span><strong>{coverage.activation_count} injected fault activation{coverage.activation_count === 1 ? '' : 's'} across {coverage.targets.length} input{coverage.targets.length === 1 ? '' : 's'}</strong><p>{coverage.interpretation}</p><div className="fault-kind-list">{coverage.kinds.map((kind) => <code key={kind}>{kind.replaceAll('_', ' ')}</code>)}</div></div><dl><div><dt>Fault cases</dt><dd>{coverage.fault_cases_passed}/{coverage.fault_case_count}</dd></div><div><dt>Recovery phases</dt><dd>{coverage.recovery_phases.length}</dd></div></dl></section>;
}

function FaultTrace({ declarations, scenario }: { declarations: FaultDeclaration[]; scenario: ScenarioEvidence }) {
  if (!declarations.length) return null;
  return <div className="fault-trace"><div className="fault-trace-title"><TriangleAlert size={13} /><strong>Injected failures</strong><span>Raw → effective → response</span></div>{declarations.map((fault, index) => {
    const prefix = `fault.${fault.id}`;
    const samples = scenario.samples.filter((sample) => sample[`${prefix}.active`] === true);
    const first = samples[0];
    const last = samples.at(-1);
    const quality = fault.quality_target && last ? last[`effective.${fault.quality_target}`] : undefined;
    return <div className="fault-trace-row" key={`${fault.id}-${fault.phase ?? index}`}><div><code>{fault.id}</code><span>{fault.kind.replaceAll('_', ' ')} · {fault.target}{fault.phase ? ` · ${fault.phase}` : ''}</span></div><div><span>Raw <strong>{formatSampleValue(first?.[`${prefix}.raw`])}</strong></span><span>Applied <strong>{formatSampleValue(last?.[`${prefix}.applied`])}</strong></span>{fault.quality_target && <span>{fault.quality_target} <strong>{formatSampleValue(quality)}</strong></span>}</div></div>;
  })}<div className="fault-recovery-note"><RotateCcw size={12} />Recovery is only credited when a later no-fault phase has explicit passing assertions.</div></div>;
}

function formatSampleValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'TRUE' : 'FALSE';
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2);
  return '—';
}

function EvidenceChart({ categories, series, unit, binary = false }: { categories: string[]; series: EvidenceSeries[]; unit: string; binary?: boolean }) {
  const option = useMemo<EChartsCoreOption>(() => ({ animation: false, aria: { enabled: true, decal: { show: true }, description: `${series.map((item) => item.name).join(', ')} by acceptance scenario in ${unit}.` }, color: ['#17785a', '#bb7045', '#2d6f9d', '#745da8', '#9b6420'], tooltip: { trigger: 'axis' }, legend: { bottom: 0, type: 'scroll', textStyle: { color: '#3c4953', fontSize: 10 } }, grid: { left: 52, right: 22, top: 35, bottom: 68 }, xAxis: { type: 'category', data: categories, axisLabel: { color: '#596772', fontSize: 9, interval: 0, overflow: 'truncate', width: 100 } }, yAxis: binary ? { type: 'value', min: 0, max: 1, interval: 1, name: 'State', axisLabel: { formatter: (value: number) => value === 1 ? 'ON' : 'OFF', color: '#596772' } } : { type: 'value', name: unit, nameTextStyle: { color: '#596772' }, axisLabel: { color: '#596772' }, splitLine: { lineStyle: { color: '#e7ebed' } } }, series: series.map((item) => ({ name: item.name, type: 'line', step: binary ? 'end' : false, symbolSize: 8, lineStyle: { width: 2.5 }, data: item.values, connectNulls: false })) }), [binary, categories, series, unit]);
  return <div className="evidence-chart"><div className="chart-label"><strong>{binary ? 'Binary state lanes' : `Analog outputs · ${unit}`}</strong><span>{categories.length} scenarios</span></div><EChart label={`${series.map((item) => item.name).join(', ')} acceptance trace`} option={option} /></div>;
}

function EChart({ option, label }: { option: EChartsCoreOption; label: string }) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => { if (!container.current) return; const chart: EChartsType = echarts.init(container.current, undefined, { renderer: 'canvas' }); chart.setOption(option); const observer = new ResizeObserver(() => chart.resize()); observer.observe(container.current); return () => { observer.disconnect(); chart.dispose(); }; }, [option]);
  return <div aria-label={label} className="chart-canvas" ref={container} role="img" />;
}

function EvidenceTable({ categories, series }: { categories: string[]; series: EvidenceSeries[] }) {
  if (!series.length) return null;
  return <details className="evidence-table"><summary>Accessible trace table</summary><div><table><thead><tr><th>Scenario</th>{series.map((item) => <th key={item.name}>{item.name}<small>{item.unit}</small></th>)}</tr></thead><tbody>{categories.map((category, index) => <tr key={category}><th>{category}</th>{series.map((item) => <td key={item.name}>{item.values[index] === null ? '—' : item.unit === 'state' ? (item.values[index] ? 'ON' : 'OFF') : item.values[index]}</td>)}</tr>)}</tbody></table></div></details>;
}
