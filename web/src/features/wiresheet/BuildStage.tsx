import { GitCompareArrows } from 'lucide-react';
import { ReactFlowProvider, useReactFlow } from '@xyflow/react';
import { Group, Panel, Separator } from 'react-resizable-panels';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import type { RunDetail } from '../../api/client';
import { useBlockCatalog, useGraph, useReport } from '../../api/queries';
import { Button, StatusPill } from '../../design-system/primitives';
import { ErrorState, LoadingState } from '../../design-system/states';
import { useSelection } from '../../stores/selection';
import { traceStore, useTrace } from '../../stores/trace';
import { useTimeCursor } from '../../stores/timeCursor';
import { useUi } from '../../stores/ui';
import { buildTrace, traceIdForRun } from '../../trace/build-trace';
import { Transport } from '../timeline/Transport';
import { computeDiff, unexplainedChanges } from './diff/compute-diff';
import { buildFlow, feedbackKinds } from './graph-model';
import { Inspector } from './Inspector';
import { NiagaraFolders } from './NiagaraFolders';
import { needsLayout, tidy } from './layout/tidy';
import { Outline } from './Outline';
import { Wiresheet } from './Wiresheet';

const LAYOUT_KEY = 'build';
const defaultLayout = { outline: 18, canvas: 58, inspector: 24 };
const defaultInspectorLayout = { inspector: 62, folders: 38 };

/** Build stage: outline · animated wiresheet · inspector, on the shared clock. */
export function BuildStage({ run }: { run: RunDetail }) {
  const graph = useGraph(run.id);
  const report = useReport(run.id);
  const catalog = useBlockCatalog();
  if (graph.isLoading || catalog.isLoading) return <LoadingState label="Loading control graph" />;
  if (graph.isError || !graph.data) return <ErrorState error={graph.error ?? 'Graph unavailable'} onRetry={() => graph.refetch()} />;
  return (
    <ReactFlowProvider>
      <BuildBody run={run} graph={graph.data} report={report.data} catalog={catalog.data} />
    </ReactFlowProvider>
  );
}

