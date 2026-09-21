/**
 * Order blocks topologically so the sheet materializes from inputs to
 * outputs. Feedback blocks are left out of the ordering pass so loops do not
 * stall it. Delays are capped so a large sheet still finishes quickly.
 */

import type { ControlGraph } from '../../../api/client';

export const STAGGER_MS = 20;
export const MAX_DELAY_MS = 1100;

export function materializeOrder(
  graph: Pick<ControlGraph, 'blocks' | 'links'>,
  feedbackKinds: ReadonlySet<string> = new Set(),
): Map<string, number> {
  const kinds = new Map(graph.blocks.map((block) => [block.id, block.kind]));
  const indegree = new Map<string, number>(graph.blocks.map((block) => [block.id, 0]));
  const out = new Map<string, string[]>();
  for (const link of graph.links) {
    if (!kinds.has(link.source) || !kinds.has(link.target)) continue;
    if (feedbackKinds.has(kinds.get(link.source)!)) continue;
    indegree.set(link.target, (indegree.get(link.target) ?? 0) + 1);
    out.set(link.source, [...(out.get(link.source) ?? []), link.target]);
  }
  const order = new Map<string, number>();
  let frontier = graph.blocks.filter((block) => (indegree.get(block.id) ?? 0) === 0).map((block) => block.id);
  let rank = 0;
  while (frontier.length > 0) {
    const next: string[] = [];
    for (const id of frontier) {
      if (order.has(id)) continue;
      order.set(id, rank);
      for (const target of out.get(id) ?? []) {
        indegree.set(target, (indegree.get(target) ?? 1) - 1);
        if ((indegree.get(target) ?? 0) <= 0) next.push(target);
      }
    }
    frontier = next;
    rank += 1;
  }
  // Anything still unordered sits in a cycle; place it after everything else.
  for (const block of graph.blocks) if (!order.has(block.id)) order.set(block.id, rank);
  return order;
}

export function delayFor(rank: number): number {
  return Math.min(rank * STAGGER_MS, MAX_DELAY_MS);
}
