import { useState } from 'react';
import { useMutation, useQueries, useQuery } from '@tanstack/react-query';
import {
  Blocks,
  BookOpen,
  Box,
  Braces,
  Brush,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  ClipboardCheck,
  Code2,
  Cpu,
  FileArchive,
  FileSpreadsheet,
  FileText,
  FlaskConical,
  Layers3,
  Library,
  Network,
  PackageCheck,
  Search,
  ServerCog,
  ShieldCheck,
} from 'lucide-react';
import { Link } from 'react-router-dom';

import { api, type ArtifactState, type Catalog, type Deliverables, type RunSummary } from '../../api/client';
import './workspace-pages.css';

export function StudioIndex() {
  const runs = useQuery({ queryKey: ['runs'], queryFn: api.runs });
  return <RunWorkspace heading="Control Studio" eyebrow="PROGRAM WORKSPACES" description="Open any retained candidate to inspect its typed graph, tests, simulations, graphics, and release evidence." runs={runs.data ?? []} loading={runs.isLoading} mode="studio" />;
}

export function SimulationIndex() {
  const runs = useQuery({ queryKey: ['runs'], queryFn: api.runs });
  return <RunWorkspace heading="Simulation Center" eyebrow="MULTI-FIDELITY EVIDENCE" description="Move from deterministic logic tests to protocol emulation, dynamic building physics, and licensed-runtime qualification." runs={runs.data ?? []} loading={runs.isLoading} mode="simulation" />;
}

function RunWorkspace({ heading, eyebrow, description, runs, loading, mode }: { heading: string; eyebrow: string; description: string; runs: RunSummary[]; loading: boolean; mode: 'studio' | 'simulation' }) {
  return (
    <div className="workspace-index-page">
      <header className="workspace-page-heading"><div><span className="eyebrow">{eyebrow}</span><h1>{heading}</h1><p>{description}</p></div></header>
      {loading ? <WorkspaceLoading /> : <section className="run-workspace-grid" aria-label={heading}>{runs.map((run) => (
        <Link className="run-workspace-card" key={run.id} to={`/studio/${run.id}/${mode === 'simulation' ? 'simulation' : 'wiresheet'}`}>
          <header><span className="run-workspace-icon">{mode === 'simulation' ? <FlaskConical size={19} /> : <Blocks size={19} />}</span><div><span className="eyebrow">{run.job.site}</span><h2>{run.job.equipment_name}</h2></div><ChevronRight size={16} /></header>
          <p>{run.job.name}</p>
          {mode === 'simulation' ? <div className="qualification-lanes"><Lane label="Typed" active={run.status !== 'failed'} /><Lane label="BACnet" active={Boolean(run.bacnet_lab_manifest_path)} /><Lane label="BOPTEST" active={Boolean(run.boptest_verification_path)} /><Lane label="Niagara" active={false} /></div> : <div className="run-workspace-meta"><span>{run.job.sequence.family.replaceAll('_', ' ')}</span><code>{run.artifact_sha256.slice(0, 10)}</code></div>}
          <footer><span className={`status-badge ${run.status}`}>{run.status.replaceAll('_', ' ')}</span><span>{mode === 'simulation' ? 'Open evidence' : 'Open program'}</span></footer>
        </Link>
      ))}</section>}
    </div>
  );
}

function Lane({ label, active }: { label: string; active: boolean }) {
  return <span className={active ? 'active' : ''}><i />{label}</span>;
}

type LibraryDefinition = {
  key: keyof Awaited<ReturnType<typeof api.libraryCatalogs>>;
  name: string;
  detail: string;
  icon: React.ReactNode;
  color: string;
};

const libraryDefinitions: LibraryDefinition[] = [
  { key: 'g36', name: 'Guideline 36 Controls', detail: 'AHUs, terminal units, zones, and fan coils', icon: <BookOpen size={20} />, color: 'green' },
  { key: 'plant', name: 'LBNL Plant Controls', detail: 'Pumps, staging, heat pumps, HRCs, and reset logic', icon: <Cpu size={20} />, color: 'blue' },
  { key: 'faults', name: 'Open Control Faults', detail: 'Vector-verified FDD and commissioning rules', icon: <ShieldCheck size={20} />, color: 'amber' },
  { key: 'aixocat', name: 'AixOCAT Patterns', detail: 'Allowlisted IEC 61131-3 control patterns', icon: <Braces size={20} />, color: 'purple' },
  { key: 'niagara', name: 'Niagara ProgramObjects', detail: 'Pinned Niagara-native reference templates', icon: <Code2 size={20} />, color: 'slate' },
  { key: 'ctrlFlow', name: 'HVAC System Configurator', detail: 'Conditional system choices from LBNL ctrl-flow', icon: <Layers3 size={20} />, color: 'blue' },
];