function BuildBody({
  run,
  graph,
  report,
  catalog,
}: {
  run: RunDetail;
  graph: NonNullable<ReturnType<typeof useGraph>['data']>;
  report: ReturnType<typeof useReport>['data'];
  catalog: ReturnType<typeof useBlockCatalog>['data'];
}) {
  const flow = useReactFlow();
  const clear = useSelection((state) => state.clear);
  const savePanelSizes = useUi((state) => state.savePanelSizes);
  const [initialLayout] = useState(() => useUi.getState().panelSizes[LAYOUT_KEY] ?? defaultLayout);
  const [inspectorLayout] = useState(() => useUi.getState().panelSizes[`${LAYOUT_KEY}:inspector`] ?? defaultInspectorLayout);
  const traceId = traceIdForRun(run.id);
  const trace = useTrace(traceId);
  const [searchParams, setSearchParams] = useSearchParams();
  const compare = Boolean(run.parent_run_id) && searchParams.get('compare') === '1';
  const setCompare = useCallback(
    (next: boolean | ((current: boolean) => boolean)) => {
      const value = typeof next === 'function' ? next(compare) : next;
      setSearchParams(
        (current) => {
          const params = new URLSearchParams(current);
          if (value) params.set('compare', '1');
          else params.delete('compare');
          return params;
        },
        { replace: true },
      );
    },
    [compare, setSearchParams],
  );
  const parent = useGraph(compare && run.parent_run_id ? run.parent_run_id : undefined);
  const [tidied, setTidied] = useState<Map<string, { x: number; y: number }> | null>(null);
  const [intro, setIntro] = useState(true);

  // Load the trace once per run; the Test stage reuses it.
  useEffect(() => {
    if (!report) return;
    if (!traceStore.has(traceId)) traceStore.put(buildTrace(run, report, { catalog, graph }));
    if (useTimeCursor.getState().traceId !== traceId) useTimeCursor.getState().setTrace(traceId);
  }, [run, report, catalog, graph, traceId]);

  // A new graph materializes again; the flag is derived during render so
  // no effect has to set state synchronously.
  const [introGraph, setIntroGraph] = useState(graph);
  if (introGraph !== graph) {
    setIntroGraph(graph);
    setIntro(true);
  }
  useEffect(() => {
    clear();
    const timer = window.setTimeout(() => setIntro(false), 1600);
    return () => window.clearTimeout(timer);
  }, [graph, clear]);

  const diff = useMemo(() => {
    if (!compare || !parent.data) return null;
    return { parent: parent.data, result: computeDiff(parent.data, graph) };
  }, [compare, parent.data, graph]);

  const positions = useMemo(() => {
    if (tidied) return tidied;
    if (needsLayout(graph)) return tidy(graph, new Map(), feedbackKinds(catalog));
    return undefined;
  }, [graph, tidied, catalog]);

  const { nodes, edges } = useMemo(
    () => buildFlow({ graph, catalog, trace, report: report ?? undefined, run, diff, intro, positions }),
    [graph, catalog, trace, report, run, diff, intro, positions],
  );

  const onTidy = useCallback(() => {
    const sizes = new Map<string, { width: number; height: number }>();
    for (const node of flow.getNodes()) {
      if (node.measured?.width && node.measured?.height) sizes.set(node.id, { width: node.measured.width, height: node.measured.height });
    }
    setTidied(tidy(graph, sizes, feedbackKinds(catalog)));
    window.setTimeout(() => flow.fitView({ padding: 0.15, duration: 260 }), 30);
  }, [flow, graph, catalog]);

  const focusBlock = useCallback(
    (id: string) => {
      useSelection.getState().selectBlocks([id]);
      void flow.fitView({ nodes: [{ id }], duration: 260, maxZoom: 1.25, padding: 0.4 });
    },
    [flow],
  );

  const unexplained = diff ? unexplainedChanges(diff.result, run.changes) : [];
  const graphKey = `${run.id}:${compare ? 'diff' : 'plain'}:${tidied ? 'tidy' : 'stored'}`;

  return (
    <Group
      orientation="horizontal"
      className="h-full"
      defaultLayout={initialLayout}
      onLayoutChanged={(layout) => savePanelSizes(LAYOUT_KEY, layout)}
    >
      <Panel id="outline" minSize="12" defaultSize={defaultLayout.outline} className="bg-bg-1 hairline-r">
        <Outline nodes={nodes} onFocus={focusBlock} />
      </Panel>
      <Separator className="w-px bg-line-1 hover:bg-accent transition-colors data-[resize-handle-active]:bg-accent" />
      <Panel id="canvas" minSize="30" defaultSize={defaultLayout.canvas} className="flex flex-col min-w-0">
        <div className="flex-1 min-h-0 relative">
          <Wiresheet
            graph={graph}
            graphKey={graphKey}
            nodes={nodes}
            edges={edges}
            onTidy={onTidy}
            toolbar={
              run.parent_run_id ? (
                <Button
                  variant={compare ? 'primary' : 'outline'}
                  size="sm"
                  onClick={() => setCompare((value) => !value)}
                  aria-pressed={compare}
                  title="Overlay the parent candidate: removed blocks ghost, added glow, changed marked"
                >
                  <GitCompareArrows size={13} /> Compare with parent
                </Button>
              ) : null
            }
          />
          {compare && (
            <div className="absolute left-1/2 -translate-x-1/2 top-12 flex items-center gap-2 pointer-events-none">
              <StatusPill tone="sim">
                ghost diff · {diff ? `${diff.result.addedBlocks.size} added, ${diff.result.removedBlocks.size} removed, ${diff.result.modifiedBlocks.size} changed` : 'loading parent'}
              </StatusPill>
              {unexplained.length > 0 && (
                <StatusPill tone="warn" title={unexplained.join('\n')}>
                  {unexplained.length} server-listed changes not visible
                </StatusPill>
              )}
            </div>
          )}
        </div>
        <Transport trace={trace} compact />
      </Panel>
      <Separator className="w-px bg-line-1 hover:bg-accent transition-colors data-[resize-handle-active]:bg-accent" />
      <Panel id="inspector" minSize="16" defaultSize={defaultLayout.inspector} className="bg-bg-1 hairline-r">
        <Group orientation="vertical" className="h-full" defaultLayout={inspectorLayout} onLayoutChanged={(layout) => savePanelSizes(`${LAYOUT_KEY}:inspector`, layout)}>
          <Panel id="inspector" minSize="30" defaultSize={defaultInspectorLayout.inspector} className="min-h-0 overflow-auto">
            <Inspector graph={graph} nodes={nodes} trace={trace} report={report ?? undefined} run={run} />
          </Panel>
          <Separator className="h-px bg-line-1 hover:bg-accent transition-colors data-[resize-handle-active]:bg-accent" />
          <Panel id="folders" minSize="10" defaultSize={defaultInspectorLayout.folders} className="min-h-0 flex flex-col">
            <NiagaraFolders runId={run.id} />
          </Panel>
        </Group>
      </Panel>
    </Group>
  );
}
