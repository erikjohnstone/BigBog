/**
 * A whole-project trace: the project report's samples are keyed
 * `Equipment.Block[.slot]`, so the generic builder runs over a synthetic run
 * whose graph and points carry the same qualified ids. Signal bindings and
 * the system map then read `Equip.Point` straight from the trace.
 */

import type { ControlGraph, ProjectRecord, RunDetail, TestReport } from '../api/client';
import type { Trace } from '../stores/trace';
import { buildTrace } from './build-trace';

export function projectTraceId(projectId: string): string {
  return `project:${projectId}`;
}

type ProjectPhase = { name: string; repeat?: number; step_seconds?: number; expectations?: Array<{ equipment: string; point: string }> };
type ProjectCase = { name: string; phases?: ProjectPhase[] };

/** Project acceptance cases in the shape the generic trace builder reads. */
export function projectCasesAsAcceptance(cases: unknown[]): Array<{ name: string; expectations: Array<{ target: string }>; timeline: Array<{ name: string; repeat: number; step_seconds: number }> }> {
  const out = [];
  for (const raw of cases) {
    const item = raw as ProjectCase;
    if (!item || typeof item.name !== 'string' || !Array.isArray(item.phases)) continue;
    out.push({
      name: item.name,
      expectations: item.phases.flatMap((phase) => (phase.expectations ?? []).map((expectation) => ({ target: `${expectation.equipment}.${expectation.point}` }))),
      timeline: item.phases.map((phase) => ({ name: phase.name, repeat: phase.repeat ?? 1, step_seconds: phase.step_seconds ?? 1 })),
    });
  }
  return out;
}

/** Every equipment graph, with ids qualified by equipment name. */
export function projectGraph(project: ProjectRecord): ControlGraph {
  const blocks: ControlGraph['blocks'] = [];
  const links: ControlGraph['links'] = [];
  for (const equipment of project.project.equipment) {
    const graph = (equipment as { control_graph?: ControlGraph | null }).control_graph;
    if (!graph) continue;
    for (const block of graph.blocks) blocks.push({ ...block, id: `${equipment.equipment_name}.${block.id}`, label: `${equipment.equipment_name} · ${block.label}` });
    for (const link of graph.links) links.push({ ...link, source: `${equipment.equipment_name}.${link.source}`, target: `${equipment.equipment_name}.${link.target}` });
  }
  return { ...(project.project.equipment[0] as { control_graph?: ControlGraph | null }).control_graph, name: project.project.name, blocks, links } as ControlGraph;
}

export function buildProjectTrace(project: ProjectRecord, report: TestReport): Trace {
  const points = project.project.equipment.flatMap((equipment) =>
    equipment.points.map((point) => ({ ...point, name: `${equipment.equipment_name}.${point.name}`, label: `${equipment.equipment_name} · ${point.label}` })),
  );
  const run = {
    id: project.id,
    status: project.status,
    artifact_sha256: project.artifact_sha256,
    job: { name: project.project.name, site: project.project.site, equipment_name: project.project.name, points, acceptance_tests: projectCasesAsAcceptance(project.project.acceptance_tests) },
  } as unknown as RunDetail;
  const trace = buildTrace(run, report, { graph: projectGraph(project) });
  return { ...trace, id: projectTraceId(project.id), engine: 'project', label: project.project.name };
}
