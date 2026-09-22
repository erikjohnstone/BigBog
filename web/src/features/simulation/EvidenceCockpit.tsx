import { Clock3 } from 'lucide-react';

import type { AlfalfaEvidence, BoptestEvidence, RunDetail, ShadowEvidence } from '../../api/client';
import { useAlfalfaEvidence, useBlockCatalog, useBoptestEvidence, useGraph, useShadowEvidence } from '../../api/queries';
import { Button, StatusPill } from '../../design-system/primitives';
import { MissingEvidence } from '../../design-system/states';
import { traceStore } from '../../stores/trace';
import { alfalfaTraceId, boptestTraceId, buildAlfalfaTrace, buildBoptestTrace } from '../../trace/evidence-trace';
import { buildShadowTrace, shadowTraceId } from '../../trace/shadow-trace';
import { KpiCards } from './KpiCards';
import { formatDivergence } from './shadow-format';

export type EvidenceKind = 'boptest' | 'alfalfa' | 'shadow';

function ShadowSummary({ evidence, run, onLoad }: { evidence: ShadowEvidence; run: RunDetail; onLoad: () => void }) {
  const graph = useGraph(run.id);
  const catalog = useBlockCatalog();
  const scenarios = evidence.report.scenarios;
  const cases = evidence.differential.cases;
  const passedCount = scenarios.filter((scenario) => scenario.passed && (cases.find((item) => item.name === scenario.name)?.passed ?? true)).length;
  const rows = scenarios.map((scenario) => {
    const differential = cases.find((item) => item.name === scenario.name);
    const passed = scenario.passed && (differential?.passed ?? true);
    return { name: scenario.name, passed, divergence: differential?.first_divergence ?? null, assertions: scenario.assertions };
  });
  for (const item of cases) {
    if (!scenarios.some((scenario) => scenario.name === item.name)) rows.push({ name: item.name, passed: item.passed, divergence: item.first_divergence ?? null, assertions: [] });
  }
  return (
    <div className="flex flex-col">
      <div className="px-4 py-3 flex items-center gap-2 flex-wrap">
        <StatusPill tone={evidence.status === 'pass' ? 'ok' : 'fail'}>{evidence.status === 'pass' ? 'Shadow Runtime passed' : 'Shadow Runtime failed'}</StatusPill>
        <StatusPill tone="sim">bog-simulated</StatusPill>
        <span className="num text-xs text-fg-2">
          {passedCount}/{scenarios.length} scenarios
        </span>
        <span className="text-xs text-fg-2 truncate hidden sm:inline" title={evidence.engine}>
          {evidence.engine}
        </span>
        <span className="flex-1" />
        <Button
          size="xs"
          variant="secondary"
          onClick={() => {
            const id = shadowTraceId(run.id);
            if (!traceStore.has(id)) traceStore.put(buildShadowTrace(run, evidence, { catalog: catalog.data, graph: graph.data ?? undefined }));
            onLoad();
          }}
        >
          <Clock3 size={12} /> Load onto the clock
        </Button>
      </div>
      <ul className="px-4 pb-3 flex flex-col gap-1 text-xs hairline-t pt-3" aria-label="Shadow Runtime scenarios">
        {rows.map((row) => (
          <li key={row.name} className="flex items-center gap-2 min-w-0 flex-wrap">
            <StatusPill tone={row.passed ? 'ok' : 'fail'} icon={null}>
              {row.passed ? 'pass' : 'fail'}
            </StatusPill>
            <span className="text-fg-0 truncate">{row.name}</span>
            {!row.passed && row.divergence && <span className="num text-fail truncate">{formatDivergence(row.divergence)}</span>}
            {!row.passed && !row.divergence && row.assertions.some((item) => !item.passed) && (
              <span className="text-fail truncate">{row.assertions.filter((item) => !item.passed).map((item) => item.name).join(', ')}</span>
            )}
          </li>
        ))}
      </ul>
      <p className="px-4 pb-3 text-2xs text-fg-2">
        Executed by the Niagara Shadow Runtime, a model of the exported .bog. Differential against {evidence.differential.reference_available ? 'the interpreter and the reference engine' : 'the interpreter'}. Not a licensed Niagara runtime qualification.
      </p>
    </div>
  );
}