export function LibraryWorkspace() {
  const catalogs = useQuery({ queryKey: ['library-catalogs'], queryFn: api.libraryCatalogs });
  const [selected, setSelected] = useState<LibraryDefinition['key']>('g36');
  const [search, setSearch] = useState('');
  if (catalogs.isLoading) return <WorkspaceLoading />;
  if (!catalogs.data || catalogs.isError) return <WorkspaceError message="The installed control libraries could not be indexed." />;
  const definition = libraryDefinitions.find((item) => item.key === selected) ?? libraryDefinitions[0];
  const catalog = catalogs.data[selected];
  const rows = catalogRows(catalog);
  const filtered = rows.filter((row) => JSON.stringify(row).toLowerCase().includes(search.trim().toLowerCase()));
  return (
    <div className="workspace-index-page library-workspace">
      <header className="workspace-page-heading"><div><span className="eyebrow">CONTROL KNOWLEDGE</span><h1>Library Workspace</h1><p>Inspect what the agent can actually use, the source license, and the difference between cataloged references and product-wired controls.</p></div><span className="workspace-proof"><PackageCheck size={17} />Installed and API-bound</span></header>
      <section className="library-stats" aria-label="Installed library summary">{libraryDefinitions.map((item) => { const value = catalogs.data[item.key]; return <button className={`${item.color} ${selected === item.key ? 'active' : ''}`} key={item.key} onClick={() => { setSelected(item.key); setSearch(''); }} type="button"><span>{item.icon}</span><div><strong>{catalogCount(value).toLocaleString()}</strong><small>{item.name}</small></div></button>; })}</section>
      <div className="library-browser">
        <aside className="library-nav"><div className="pane-heading"><Library size={16} /><strong>Installed sources</strong></div>{libraryDefinitions.map((item) => <button className={selected === item.key ? 'active' : ''} key={item.key} onClick={() => setSelected(item.key)} type="button"><span className={`library-dot ${item.color}`} /> <span><strong>{item.name}</strong><small>{item.detail}</small></span></button>)}</aside>
        <section className="library-results">
          <header><div><span className="eyebrow">{definition.name}</span><h2>{stringValue(catalog.source) || definition.detail}</h2><p>{stringValue(catalog.scope) || definition.detail}</p></div><div className="license-chip"><ShieldCheck size={14} /><span><small>License</small><strong>{stringValue(catalog.license) || 'Source-specific'}</strong></span></div></header>
          {selected === 'ctrlFlow' ? <CtrlFlowConfigurator catalog={catalog} /> : <><label className="library-search"><Search size={15} /><span className="sr-only">Search current library</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={`Search ${rows.length.toLocaleString()} records…`} /></label>
          <div aria-label={`${definition.name} records`} className="library-table" tabIndex={0}><table><thead><tr><th>Name / identifier</th><th>Family</th><th>Product status</th><th>Source</th></tr></thead><tbody>{filtered.slice(0, 500).map((row, index) => <tr key={stringValue(row.id) || stringValue(row.name) || index}><th><strong>{stringValue(row.name) || stringValue(row.id) || `Record ${index + 1}`}</strong><code>{stringValue(row.id) || stringValue(row.relative_path)}</code></th><td>{stringValue(row.family) || stringValue(row.group) || stringValue(row.declaration) || '—'}</td><td><span className={`library-status ${libraryStatus(row)}`}>{libraryStatusLabel(row)}</span></td><td>{stringValue(row.relative_path) || stringValue(row.method) || stringValue(row.file) || 'Pinned source'}</td></tr>)}</tbody></table>{filtered.length > 500 && <div className="table-limit">Showing 500 of {filtered.length.toLocaleString()} matches. Refine the search to inspect more.</div>}{filtered.length === 0 && <div className="table-limit">No records match this search.</div>}</div></>}
        </section>
      </div>
    </div>
  );
}

