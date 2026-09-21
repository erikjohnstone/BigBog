import { Group, Panel, Separator } from 'react-resizable-panels';
import { useCallback, useEffect, useMemo, useState } from 'react';

import type { RunDetail } from '../../api/client';
import { useBlockCatalog, useGraph, useReport } from '../../api/queries';
import { PanelRightClose, PanelRightOpen } from 'lucide-react';

import { Button, StatusPill, Tab, TabList, TabPanel, Tabs } from '../../design-system/primitives';
import { ErrorState, LoadingState } from '../../design-system/states';
import { traceStore, useTrace } from '../../stores/trace';
import type { Signal } from '../../stores/trace';
import { useTimeCursor } from '../../stores/timeCursor';
import { useTrends } from '../../stores/trends';
import { useUi } from '../../stores/ui';
import { buildTrace, traceIdForRun } from '../../trace/build-trace';
import { DecisionMatrix } from '../coverage/DecisionMatrix';
import { FaultMatrix } from '../coverage/FaultMatrix';
import { QualificationMatrix } from '../coverage/QualificationMatrix';
import { SchematicPanel } from '../schematic/SchematicPanel';
import { MasterTimeline } from '../timeline/MasterTimeline';
import { Transport } from '../timeline/Transport';
import { SignalRail } from '../trends/SignalRail';
import { StateRibbon } from '../trends/StateRibbon';
import { TrendPane } from '../trends/TrendPane';
import { composeDefaultTrends } from '../trends/unit-groups';
import { catalogKind } from '../wiresheet/graph-model';
import { AssertionList } from './AssertionList';
import { DataTable } from './DataTable';

const LAYOUT_KEY = 'test';
const defaultOuter = { top: 64, evidence: 36 };
const defaultInner = { rail: 18, trends: 52, schematic: 30 };

/**
 * Test stage: master timeline, trend panes, and boolean lanes on the shared
 * clock, with the evidence (assertions, decision coverage, faults, the
 * qualification matrix, raw data) below.
 */
export function TestStage({ run }: { run: RunDetail }) {
  const report = useReport(run.id);
  const graph = useGraph(run.id);
  const catalog = useBlockCatalog();
  if (report.isLoading || catalog.isLoading) return <LoadingState label="Loading test report" />;
  if (report.isError || !report.data) return <ErrorState error={report.error ?? 'Report unavailable'} onRetry={() => report.refetch()} />;
  return <TestBody run={run} report={report.data} graph={graph.data} catalog={catalog.data} />;
}

