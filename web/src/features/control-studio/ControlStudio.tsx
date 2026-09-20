import { lazy, Suspense, useCallback, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
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
  Blocks,
  Bot,
  Brush,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Download,
  FileArchive,
  FileCheck2,
  FlaskConical,
  GitCompareArrows,
  Hash,
  Info,
  ListTree,
  PackageCheck,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  TestTube2,
  Waves,
} from 'lucide-react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';

import {
  api,
  type ControlGraph,
  type ReleaseSummary,
  type RunDetail,
  type TestReport,
} from '../../api/client';

type StudioView = 'wiresheet' | 'tests' | 'simulation' | 'graphics' | 'review';

type ControlNodeData = {
  label: string;
  kind: string;
  config: Record<string, unknown>;
  inputs: string[];
  outputs: string[];
  isMatch: boolean;
};

type ControlFlowNode = Node<ControlNodeData, 'control'>;

const nodeTypes = { control: ControlNode };
const AgentDrawer = lazy(() => import('./AgentDrawer').then((module) => ({ default: module.AgentDrawer })));
const SimulationLab = lazy(() => import('./SimulationLab').then((module) => ({ default: module.SimulationLab })));
const GraphicsStudio = lazy(() => import('./GraphicsStudio').then((module) => ({ default: module.GraphicsStudio })));
const TestLab = lazy(() => import('./TestLab').then((module) => ({ default: module.TestLab })));

const statusCopy: Record<string, string> = {
  failed: 'Tests failed',
  ready_for_review: 'Ready for review',
  approved: 'Approved',
  rejected: 'Rejected',
};

function ControlNode({ data, selected }: NodeProps<ControlFlowNode>) {
  const value = data.config.value ?? data.config.default;
  const maxPorts = Math.max(data.inputs.length, data.outputs.length, 1);
  const portTop = (index: number) => 64 + index * 22;
  const group = data.kind.endsWith('_input') || data.kind.endsWith('_const')
    ? 'source'
    : data.kind.endsWith('_output')
      ? 'output'
      : 'logic';

  return (
    <div
      className={`control-node ${group} ${selected ? 'selected' : ''} ${data.isMatch ? '' : 'search-dimmed'}`}
      style={{ minHeight: 82 + (maxPorts - 1) * 22 }}
    >
      <span className="control-node-kind">{data.kind.replaceAll('_', ' ')}</span>
      <strong title={data.label}>{data.label}</strong>
      {value !== undefined && <code>{String(value)}</code>}
      {data.inputs.map((slot, index) => (
        <div className="port-label input" key={`in-${slot}`} style={{ top: portTop(index) }}>
          <Handle id={slot} position={Position.Left} type="target" />
          <span>{slot}</span>
        </div>
      ))}
      {data.outputs.map((slot, index) => (
        <div className="port-label output" key={`out-${slot}`} style={{ top: portTop(index) }}>
          <span>{slot}</span>
          <Handle id={slot} position={Position.Right} type="source" />
        </div>
      ))}
    </div>
  );
}

function buildFlow(graph: ControlGraph, search: string, selectedId: string | null) {
  const incoming = new Map<string, string[]>();
  const outgoing = new Map<string, string[]>();
  graph.blocks.forEach((block) => {
    incoming.set(block.id, []);
    outgoing.set(block.id, []);
  });
  graph.links.forEach((link) => {
    const inputs = incoming.get(link.target) ?? [];
    const outputs = outgoing.get(link.source) ?? [];
    if (!inputs.includes(link.target_slot)) inputs.push(link.target_slot);
    if (!outputs.includes(link.source_slot)) outputs.push(link.source_slot);
    incoming.set(link.target, inputs);
    outgoing.set(link.source, outputs);
  });
  const needle = search.trim().toLowerCase();
  const nodes: ControlFlowNode[] = graph.blocks.map((block) => ({
    id: block.id,
    type: 'control',
    position: { x: block.x, y: block.y },
    selected: block.id === selectedId,
    data: {
      label: block.label,
      kind: block.kind,
      config: block.config,
      inputs: incoming.get(block.id) ?? [],
      outputs: outgoing.get(block.id) ?? [],
      isMatch: !needle || `${block.id} ${block.label} ${block.kind}`.toLowerCase().includes(needle),
    },
  }));
  const edges: Edge[] = graph.links.map((link, index) => ({
    id: `edge-${index}-${link.source}-${link.target}`,
    source: link.source,
    sourceHandle: link.source_slot,
    target: link.target,
    targetHandle: link.target_slot,
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, width: 15, height: 15, color: '#5e8174' },
    style: { stroke: '#6f8f83', strokeWidth: 1.5 },
  }));
  return { nodes, edges };
}

