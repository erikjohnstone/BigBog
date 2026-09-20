import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useForm, useWatch } from 'react-hook-form';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Cpu,
  FileArchive,
  FileCode2,
  FileSpreadsheet,
  FileText,
  HardDriveUpload,
  Network,
  Play,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  X,
} from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { api, type IntakeInspection } from '../../api/client';

type IntakeValues = {
  name: string;
  site: string;
  equipmentName: string;
  sequenceFamily: string;
  sequenceVersion: string;
  controllerId: string;
  executionProfile: 'modelica_exact' | 'host_tick_v1';
  sequenceParameters: string;
  deliverableRequirements: string;
  acceptanceTests: string;
  notes: string;
};

type IntakeFiles = {
  points: File | null;
  sequence: File | null;
  bacnet: File | null;
  template: File | null;
  environment: File | null;
};

const emptyFiles: IntakeFiles = {
  points: null,
  sequence: null,
  bacnet: null,
  template: null,
  environment: null,
};

const families = [
  ['AUTO', 'Detect from sequence document'],
  ['AI_CUSTOM', 'AI custom · engineer-tested'],
  ['G36_VAV_REHEAT', 'Guideline 36 VAV with reheat'],
  ['LBNL_G36_CONTROLLER', 'LBNL G36 configured controller'],
  ['LBNL_PLANT_CONTROLLER', 'LBNL plant controller · 38 proven models'],
  ['CUSTOM_AHU_SAFETY_COOLING', 'AHU safety and cooling'],
  ['AHU_DUCT_STATIC_PI', 'AHU duct-static PI loop'],
  ['EXHAUST_FAN_PROOF', 'Exhaust fan command/proof'],
  ['TWO_PUMP_AVAILABILITY_SELECTOR', 'Two-pump duty/standby selector'],
];

