import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import dagre from '@dagrejs/dagre';
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import {
  ArrowLeft,
  ArrowRight,
  Blocks,
  Building2,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  FileCheck2,
  GitBranch,
  Network,
  ShieldCheck,
  Workflow,
} from 'lucide-react';
import { Link, useParams } from 'react-router-dom';

import { api, type ProjectRecord } from '../../api/client';
import './project-workspace.css';

type EquipmentNodeData = {
  equipment: ProjectRecord['project']['equipment'][number];
  run: ProjectRecord['equipment_runs'][number] | undefined;
  incomingSignals: number;
  outgoingSignals: number;
};

type EquipmentNode = Node<EquipmentNodeData, 'equipment'>;
const nodeTypes = { equipment: EquipmentCard };

const statusLabels: Record<string, string> = {
  approved: 'Approved',
  failed: 'Failed',
  ready_for_review: 'Ready for review',
  rejected: 'Rejected',
};

function EquipmentCard({ data }: NodeProps<EquipmentNode>) {
  const family = data.equipment.sequence.family.replaceAll('_', ' ');
  return (
    <article className="topology-equipment">
      <Handle className="topology-handle" position={Position.Left} type="target" />
      <header>
        <span><Blocks size={15} aria-hidden="true" /></span>
        <div><strong>{data.equipment.equipment_name}</strong><small>{family}</small></div>
      </header>
      <div className="equipment-node-meta">
        <span>{data.equipment.points.length} points</span>
        <span>{data.incomingSignals} in · {data.outgoingSignals} out</span>
      </div>
      {data.run ? (
        <Link className="equipment-node-link" to={`/studio/${data.run.run_id}/wiresheet`}>
          Open program <ArrowRight size={13} aria-hidden="true" />
        </Link>
      ) : <span className="equipment-node-missing">No retained child run</span>}
      <Handle className="topology-handle" position={Position.Right} type="source" />
    </article>
  );
}

function topology(record: ProjectRecord): { nodes: EquipmentNode[]; edges: Edge[] } {
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({ rankdir: 'LR', ranksep: 140, nodesep: 65, marginx: 45, marginy: 45 });
  graph.setDefaultEdgeLabel(() => ({}));
  record.project.equipment.forEach((equipment) => graph.setNode(equipment.equipment_name, { width: 260, height: 148 }));
  record.project.relationships.forEach((relation) => graph.setEdge(relation.source, relation.target));
  record.project.signal_bindings.forEach((binding) => graph.setEdge(binding.source_equipment, binding.target_equipment));
  dagre.layout(graph);

  const nodes: EquipmentNode[] = record.project.equipment.map((equipment) => {
    const layout = graph.node(equipment.equipment_name) as { x: number; y: number };
    return {
      id: equipment.equipment_name,
      type: 'equipment',
      position: { x: layout.x - 130, y: layout.y - 74 },
      style: { width: 260, height: 148 },
      data: {
        equipment,
        run: record.equipment_runs.find((item) => item.equipment_name === equipment.equipment_name),
        incomingSignals: record.project.signal_bindings.filter((item) => item.target_equipment === equipment.equipment_name).length,
        outgoingSignals: record.project.signal_bindings.filter((item) => item.source_equipment === equipment.equipment_name).length,
      },
    };
  });
  const relationshipEdges: Edge[] = record.project.relationships.map((relation, index) => ({
    id: `relationship-${index}`,
    source: relation.source,
    target: relation.target,
    label: relation.relation,
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#81909a', width: 16, height: 16 },
    style: { stroke: '#81909a', strokeWidth: 1.5 },
    labelStyle: { fill: '#61717c', fontSize: 9, fontWeight: 700 },
    labelBgStyle: { fill: '#f7f9f9', fillOpacity: 0.95 },
  }));
  const signalEdges: Edge[] = record.project.signal_bindings.map((binding, index) => ({
    id: `signal-${index}`,
    source: binding.source_equipment,
    target: binding.target_equipment,
    label: `${binding.source_point} → ${binding.target_point}`,
    type: 'smoothstep',
    animated: true,
    markerEnd: { type: MarkerType.ArrowClosed, color: '#17785a', width: 18, height: 18 },
    style: { stroke: '#17785a', strokeWidth: 2.2 },
    labelStyle: { fill: '#146047', fontSize: 9, fontWeight: 750 },
    labelBgStyle: { fill: '#edf8f3', fillOpacity: 0.96 },
  }));
  return { nodes, edges: [...relationshipEdges, ...signalEdges] };
}

