import { useEffect, useMemo, useRef } from 'react';
import { LineChart } from 'echarts/charts';
import { AriaComponent, GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import type { EChartsCoreOption, EChartsType } from 'echarts/core';
import { Activity, Check, CheckCircle2, XCircle } from 'lucide-react';

import type { RunDetail, TestReport } from '../../api/client';

echarts.use([AriaComponent, GridComponent, LegendComponent, TooltipComponent, LineChart, CanvasRenderer]);

type EvidenceSeries = { name: string; unit: string; values: Array<number | null> };

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
  return <div className="test-lab"><section className={`test-summary ${report.passed ? 'pass' : 'fail'}`}><div className="test-summary-icon">{report.passed ? <CheckCircle2 size={25} /> : <XCircle size={25} />}</div><div><span className="eyebrow">DETERMINISTIC ACCEPTANCE</span><h2>{report.passed ? 'Candidate behavior passed' : 'Candidate behavior failed'}</h2><p>{report.engine}</p></div><div className="test-summary-numbers"><strong>{passedAssertions}/{assertions.length}</strong><span>assertions passed</span></div></section><div className="evidence-grid"><section className="evidence-panel evidence-visuals"><div className="panel-title"><div><span className="eyebrow">BEHAVIOR TRACE</span><h2>What the program did</h2></div><Activity size={19} /></div>{[...analogGroups.entries()].map(([unit, series]) => <EvidenceChart categories={scenarioNames} key={unit} series={series} unit={unit} />)}{binary.length > 0 && <EvidenceChart binary categories={scenarioNames} series={binary} unit="state" />}{!analogGroups.size && !binary.length && <div className="evidence-empty">This report does not retain output samples for charting.</div>}<EvidenceTable categories={scenarioNames} series={[...analogGroups.values()].flat().concat(binary)} /></section><section className="evidence-panel scenario-panel"><div className="panel-title"><div><span className="eyebrow">TEST MATRIX</span><h2>Scenario evidence</h2></div><span className={`evidence-status ${report.passed ? 'pass' : 'fail'}`}>{report.passed ? 'All passed' : 'Blocked'}</span></div><div className="scenario-cards">{report.scenarios.map((scenario, index) => <article className={scenario.passed ? 'passed' : 'failed'} key={scenario.name}><header><span>{String(index + 1).padStart(2, '0')}</span><div><h3>{scenario.name}</h3><small>{scenario.assertions.length} assertions</small></div>{scenario.passed ? <CheckCircle2 size={18} /> : <XCircle size={18} />}</header><div>{scenario.assertions.map((assertion) => <div className="assertion-row" key={assertion.name}><span>{assertion.passed ? <Check size={14} /> : <XCircle size={14} />}{assertion.name}</span><code>{assertion.observed}</code></div>)}</div></article>)}</div></section></div></div>;
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