function IntakeStudio() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [step, setStep] = useState(1);
  const [files, setFiles] = useState<IntakeFiles>(emptyFiles);
  const [inspection, setInspection] = useState<IntakeInspection | null>(null);
  const {
    register,
    handleSubmit,
    getValues,
    control,
    trigger,
    formState: { errors },
  } = useForm<IntakeValues>({
    mode: 'onBlur',
    defaultValues: {
      name: '',
      site: '',
      equipmentName: '',
      sequenceFamily: 'AUTO',
      sequenceVersion: 'Contractor sequence of operations',
      controllerId: '',
      executionProfile: 'modelica_exact',
      sequenceParameters: '{}',
      deliverableRequirements: '{}',
      acceptanceTests: '[]',
      notes: '',
    },
  });
  const family = useWatch({ control, name: 'sequenceFamily' });
  const libraryLane = family === 'LBNL_G36_CONTROLLER' || family === 'LBNL_PLANT_CONTROLLER';

  const inspect = useMutation({
    mutationFn: async () => {
      if (!files.points) throw new Error('Choose a points CSV or XLSX file first.');
      const body = new FormData();
      body.append('points_file', files.points);
      body.append('sequence_family', getValues('sequenceFamily'));
      if (files.sequence) body.append('sequence_document', files.sequence);
      return api.inspectIntake(body);
    },
    onSuccess: (result) => {
      setInspection(result);
      setStep(3);
      toast.success(`${result.point_count} points normalized and checked`);
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Intake inspection failed'),
  });

  const build = useMutation({
    mutationFn: async (values: IntakeValues) => {
      if (!files.points || !inspection) throw new Error('Inspect the source package before building.');
      validateJson(values.sequenceParameters, 'Sequence parameters', 'object');
      validateJson(values.deliverableRequirements, 'Deliverable requirements', 'object');
      validateJson(values.acceptanceTests, 'Acceptance tests', 'array');
      if (values.sequenceFamily === 'AI_CUSTOM' && JSON.parse(values.acceptanceTests).length === 0) {
        throw new Error('AI custom programming requires engineer-authored acceptance tests.');
      }
      if (libraryLane && !values.controllerId.trim()) {
        throw new Error('Choose an exact library controller ID for this source lane.');
      }
      const body = new FormData();
      body.append('name', values.name);
      body.append('site', values.site);
      body.append('equipment_name', values.equipmentName);
      body.append('sequence_family', values.sequenceFamily);
      body.append('sequence_version', values.sequenceVersion);
      body.append('sequence_parameters', values.sequenceParameters);
      body.append('deliverable_requirements', values.deliverableRequirements);
      body.append('acceptance_tests', values.acceptanceTests);
      body.append('execution_profile', values.executionProfile);
      body.append('notes', values.notes);
      if (family === 'LBNL_PLANT_CONTROLLER') body.append('sequence_library', 'plant_controls');
      if (family === 'LBNL_G36_CONTROLLER') body.append('sequence_library', 'g36');
      if (libraryLane) body.append('controller_id', values.controllerId);
      body.append('points_file', files.points);
      if (files.sequence) body.append('sequence_document', files.sequence);
      if (files.bacnet) body.append('bacnet_scan', files.bacnet);
      if (files.template) body.append('template_bog', files.template);
      if (files.environment) body.append('environment_pack', files.environment);
      return api.importRun(body);
    },
    onSuccess: (record) => {
      queryClient.invalidateQueries({ queryKey: ['runs'] });
      toast.success('Candidate compiled and tested. Human review is next.');
      navigate(`/studio/${record.id}/tests`);
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Build failed'),
  });

  const updateFile = (key: keyof IntakeFiles, file: File | null) => {
    setFiles((current) => ({ ...current, [key]: file }));
    setInspection(null);
    if (step === 3) setStep(2);
  };

  const advanceScope = async () => {
    const valid = await trigger(['name', 'site', 'equipmentName', 'sequenceFamily', 'sequenceVersion']);
    if (valid) setStep(2);
  };

  const canBuild = Boolean(
    inspection
    && inspection.selected_sequence_family
    && inspection.missing_required_points.length === 0
    && !inspection.writes_enabled,
  );

  return (
    <form className="intake-studio" onSubmit={handleSubmit((values) => build.mutate(values))}>
      <header className="intake-header">
        <div><Link to="/"><ArrowLeft size={15} />Project cockpit</Link><span className="eyebrow">NEW CONTRACTOR JOB</span><h1>Turn the job package into a tested candidate</h1><p>Bring the documents your engineer already has. BACTalk will normalize, map, compile, test, and retain the exact evidence.</p></div>
        <div className="intake-safe"><ShieldCheck size={17} /><span><strong>Offline by design</strong>No live discovery or writes</span></div>
      </header>

      <div className="intake-layout">
        <aside className="intake-stepper" aria-label="Contractor intake progress">
          <IntakeStep active={step === 1} complete={step > 1} index={1} label="Define the job" detail="Site, equipment, sequence" onClick={() => setStep(1)} />
          <IntakeStep active={step === 2} complete={step > 2} disabled={step < 2} index={2} label="Attach sources" detail="Points, sequence, BACnet" onClick={() => setStep(2)} />
          <IntakeStep active={step === 3} complete={Boolean(inspection)} disabled={!inspection} index={3} label="Review mapping" detail="Aliases, gaps, exact inputs" onClick={() => setStep(3)} />
          <div className="intake-boundary"><Cpu size={18} /><strong>What happens next</strong><span>The server validates the typed graph, compiles the target, executes acceptance tests, and creates a separate immutable candidate.</span></div>
        </aside>

        <div className="intake-main">
          {step === 1 && (
            <section className="intake-section">
              <SectionHeading kicker="STEP 1 OF 3" title="Define the engineering scope" detail="Use the names that should appear in the review package and station handoff." />
              <div className="intake-form-grid">
                <Field label="Job name" error={errors.name?.message} wide><input {...register('name', { required: 'Job name is required', maxLength: 200 })} placeholder="North Wing air systems retrofit" /></Field>
                <Field label="Site" error={errors.site?.message}><input {...register('site', { required: 'Site is required', maxLength: 200 })} placeholder="Example Campus" /></Field>
                <Field label="Equipment identifier" hint="Letters, numbers, and underscores"><input {...register('equipmentName', { required: 'Equipment identifier is required', pattern: { value: /^[A-Za-z_][A-Za-z0-9_]*$/, message: 'Use a Niagara-safe identifier such as AHU_3' } })} placeholder="AHU_3" /></Field>
                <Field label="Sequence strategy" wide><select {...register('sequenceFamily')}>{families.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
                <Field label="Sequence version or source" wide><input {...register('sequenceVersion', { required: 'Sequence source is required', maxLength: 200 })} /></Field>
                {libraryLane && <><Field label="Exact controller ID" hint="For example: HeatPumps.AirToWater" wide><input {...register('controllerId')} placeholder="HeatPumps.AirToWater" /></Field><Field label="Execution semantics" wide><select {...register('executionProfile')}><option value="modelica_exact">Modelica exact</option><option value="host_tick_v1">Niagara host tick · explicit sampled profile</option></select></Field></>}
              </div>
              {family === 'AI_CUSTOM' && <div className="intake-callout amber"><Sparkles size={18} /><div><strong>AI drafts; engineers define truth</strong><span>A real sequence document and independently authored acceptance tests are mandatory. The model cannot grade its own proposal.</span></div></div>}
              <div className="intake-actions"><span /><button className="intake-primary" onClick={advanceScope} type="button">Attach source files<ArrowRight size={16} /></button></div>
            </section>
          )}

          {step === 2 && (
            <section className="intake-section">
              <SectionHeading kicker="STEP 2 OF 3" title="Attach the contractor source package" detail="The uploaded bytes are retained and become part of the immutable approval digest." />
              <div className="file-grid">
                <FileSlot accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" file={files.points} icon={<FileSpreadsheet size={21} />} label="Points list" name="points" note="CSV or XLSX · required" onChange={(file) => updateFile('points', file)} required />
                <FileSlot accept=".txt,.md,.json,.docx,.pdf,text/plain,text/markdown,application/json,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/pdf" file={files.sequence} icon={<FileText size={21} />} label="Sequence of operations" name="sequence" note="TXT, Markdown, JSON, DOCX, or PDF" onChange={(file) => updateFile('sequence', file)} recommended />
                <FileSlot accept=".json,application/json" file={files.bacnet} icon={<Network size={21} />} label="BACnet scan" name="bacnet" note="Object inventory JSON · optional" onChange={(file) => updateFile('bacnet', file)} />
                <FileSlot accept=".bog,application/zip" file={files.template} icon={<FileCode2 size={21} />} label="Shop Niagara template" name="template" note="Baseline .bog · optional" onChange={(file) => updateFile('template', file)} />
                <FileSlot accept=".zip,application/zip" file={files.environment} icon={<FileArchive size={21} />} label="Niagara environment pack" name="environment" note="Declared modules, palettes, graphics" onChange={(file) => updateFile('environment', file)} />
              </div>
              <div className="source-summary"><HardDriveUpload size={18} /><div><strong>{Object.values(files).filter(Boolean).length} source files selected</strong><span>{files.points ? `${files.points.name} is ready for normalization.` : 'A points list is required before inspection.'}</span></div></div>
              <div className="intake-actions"><button className="intake-secondary" onClick={() => setStep(1)} type="button"><ArrowLeft size={15} />Back</button><button className="intake-primary" disabled={!files.points || inspect.isPending} onClick={() => inspect.mutate()} type="button">{inspect.isPending ? <RefreshCw className="spin" size={16} /> : <Play size={16} />}{inspect.isPending ? 'Inspecting sources…' : 'Inspect mapping'}</button></div>
            </section>
          )}

          {step === 3 && inspection && (
            <section className="intake-section review-source">
              <SectionHeading kicker="STEP 3 OF 3" title="Review the normalized engineering inputs" detail="Resolve missing required points before BACTalk is allowed to create a candidate." />
              <InspectionSummary inspection={inspection} />
              <PointPreview inspection={inspection} />
              <details className="advanced-intake">
                <summary><ChevronDown size={15} /><span><strong>Engineering configuration</strong><small>Parameters, deliverables, acceptance tests, and notes</small></span></summary>
                <div className="advanced-grid">
                  <Field label="Sequence parameters" hint="JSON object"><textarea {...register('sequenceParameters')} rows={5} /></Field>
                  <Field label="Deliverable requirements" hint="JSON object"><textarea {...register('deliverableRequirements')} rows={5} /></Field>
                  <Field label="Acceptance tests" hint={family === 'AI_CUSTOM' ? 'JSON array · required for AI custom' : 'JSON array'} wide><textarea {...register('acceptanceTests')} rows={7} /></Field>
                  <Field label="Engineer notes" wide><textarea {...register('notes')} maxLength={5000} placeholder="Scope, assumptions, exclusions, and review notes" rows={4} /></Field>
                </div>
              </details>
              <div className="build-boundary"><ShieldCheck size={19} /><div><strong>Candidate generation is still offline</strong><span>Build runs typed validation and tests. It does not connect to or command a live controller.</span></div></div>
              <div className="intake-actions"><button className="intake-secondary" onClick={() => setStep(2)} type="button"><ArrowLeft size={15} />Change files</button><button className="intake-primary build" disabled={!canBuild || build.isPending} type="submit">{build.isPending ? <RefreshCw className="spin" size={16} /> : <Sparkles size={16} />}{build.isPending ? 'Compiling and testing…' : 'Build and test candidate'}</button></div>
            </section>
          )}
        </div>
      </div>
    </form>
  );
}

function IntakeStep({ active, complete, disabled = false, index, label, detail, onClick }: { active: boolean; complete: boolean; disabled?: boolean; index: number; label: string; detail: string; onClick: () => void }) {
  return <button aria-current={active ? 'step' : undefined} className={`${active ? 'active' : ''} ${complete ? 'complete' : ''}`} disabled={disabled} onClick={onClick} type="button"><span>{complete ? <Check size={14} /> : index}</span><div><strong>{label}</strong><small>{detail}</small></div></button>;
}

function SectionHeading({ kicker, title, detail }: { kicker: string; title: string; detail: string }) {
  return <div className="intake-section-heading"><span className="eyebrow">{kicker}</span><h2>{title}</h2><p>{detail}</p></div>;
}

function Field({ label, hint, error, wide = false, children }: { label: string; hint?: string; error?: string; wide?: boolean; children: React.ReactNode }) {
  return <label className={`intake-field ${wide ? 'wide' : ''} ${error ? 'invalid' : ''}`}><span><strong>{label}</strong>{hint && <small>{hint}</small>}</span>{children}{error && <em>{error}</em>}</label>;
}

function FileSlot({ accept, file, icon, label, name, note, onChange, required = false, recommended = false }: { accept: string; file: File | null; icon: React.ReactNode; label: string; name: string; note: string; onChange: (file: File | null) => void; required?: boolean; recommended?: boolean }) {
  const id = `intake-file-${name}`;
  return (
    <div className={`file-slot ${file ? 'selected' : ''}`} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); onChange(event.dataTransfer.files[0] ?? null); }}>
      <input accept={accept} id={id} name={name} onChange={(event) => onChange(event.target.files?.[0] ?? null)} type="file" />
      <label htmlFor={id}>
        <span className="file-icon">{file ? <CheckCircle2 size={21} /> : icon}</span>
        <span><strong>{file?.name ?? label}</strong><small>{file ? `${formatBytes(file.size)} · click to replace` : note}</small></span>
        <span className={`file-requirement ${required ? 'required' : recommended ? 'recommended' : ''}`}>{required ? 'Required' : recommended ? 'Recommended' : 'Optional'}</span>
        {!file && <UploadCloud aria-hidden="true" size={17} />}
      </label>
      {file && <button aria-label={`Remove ${label}`} className="file-remove" onClick={() => onChange(null)} type="button"><X size={15} /></button>}
    </div>
  );
}

