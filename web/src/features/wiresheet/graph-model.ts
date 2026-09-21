/**
 * Turn a ControlGraph plus the block catalog into React Flow nodes and edges.
 * Ports come from the catalog, never from which links happen to exist, so an
 * unlinked input is still drawn as an open slot.
 */

import type { Edge, Node } from '@xyflow/react';

import type { BlockCatalog, BlockCatalogKind, ControlGraph, RunDetail, TestReport } from '../../api/client';
import { linkKey } from '../../stores/selection';
import type { Trace } from '../../stores/trace';
import { signalIdForOutput } from '../../trace/build-trace';
import type { DiffStatus, GraphDiff } from './diff/compute-diff';
import { materializeOrder } from './intro/materialize';

export type Family =
  | 'io'
  | 'const'
  | 'math'
  | 'compare'
  | 'logic'
  | 'switch'
  | 'timing'
  | 'state'
  | 'filter'
  | 'loop'
  | 'plant'
  | 'assert'
  | 'unknown';

export type PortType = 'numeric' | 'boolean';

export interface PortSpec {
  name: string;
  type: PortType;
  /** Signal carrying this output's value, when the trace has one. */
  signalId?: string;
  /** For inputs: the upstream `block.slot` feeding it, if linked. */
  from?: string;
}

export interface Coverage {
  bothOutcomes: boolean;
  observed: unknown[];
}

export interface BlockNodeData extends Record<string, unknown> {
  id: string;
  kind: string;
  label: string;
  family: Family;
  config: Record<string, unknown>;
  inputs: PortSpec[];
  outputs: PortSpec[];
  stateful: boolean;
  feedback: boolean;
  isInput: boolean;
  isOutput: boolean;
  unit?: string;
  pointName?: string;
  /** `effective.<id>` signal, present when a fault can override this input. */
  overrideSignalId?: string;
  /** `fault.<id>.active` signals targeting this block. */
  faultSignalIds: string[];
  coverage: Coverage | null;
  diff?: DiffStatus;
  diffFields?: Array<{ field: string; before: unknown; after: unknown }>;
  rank: number;
  intro: boolean;
}

export type BlockNode = Node<BlockNodeData, 'block'>;

export interface SignalEdgeData extends Record<string, unknown> {
  key: string;
  type: PortType;
  signalId?: string;
  feedback: boolean;
  diff?: DiffStatus;
  rank: number;
  intro: boolean;
}

export type SignalEdge = Edge<SignalEdgeData, 'signal'>;

/** Binding groups the wiresheet pauses when zoomed out past legibility. */
export const LOD_NODE_CHIPS = 'wiresheet:node-chips';
export const LOD_EDGE_FLOW = 'wiresheet:edge-flow';
/** Below this zoom chips are unreadable and stop updating. */
export const LOD_CHIP_ZOOM = 0.5;
/** Below this zoom wires stop animating. */
export const LOD_FLOW_ZOOM = 0.35;

export const FAMILIES: Family[] = ['io', 'const', 'math', 'compare', 'logic', 'switch', 'timing', 'state', 'filter', 'loop', 'plant', 'assert', 'unknown'];

export const familyLabel: Record<Family, string> = {
  io: 'Points',
  const: 'Constants',
  math: 'Math',
  compare: 'Compare',
  logic: 'Logic',
  switch: 'Switches',
  timing: 'Timing',
  state: 'State',
  filter: 'Filters',
  loop: 'Loops',
  plant: 'Plant',
  assert: 'Assertions',
  unknown: 'Other',
};

export function familyColor(family: Family): string {
  return `var(--family-${family})`;
}

function guessType(kind: string, slot: string): PortType {
  if (kind.startsWith('boolean') || ['and', 'or', 'xor', 'not', 'timer'].some((k) => kind.startsWith(k))) return 'boolean';
  if (['selector', 'enable', 'device_on', 'trigger', 'direct', 'clock', 'reset', 'set', 'clear', 'hold', 'condition'].includes(slot)) {
    return 'boolean';
  }
  return 'numeric';
}