function oracleSummary(oracles: Array<{ passed: boolean; completed: boolean }>) {
  const passed = oracles.filter((item) => item.passed).length;
  const incomplete = oracles.filter((item) => !item.completed).length;
  return { passed, total: oracles.length, incomplete };
}

function BoptestSummary({ evidence, runId, onLoad }: { evidence: BoptestEvidence; runId: string; onLoad: () => void }) {
  const cases = evidence.schema === 'bactalk.boptest-qualification-suite/v1' ? evidence.cases : [{ id: evidence.runtime.test_case, status: evidence.status, runtime: evidence.runtime, oracles: evidence.oracles }];
  const oracles = oracleSummary(cases.flatMap((item) => item.oracles));
  return (
    <div className="flex flex-col">
      <div className="px-4 py-3 flex items-center gap-2 flex-wrap">
        <StatusPill tone={evidence.status === 'pass' ? 'ok' : 'fail'}>{evidence.status === 'pass' ? 'BOPTEST passed' : 'BOPTEST failed'}</StatusPill>
        <StatusPill tone="sim">Simulated</StatusPill>
        <span className="num text-xs text-fg-2">
          {oracles.passed}/{oracles.total} oracles{oracles.incomplete ? ` · ${oracles.incomplete} incomplete` : ''}
        </span>
        <span className="text-xs text-fg-2 hidden sm:inline">{cases.length > 1 ? `${cases.length} operating conditions` : cases[0].runtime.test_case}</span>
        <span className="flex-1" />
        <Button
          size="xs"
          variant="secondary"
          onClick={() => {
            const id = boptestTraceId(runId);
            if (!traceStore.has(id)) traceStore.put(buildBoptestTrace(runId, evidence));
            onLoad();
          }}
        >
          <Clock3 size={12} /> Load onto the clock
        </Button>
      </div>
      {cases.map((item) => (
        <div key={item.id} className="hairline-t">
          <KpiCards kpis={item.runtime.kpis} title={cases.length > 1 ? `${item.id} · KPIs` : 'BOPTEST KPIs'} />
          <ul className="px-4 pb-3 flex flex-col gap-1 text-xs">
            {item.oracles.map((oracle) => (
              <li key={oracle.oracle.id} className="flex items-center gap-2 min-w-0">
                <StatusPill tone={!oracle.completed ? 'warn' : oracle.passed ? 'ok' : 'fail'}>{!oracle.completed ? 'Incomplete' : oracle.passed ? 'Within tolerance' : 'Violated'}</StatusPill>
                <span className="text-fg-0 truncate">{oracle.oracle.id}</span>
                <span className="text-fg-2 truncate">{oracle.oracle.signal_kind.replace('_', ' ')} {oracle.oracle.signal}</span>
                <span className="num text-fg-2 ml-auto shrink-0">{oracle.max_error === null ? '—' : `max err ${oracle.max_error.toFixed(3)} / ±${oracle.oracle.absolute_value_tolerance}`}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function AlfalfaSummary({ evidence, runId, onLoad }: { evidence: AlfalfaEvidence; runId: string; onLoad: () => void }) {
  const oracles = oracleSummary(evidence.oracles);
  const mismatches = evidence.trajectory.reduce((sum, step) => sum + Object.values(step.command_echoes).filter((echo) => !echo.matched).length, 0);
  const transport = evidence.control_transport;
  return (
    <div className="flex flex-col">
      <div className="px-4 py-3 flex items-center gap-2 flex-wrap">
        <StatusPill tone={evidence.status === 'pass' ? 'ok' : 'fail'}>{evidence.status === 'pass' ? 'Alfalfa passed' : 'Alfalfa failed'}</StatusPill>
        <StatusPill tone="sim">Simulated</StatusPill>
        <span className="num text-xs text-fg-2">
          {oracles.passed}/{oracles.total} oracles
        </span>
        <span className="text-xs text-fg-2 truncate hidden sm:inline">{evidence.model_name}</span>
        <span className="flex-1" />
        <Button
          size="xs"
          variant="secondary"
          onClick={() => {
            const id = alfalfaTraceId(runId);
            if (!traceStore.has(id)) traceStore.put(buildAlfalfaTrace(runId, evidence));
            onLoad();
          }}
        >
          <Clock3 size={12} /> Load onto the clock
        </Button>
      </div>
      <dl className="px-4 pb-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
        {[
          ['Steps', `${evidence.steps} × ${evidence.step_seconds} s`],
          ['Runtime I/O', `${evidence.runtime_input_count} in · ${evidence.runtime_output_count} out`],
          ['Echo mismatches', String(mismatches)],
          ['Stop', evidence.clean_stop ? 'clean' : 'unclean'],
        ].map(([label, value]) => (
          <div key={label} className="raised px-3 py-2 min-w-0">
            <dt className="text-2xs text-fg-2">{label}</dt>
            <dd className="num text-fg-0 truncate">{value}</dd>
          </div>
        ))}
      </dl>
      {transport && (
        <p className="px-4 pb-3 text-2xs text-fg-2">
          Control transport {transport.protocol} at priority {transport.write_priority}: {transport.read_transaction_count} reads, {transport.write_transaction_count} writes, readbacks matched. Virtual objects only; no licensed Niagara runtime.
        </p>
      )}
    </div>
  );
}

/**
 * Retained BOPTEST and Alfalfa evidence for a run. Missing and invalid states
 * are explicit, and "Load onto the clock" turns the trajectory into a trace
 * the timeline, trends, and schematic all follow.
 */
export function EvidenceCockpit({ run, onLoad }: { run: RunDetail; onLoad: (kind: EvidenceKind) => void }) {
  const runId = run.id;
  const boptest = useBoptestEvidence(runId);
  const alfalfa = useAlfalfaEvidence(runId);
  const shadow = useShadowEvidence(runId);
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <section className="panel" aria-label="BOPTEST evidence">
        <h3 className="px-4 h-9 flex items-center text-xs font-medium hairline-b">BOPTEST</h3>
        {boptest.isLoading ? <p className="px-4 py-3 text-sm text-fg-2">Loading…</p> : !boptest.data || boptest.data.state !== 'available' ? <MissingEvidence kind="BOPTEST" state={boptest.data?.state === 'invalid' ? 'invalid' : 'missing'} detail={boptest.data?.state === 'invalid' ? boptest.data.message : undefined} /> : <BoptestSummary evidence={boptest.data.data} runId={runId} onLoad={() => onLoad('boptest')} />}
      </section>
      <section className="panel" aria-label="Alfalfa evidence">
        <h3 className="px-4 h-9 flex items-center text-xs font-medium hairline-b">Alfalfa</h3>
        {alfalfa.isLoading ? <p className="px-4 py-3 text-sm text-fg-2">Loading…</p> : !alfalfa.data || alfalfa.data.state !== 'available' ? <MissingEvidence kind="Alfalfa" state={alfalfa.data?.state === 'invalid' ? 'invalid' : 'missing'} detail={alfalfa.data?.state === 'invalid' ? alfalfa.data.message : undefined} /> : <AlfalfaSummary evidence={alfalfa.data.data} runId={runId} onLoad={() => onLoad('alfalfa')} />}
      </section>
      <section className="panel lg:col-span-2" aria-label="Shadow Runtime evidence">
        <h3 className="px-4 h-9 flex items-center text-xs font-medium hairline-b">Shadow Runtime</h3>
        {shadow.isLoading ? <p className="px-4 py-3 text-sm text-fg-2">Loading…</p> : !shadow.data || shadow.data.state !== 'available' ? <MissingEvidence kind="Shadow Runtime" state={shadow.data?.state === 'invalid' ? 'invalid' : 'missing'} detail={shadow.data?.state === 'invalid' ? shadow.data.message : 'The exported .bog has not been executed by the Shadow Runtime for this candidate. Enqueue it above; the tier is bog-simulated.'} /> : <ShadowSummary evidence={shadow.data.data} run={run} onLoad={() => onLoad('shadow')} />}
      </section>
    </div>
  );
}