function CtrlFlowConfigurator({ catalog }: { catalog: Catalog }) {
  const templates = catalogRows(catalog);
  const [templateId, setTemplateId] = useState(() => stringValue(templates[0]?.id));
  const [selections, setSelections] = useState<Record<string, unknown>>({});
  const [pointsFile, setPointsFile] = useState<File | null>(null);
  const [sequenceFile, setSequenceFile] = useState<File | null>(null);
  const [reviewer, setReviewer] = useState('');
  const [reviewDecisions, setReviewDecisions] = useState<Record<string, { disposition: 'approve' | 'reject' | 'resolve'; selected_point?: string; replacement_text?: string; note?: string }>>({});
  const configuration = useQuery({
    queryKey: ['ctrl-flow-configuration', templateId, selections],
    queryFn: () => api.ctrlFlowConfigure(templateId, selections),
    enabled: Boolean(templateId),
  });
  const effectiveSelections = configuration.data?.selections ?? selections;
  const brief = useMutation({ mutationFn: () => api.ctrlFlowProgrammingBrief(templateId, effectiveSelections) });
  const reconciliation = useMutation({ mutationFn: () => {
    if (!pointsFile) throw new Error('Choose a points CSV or XLSX file first.');
    return api.inspectCtrlFlowPoints(templateId, effectiveSelections, pointsFile);
  } });
  const sequenceReconciliation = useMutation({ mutationFn: () => {
    if (!sequenceFile) throw new Error('Choose a sequence document first.');
    return api.inspectCtrlFlowSequence(templateId, effectiveSelections, sequenceFile);
  } });
  const candidates = sequenceReconciliation.data?.requirement_candidates;
  const reviewItems = candidates ? [
    ...candidates.quantities.map((item) => ({ id: item.id, group: 'quantity' as const, label: `${item.kind.replaceAll('-', ' ')} · ${item.canonical.value} ${item.canonical.unit}`, clause: item.source.clause, pointCandidates: item.input_point_candidates, needsPoint: ['threshold', 'parameter'].includes(item.kind), unresolved: false })),
    ...candidates.actions.map((item) => ({ id: item.id, group: 'action' as const, label: `${item.verb} ${item.subject}`, clause: item.source.clause, pointCandidates: item.point_candidates, needsPoint: true, unresolved: false })),
    ...candidates.policies.map((item) => ({ id: item.id, group: 'policy' as const, label: item.policy.replaceAll('-', ' '), clause: item.source.clause, pointCandidates: [] as string[], needsPoint: false, unresolved: false })),
    ...candidates.unresolved.map((item) => ({ id: item.id, group: 'unresolved' as const, label: `${item.kind.replaceAll('-', ' ')} · “${item.text}”`, clause: item.source.clause, pointCandidates: [] as string[], needsPoint: false, unresolved: true })),
  ] : [];
  const sequenceReview = useMutation({ mutationFn: () => {
    if (!sequenceFile || !candidates) throw new Error('Inspect a sequence before review.');
    return api.approveCtrlFlowSequenceRequirements(templateId, effectiveSelections, sequenceFile, {
      candidate_digest: candidates.candidate_digest,
      reviewer,
      decisions: reviewItems.map((item) => ({ candidate_id: item.id, ...reviewDecisions[item.id] })),
    });
  } });
  const updateReview = (id: string, patch: Partial<(typeof reviewDecisions)[string]>) => setReviewDecisions((current) => ({ ...current, [id]: { ...current[id], ...patch } as (typeof reviewDecisions)[string] }));
  const reviewComplete = reviewer.trim().length >= 2 && reviewItems.length > 0 && reviewItems.every((item) => {
    const decision = reviewDecisions[item.id];
    if (!decision) return false;
    if (item.unresolved) return decision.disposition === 'resolve' && Boolean(decision.replacement_text?.trim());
    if (decision.disposition === 'reject') return Boolean(decision.note?.trim());
    if (decision.disposition !== 'approve') return false;
    return !item.needsPoint || item.pointCandidates.length === 1 || Boolean(decision.selected_point);
  });
  const chooseTemplate = (value: string) => {
    setTemplateId(value);
    setSelections({});
    setPointsFile(null);
    setSequenceFile(null);
    setReviewer('');
    setReviewDecisions({});
    brief.reset();
    reconciliation.reset();
    sequenceReconciliation.reset();
    sequenceReview.reset();
  };
  const chooseValue = (path: string, value: unknown) => {
    setSelections({ ...(configuration.data?.selections ?? selections), [path]: value });
    brief.reset();
    reconciliation.reset();
    sequenceReconciliation.reset();
    setReviewDecisions({});
    sequenceReview.reset();
  };
  return <div className="ctrl-flow-configurator">
    <aside className="ctrl-flow-controls">
      <div className="ctrl-flow-boundary"><Layers3 size={18} /><span><strong>System design, evaluated by LBNL semantics</strong><small>Selections change the point and test contract. Nothing here writes to a building.</small></span></div>
      <label><span>System template</span><select value={templateId} onChange={(event) => chooseTemplate(event.target.value)}>{templates.map((template) => <option key={stringValue(template.id)} value={stringValue(template.id)}>{stringValue(template.name) || stringValue(template.id)}</option>)}</select></label>
      <div className="ctrl-flow-fields" aria-label="Applicable system choices">
        {configuration.isLoading && <div className="ctrl-flow-state">Evaluating applicable choices…</div>}
        {configuration.isError && <div className="ctrl-flow-state error">{configuration.error.message}</div>}
        {configuration.data?.fields.map((field) => <label key={field.selection_path}><span>{field.name}<small>{field.instance_path}</small></span>{field.choices ? <select value={String(selections[field.selection_path] ?? field.value)} onChange={(event) => chooseValue(field.selection_path, event.target.value)}>{field.choices.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}</select> : <select value={String(selections[field.selection_path] ?? field.value)} onChange={(event) => chooseValue(field.selection_path, event.target.value === 'true')}><option value="true">Yes</option><option value="false">No</option></select>}</label>)}
      </div>
      <button className="ctrl-flow-primary" disabled={brief.isPending || configuration.isFetching} onClick={() => brief.mutate()} type="button">{brief.isPending ? 'Building engineering brief…' : 'Generate programming brief'}<ChevronRight size={15} /></button>
      <div className="ctrl-flow-upload"><FileSpreadsheet size={18} /><label><strong>{pointsFile?.name || 'Contractor points list'}</strong><small>CSV or XLSX · checked against this design</small><input accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event) => { setPointsFile(event.target.files?.[0] ?? null); reconciliation.reset(); }} type="file" /></label><button disabled={!pointsFile || reconciliation.isPending} onClick={() => reconciliation.mutate()} type="button">{reconciliation.isPending ? 'Checking…' : 'Check points'}</button></div>
      <div className="ctrl-flow-upload ctrl-flow-sequence-upload"><FileText size={18} /><label><strong>{sequenceFile?.name || 'Sequence of operations'}</strong><small>TXT, MD, JSON, DOCX, or PDF · scenario coverage</small><input accept=".txt,.md,.json,.docx,.pdf,text/plain,text/markdown,application/json,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(event) => { setSequenceFile(event.target.files?.[0] ?? null); setReviewDecisions({}); sequenceReconciliation.reset(); sequenceReview.reset(); }} type="file" /></label><button disabled={!sequenceFile || sequenceReconciliation.isPending} onClick={() => sequenceReconciliation.mutate()} type="button">{sequenceReconciliation.isPending ? 'Checking…' : 'Check sequence'}</button></div>
    </aside>
    <section className="ctrl-flow-results">
      {!brief.data && !brief.isError && <div className="ctrl-flow-empty"><Network size={28} /><strong>Configure the physical system</strong><p>Generate a traceable component, point, controller, and qualification contract before any code is proposed.</p></div>}
      {brief.isError && <div className="ctrl-flow-empty error"><CircleAlert size={28} /><strong>Brief generation stopped</strong><p>{brief.error.message}</p></div>}
      {brief.data && <>
        <header><div><span className="eyebrow">PROGRAMMING BRIEF</span><h3>{brief.data.design_binding.equipment_family.replaceAll('.', ' / ')}</h3><code>{brief.data.design_binding.controller_id}</code></div><span className="ctrl-flow-status"><CheckCircle2 size={14} />Engineering brief ready</span></header>
        <div className="ctrl-flow-metrics"><div><strong>{brief.data.components.length}</strong><span>Selected components</span></div><div><strong>{brief.data.point_requirements.required_count}</strong><span>Required points</span></div><div><strong>{brief.data.qualification_plan.scenario_count}</strong><span>Test scenarios</span></div><div><strong>{brief.data.capability_alignment.candidate_packs.length}</strong><span>Candidate packs</span></div></div>
        <div className="ctrl-flow-detail-grid"><article aria-label="Selected physical components" tabIndex={0}><h4>Physical components</h4><ul>{brief.data.components.map((component) => <li key={component.id}><span>{component.id.replaceAll('-', ' ')}</span><small>{component.type} · {component.quantity}</small></li>)}</ul></article><article aria-label="Required test coverage" tabIndex={0}><h4>Required test coverage</h4><ul>{brief.data.qualification_plan.scenarios.map((scenario) => <li key={scenario.id}><span>{scenario.title}</span><small>{scenario.status.replaceAll('-', ' ')}</small></li>)}</ul></article></div>
        <details className="ctrl-flow-points"><summary>{brief.data.point_requirements.required_count} required + {brief.data.point_requirements.conditional_count} conditional points</summary><div>{brief.data.point_requirements.points.map((point) => <span key={point.id}><strong>{point.id}</strong><small>{point.role} · {point.units || point.data_type}</small></span>)}</div></details>
        <details className="ctrl-flow-blockers" open><summary>Why this is not deployable yet</summary><ol>{brief.data.release_blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ol></details>
      </>}
      {reconciliation.data && <div className={`ctrl-flow-reconciliation ${reconciliation.data.ready_for_sequence_reconciliation ? 'ready' : 'blocked'}`}><header>{reconciliation.data.ready_for_sequence_reconciliation ? <CheckCircle2 size={18} /> : <CircleAlert size={18} />}<div><strong>{reconciliation.data.ready_for_sequence_reconciliation ? 'Point contract satisfied' : 'Point contract blocked'}</strong><span>{reconciliation.data.matched_requirement_count}/{reconciliation.data.required_point_count} required points matched · {reconciliation.data.blocking_issues.length} blocking issues</span></div></header>{reconciliation.data.missing_required.length > 0 && <p>Missing: {reconciliation.data.missing_required.join(' · ')}</p>}{reconciliation.data.unit_conversions.length > 0 && <p>{reconciliation.data.unit_conversions.length} explicit unit converter(s) required.</p>}</div>}
      {reconciliation.isError && <div className="ctrl-flow-reconciliation blocked"><header><CircleAlert size={18} /><div><strong>Points inspection stopped</strong><span>{reconciliation.error.message}</span></div></header></div>}
      {sequenceReconciliation.data && <div className={`ctrl-flow-sequence-result ${sequenceReconciliation.data.language_coverage_complete ? 'ready' : 'blocked'}`}>
        <header>{sequenceReconciliation.data.language_coverage_complete ? <CheckCircle2 size={18} /> : <CircleAlert size={18} />}<div><strong>{sequenceReconciliation.data.language_coverage_complete ? 'All required scenario facets mentioned' : 'Sequence gaps found'}</strong><span>{sequenceReconciliation.data.all_facets_mentioned_count}/{sequenceReconciliation.data.scenario_count} scenarios mention every required facet · {sequenceReconciliation.data.missing_facet_count} missing facets</span></div></header>
        <p><b>{sequenceReconciliation.data.source_document.filename}</b> · Phrase coverage only. Semantic validation and engineer review are still required.</p>
        <div aria-label="Sequence scenario coverage" className="ctrl-flow-sequence-matrix" tabIndex={0}>{sequenceReconciliation.data.scenarios.map((scenario) => <details key={scenario.id}><summary><span>{scenario.title}</span><b className={scenario.coverage_status}>{scenario.coverage_status.replaceAll('-', ' ')}</b></summary><div><small>{scenario.mentioned_facet_count}/{scenario.facet_count} facets mentioned</small>{scenario.missing_facets.length > 0 ? <p>Missing: {scenario.missing_facets.join(' · ')}</p> : <p>Every deterministic phrase facet has evidence; engineering meaning is not yet approved.</p>}</div></details>)}</div>
        <section className="ctrl-flow-requirements" aria-label="Structured requirement candidates">
          <header><strong>Structured requirement candidates</strong><span>Unapproved · never executable from text alone</span></header>
          <div><span><b>{sequenceReconciliation.data.requirement_candidates.threshold_count}</b> Thresholds</span><span><b>{sequenceReconciliation.data.requirement_candidates.duration_count}</b> Durations</span><span><b>{sequenceReconciliation.data.requirement_candidates.action_count}</b> Actions</span><span><b>{sequenceReconciliation.data.requirement_candidates.unresolved_count}</b> Unresolved</span></div>
          {(sequenceReconciliation.data.requirement_candidates.quantities.length > 0 || sequenceReconciliation.data.requirement_candidates.actions.length > 0) && <details><summary>Review normalized math and actions</summary><ul>{sequenceReconciliation.data.requirement_candidates.quantities.map((candidate) => <li key={candidate.id}><span><b>{candidate.kind.replaceAll('-', ' ')}</b>{candidate.comparison ? `${candidate.comparison} ` : ''}{candidate.canonical.value} {candidate.canonical.unit}{candidate.timing_relation ? ` · ${candidate.timing_relation}` : ''}</span><small>{candidate.input_point_candidates.join(' / ') || candidate.point_binding_status}</small></li>)}{sequenceReconciliation.data.requirement_candidates.actions.map((candidate) => <li key={candidate.id}><span><b>action</b>{candidate.verb} {candidate.subject}</span><small>{candidate.point_candidates.join(' / ') || candidate.point_binding_status}</small></li>)}</ul></details>}
          {sequenceReconciliation.data.requirement_candidates.unresolved.length > 0 && <details open><summary>Resolve vague or external language</summary><ul>{sequenceReconciliation.data.requirement_candidates.unresolved.map((item) => <li key={item.id}><span><b>{item.kind.replaceAll('-', ' ')}</b>“{item.text}”</span><small>{item.blocking_reason}</small></li>)}</ul></details>}
        </section>
        {reviewItems.length > 0 && <section className="ctrl-flow-review" aria-label="Engineer requirement review">
          <header><div><strong>Engineer requirement review</strong><span>Every candidate needs an explicit decision. Nothing is pre-approved.</span></div><ShieldCheck size={17} /></header>
          <label><span>Reviewer</span><input aria-label="Requirement reviewer" onChange={(event) => setReviewer(event.target.value)} placeholder="Name or authenticated identity" value={reviewer} /></label>
          <div className="ctrl-flow-review-list">{reviewItems.map((item) => { const decision = reviewDecisions[item.id]; const availablePoints = sequenceReconciliation.data.requirement_candidates.available_review_points; const compatiblePoints = item.pointCandidates.length > 0 ? availablePoints.filter((point) => item.pointCandidates.includes(point.id)) : availablePoints.filter((point) => item.group === 'action' ? ['command', 'alarm'].includes(point.role) : ['sensor', 'status', 'setpoint'].includes(point.role)); return <article key={item.id}><div><b>{item.group}</b><strong>{item.label}</strong><small>{item.clause}</small></div><select aria-label={`Decision for ${item.label}`} value={decision?.disposition ?? ''} onChange={(event) => { const disposition = event.target.value as 'approve' | 'reject' | 'resolve'; updateReview(item.id, { disposition, selected_point: undefined, replacement_text: undefined, note: undefined }); }}><option value="">Choose…</option>{item.unresolved ? <option value="resolve">Resolve in revised source</option> : <><option value="approve">Approve candidate</option><option value="reject">Reject candidate</option></>}</select>{decision?.disposition === 'approve' && item.needsPoint && item.pointCandidates.length !== 1 && <select aria-label={`Point for ${item.label}`} value={decision.selected_point ?? ''} onChange={(event) => updateReview(item.id, { selected_point: event.target.value || undefined })}><option value="">Select point…</option>{compatiblePoints.map((point) => <option key={point.id} value={point.id}>{point.id} · {point.role}</option>)}</select>}{decision?.disposition === 'reject' && <input aria-label={`Rejection note for ${item.label}`} onChange={(event) => updateReview(item.id, { note: event.target.value })} placeholder="Engineering reason required" value={decision.note ?? ''} />}{decision?.disposition === 'resolve' && <textarea aria-label={`Resolution for ${item.label}`} onChange={(event) => updateReview(item.id, { replacement_text: event.target.value })} placeholder="Exact replacement language for the revised source" value={decision.replacement_text ?? ''} />}</article>; })}</div>
          <button className="ctrl-flow-review-submit" disabled={!reviewComplete || sequenceReview.isPending} onClick={() => sequenceReview.mutate()} type="button">{sequenceReview.isPending ? 'Re-deriving and validating…' : `Submit ${reviewItems.length} decisions`}<ChevronRight size={15} /></button>
          {sequenceReview.data && <div className={`ctrl-flow-review-outcome ${sequenceReview.data.ready_for_independent_oracle_authoring ? 'ready' : 'blocked'}`}><strong>{sequenceReview.data.ready_for_independent_oracle_authoring ? `${sequenceReview.data.oracle_draft_count} oracle drafts ready for independent authoring` : 'Requirement review remains blocked'}</strong><span>Review {sequenceReview.data.review_digest.slice(0, 12)} · graph generation remains disabled</span>{sequenceReview.data.blockers.length > 0 && <ul>{sequenceReview.data.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul>}</div>}
          {sequenceReview.isError && <div className="ctrl-flow-review-outcome blocked"><strong>Review rejected</strong><span>{sequenceReview.error.message}</span></div>}
        </section>}
      </div>}
      {sequenceReconciliation.isError && <div className="ctrl-flow-sequence-result blocked"><header><CircleAlert size={18} /><div><strong>Sequence inspection stopped</strong><span>{sequenceReconciliation.error.message}</span></div></header></div>}
    </section>
  </div>;
}

export function EnvironmentWorkspace() {
  const runs = useQuery({ queryKey: ['runs'], queryFn: api.runs });
  const environmentQueries = useQueries({ queries: (runs.data ?? []).map((run) => ({ queryKey: ['environment', run.id], queryFn: () => api.environment(run.id), enabled: Boolean(run.environment_manifest_path) })) });
  const deliverableQueries = useQueries({ queries: (runs.data ?? []).map((run) => ({ queryKey: ['deliverables', run.id], queryFn: () => api.deliverables(run.id) })) });
  const rows = (runs.data ?? []).map((run, index) => ({ run, environment: environmentQueries[index]?.data, deliverables: deliverableQueries[index]?.data }));
  return (
    <div className="workspace-index-page environment-workspace">
      <header className="workspace-page-heading"><div><span className="eyebrow">CONTRACTOR TOOLCHAIN</span><h1>Environment Workspace</h1><p>Track the exact Niagara versions, custom modules, palettes, station templates, and graphics assets supplied with each job.</p></div><span className="workspace-proof"><ShieldCheck size={17} />Inspection only · never executed</span></header>
      <section className="environment-boundary"><FileArchive size={22} /><div><strong>Custom contractor environments are first-class inputs</strong><span>Uploaded JARs, palettes, PX templates, and station BOGs are inventoried, hashed, policy-checked, and bound to generated deliverables. Unavailable runtime dependencies remain explicit blockers.</span></div></section>
      {runs.isLoading ? <WorkspaceLoading /> : <section className="environment-grid">{rows.map(({ run, environment, deliverables }) => <EnvironmentCard key={run.id} run={run} environment={environment} deliverables={deliverables} />)}</section>}
    </div>
  );
}

const maturityStages = ['discovered', 'installed', 'executable', 'product-wired', 'target-compiled', 'verified', 'field-qualified', 'production-supported'];

export function SystemWorkspace() {
  const readiness = useQuery({ queryKey: ['readiness'], queryFn: api.readiness });
  const integration = useQuery({ queryKey: ['integration-audit'], queryFn: api.integrationAudit });
  const security = useQuery({ queryKey: ['security-status'], queryFn: api.securityStatus });
  const audit = useQuery({ queryKey: ['security-audit-status'], queryFn: api.securityAuditStatus });
  const loading = readiness.isLoading || integration.isLoading || security.isLoading || audit.isLoading;
  const failed = readiness.isError || integration.isError || security.isError || audit.isError;
  if (loading) return <WorkspaceLoading />;
  if (failed || !readiness.data || !integration.data || !security.data || !audit.data) return <WorkspaceError message="Production controls could not be loaded." />;
  const selected = readiness.data.components.filter((component) => component.selected);
  const wired = selected.filter((component) => maturityStages.indexOf(component.stage) >= maturityStages.indexOf('product-wired')).length;
  const targetCompiled = selected.filter((component) => maturityStages.indexOf(component.stage) >= maturityStages.indexOf('target-compiled')).length;
  return (
    <div className="workspace-index-page system-workspace">
      <header className="workspace-page-heading"><div><span className="eyebrow">PRODUCTION CONTROL PLANE</span><h1>Administration</h1><p>One evidence-backed view of integrations, qualification maturity, safety boundaries, and the tamper-evident engineering ledger.</p></div><span className={integration.data.passed && audit.data.valid ? 'workspace-proof' : 'workspace-proof warning'}><ClipboardCheck size={17} />{integration.data.passed && audit.data.valid ? 'Control plane verified' : 'Control plane attention required'}</span></header>
      <section className="system-scorecards" aria-label="System posture">
        <SystemScore icon={<PackageCheck size={19} />} label="OSS integrations bound" value={`${integration.data.bound_component_count}/${integration.data.pinned_component_count}`} detail="Every pinned source names a product path and executable proof" good={integration.data.passed} />
        <SystemScore icon={<ServerCog size={19} />} label="Product-wired or beyond" value={`${wired}/${selected.length}`} detail={`${targetCompiled} targets compile; field qualification remains explicit`} good={wired === selected.length} />
        <SystemScore icon={<ClipboardCheck size={19} />} label="Ledger integrity" value={audit.data.valid ? 'Valid' : 'Invalid'} detail={`${audit.data.event_count.toLocaleString()} hash-chained API events`} good={audit.data.valid} />
        <SystemScore icon={<ShieldCheck size={19} />} label="Runtime authority" value={security.data.live_writes_enabled ? 'Live writes' : 'Offline only'} detail="Generated work cannot command a live building" good={!security.data.live_writes_enabled} />
      </section>
      <section className="system-boundaries">
        <article><ShieldCheck size={20} /><div><span className="eyebrow">DEPLOYMENT SAFETY</span><h2>Human approval remains mandatory</h2><p>The agent proposes and tests candidates. This runtime does not write to a live building, and every release retains reviewer and artifact evidence.</p></div><dl><div><dt>Authentication</dt><dd>{security.data.mode.replaceAll('-', ' ')}</dd></div><div><dt>Review identity</dt><dd>{security.data.review_identity.replaceAll('-', ' ')}</dd></div><div><dt>HTTPS required</dt><dd>{security.data.https_required ? 'Yes' : 'Local development'}</dd></div></dl></article>
        <article><ClipboardCheck size={20} /><div><span className="eyebrow">AUDIT CHAIN</span><h2>{audit.data.event_count.toLocaleString()} retained events</h2><p>API activity is append-only and hash chained. External immutable retention is still required for a production deployment.</p></div><code title={audit.data.head_hash}>{audit.data.head_hash}</code></article>
      </section>
      <section className="maturity-ledger">
        <header><div><span className="eyebrow">CAPABILITY MATURITY</span><h2>What is installed, wired, compiled, and still blocked</h2></div><span>{selected.length} selected components</span></header>
        <div className="maturity-table" tabIndex={0}><table><thead><tr><th>Component</th><th>Purpose</th><th>License</th><th>Maturity</th><th>Evidence / blocker</th></tr></thead><tbody>{selected.map((component) => <tr key={component.id}><th><strong>{component.name}</strong><code>{component.version || component.id}</code></th><td>{component.role}</td><td>{component.license}</td><td><span className={`maturity-stage stage-${maturityStages.indexOf(component.stage)}`}>{component.stage.replaceAll('-', ' ')}</span></td><td>{component.blocker ? <details><summary>Open qualification boundary</summary><p>{component.blocker}</p></details> : <span className="maturity-clear"><CheckCircle2 size={13} /> No declared blocker</span>}</td></tr>)}</tbody></table></div>
      </section>
    </div>
  );
}

function SystemScore({ icon, label, value, detail, good }: { icon: React.ReactNode; label: string; value: string; detail: string; good: boolean }) {
  return <article className={good ? 'system-score good' : 'system-score'}><header><span>{icon}</span><small>{label}</small></header><strong>{value}</strong><p>{detail}</p></article>;
}

function EnvironmentCard({ run, environment, deliverables }: { run: RunSummary; environment?: ArtifactState<Record<string, unknown>>; deliverables?: ArtifactState<Deliverables> }) {
  const hasEnvironment = environment?.state === 'available';
  const coverage = deliverables?.state === 'available' ? deliverables.data.coverage : {};
  const compiled = Object.values(coverage).filter((item) => item.target_compiled === true).length;
  const emitted = Object.values(coverage).filter((item) => item.emitted === true).length;
  const environmentData = hasEnvironment ? environment.data : null;
  return <article className="environment-card-main"><header><span className={hasEnvironment ? 'environment-icon supplied' : 'environment-icon'}>{hasEnvironment ? <PackageCheck size={19} /> : <Box size={19} />}</span><div><span className="eyebrow">{run.job.site}</span><h2>{run.job.equipment_name}</h2></div><span className={`status-badge ${run.status}`}>{run.status.replaceAll('_', ' ')}</span></header><p>{run.job.name}</p><div className="environment-posture"><div><strong>{hasEnvironment ? 'Supplied pack' : 'Open baseline'}</strong><span>{hasEnvironment ? stringValue(environmentData?.name) || stringValue(environmentData?.id) || 'Contractor environment' : 'No proprietary environment attached'}</span></div><div><strong>{compiled}/{emitted}</strong><span>emitted targets compiled</span></div></div><div className="environment-capabilities"><Capability icon={<Code2 size={13} />} label="Logic" active={Boolean(coverage.logic?.emitted)} /><Capability icon={<Network size={13} />} label="Point map" active={Boolean(coverage.point_mapping?.emitted)} /><Capability icon={<Brush size={13} />} label="Graphics" active={Boolean(coverage.graphics?.target_compiled)} /><Capability icon={<Layers3 size={13} />} label="Station" active={Boolean(coverage.station_assembly?.emitted)} /></div>{deliverables?.state === 'available' && deliverables.data.blocking_gates.length > 0 && <details><summary>{deliverables.data.blocking_gates.length} target gates remain</summary><ul>{deliverables.data.blocking_gates.map((gate) => <li key={gate}>{gate}</li>)}</ul></details>}<Link to={`/studio/${run.id}/graphics`}>Inspect generated environment fit <ChevronRight size={14} /></Link></article>;
}

function Capability({ icon, label, active }: { icon: React.ReactNode; label: string; active: boolean }) { return <span className={active ? 'active' : ''}>{icon}{label}</span>; }
function WorkspaceLoading() { return <div className="workspace-loading"><div className="studio-state-spinner" /><strong>Loading retained workspace data…</strong></div>; }
function WorkspaceError({ message }: { message: string }) { return <div className="workspace-loading error"><CircleAlert size={25} /><strong>{message}</strong></div>; }

function catalogRows(catalog: Catalog): Array<Record<string, unknown>> {
  for (const key of ['controllers', 'rules', 'patterns', 'templates']) {
    const value = catalog[key];
    if (Array.isArray(value)) return value.filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null);
  }
  return [];
}

function catalogCount(catalog: Catalog): number {
  for (const key of ['controller_count', 'source_model_count', 'count', 'pattern_count', 'template_count']) {
    if (typeof catalog[key] === 'number') return catalog[key];
  }
  return catalogRows(catalog).length;
}

function stringValue(value: unknown): string { return typeof value === 'string' ? value : ''; }
function libraryStatus(row: Record<string, unknown>): 'wired' | 'verified' | 'source' {
  const value = `${stringValue(row.product_status)} ${stringValue(row.niagara_translation_status)} ${String(row.translatable ?? '')}`.toLowerCase();
  if (value.includes('exact_ir') || value.includes('compiled-vector')) return 'wired';
  if (value.includes('verified') || value.includes('true')) return 'verified';
  return 'source';
}
function libraryStatusLabel(row: Record<string, unknown>): string {
  const status = libraryStatus(row);
  return status === 'wired' ? 'Product-wired' : status === 'verified' ? 'Verified adapter' : 'Cataloged source';
}
