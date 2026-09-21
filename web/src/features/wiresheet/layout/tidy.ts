/**
 * Deterministic left-to-right layout with dagre. Used on demand ("Tidy") and
 * automatically only when a graph carries no positions of its own.
 */

import dagre from '@dagrejs/dagre';

import type { ControlGraph } from '../../../api/client';

export interface Size {
  width: number;
  height: number;
}
export interface Point {
  x: number;
  y: number;
}

export const DEFAULT_SIZE: Size = { width: 190, height: 88 };

export function tidy(
  graph: Pick<ControlGraph, 'blocks' | 'links'>,
  sizes: ReadonlyMap<string, Size> = new Map(),
  feedbackKinds: ReadonlySet<string> = new Set(),
): Map<string, Point> {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', ranksep: 72, nodesep: 28, marginx: 24, marginy: 24 });
  g.setDefaultEdgeLabel(() => ({}));
  const sorted = [...graph.blocks].sort((a, b) => a.id.localeCompare(b.id));
  for (const block of sorted) {
    const size = sizes.get(block.id) ?? DEFAULT_SIZE;
    g.setNode(block.id, { width: size.width, height: size.height });
  }
  const kinds = new Map(graph.blocks.map((block) => [block.id, block.kind]));
  const links = [...graph.links].sort((a, b) => `${a.source}${a.target}`.localeCompare(`${b.source}${b.target}`));
  for (const link of links) {
    if (!kinds.has(link.source) || !kinds.has(link.target)) continue;
    // Feedback blocks close loops; leave their outgoing edge out of ranking.
    if (feedbackKinds.has(kinds.get(link.source)!)) continue;
    g.setEdge(link.source, link.target);
  }
  dagre.layout(g);
  const positions = new Map<string, Point>();
  for (const block of sorted) {
    const node = g.node(block.id);
    const size = sizes.get(block.id) ?? DEFAULT_SIZE;
    positions.set(block.id, { x: Math.round(node.x - size.width / 2), y: Math.round(node.y - size.height / 2) });
  }
  return positions;
}

/** True when the graph has no meaningful positions (every block at the origin). */
export function needsLayout(graph: Pick<ControlGraph, 'blocks'>): boolean {
  if (graph.blocks.length === 0) return false;
  const origin = graph.blocks.filter((block) => block.x === 0 && block.y === 0).length;
  return origin / graph.blocks.length > 0.5;
}