export function ProjectWorkspace() {
  const { projectId } = useParams();
  const projects = useQuery({ queryKey: ['projects'], queryFn: api.projects, enabled: !projectId });
  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => api.project(projectId ?? ''), enabled: Boolean(projectId) });
  const report = useQuery({ queryKey: ['project-report', projectId], queryFn: () => api.projectReport(projectId ?? ''), enabled: Boolean(projectId) });

  if (!projectId) return <ProjectIndex projects={projects.data ?? []} loading={projects.isLoading} failed={projects.isError} />;
  if (project.isLoading || report.isLoading) return <WorkspaceState label="Opening the whole-building model…" />;
  if (!project.data || !report.data || project.isError || report.isError) return <WorkspaceState error label="The retained building model or its evidence could not be loaded." />;
  return <ProjectDetail record={project.data} report={report.data} />;
}

function ProjectIndex({ projects, loading, failed }: { projects: ProjectRecord[]; loading: boolean; failed: boolean }) {
  return (
    <div className="project-index">
      <header className="workspace-page-heading">
        <div><span className="eyebrow">WHOLE-BUILDING WORKSPACE</span><h1>Projects</h1><p>See equipment programs as one connected control system, with retained cross-equipment proof.</p></div>
        <Link className="primary-action" to="/intake"><Building2 size={17} />Start a job</Link>
      </header>
      {failed && <div className="system-error" role="alert"><CircleAlert size={18} />Project builds could not be loaded.</div>}
      {loading ? <WorkspaceState label="Loading building projects…" /> : projects.length ? (
        <section className="project-card-grid" aria-label="Whole-building projects">
          {projects.map((record) => (
            <Link className="project-card" key={record.id} to={`/projects/${record.id}`}>
              <div className="project-card-icon"><Building2 size={22} /></div>
              <div><span className="eyebrow">{record.project.site}</span><h2>{record.project.name}</h2></div>
              <div className="project-card-stats"><span><strong>{record.project.equipment.length}</strong> equipment</span><span><strong>{record.project.signal_bindings.length}</strong> signal links</span><span><strong>{record.project.relationships.length}</strong> relationships</span></div>
              <footer><span className={`status-badge ${record.status}`}>{statusLabels[record.status]}</span><ChevronRight size={16} /></footer>
            </Link>
          ))}
        </section>
      ) : (
        <section className="project-empty"><Network size={30} /><h2>No whole-building project yet</h2><p>Individual programs are already retained. A project build binds them into a topology and runs typed, cross-equipment acceptance scenarios.</p><Link className="primary-action" to="/intake">Start the first building</Link></section>
      )}
    </div>
  );
}

