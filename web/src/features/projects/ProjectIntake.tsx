import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  ArrowRight,
  Building2,
  Check,
  CheckCircle2,
  CircleAlert,
  FileArchive,
  FileJson2,
  GitBranch,
  Network,
  RefreshCw,
  ShieldCheck,
  UploadCloud,
  Workflow,
  X,
} from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { api, type ProjectPreflight } from '../../api/client';
import './project-intake.css';

type ProjectPackage = {
  name: string;
  site: string;
  equipment: Array<{
    equipment_name: string;
    equipment_brick_class?: string;
    sequence: { family: string; version?: string };
    points: unknown[];
  }>;
  relationships?: unknown[];
  signal_bindings?: unknown[];
  acceptance_tests?: unknown[];
  station_assembly_mode?: 'none' | 'insert' | 'replace';
  [key: string]: unknown;
};

export function ProjectIntake() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [packageFile, setPackageFile] = useState<File | null>(null);
  const [stationTemplate, setStationTemplate] = useState<File | null>(null);
  const [project, setProject] = useState<ProjectPackage | null>(null);
  const [preflight, setPreflight] = useState<ProjectPreflight | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  const inspect = useMutation({
    mutationFn: async (candidate: ProjectPackage) => api.preflightProject(candidate),
    onSuccess: (result) => {
      setPreflight(result);
      toast.success(`${result.equipment_count} equipment programs passed through project preflight`);
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Project preflight failed'),
  });

  const build = useMutation({
    mutationFn: async () => {
      if (!project || !preflight?.accepted_for_build) throw new Error('Run a passing project preflight first.');
      if (project.station_assembly_mode !== 'none' && !stationTemplate) {
        throw new Error('This project requires the contractor station template before assembly.');
      }
      return api.buildProject(project, stationTemplate);
    },
    onSuccess: (record) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      queryClient.invalidateQueries({ queryKey: ['runs'] });
      toast.success('Whole-building candidate compiled, assembled, and tested');
      navigate(`/projects/${record.id}`);
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Project build failed'),
  });

  const readPackage = async (file: File | null) => {
    setPackageFile(file);
    setProject(null);
    setPreflight(null);
    setFileError(null);
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text()) as unknown;
      if (!isProjectPackage(parsed)) throw new Error('Expected a project name, site, and at least one equipment job.');
      setProject(parsed);
    } catch (error) {
      setFileError(error instanceof Error ? error.message : 'The project package is not valid JSON.');
    }
  };

  const assemblyRequired = Boolean(project && project.station_assembly_mode !== 'none');
  const canBuild = Boolean(
    project
      && preflight?.accepted_for_build
      && (!assemblyRequired || stationTemplate)
      && !build.isPending,
  );

  return (
    <div className="project-intake">
      <header className="project-intake-header">
        <div>
          <Link to="/projects"><ArrowLeft size={15} />Whole-building projects</Link>
          <span className="eyebrow">NEW BUILDING PROJECT</span>
          <h1>Compile the full controls package</h1>
          <p>Upload the coordinated equipment jobs and the contractor’s Niagara station baseline. BACTalk validates the system contract before it creates a single candidate.</p>
        </div>
        <div className="intake-safe"><ShieldCheck size={17} /><span><strong>Offline assembly</strong>No discovery or controller writes</span></div>
      </header>

      <section className="project-intake-progress" aria-label="Whole-building intake progress">
        <ProgressStep active={!preflight} complete={Boolean(project)} index={1} label="Upload package" detail="Equipment, points, sequences" />
        <ProgressStep active={Boolean(project && !preflight)} complete={Boolean(preflight?.accepted_for_build)} index={2} label="System preflight" detail="Capabilities and contracts" />
        <ProgressStep active={Boolean(preflight)} complete={false} index={3} label="Build and prove" detail="Compile, assemble, test" />
      </section>

      <div className="project-intake-grid">
        <section className="project-intake-panel source-panel">
          <div className="panel-title">
            <div><span className="eyebrow">CONTRACTOR INPUTS</span><h2>Whole-building job package</h2></div>
            <span className="source-count">{[packageFile, stationTemplate].filter(Boolean).length}/2 files</span>
          </div>
          <ProjectFileSlot
            accept=".json,application/json"
            file={packageFile}
            icon={<FileJson2 size={23} />}
            id="project-package"
            label="Building project package"
            note="JSON · equipment jobs, topology, signals, tests"
            onChange={readPackage}
            required
          />
          <ProjectFileSlot
            accept=".bog,application/zip"
            file={stationTemplate}
            icon={<FileArchive size={23} />}
            id="station-template"
            label="Contractor station template"
            note={assemblyRequired ? 'Niagara .bog · required by this package' : 'Niagara .bog · required for station assembly'}
            onChange={(file) => setStationTemplate(file)}
            required={assemblyRequired}
          />
          {fileError && <div className="project-intake-error" role="alert"><CircleAlert size={17} /><span><strong>Package could not be read</strong>{fileError}</span></div>}
          <div className="project-input-boundary"><ShieldCheck size={18} /><div><strong>Uploaded code is treated as data</strong><span>The project contract and BOG are parsed and validated. Contractor modules are inventoried, never executed by this intake.</span></div></div>
          <button className="intake-primary project-preflight-button" disabled={!project || inspect.isPending} onClick={() => project && inspect.mutate(project)} type="button">
            {inspect.isPending ? <RefreshCw className="spin" size={16} /> : <Workflow size={16} />}
            {inspect.isPending ? 'Checking every program…' : 'Run system preflight'}
          </button>
        </section>

        <section className="project-intake-panel scope-panel">
          {!project ? (
            <div className="project-intake-empty"><UploadCloud size={31} /><h2>Drop in the coordinated job package</h2><p>The review appears here before any compiler or simulator is allowed to run.</p></div>
          ) : (
            <>
              <div className="panel-title project-scope-title"><div><span className="eyebrow">{project.site}</span><h2>{project.name}</h2></div><span className={`assembly-pill ${project.station_assembly_mode ?? 'none'}`}>{project.station_assembly_mode ?? 'none'} assembly</span></div>
              <div className="project-scope-metrics">
                <ScopeMetric icon={<Building2 size={17} />} label="Equipment jobs" value={project.equipment.length} />
                <ScopeMetric icon={<GitBranch size={17} />} label="Relationships" value={project.relationships?.length ?? 0} />
                <ScopeMetric icon={<Network size={17} />} label="Typed signals" value={project.signal_bindings?.length ?? 0} />
                <ScopeMetric icon={<CheckCircle2 size={17} />} label="System tests" value={project.acceptance_tests?.length ?? 0} />
              </div>
              <div className="project-equipment-review" aria-label="Equipment programs in uploaded project">
                {project.equipment.map((equipment) => {
                  const result = preflight?.equipment.find((item) => item.equipment_name === equipment.equipment_name);
                  return (
                    <article key={equipment.equipment_name}>
                      <span className={result ? (result.preflight_passed ? 'equipment-pass' : 'equipment-blocked') : 'equipment-pending'}>
                        {result ? (result.preflight_passed ? <Check size={14} /> : <CircleAlert size={14} />) : <Building2 size={14} />}
                      </span>
                      <div><strong>{equipment.equipment_name}</strong><small>{equipment.sequence.family.replaceAll('_', ' ')} · {equipment.points.length} points</small></div>
                      <div className="equipment-pack"><span>{result?.pack_id ?? 'Awaiting preflight'}</span><small>{result?.pack_stage ?? 'Not yet checked'}</small></div>
                    </article>
                  );
                })}
              </div>
              {preflight && (
                <div className={preflight.accepted_for_build ? 'project-preflight-result pass' : 'project-preflight-result blocked'}>
                  {preflight.accepted_for_build ? <CheckCircle2 size={22} /> : <CircleAlert size={22} />}
                  <div><strong>{preflight.accepted_for_build ? 'System contract accepted for build' : 'Build blocked by preflight'}</strong><span>{preflight.next_gate}</span></div>
                </div>
              )}
            </>
          )}
        </section>
      </div>

      <section className="project-build-bar">
        <div><ShieldCheck size={19} /><span><strong>One immutable system candidate</strong><small>Child programs, cross-equipment tests, station assembly, hashes, and evidence are retained together.</small></span></div>
        <button className="intake-primary build" disabled={!canBuild} onClick={() => build.mutate()} type="button">
          {build.isPending ? <RefreshCw className="spin" size={16} /> : <Workflow size={16} />}
          {build.isPending ? 'Compiling six programs and assembling station…' : <>Build, assemble, and test<ArrowRight size={16} /></>}
        </button>
      </section>
    </div>
  );
}