function fallbackKind(graph: ControlGraph, kind: string): BlockCatalogKind {
  // No catalog entry: infer ports from the links that touch blocks of this kind.
  const ids = new Set(graph.blocks.filter((block) => block.kind === kind).map((block) => block.id));
  const inputs = new Set<string>();
  const outputs = new Set<string>();
  for (const link of graph.links) {
    if (ids.has(link.target)) inputs.add(link.target_slot);
    if (ids.has(link.source)) outputs.add(link.source_slot);
  }
  if (outputs.size === 0) outputs.add('out');
  return {
    kind,
    family: 'unknown',
    stateful: false,
    feedback: false,
    inputs: [...inputs].map((name) => ({ name, type: guessType(kind, name) })),
    outputs: [...outputs].map((name) => ({ name, type: guessType(kind, name) })),
  };
}

export function catalogKind(catalog: BlockCatalog | undefined, graph: ControlGraph, kind: string): BlockCatalogKind {
  return catalog?.kinds.find((item) => item.kind === kind) ?? fallbackKind(graph, kind);
}

export function feedbackKinds(catalog: BlockCatalog | undefined): Set<string> {
  return new Set((catalog?.kinds ?? []).filter((item) => item.feedback).map((item) => item.kind));
}

export interface BuildFlowInput {
  graph: ControlGraph;
  catalog?: BlockCatalog;
  trace?: Trace;
  report?: TestReport;
  run?: RunDetail;
  /** Parent graph for the ghost overlay; removed blocks come from it. */
  diff?: { parent: ControlGraph; result: GraphDiff } | null;
  intro: boolean;
  positions?: ReadonlyMap<string, { x: number; y: number }>;
}