function ProjectDetail({ record, report }: { record: ProjectRecord; report: Awaited<ReturnType<typeof api.projectReport>> }) {
  const flow = useMemo(() => topology(record), [record]);
  const assertions = report.scenarios.flatMap((scenario) => scenario.assertions);
  const passed = assertions.filter((assertion) => assertion.passed).length;
  return (
    <div className="project-detail">
      <div className="studio-breadcrumbs"><Link to="/projects"><ArrowLeft size={15} />Projects</Link><ChevronRight size={14} /><span>{record.project.site}</span><ChevronRight size={14} /><strong>{record.project.name}</strong></div>
      <header className="project-detail-header">
        <div><span className="eyebrow">WHOLE-BUILDING CONTROL SYSTEM</span><h1>{record.project.name}</h1><p>{record.project.site} · built {new Date(record.created_at).toLocaleString()}</p></div>
        <span className={`status-badge ${record.status}`}>{statusLabels[record.status]}</span>
      </header>
      <div className="engineering-boundary" role="note"><ShieldCheck size={17} /><strong>Offline building topology</strong><span>Animated green paths are typed program-to-program signals—not traffic to a live building.</span></div>
      <section className="project-metrics" aria-label="Project summary">
        <Metric icon={<Building2 size={17} />} label="Equipment programs" value={record.project.equipment.length} />
        <Metric icon={<Workflow size={17} />} label="Signal bindings" value={record.project.signal_bindings.length} />
        <Metric icon={<GitBranch size={17} />} label="Relationships" value={record.project.relationships.length} />
        <Metric icon={<CheckCircle2 size={17} />} label="Assertions passed" value={`${passed}/${assertions.length}`} good={report.passed} />
        <Metric icon={<FileCheck2 size={17} />} label="Station assembly" value={record.project.station_assembly_mode} />
      </section>
      <div className="project-detail-grid">
        <section className="topology-panel">
          <div className="panel-title"><div><span className="eyebrow">SYSTEM TOPOLOGY</span><h2>How the building controls connect</h2></div><div className="topology-legend"><span><i className="signal" />Typed signal</span><span><i />Equipment relationship</span></div></div>
          <div className="topology-canvas" aria-label={`${record.project.name} equipment topology`}>
            <ReactFlow fitView fitViewOptions={{ padding: 0.2 }} minZoom={0.2} nodes={flow.nodes} edges={flow.edges} nodesConnectable={false} nodesDraggable={false} nodeTypes={nodeTypes} proOptions={{ hideAttribution: true }}>
              <Background color="#d8dee1" gap={24} size={1} />
              <MiniMap pannable zoomable maskColor="rgba(244,247,246,.76)" nodeColor="#17785a" />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
        </section>
        <aside className="project-evidence-panel">
          <div className="panel-title"><div><span className="eyebrow">CROSS-EQUIPMENT PROOF</span><h2>{report.passed ? 'System behavior passed' : 'System behavior blocked'}</h2></div>{report.passed ? <CheckCircle2 className="pass-icon" size={20} /> : <CircleAlert className="fail-icon" size={20} />}</div>
          <p className="project-engine">{report.engine}</p>
          <div className="project-scenarios">
            {report.scenarios.length ? report.scenarios.map((scenario) => (
              <article key={scenario.name}>
                <header><strong>{scenario.name}</strong><span className={scenario.passed ? 'pass' : 'fail'}>{scenario.passed ? 'Passed' : 'Failed'}</span></header>
                {scenario.assertions.map((assertion) => <div className="project-assertion" key={assertion.name}><span>{assertion.passed ? <CheckCircle2 size={13} /> : <CircleAlert size={13} />}{assertion.name}</span><code>{assertion.observed}</code></div>)}
              </article>
            )) : <div className="project-no-scenarios">No explicit cross-equipment acceptance cases were supplied. Equipment programs were still tested independently.</div>}
          </div>
          <div className="project-digest"><span>Immutable project digest</span><code>{record.artifact_sha256}</code></div>
        </aside>
      </div>
    </div>
  );
}

function Metric({ icon, label, value, good = false }: { icon: React.ReactNode; label: string; value: string | number; good?: boolean }) {
  return <div className={good ? 'project-metric good' : 'project-metric'}><span>{icon}{label}</span><strong>{value}</strong></div>;
}

function WorkspaceState({ label, error = false }: { label: string; error?: boolean }) {
  return <div className={error ? 'project-workspace-state error' : 'project-workspace-state'}>{error ? <CircleAlert size={26} /> : <div className="studio-state-spinner" />}<strong>{label}</strong>{error && <Link to="/projects">Return to projects</Link>}</div>;
}