function ControlStudio() {
  const { runId = '', view } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const activeView: StudioView = view === 'tests' || view === 'simulation' || view === 'graphics' || view === 'review' ? view : 'wiresheet';
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reviewer, setReviewer] = useState('');
  const [checks, setChecks] = useState([false, false, false, false]);
  const [manualAgentOpen, setManualAgentOpen] = useState(false);
  const agentOpen = manualAgentOpen || searchParams.get('agent') === '1';
  const closeAgent = useCallback(() => {
    setManualAgentOpen(false);
    if (searchParams.has('agent')) {
      const next = new URLSearchParams(searchParams);
      next.delete('agent');
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const run = useQuery({ queryKey: ['run', runId], queryFn: () => api.run(runId), enabled: Boolean(runId) });
  const graph = useQuery({ queryKey: ['graph', runId], queryFn: () => api.graph(runId), enabled: Boolean(runId) });
  const report = useQuery({ queryKey: ['report', runId], queryFn: () => api.report(runId), enabled: Boolean(runId) });
  const approve = useMutation({
    mutationFn: () => api.approve(runId, reviewer.trim()),
    onSuccess: (record) => {
      queryClient.setQueryData(['run', runId], record);
      queryClient.invalidateQueries({ queryKey: ['runs'] });
      queryClient.invalidateQueries({ queryKey: ['release-summary', runId] });
      toast.success(`Approved exact candidate ${record.id}`);
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Approval failed'),
  });

  if (run.isLoading || graph.isLoading || report.isLoading) return <StudioLoading />;
  if (!run.data || !graph.data || !report.data || run.isError || graph.isError || report.isError) {
    return <StudioError />;
  }

  const record = run.data;
  const typedGraph = graph.data;
  const testReport = report.data;
  const selected = typedGraph.blocks.find((block) => block.id === selectedId) ?? null;
  const passedScenarios = testReport.scenarios.filter((scenario) => scenario.passed).length;

  return (
    <div className="studio-page">
      <div className="studio-breadcrumbs">
        <Link to="/"><ArrowLeft aria-hidden="true" size={15} />Projects</Link>
        <ChevronRight aria-hidden="true" size={14} />
        <span>{record.job.site}</span><ChevronRight aria-hidden="true" size={14} />
        <strong>{record.job.equipment_name}</strong>
      </div>

      <header className="studio-header">
        <div>
          <div className="studio-title-line">
            <span className="equipment-avatar"><Blocks aria-hidden="true" size={20} /></span>
            <div><span className="eyebrow">CONTROL PROGRAM</span><h1>{record.job.name}</h1></div>
          </div>
          <p>{record.job.sequence.family.replaceAll('_', ' ')} · {record.job.sequence.version}</p>
        </div>
        <div className="studio-header-actions">
          <span className={`status-badge ${record.status}`}>{statusCopy[record.status] ?? record.status}</span>
          <button aria-expanded={agentOpen} aria-haspopup="dialog" className="secondary-inline agent-launch" onClick={() => setManualAgentOpen(true)} type="button">
            <Sparkles aria-hidden="true" size={16} />Ask AI engineer
          </button>
          <button className="secondary-inline" onClick={() => navigate(`/studio/${runId}/review`)} type="button">
            <FileCheck2 aria-hidden="true" size={16} />Review candidate
          </button>
        </div>
      </header>

      <div className="engineering-boundary" role="note">
        <ShieldCheck aria-hidden="true" size={17} />
        <strong>Offline engineering workspace</strong>
        <span>This candidate can be inspected, simulated, approved, and exported. It cannot command a live building.</span>
      </div>

      <section className="studio-stats" aria-label="Candidate summary">
        <StudioStat icon={<Blocks size={16} />} label="Logic blocks" value={String(typedGraph.blocks.length)} />
        <StudioStat icon={<GitCompareArrows size={16} />} label="Typed links" value={String(typedGraph.links.length)} />
        <StudioStat icon={<TestTube2 size={16} />} label="Scenarios" value={`${passedScenarios}/${testReport.scenarios.length}`} tone={testReport.passed ? 'pass' : 'fail'} />
        <StudioStat icon={<Bot size={16} />} label="Agent attempts" value={String(record.agent_attempts.length || 1)} />
        <StudioStat icon={<Hash size={16} />} label="Candidate digest" value={record.artifact_sha256.slice(0, 10)} mono />
      </section>

      <nav className="studio-tabs" aria-label="Control Studio views">
        <StudioTab active={activeView === 'wiresheet'} icon={<Blocks size={16} />} label="Wiresheet" onClick={() => navigate(`/studio/${runId}/wiresheet`)} />
        <StudioTab active={activeView === 'tests'} icon={<FlaskConical size={16} />} label="Test Lab" count={testReport.scenarios.length} onClick={() => navigate(`/studio/${runId}/tests`)} />
        <StudioTab active={activeView === 'simulation'} icon={<Waves size={16} />} label="Simulation" onClick={() => navigate(`/studio/${runId}/simulation`)} />
        <StudioTab active={activeView === 'graphics'} icon={<Brush size={16} />} label="Graphics" onClick={() => navigate(`/studio/${runId}/graphics`)} />
        <StudioTab active={activeView === 'review'} icon={<FileCheck2 size={16} />} label="Review & release" onClick={() => navigate(`/studio/${runId}/review`)} />
      </nav>

      {activeView === 'wiresheet' && (
        <WiresheetView
          graph={typedGraph}
          search={search}
          selected={selected}
          selectedId={selectedId}
          setSearch={setSearch}
          setSelectedId={setSelectedId}
        />
      )}
      {activeView === 'tests' && <Suspense fallback={<div className="route-loading">Opening deterministic test evidence…</div>}><TestLab report={testReport} run={record} /></Suspense>}
      {activeView === 'simulation' && <Suspense fallback={<div className="route-loading">Opening multi-fidelity simulation evidence…</div>}><SimulationLab run={record} /></Suspense>}
      {activeView === 'graphics' && <Suspense fallback={<div className="route-loading">Opening Graphics Studio…</div>}><GraphicsStudio runId={runId} /></Suspense>}
      {activeView === 'review' && (
        <ReviewRelease
          checks={checks}
          onApprove={() => approve.mutate()}
          approving={approve.isPending}
          record={record}
          report={testReport}
          reviewer={reviewer}
          setChecks={setChecks}
          setReviewer={setReviewer}
        />
      )}
      {agentOpen && <Suspense fallback={<div aria-live="polite" className="agent-opening" role="status">Opening the AI controls engineer…</div>}><AgentDrawer onClose={closeAgent} open run={record} /></Suspense>}
    </div>
  );
}

function StudioStat({ icon, label, value, tone = '', mono = false }: { icon: React.ReactNode; label: string; value: string; tone?: string; mono?: boolean }) {
  return <div className={`studio-stat ${tone}`}><span>{icon}{label}</span><strong className={mono ? 'mono' : ''}>{value}</strong></div>;
}

function StudioTab({ active, icon, label, count, onClick }: { active: boolean; icon: React.ReactNode; label: string; count?: number; onClick: () => void }) {
  return <button aria-current={active ? 'page' : undefined} className={active ? 'active' : ''} onClick={onClick} type="button">{icon}{label}{count !== undefined && <span>{count}</span>}</button>;
}

function WiresheetView({
  graph,
  search,
  selected,
  selectedId,
  setSearch,
  setSelectedId,
}: {
  graph: ControlGraph;
  search: string;
  selected: ControlGraph['blocks'][number] | null;
  selectedId: string | null;
  setSearch: (value: string) => void;
  setSelectedId: (value: string | null) => void;
}) {
  const { nodes, edges } = useMemo(() => buildFlow(graph, search, selectedId), [graph, search, selectedId]);
  const pointIds = new Set(graph.blocks.filter((block) => block.kind.endsWith('_input') || block.kind.endsWith('_output')).map((block) => block.id));
  const logic = graph.blocks.filter((block) => !pointIds.has(block.id));
  const matchingBlocks = graph.blocks.filter((block) => !search.trim() || `${block.id} ${block.label} ${block.kind}`.toLowerCase().includes(search.trim().toLowerCase()));

  return (
    <section className="wiresheet-workspace">
      <aside className="workspace-tree" aria-label="Program hierarchy">
        <div className="pane-heading"><ListTree size={16} /><strong>Program outline</strong></div>
        <label className="tree-search"><Search aria-hidden="true" size={14} /><span className="sr-only">Search blocks</span><input onChange={(event) => setSearch(event.target.value)} placeholder="Find a block…" value={search} /></label>
        <TreeGroup label="I/O and constants" blocks={matchingBlocks.filter((block) => pointIds.has(block.id))} selectedId={selectedId} onSelect={setSelectedId} />
        <TreeGroup label="Control logic" blocks={logic.filter((block) => matchingBlocks.includes(block))} selectedId={selectedId} onSelect={setSelectedId} />
      </aside>
      <div className="wiresheet-canvas" aria-label={`${graph.name} read-only wiresheet`}>
        <div className="canvas-toolbar">
          <div><span className="eyebrow">TYPED CONTROL GRAPH</span><strong>{graph.name}</strong></div>
          <span>{search ? `${matchingBlocks.length} matches` : `${graph.blocks.length} blocks · ${graph.links.length} links`}</span>
        </div>
        <ReactFlow
          edges={edges}
          fitView
          fitViewOptions={{ padding: 0.18 }}
          minZoom={0.08}
          nodes={nodes}
          nodesConnectable={false}
          nodesDraggable={false}
          nodeTypes={nodeTypes}
          onNodeClick={(_, node) => setSelectedId(node.id)}
          onPaneClick={() => setSelectedId(null)}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#d7dee2" gap={22} size={1} />
          <MiniMap className="studio-minimap" maskColor="rgba(244,246,247,.78)" nodeColor={(node) => node.data.kind?.toString().endsWith('_output') ? '#bb7045' : node.data.kind?.toString().endsWith('_input') ? '#3d8a70' : '#697985'} pannable zoomable />
          <Controls position="bottom-right" showInteractive={false} />
        </ReactFlow>
      </div>
      <aside className="node-inspector" aria-label="Block inspector">
        <div className="pane-heading"><SlidersHorizontal size={16} /><strong>Inspector</strong></div>
        {selected ? <Inspector graph={graph} block={selected} /> : (
          <div className="inspector-empty"><Info size={20} /><strong>Select a block</strong><span>Inspect typed slots, drivers, destinations, and configuration.</span></div>
        )}
      </aside>
    </section>
  );
}

function TreeGroup({ label, blocks, selectedId, onSelect }: { label: string; blocks: ControlGraph['blocks']; selectedId: string | null; onSelect: (id: string) => void }) {
  return (
    <div className="tree-group">
      <div><strong>{label}</strong><span>{blocks.length}</span></div>
      {blocks.slice(0, 250).map((block) => <button className={selectedId === block.id ? 'active' : ''} key={block.id} onClick={() => onSelect(block.id)} type="button"><span>{block.label}</span><small>{block.kind.replaceAll('_', ' ')}</small></button>)}
      {blocks.length > 250 && <small className="tree-limit">Refine search to inspect {blocks.length - 250} more blocks.</small>}
    </div>
  );
}

function Inspector({ graph, block }: { graph: ControlGraph; block: ControlGraph['blocks'][number] }) {
  const incoming = graph.links.filter((link) => link.target === block.id);
  const outgoing = graph.links.filter((link) => link.source === block.id);
  return (
    <div className="inspector-content">
      <span className="eyebrow">{block.kind.replaceAll('_', ' ')}</span>
      <h2>{block.label}</h2><code>{block.id}</code>
      <InspectorSection label="Inputs" empty="No driven inputs">
        {incoming.map((link) => <div className="slot-row" key={`${link.source}-${link.target_slot}`}><b>{link.target_slot}</b><span>← {link.source}.{link.source_slot}</span></div>)}
      </InspectorSection>
      <InspectorSection label="Outputs" empty="No downstream links">
        {outgoing.map((link) => <div className="slot-row" key={`${link.target}-${link.source_slot}`}><b>{link.source_slot}</b><span>→ {link.target}.{link.target_slot}</span></div>)}
      </InspectorSection>
      <InspectorSection label="Configuration" empty="No explicit configuration">
        {Object.entries(block.config).map(([key, value]) => <div className="config-row" key={key}><span>{key}</span><code>{JSON.stringify(value)}</code></div>)}
      </InspectorSection>
    </div>
  );
}

function InspectorSection({ label, empty, children }: { label: string; empty: string; children: React.ReactNode }) {
  const hasChildren = Array.isArray(children) ? children.length > 0 : Boolean(children);
  return <section className="inspector-section"><h3>{label}</h3>{hasChildren ? children : <span className="muted">{empty}</span>}</section>;
}

function ReviewRelease({ checks, onApprove, approving, record, report, reviewer, setChecks, setReviewer }: { checks: boolean[]; onApprove: () => void; approving: boolean; record: RunDetail; report: TestReport; reviewer: string; setChecks: (checks: boolean[]) => void; setReviewer: (value: string) => void }) {
  const release = useQuery({ queryKey: ['release-summary', record.id], queryFn: () => api.releaseSummary(record.id) });
  const summary = release.data;
  const allChecked = checks.every(Boolean);
  const canApprove = record.status === 'ready_for_review' && report.passed && summary?.integrity.verified === true && allChecked && reviewer.trim().length >= 2 && !approving;
  const changeTotal = record.changes.added.length + record.changes.modified.length + record.changes.removed.length;
  const checklist = [
    ['I reviewed the typed graph and all external point mappings.', `${record.job.points.length} points · ${record.changes.added.length} additions`],
    ['I reviewed deterministic behavior and every failed or passing assertion.', `${report.scenarios.length} scenarios · ${report.passed ? 'all pass' : 'approval blocked'}`],
    ['I reviewed target and environment limitations for this artifact.', record.target_artifact_kind || 'Target package recorded by backend'],
    ['I understand this approval signs the exact immutable candidate digest.', record.artifact_sha256],
  ];
  return (
    <div className="review-layout">
      <div className="review-main">
        <section className="review-card">
          <div className="panel-title"><div><span className="eyebrow">SEMANTIC CHANGESET</span><h2>What will enter the station</h2></div><span className="change-total">{changeTotal} changes</span></div>
          <div className="change-columns">
            <ChangeColumn label="Added" tone="added" values={record.changes.added} />
            <ChangeColumn label="Modified" tone="modified" values={record.changes.modified} />
            <ChangeColumn label="Removed" tone="removed" values={record.changes.removed} />
          </div>
        </section>
        <section className="review-card deliverable-review">
          <div className="panel-title"><div><span className="eyebrow">SIGNED HANDOFF CONTENTS</span><h2>Exactly what the contractor receives</h2></div>{summary?.integrity.verified ? <span className="integrity-chip"><PackageCheck size={14} />Integrity verified</span> : <FileArchive size={20} />}</div>
          {release.isLoading && <div className="release-loading"><div className="studio-state-spinner" />Verifying the retained release contract…</div>}
          {release.isError && <div className="release-error"><CircleAlert size={16} />The server could not verify the release contract. Approval remains unavailable.</div>}
          {summary && <DeliverableReview summary={summary} />}
        </section>
        <section className="review-card">
          <div className="panel-title"><div><span className="eyebrow">ENGINEER CHECKLIST</span><h2>Review the evidence, then sign</h2></div><ShieldCheck size={20} /></div>
          <div className="review-checklist">
            {checklist.map(([label, detail], index) => <label key={label}><input checked={checks[index]} onChange={(event) => setChecks(checks.map((value, checkIndex) => checkIndex === index ? event.target.checked : value))} type="checkbox" /><span><strong>{label}</strong><small className={index === 3 ? 'mono' : ''}>{detail}</small></span></label>)}
          </div>
        </section>
      </div>
      <aside className="release-card">
        <span className="eyebrow">RELEASE DECISION</span>
        <h2>{record.status === 'approved' ? 'Candidate approved' : 'Human sign-off required'}</h2>
        <p>BACTalk revalidates the artifact and evidence on the server. UI state alone can never authorize export.</p>
        <div className={`release-gate ${report.passed ? 'pass' : 'fail'}`}>{report.passed ? <CheckCircle2 size={18} /> : <CircleAlert size={18} />}<span><strong>{report.passed ? 'Behavior gate passed' : 'Behavior gate blocked'}</strong><small>{report.scenarios.length} independent scenarios retained</small></span></div>
        {summary && <div className={`release-gate ${summary.integrity.verified ? 'pass' : 'fail'}`}>{summary.integrity.verified ? <PackageCheck size={18} /> : <CircleAlert size={18} />}<span><strong>{summary.integrity.verified ? 'Artifact integrity verified' : 'Artifact integrity blocked'}</strong><small>{summary.behavior.passed_assertion_count}/{summary.behavior.assertion_count} assertions passed</small></span></div>}
        <div className="digest-box"><span>SHA-256 candidate</span><code>{record.artifact_sha256}</code></div>
        {record.approval ? (
          <div className="approved-box"><CheckCircle2 size={22} /><div><strong>Approved by {record.approval.reviewer}</strong><span>{new Date(record.approval.approved_at).toLocaleString()}</span></div></div>
        ) : (
          <>
            <label className="reviewer-field"><span>Reviewer name</span><input onChange={(event) => setReviewer(event.target.value)} placeholder="Licensed engineer or authorized reviewer" value={reviewer} /></label>
            <button className="approve-button" disabled={!canApprove} onClick={onApprove} type="button"><ShieldCheck size={17} />{approving ? 'Verifying exact artifact…' : 'Approve exact candidate'}</button>
          </>
        )}
        <a aria-disabled={!summary?.downloads.available} className={`export-button ${!summary?.downloads.available ? 'disabled' : ''}`} href={summary?.downloads.target_url ?? undefined}><Download size={16} />Download deployable target</a>
        <a aria-disabled={!summary?.downloads.available} className={`export-button bundle ${!summary?.downloads.available ? 'disabled' : ''}`} href={summary?.downloads.review_bundle_url ?? undefined}><FileArchive size={16} />Download complete review bundle</a>
        <small className="release-footnote">Manual import through licensed Niagara Workbench remains required.</small>
      </aside>
    </div>
  );
}

function DeliverableReview({ summary }: { summary: ReleaseSummary }) {
  const coverage = Object.entries(summary.deliverables.coverage);
  const totalBytes = summary.deliverables.artifacts.reduce((total, artifact) => total + artifact.bytes, 0);
  return <div className="deliverable-review-body">
    <div className="deliverable-overview">
      <div><span>Target</span><strong>{summary.target.filename || summary.target.artifact_kind.replaceAll('_', ' ')}</strong></div>
      <div><span>Review artifacts</span><strong>{summary.deliverables.artifacts.length}</strong></div>
      <div><span>Package payload</span><strong>{formatBytes(totalBytes)}</strong></div>
      <div><span>Deployment posture</span><strong className={summary.deliverables.deployment_ready ? 'good' : 'warn'}>{summary.deliverables.deployment_ready ? 'Qualified' : 'Runtime gates open'}</strong></div>
    </div>
    <div className="coverage-grid" aria-label="Deliverable coverage">{coverage.map(([name, item]) => { const status = coverageStatus(item); return <div className={status} key={name}><span>{name.replaceAll('_', ' ')}</span><strong>{status === 'qualified' ? 'Qualified' : status === 'compiled' ? 'Target compiled' : status === 'emitted' ? 'Review artifact' : 'Not emitted'}</strong><small>{item.target || 'No target declared'}</small></div>; })}</div>
    <details className="artifact-inventory" open><summary><span>Artifact inventory</span><strong>{summary.deliverables.artifacts.length} files · {formatBytes(totalBytes)}</strong></summary><div aria-label="Signed artifact inventory" tabIndex={0}><table><thead><tr><th>File</th><th>Size</th><th>SHA-256</th></tr></thead><tbody>{summary.deliverables.artifacts.map((artifact) => <tr key={artifact.path}><th>{artifact.path}</th><td>{formatBytes(artifact.bytes)}</td><td><code title={artifact.sha256}>{artifact.sha256}</code></td></tr>)}</tbody></table></div></details>
    <details className="release-blockers" open={!summary.deliverables.deployment_ready}><summary><span>Qualification boundaries</span><strong>{summary.deliverables.blocking_gates.length} open</strong></summary>{summary.deliverables.blocking_gates.length ? <ol>{summary.deliverables.blocking_gates.map((gate) => <li key={gate}>{gate}</li>)}</ol> : <p>No declared deployment blockers remain in this manifest.</p>}</details>
    {!summary.safety.approval_authorizes_live_deployment && <div className="approval-boundary"><ShieldCheck size={16} /><span><strong>Approval signs this engineering package only.</strong> It does not authorize a live building write or claim licensed-runtime qualification.</span></div>}
  </div>;
}

function coverageStatus(item: ReleaseSummary['deliverables']['coverage'][string]): 'qualified' | 'compiled' | 'emitted' | 'missing' {
  if (item.licensed_runtime_qualified) return 'qualified';
  if (item.target_compiled) return 'compiled';
  if (item.emitted) return 'emitted';
  return 'missing';
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function ChangeColumn({ label, tone, values }: { label: string; tone: string; values: string[] }) {
  return <div className={`change-column ${tone}`}><header><span>{label}</span><strong>{values.length}</strong></header><div aria-label={`${label} changes`} tabIndex={0}>{values.slice(0, 24).map((value) => <code key={value}>{value}</code>)}{values.length === 0 && <span className="muted">None</span>}{values.length > 24 && <small>+ {values.length - 24} more in signed changeset</small>}</div></div>;
}

function StudioLoading() {
  return <div className="studio-state"><div className="studio-state-spinner" /><strong>Opening the engineering workspace</strong><span>Loading the exact candidate, graph, and test evidence…</span></div>;
}

function StudioError() {
  return <div className="studio-state error"><CircleAlert size={28} /><strong>This candidate could not be opened</strong><span>The graph or evidence endpoint did not return a valid product contract.</span><Link to="/">Return to the project cockpit</Link></div>;
}

export { ControlStudio };