function TestBody({
  run,
  report,
  graph,
  catalog,
}: {
  run: RunDetail;
  report: NonNullable<ReturnType<typeof useReport>['data']>;
  graph: ReturnType<typeof useGraph>['data'];
  catalog: ReturnType<typeof useBlockCatalog>['data'];
}) {
  const traceId = traceIdForRun(run.id);
  const trace = useTrace(traceId);
  const savePanelSizes = useUi((state) => state.savePanelSizes);
  const schematicOpen = useUi((state) => state.schematicOpen);
  const [outerLayout] = useState(() => useUi.getState().panelSizes[`${LAYOUT_KEY}:outer`] ?? defaultOuter);
  const [innerLayouts] = useState(() => ({
    3: useUi.getState().panelSizes[`${LAYOUT_KEY}:inner:3`] ?? defaultInner,
    2: useUi.getState().panelSizes[`${LAYOUT_KEY}:inner:2`] ?? { rail: 22, trends: 78 },
  }));
  const setSchematicOpen = useUi((state) => state.setSchematicOpen);
  const trends = useTrends((state) => state.byTrace[traceId]);
  const ensure = useTrends((state) => state.ensure);
  const toggleSignal = useTrends((state) => state.toggleSignal);
  const removePane = useTrends((state) => state.removePane);
  const reset = useTrends((state) => state.reset);
  const [tab, setTab] = useState('assertions');

  const outputsOf = useCallback(
    (blockId: string) => {
      if (!graph) return [];
      const block = graph.blocks.find((item) => item.id === blockId);
      return block ? catalogKind(catalog, graph, block.kind).outputs.map((slot) => slot.name) : [];
    },
    [graph, catalog],
  );

  useEffect(() => {
    if (!traceStore.has(traceId)) traceStore.put(buildTrace(run, report, { catalog, graph: graph ?? undefined }));
    if (useTimeCursor.getState().traceId !== traceId) useTimeCursor.getState().setTrace(traceId);
  }, [run, report, catalog, graph, traceId]);

  useEffect(() => {
    if (trace && !trends) ensure(traceId, () => composeDefaultTrends(trace, outputsOf));
  }, [trace, trends, ensure, traceId, outputsOf]);

  const onToggle = useCallback(
    (signal: Signal) => toggleSignal(traceId, signal.id, { kind: signal.kind, unit: signal.unit }),
    [toggleSignal, traceId],
  );

  const summary = useMemo(() => {
    const total = report.scenarios.reduce((sum, scenario) => sum + scenario.assertions.length, 0);
    const passed = report.scenarios.reduce((sum, scenario) => sum + scenario.assertions.filter((item) => item.passed).length, 0);
    return { total, passed };
  }, [report]);

  if (!trace || !trends) return <LoadingState label="Building trace" />;

  return (
    <div className="h-full flex flex-col">
      <Group orientation="vertical" className="flex-1 min-h-0" defaultLayout={outerLayout} onLayoutChanged={(layout) => savePanelSizes(`${LAYOUT_KEY}:outer`, layout)}>
        <Panel id="top" defaultSize={defaultOuter.top} minSize="30" className="min-h-0">
          <Group orientation="horizontal" className="h-full" key={schematicOpen ? 'with-schematic' : 'no-schematic'}
            defaultLayout={schematicOpen ? innerLayouts[3] : innerLayouts[2]}
            onLayoutChanged={(layout) => savePanelSizes(`${LAYOUT_KEY}:inner:${schematicOpen ? 3 : 2}`, layout)}
          >
            <Panel id="rail" defaultSize={defaultInner.rail} minSize="12" className="hairline-r min-w-0">
              <SignalRail trace={trace} trends={trends} onToggle={onToggle} outputsOf={outputsOf} />
            </Panel>
            <Separator className="w-px bg-line-1 hover:bg-accent transition-colors" />
            <Panel id="trends" defaultSize={defaultInner.trends} minSize="40" className="flex flex-col min-w-0">
              <div className="flex items-center gap-2 px-3 h-9 hairline-b shrink-0 bg-bg-1">
                <StatusPill tone={report.passed ? 'ok' : 'fail'}>{report.passed ? 'Tests passed' : 'Tests failed'}</StatusPill>
                <span className="num text-fg-2">
                  {summary.passed}/{summary.total} assertions
                </span>
                <span className="text-xs text-fg-2 truncate hidden lg:inline">{report.engine}</span>
                <span className="flex-1" />
                <span className="text-2xs text-fg-2 hidden md:inline">Drag on the timeline to zoom · drag in a pane to scrub</span>
                <Button size="xs" variant="ghost" onClick={() => reset(traceId, () => composeDefaultTrends(trace, outputsOf))}>
                  Reset panes
                </Button>
                <Button size="xs" variant={schematicOpen ? 'secondary' : 'outline'} onClick={() => setSchematicOpen(!schematicOpen)} aria-pressed={schematicOpen} title="Show the equipment schematic">
                  {schematicOpen ? <PanelRightClose size={12} /> : <PanelRightOpen size={12} />} Schematic
                </Button>
              </div>
              <MasterTimeline trace={trace} />
              <div
                className="flex-1 min-h-0 overflow-auto"
                onDragOver={(event) => {
                  if (event.dataTransfer.types.includes('application/x-bactalk-signal')) event.preventDefault();
                }}
                onDrop={(event) => {
                  const id = event.dataTransfer.getData('application/x-bactalk-signal');
                  const signal = trace.signals.get(id);
                  if (signal) onToggle(signal);
                }}
              >
                <StateRibbon trace={trace} signalIds={trends.ribbon} />
                {trends.panes.map((pane) => (
                  <TrendPane key={pane.id} trace={trace} pane={pane} onRemove={() => removePane(traceId, pane.id)} />
                ))}
                {trends.panes.length === 0 && trends.ribbon.length === 0 && (
                  <p className="p-6 text-sm text-fg-2">No signals on the trends. Pick some from the rail.</p>
                )}
              </div>
            </Panel>
            {schematicOpen && (
              <>
                <Separator className="w-px bg-line-1 hover:bg-accent transition-colors" />
                <Panel id="schematic" defaultSize={defaultInner.schematic} minSize="16" className="min-w-0 bg-bg-1">
                  <SchematicPanel run={run} trace={trace} />
                </Panel>
              </>
            )}
          </Group>
        </Panel>
        <Separator className="h-px bg-line-1 hover:bg-accent transition-colors" />
        <Panel id="evidence" defaultSize={defaultOuter.evidence} minSize="16" className="min-h-0 bg-bg-1">
          <Tabs value={tab} onValueChange={(value) => setTab(String(value))} className="h-full flex flex-col">
            <TabList ariaLabel="Evidence" className="px-2 shrink-0">
              <Tab value="assertions">Assertions</Tab>
              <Tab value="decisions">Decision coverage</Tab>
              <Tab value="faults">Faults</Tab>
              <Tab value="qualification">Qualification</Tab>
              <Tab value="data">Data</Tab>
            </TabList>
            <TabPanel value="assertions" className="flex-1 min-h-0 overflow-auto">
              <AssertionList trace={trace} graph={graph ?? undefined} />
            </TabPanel>
            <TabPanel value="decisions" className="flex-1 min-h-0 overflow-auto">
              <DecisionMatrix report={report} />
            </TabPanel>
            <TabPanel value="faults" className="flex-1 min-h-0 overflow-auto">
              <FaultMatrix report={report} trace={trace} />
            </TabPanel>
            <TabPanel value="qualification" className="flex-1 min-h-0 overflow-auto">
              <QualificationMatrix report={report} trace={trace} />
            </TabPanel>
            <TabPanel value="data" className="flex-1 min-h-0">
              <DataTable trace={trace} />
            </TabPanel>
          </Tabs>
        </Panel>
      </Group>
      <Transport trace={trace} />
    </div>
  );
}