export function buildFlow(input: BuildFlowInput): { nodes: BlockNode[]; edges: SignalEdge[] } {
  const { graph, catalog, trace, report, run, diff, intro, positions } = input;
  const feedback = feedbackKinds(catalog);
  const rank = materializeOrder(graph, feedback);

  const decisions = new Map<string, Coverage>();
  for (const decision of report?.coverage?.decisions ?? []) {
    const blockId = decision.decision.split('.')[0];
    decisions.set(blockId, { bothOutcomes: decision.both_outcomes, observed: decision.observed });
  }
  const declarations = report?.coverage?.fault_injection?.declarations ?? [];

  // Removed blocks come from the parent graph so the ghost sits where it was.
  const blocks = [...graph.blocks];
  if (diff) {
    for (const id of diff.result.removedBlocks) {
      const block = diff.parent.blocks.find((item) => item.id === id);
      if (block) blocks.push(block);
    }
  }

  const upstreamOf = new Map<string, string>();
  for (const link of graph.links) upstreamOf.set(`${link.target}.${link.target_slot}`, `${link.source}.${link.source_slot}`);

  const nodes: BlockNode[] = blocks.map((block) => {
    const spec = catalogKind(catalog, graph, block.kind);
    const family = (FAMILIES.includes(spec.family as Family) ? spec.family : 'unknown') as Family;
    const point = run?.job.points.find((item) => item.name === block.id);
    const isInput = block.kind.endsWith('_input');
    const isOutput = block.kind.endsWith('_output');
    const overrideSignalId = trace?.signals.has(`effective.${block.id}`) ? `effective.${block.id}` : undefined;
    const faultSignalIds = declarations
      .filter((item) => item.target === block.id)
      .map((item) => `fault.${item.id}.active`)
      .filter((id) => trace?.signals.has(id));
    const status: DiffStatus | undefined = diff
      ? diff.result.removedBlocks.has(block.id)
        ? 'removed'
        : diff.result.addedBlocks.has(block.id)
          ? 'added'
          : diff.result.modifiedBlocks.has(block.id)
            ? 'modified'
            : undefined
      : undefined;
    const position = positions?.get(block.id) ?? { x: block.x, y: block.y };
    return {
      id: block.id,
      type: 'block',
      position,
      selectable: status !== 'removed',
      draggable: status !== 'removed',
      data: {
        id: block.id,
        kind: block.kind,
        label: block.label,
        family,
        config: block.config ?? {},
        inputs: spec.inputs.map((slot) => ({
          name: slot.name,
          type: slot.type === 'boolean' ? 'boolean' : 'numeric',
          from: upstreamOf.get(`${block.id}.${slot.name}`),
        })),
        outputs: spec.outputs.map((slot) => ({
          name: slot.name,
          type: slot.type === 'boolean' ? 'boolean' : 'numeric',
          signalId: signalIdForOutput(trace, block.id, slot.name, spec.outputs[0]?.name),
        })),
        stateful: spec.stateful,
        feedback: spec.feedback,
        isInput,
        isOutput,
        unit: point?.units ?? undefined,
        pointName: point?.name,
        overrideSignalId,
        faultSignalIds,
        coverage: decisions.get(block.id) ?? null,
        diff: status,
        diffFields: diff?.result.modifiedBlocks.get(block.id)?.fields,
        rank: rank.get(block.id) ?? 0,
        intro,
      },
    };
  });

  const kindOf = new Map(blocks.map((block) => [block.id, block.kind]));
  const links = [...graph.links.map((link) => ({ link, removed: false }))];
  if (diff) {
    for (const key of diff.result.removedLinks) {
      const link = diff.parent.links.find((item) => linkKey(item.source, item.source_slot, item.target, item.target_slot) === key);
      if (link) links.push({ link, removed: true });
    }
  }
  const edges: SignalEdge[] = links
    .filter(({ link }) => kindOf.has(link.source) && kindOf.has(link.target))
    .map(({ link, removed }) => {
      const key = linkKey(link.source, link.source_slot, link.target, link.target_slot);
      const sourceSpec = catalogKind(catalog, graph, kindOf.get(link.source)!);
      const slot = sourceSpec.outputs.find((item) => item.name === link.source_slot);
      const type: PortType = slot?.type === 'boolean' ? 'boolean' : 'numeric';
      const status: DiffStatus | undefined = removed ? 'removed' : diff?.result.addedLinks.has(key) ? 'added' : undefined;
      return {
        id: key,
        type: 'signal',
        source: link.source,
        sourceHandle: link.source_slot,
        target: link.target,
        targetHandle: link.target_slot,
        selectable: !removed,
        data: {
          key,
          type,
          signalId: removed ? undefined : signalIdForOutput(trace, link.source, link.source_slot, sourceSpec.outputs[0]?.name),
          feedback: feedback.has(kindOf.get(link.source)!),
          diff: status,
          rank: Math.max(rank.get(link.source) ?? 0, rank.get(link.target) ?? 0),
          intro,
        },
      };
    });

  return { nodes, edges };
}

/** Every block and link upstream of `blockId`, following links backwards. */
export function upstream(graph: ControlGraph, blockId: string): { blockIds: Set<string>; linkKeys: Set<string> } {
  const blockIds = new Set<string>([blockId]);
  const linkKeys = new Set<string>();
  const queue = [blockId];
  while (queue.length > 0) {
    const current = queue.shift()!;
    for (const link of graph.links) {
      if (link.target !== current) continue;
      linkKeys.add(linkKey(link.source, link.source_slot, link.target, link.target_slot));
      if (!blockIds.has(link.source)) {
        blockIds.add(link.source);
        queue.push(link.source);
      }
    }
  }
  return { blockIds, linkKeys };
}

/** Neighbours for keyboard navigation along links. */
export function neighbours(graph: ControlGraph, blockId: string): { upstream: string[]; downstream: string[] } {
  const up: string[] = [];
  const down: string[] = [];
  for (const link of graph.links) {
    if (link.target === blockId && !up.includes(link.source)) up.push(link.source);
    if (link.source === blockId && !down.includes(link.target)) down.push(link.target);
  }
  return { upstream: up, downstream: down };
}
