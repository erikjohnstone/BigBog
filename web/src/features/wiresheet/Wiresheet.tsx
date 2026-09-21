import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  useEdgesState,
  useNodesState,
  useReactFlow,
  useStore,
} from '@xyflow/react';
import type { NodeTypes, EdgeTypes, OnSelectionChangeParams } from '@xyflow/react';
import { LayoutGrid, Maximize2, Search } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';

import type { ControlGraph } from '../../api/client';
import { Button, Kbd } from '../../design-system/primitives';
import { useSelection } from '../../stores/selection';
import { setBindingGroupActive } from '../../stores/trace';
import { useTimeCursor } from '../../stores/timeCursor';
import { SignalEdge } from './edges/SignalEdge';
import { familyColor, LOD_CHIP_ZOOM, LOD_EDGE_FLOW, LOD_FLOW_ZOOM, LOD_NODE_CHIPS, neighbours } from './graph-model';
import type { BlockNode, SignalEdge as SignalEdgeType } from './graph-model';
import { BlockNode as BlockNodeComponent } from './nodes/BlockNode';

const nodeTypes: NodeTypes = { block: BlockNodeComponent };
const edgeTypes: EdgeTypes = { signal: SignalEdge };

export interface WiresheetProps {
  graph: ControlGraph;
  graphKey: string;
  nodes: BlockNode[];
  edges: SignalEdgeType[];
  onTidy: () => void;
  toolbar?: ReactNode;
}

/**
 * The read-only, animated wiresheet. Selection is shared through the
 * selection store so the outline, inspector, trends, and assistant follow.
 */