function ProgressStep({ active, complete, index, label, detail }: { active: boolean; complete: boolean; index: number; label: string; detail: string }) {
  return <div className={`${active ? 'active' : ''} ${complete ? 'complete' : ''}`}><span>{complete ? <Check size={14} /> : index}</span><div><strong>{label}</strong><small>{detail}</small></div></div>;
}

function ProjectFileSlot({ accept, file, icon, id, label, note, onChange, required = false }: { accept: string; file: File | null; icon: React.ReactNode; id: string; label: string; note: string; onChange: (file: File | null) => void | Promise<void>; required?: boolean }) {
  return (
    <div className={`project-file-slot ${file ? 'selected' : ''}`} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); void onChange(event.dataTransfer.files[0] ?? null); }}>
      <input accept={accept} id={id} name={id} onChange={(event) => void onChange(event.target.files?.[0] ?? null)} type="file" />
      <label htmlFor={id}>
        <span className="file-icon">{file ? <CheckCircle2 size={23} /> : icon}</span>
        <span><strong>{file?.name ?? label}</strong><small>{file ? `${formatBytes(file.size)} · click to replace` : note}</small></span>
        <span className={required ? 'project-file-required' : 'project-file-optional'}>{required ? 'Required' : 'Optional'}</span>
        {!file && <UploadCloud size={18} />}
      </label>
      {file && <button aria-label={`Remove ${label}`} onClick={() => void onChange(null)} type="button"><X size={15} /></button>}
    </div>
  );
}

function ScopeMetric({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return <div><span>{icon}{label}</span><strong>{value}</strong></div>;
}

function isProjectPackage(value: unknown): value is ProjectPackage {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Partial<ProjectPackage>;
  return typeof candidate.name === 'string'
    && typeof candidate.site === 'string'
    && Array.isArray(candidate.equipment)
    && candidate.equipment.length > 0
    && candidate.equipment.every((item) => Boolean(item && typeof item.equipment_name === 'string' && item.sequence?.family && Array.isArray(item.points)));
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
