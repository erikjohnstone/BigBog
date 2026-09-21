import dagre from '@dagrejs/dagre';
import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';

import type { ProjectRecord } from '../../api/client';
import { cn } from '../../design-system/cn';
import { runStatusTone } from '../../design-system/primitives';
import { useSelection } from '../../stores/selection';
import type { Trace } from '../../stores/trace';
import { useLiveSymbol } from './symbols/live';

const NODE_W = 190;
const NODE_H = 64;

function glyphFor(brick: string | null | undefined): string {
  const value = (brick ?? '').toLowerCase();
  if (value.includes('vav')) return 'VAV';
  if (value.includes('ahu') || value.includes('air_handl')) return 'AHU';
  if (value.includes('fan')) return 'FAN';
  if (value.includes('pump')) return 'PMP';
  if (value.includes('chiller')) return 'CH';
  if (value.includes('boiler')) return 'BLR';
  return 'EQ';
}

function relationColor(relation: string): string {
  switch (relation) {
    case 'feeds':
      return 'var(--m-air-supply)';
    case 'serves':
      return 'var(--m-hw)';
    case 'controls':
      return 'var(--m-cmd)';
    case 'enables':
      return 'var(--m-status)';
    default:
      return 'var(--fg-2)';
  }
}

function BindingLink({ points, signalId, label }: { points: Array<[number, number]>; signalId?: string; label: string }) {
  const ref = useLiveSymbol<SVGGElement>({ speed: signalId });
  const d = points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x} ${y}`).join(' ');
  const mid = points[Math.floor(points.length / 2)];
  return (
    <g ref={ref} className="system-binding">
      <title>{label}</title>
      <path d={d} fill="none" stroke="var(--m-cmd)" strokeWidth={1.5} opacity={0.5} />
      <path d={d} fill="none" stroke="var(--m-cmd)" strokeWidth={2.5} className="edge-flow" data-idle={signalId ? 'false' : 'true'} />
      <text x={mid[0]} y={mid[1] - 6} textAnchor="middle" className="sym-label">
        {label}
      </text>
    </g>
  );
}

/**
 * Whole-project topology: equipment as nodes, typed relationships as edges,
 * and signal bindings as animated links carrying `Equip.Point` values when
 * a project trace is on the clock.
 */
export function SystemMap({ project, trace }: { project: ProjectRecord; trace?: Trace }) {
  const navigate = useNavigate();
  const selected = useSelection((state) => state.blockIds);
  const selectBlocks = useSelection((state) => state.selectBlocks);

  const layout = useMemo(() => {
    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: 'TB', ranksep: 60, nodesep: 40, marginx: 20, marginy: 20 });
    g.setDefaultEdgeLabel(() => ({}));
    for (const equipment of project.project.equipment) g.setNode(equipment.equipment_name, { width: NODE_W, height: NODE_H });
    for (const relation of project.project.relationships) {
      if (g.hasNode(relation.source) && g.hasNode(relation.target)) g.setEdge(relation.source, relation.target);
    }
    dagre.layout(g);
    const graph = g.graph();
    const nodes = project.project.equipment.map((equipment) => {
      const node = g.node(equipment.equipment_name);
      return { equipment, x: node.x - NODE_W / 2, y: node.y - NODE_H / 2, cx: node.x, cy: node.y };
    });
    const edges = project.project.relationships
      .filter((relation) => g.hasEdge(relation.source, relation.target))
      .map((relation) => ({ relation, points: g.edge(relation.source, relation.target).points as Array<{ x: number; y: number }> }));
    return { width: graph.width ?? 600, height: graph.height ?? 400, nodes, edges };
  }, [project]);

  const centre = (name: string) => layout.nodes.find((node) => node.equipment.equipment_name === name);
  const runByEquipment = new Map(project.equipment_runs.map((item) => [item.equipment_name, item]));

  return (
    <svg viewBox={`0 0 ${layout.width} ${layout.height}`} className="schematic w-full" style={{ maxHeight: 520 }} role="group" aria-label={`System map for ${project.project.name}`}>
      <title>{`System map for ${project.project.name}`}</title>
      <defs>
        <marker id="system-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--fg-2)" />
        </marker>
      </defs>
      {layout.edges.map(({ relation, points }) => {
        const d = points.map((point, i) => `${i === 0 ? 'M' : 'L'} ${point.x} ${point.y}`).join(' ');
        const mid = points[Math.floor(points.length / 2)];
        return (
          <g key={`${relation.source}-${relation.relation}-${relation.target}`}>
            <title>{`${relation.source} ${relation.relation} ${relation.target}`}</title>
            <path d={d} fill="none" stroke={relationColor(relation.relation)} strokeWidth={1.5} markerEnd="url(#system-arrow)" opacity={0.8} />
            <text x={mid.x + 6} y={mid.y - 4} className="sym-label">
              {relation.relation}
            </text>
          </g>
        );
      })}
      {project.project.signal_bindings.map((binding) => {
        const from = centre(binding.source_equipment);
        const to = centre(binding.target_equipment);
        if (!from || !to) return null;
        const signalId = trace?.signals.has(`${binding.source_equipment}.${binding.source_point}`) ? `${binding.source_equipment}.${binding.source_point}` : undefined;
        return (
          <BindingLink
            key={`${binding.source_equipment}.${binding.source_point}->${binding.target_equipment}.${binding.target_point}`}
            points={[
              [from.cx + NODE_W / 2 - 10, from.cy],
              [Math.max(from.cx, to.cx) + NODE_W / 2 + 30, (from.cy + to.cy) / 2],
              [to.cx + NODE_W / 2 - 10, to.cy],
            ]}
            signalId={signalId}
            label={`${binding.source_point} → ${binding.target_point}`}
          />
        );
      })}
      {layout.nodes.map(({ equipment, x, y }) => {
        const run = runByEquipment.get(equipment.equipment_name);
        const tone = run ? runStatusTone(run.status) : null;
        const isSelected = selected.has(equipment.equipment_name);
        return (
          <g
            key={equipment.equipment_name}
            transform={`translate(${x} ${y})`}
            className={cn('system-node cursor-pointer', isSelected && 'is-selected')}
            onClick={() => selectBlocks([equipment.equipment_name])}
            onDoubleClick={() => run && navigate(`/jobs/${run.run_id}/build`)}
            role="button"
            tabIndex={0}
            aria-label={`${equipment.equipment_name}, ${equipment.sequence.family}${run ? `, ${run.status}` : ''}`}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && run) navigate(`/jobs/${run.run_id}/build`);
            }}
          >
            <rect width={NODE_W} height={NODE_H} rx={8} fill="var(--bg-2)" stroke={isSelected ? 'var(--accent)' : 'var(--line-2)'} strokeWidth={isSelected ? 2 : 1.5} />
            <rect x={0} y={0} width={44} height={NODE_H} rx={8} fill="var(--bg-3)" />
            <text x={22} y={NODE_H / 2 + 4} textAnchor="middle" className="sym-tag">
              {glyphFor(equipment.equipment_brick_class)}
            </text>
            <text x={54} y={24} className="sym-label-strong">
              {equipment.equipment_name}
            </text>
            <text x={54} y={42} className="sym-label">
              {equipment.sequence.family}
            </text>
            {tone && (
              <g transform={`translate(${NODE_W - 14} 14)`}>
                <circle r={5} fill={`var(--${tone.tone === 'ok' ? 'ok' : tone.tone === 'fail' ? 'fail' : tone.tone === 'info' ? 'accent' : 'warn'})`} />
                <title>{tone.label}</title>
              </g>
            )}
          </g>
        );
      })}
    </svg>
  );
}