function InspectionSummary({ inspection }: { inspection: IntakeInspection }) {
  const ready = inspection.missing_required_points.length === 0 && Boolean(inspection.selected_sequence_family);
  return (
    <div className="inspection-summary">
      <div className={ready ? 'ready' : 'blocked'}>{ready ? <CheckCircle2 size={23} /> : <CircleAlert size={23} />}<span><strong>{ready ? 'Point contract is complete' : 'Engineering input needs attention'}</strong><small>{ready ? 'Required pack points are present.' : 'Resolve the blockers below before building.'}</small></span></div>
      <InspectionMetric label="Normalized points" value={String(inspection.point_count)} />
      <InspectionMetric label="BACnet references" value={String(inspection.mapped_bacnet_points)} />
      <InspectionMetric label="Sequence family" value={inspection.selected_sequence_family?.replaceAll('_', ' ') ?? 'Unresolved'} />
      <InspectionMetric label="Live writes" value={inspection.writes_enabled ? 'Enabled' : 'Disabled'} safe={!inspection.writes_enabled} />
    </div>
  );
}

function InspectionMetric({ label, value, safe = false }: { label: string; value: string; safe?: boolean }) {
  return <div className="inspection-metric"><span>{label}</span><strong className={safe ? 'safe' : ''}>{value}</strong></div>;
}