export function Wiresheet({ graph, graphKey, nodes: inputNodes, edges: inputEdges, onTidy, toolbar }: WiresheetProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<BlockNode>(inputNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<SignalEdgeType>(inputEdges);
  const flow = useReactFlow<BlockNode, SignalEdgeType>();
  const selectBlocks = useSelection((state) => state.selectBlocks);
  const selectedIds = useSelection((state) => state.blockIds);
  const step = useTimeCursor((state) => state.step);
  const toggle = useTimeCursor((state) => state.toggle);
  const [query, setQuery] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const userMoved = useRef(false);
  const zoom = useStore((state) => state.transform[2]);
  const lod = zoom < LOD_FLOW_ZOOM ? 'low' : zoom < LOD_CHIP_ZOOM ? 'mid' : 'full';

  // Level of detail: past legibility, chips stop updating and wires stop
  // animating, so a large sheet scrubs at the cost of a small one.
  useEffect(() => {
    setBindingGroupActive(LOD_NODE_CHIPS, lod === 'full');
    setBindingGroupActive(LOD_EDGE_FLOW, lod !== 'low');
    return () => {
      setBindingGroupActive(LOD_NODE_CHIPS, true);
      setBindingGroupActive(LOD_EDGE_FLOW, true);
    };
  }, [lod]);

  // Rebuild local state when the graph (or its overlay) changes, keeping
  // positions the user dragged for blocks that still exist.
  useEffect(() => {
    setNodes((current) => {
      const dragged = new Map(current.map((node) => [node.id, node.position]));
      return inputNodes.map((node) => ({
        ...node,
        position: node.data.intro ? node.position : (dragged.get(node.id) ?? node.position),
        selected: selectedIds.has(node.id),
      }));
    });
    setEdges(inputEdges);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inputNodes, inputEdges, setNodes, setEdges]);

  // External selection (outline, jump-to-failure) → node selected flags.
  useEffect(() => {
    setNodes((current) => {
      let changed = false;
      const next = current.map((node) => {
        const selected = selectedIds.has(node.id);
        if (Boolean(node.selected) === selected) return node;
        changed = true;
        return { ...node, selected };
      });
      return changed ? next : current;
    });
  }, [selectedIds, setNodes]);

  useEffect(() => {
    userMoved.current = false;
    const frame = requestAnimationFrame(() => flow.fitView({ padding: 0.15, duration: 0 }));
    return () => cancelAnimationFrame(frame);
  }, [graphKey, flow]);

  // Refit when the panel resizes, unless the user already framed the sheet.
  useEffect(() => {
    const element = wrapperRef.current;
    if (!element) return;
    let timer: number | null = null;
    const observer = new ResizeObserver(() => {
      if (userMoved.current) return;
      if (timer !== null) window.clearTimeout(timer);
      timer = window.setTimeout(() => flow.fitView({ padding: 0.15, duration: 120 }), 100);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [flow]);

  // React Flow calls this synchronously inside its own store update. Writing
  // the shared selection there would feed straight back into node props and
  // nest updates, so the write is deferred out of React Flow's cycle.
  const pendingSelection = useRef<string[] | null>(null);
  const onSelectionChange = useCallback(
    ({ nodes: selected }: OnSelectionChangeParams<BlockNode, SignalEdgeType>) => {
      const ids = selected.map((node) => node.id);
      const already = pendingSelection.current !== null;
      pendingSelection.current = ids;
      if (already) return;
      queueMicrotask(() => {
        const next = pendingSelection.current;
        pendingSelection.current = null;
        if (!next) return;
        const current = useSelection.getState().blockIds;
        if (next.length === current.size && next.every((id) => current.has(id))) return;
        selectBlocks(next);
      });
    },
    [selectBlocks],
  );

  const focusBlock = useCallback(
    (id: string) => {
      selectBlocks([id]);
      userMoved.current = true;
      void flow.fitView({ nodes: [{ id }], duration: 260, maxZoom: 1.25, padding: 0.4 });
    },
    [flow, selectBlocks],
  );

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return [];
    return graph.blocks
      .filter((block) => block.id.toLowerCase().includes(needle) || block.label.toLowerCase().includes(needle) || block.kind.includes(needle))
      .slice(0, 8);
  }, [graph, query]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    const typing = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA';
    if (typing && event.key !== 'Escape') return;
    const selected = [...selectedIds][0];
    switch (event.key) {
      case '/':
        event.preventDefault();
        searchRef.current?.focus();
        break;
      case 't':
      case 'T':
        onTidy();
        break;
      case 'f':
      case 'F':
        userMoved.current = false;
        void flow.fitView({ padding: 0.15, duration: 200 });
        break;
      case '[':
        step(-1);
        break;
      case ']':
        step(1);
        break;
      case ' ':
        event.preventDefault();
        toggle();
        break;
      case 'ArrowRight':
      case 'ArrowLeft': {
        if (!selected) break;
        event.preventDefault();
        const next = neighbours(graph, selected);
        const candidates = event.key === 'ArrowRight' ? next.downstream : next.upstream;
        if (candidates[0]) focusBlock(candidates[0]);
        break;
      }
      case 'ArrowUp':
      case 'ArrowDown': {
        if (!selected) break;
        event.preventDefault();
        const current = nodes.find((node) => node.id === selected);
        if (!current) break;
        const direction = event.key === 'ArrowDown' ? 1 : -1;
        const candidate = nodes
          .filter((node) => node.id !== selected && Math.abs(node.position.x - current.position.x) < 140)
          .filter((node) => Math.sign(node.position.y - current.position.y) === direction)
          .sort((a, b) => Math.abs(a.position.y - current.position.y) - Math.abs(b.position.y - current.position.y))[0];
        if (candidate) focusBlock(candidate.id);
        break;
      }
      case 'Escape':
        if (typing) (target as HTMLInputElement).blur();
        else selectBlocks([]);
        break;
      default:
        break;
    }
  };

  return (
    <div
      ref={wrapperRef}
      className="relative h-full w-full outline-none"
      onKeyDown={onKeyDown}
      tabIndex={0}
      aria-label="Wiresheet"
      role="application"
      data-lod={lod}
    >
      <ReactFlow<BlockNode, SignalEdgeType>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onSelectionChange={onSelectionChange}
        onMoveStart={() => {
          userMoved.current = true;
        }}
        nodesConnectable={false}
        elementsSelectable
        deleteKeyCode={null}
        onlyRenderVisibleElements
        minZoom={0.2}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        fitView
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
        <MiniMap pannable zoomable nodeColor={(node) => familyColor((node as BlockNode).data.family)} nodeStrokeWidth={0} />
        <Controls showInteractive={false} position="bottom-right" />
        <Panel position="top-left" className="flex flex-col gap-1">
          <div className="floating flex items-center gap-2 h-8 px-2">
            <Search size={13} className="text-fg-2" />
            <input
              ref={searchRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && matches[0]) {
                  focusBlock(matches[0].id);
                  setQuery('');
                }
              }}
              placeholder="Find block"
              aria-label="Find block"
              className="w-40 bg-transparent outline-none text-xs placeholder:text-fg-2"
            />
            <Kbd>/</Kbd>
          </div>
          {matches.length > 0 && (
            <ul className="floating p-1 w-64" role="listbox" aria-label="Matching blocks">
              {matches.map((block) => (
                <li key={block.id}>
                  <button
                    type="button"
                    className="w-full text-left px-2 h-7 rounded-control text-xs hover:bg-bg-2 flex items-center gap-2"
                    onClick={() => {
                      focusBlock(block.id);
                      setQuery('');
                    }}
                  >
                    <span className="truncate">{block.label}</span>
                    <span className="font-mono text-2xs text-fg-2 truncate">{block.id}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel position="top-right" className="flex items-center gap-1">
          {toolbar}
          <Button variant="outline" size="sm" onClick={onTidy} title="Tidy layout (T)">
            <LayoutGrid size={13} /> Tidy
          </Button>
          <Button
            variant="outline"
            size="icon"
            onClick={() => {
              userMoved.current = false;
              void flow.fitView({ padding: 0.15, duration: 200 });
            }}
            aria-label="Fit to view (F)"
            title="Fit to view (F)"
            className="size-7"
          >
            <Maximize2 size={13} />
          </Button>
        </Panel>
      </ReactFlow>
    </div>
  );
}