function PointPreview({ inspection }: { inspection: IntakeInspection }) {
  const mappings = inspection.canonical_point_mappings;
  return (
    <section className="point-preview">
      <header><div><span className="eyebrow">NORMALIZED POINT CONTRACT</span><h3>What the compiler will receive</h3></div><span>{inspection.points.length} points</span></header>
      {inspection.missing_required_points.length > 0 && <div className="missing-points"><CircleAlert size={16} /><div><strong>Missing required points</strong><span>{inspection.missing_required_points.join(' · ')}</span></div></div>}
      {mappings.length > 0 && <div className="alias-strip"><RefreshCw size={15} /><span><strong>{mappings.length} canonical aliases applied</strong>{mappings.slice(0, 5).map((mapping) => `${mapping.source_name} → ${mapping.canonical_name}`).join(' · ')}</span></div>}
      <div className="point-table-wrap" tabIndex={0} aria-label="Normalized points table"><table><thead><tr><th>Canonical point</th><th>Role</th><th>Data</th><th>Units</th><th>BACnet object</th><th>Semantic class</th></tr></thead><tbody>{inspection.points.map((point) => <tr key={point.name}><th><code>{point.name}</code><span>{point.label}</span></th><td><span className={`point-role ${point.role}`}>{point.role}</span></td><td>{point.data_type}</td><td>{point.units || '—'}</td><td><code>{point.bacnet_object || 'Unmapped'}</code></td><td><code>{point.brick_class?.replace('brick:', '') || '—'}</code></td></tr>)}</tbody></table></div>
    </section>
  );
}

function validateJson(value: string, label: string, expected: 'object' | 'array') {
  let parsed: unknown;
  try { parsed = JSON.parse(value); } catch { throw new Error(`${label} must be valid JSON.`); }
  if (expected === 'array' && !Array.isArray(parsed)) throw new Error(`${label} must be a JSON array.`);
  if (expected === 'object' && (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed))) throw new Error(`${label} must be a JSON object.`);
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export { IntakeStudio };
