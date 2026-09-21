import { useMutation } from '@tanstack/react-query';
import { Hammer, Upload } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api } from '../../api/client';
import type { ProjectPreflight } from '../../api/client';
import { Button, Field, NativeSelect, StatusPill, Textarea } from '../../design-system/primitives';
import { SectionCard } from '../shared/StageFrame';

function parseProject(text: string): { project: Record<string, unknown> | null; error: string | null } {
  if (!text.trim()) return { project: null, error: null };
  try {
    const parsed = JSON.parse(text) as Record<string, unknown>;
    if (!parsed || typeof parsed !== 'object' || !Array.isArray(parsed.equipment)) return { project: null, error: 'A project has a name, a site, and an equipment list of programming jobs.' };
    return { project: parsed, error: null };
  } catch (error) {
    return { project: null, error: error instanceof Error ? error.message : 'Invalid JSON' };
  }
}

/**
 * Whole-building intake: a project spec (equipment jobs, relationships,
 * signal bindings, project acceptance tests) is preflighted, then built.
 * With a station template the build also assembles the contractor station.
 */
export function ProjectBuilder() {
  const navigate = useNavigate();
  const [text, setText] = useState('');
  const [template, setTemplate] = useState<File | null>(null);
  const [assembly, setAssembly] = useState<'none' | 'insert' | 'replace'>('none');
  const parsed = parseProject(text);
  const spec = parsed.project ? { ...parsed.project, station_assembly_mode: assembly } : null;

  const preflight = useMutation({ mutationFn: (project: unknown) => api.preflightProject(project) });
  const build = useMutation({
    mutationFn: (project: unknown) => api.buildProject(project, template),
    onSuccess: (record) => navigate(`/projects/${record.id}`),
  });

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setText(await file.text());
    preflight.reset();
  };

  const result: ProjectPreflight | undefined = preflight.data;
  const buildable = Boolean(spec) && result?.accepted_for_build === true && (assembly === 'none' || Boolean(template));

  return (
    <div className="max-w-5xl mx-auto px-6 py-6 flex flex-col gap-4">
      <header>
        <p className="eyebrow">Whole building</p>
        <h2 className="text-xl font-semibold tracking-tight">Build a project</h2>
        <p className="mt-1 text-sm text-fg-1">Equipment jobs, typed relationships, cross-equipment signal bindings, and project acceptance tests, preflighted before anything is built.</p>
      </header>
      <SectionCard
        title="Project specification"
        aside={
          <label className="inline-flex items-center gap-2 text-xs text-accent cursor-pointer">
            <Upload size={13} /> Load JSON file
            <input type="file" accept="application/json,.json" className="sr-only" onChange={(event) => void onFile(event.target.files?.[0])} />
          </label>
        }
      >
        <div className="px-4 py-3 flex flex-col gap-3">
          <Field label="Project JSON" error={parsed.error} hint={!parsed.error && parsed.project ? `${(parsed.project.equipment as unknown[]).length} equipment jobs · ${((parsed.project.relationships as unknown[]) ?? []).length} relationships · ${((parsed.project.signal_bindings as unknown[]) ?? []).length} signal bindings` : 'Paste a project specification or load a file.'} htmlFor="project-json">
            <Textarea
              id="project-json"
              mono
              rows={12}
              value={text}
              placeholder='{"name": "Office building", "site": "Campus", "equipment": [ … ], "relationships": [ … ], "signal_bindings": [ … ]}'
              onChange={(event) => {
                setText(event.target.value);
                preflight.reset();
              }}
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Station assembly" htmlFor="assembly-mode" hint="Insert or replace requires a contractor station template; the assembled station is retained with the project.">
              <NativeSelect id="assembly-mode" value={assembly} onChange={(event) => setAssembly(event.target.value as typeof assembly)}>
                <option value="none">None (programs only)</option>
                <option value="insert">Insert into station template</option>
                <option value="replace">Replace in station template</option>
              </NativeSelect>
            </Field>
            <Field label="Station template (.bog / .zip)" htmlFor="station-template">
              <input id="station-template" type="file" accept=".bog,.zip,application/zip" className="text-sm text-fg-1" onChange={(event) => setTemplate(event.target.files?.[0] ?? null)} />
            </Field>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={() => spec && preflight.mutate(spec)} disabled={!spec || preflight.isPending}>
              {preflight.isPending ? 'Preflighting…' : 'Preflight'}
            </Button>
            <Button variant="primary" onClick={() => spec && build.mutate(spec)} disabled={!buildable || build.isPending}>
              <Hammer size={13} /> {build.isPending ? 'Building…' : 'Build project'}
            </Button>
            {preflight.isError && (
              <span role="alert" className="text-xs text-fail">
                {(preflight.error as Error).message}
              </span>
            )}
            {build.isError && (
              <span role="alert" className="text-xs text-fail">
                {(build.error as Error).message}
              </span>
            )}
          </div>
        </div>
      </SectionCard>
      {result && (
        <SectionCard
          title="Preflight"
          aside={
            <span className="inline-flex gap-2">
              <StatusPill tone={result.accepted_for_build ? 'ok' : 'fail'}>{result.accepted_for_build ? 'accepted for build' : 'not accepted'}</StatusPill>
              <StatusPill tone={result.production_ready ? 'ok' : 'warn'}>{result.production_ready ? 'production ready' : 'not production ready'}</StatusPill>
            </span>
          }
        >
          <div className="px-4 py-3 text-sm flex flex-col gap-3">
            <p className="text-fg-1">
              {result.project} at {result.site}: {result.equipment_count} equipment, {result.relationship_count} relationships, {result.signal_binding_count} signal bindings, {result.project_acceptance_case_count} project acceptance cases.
            </p>
            <table className="w-full text-sm">
              <thead className="text-left">
                <tr className="hairline-b">
                  <th className="eyebrow h-8 font-semibold">Equipment</th>
                  <th className="eyebrow h-8 font-semibold">Sequence</th>
                  <th className="eyebrow h-8 font-semibold">Pack</th>
                  <th className="eyebrow h-8 font-semibold">Preflight</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line-1">
                {result.equipment.map((item) => (
                  <tr key={item.equipment_name}>
                    <td className="py-2 font-mono text-xs">{item.equipment_name}</td>
                    <td className="py-2 text-xs">{item.sequence_family}</td>
                    <td className="py-2 text-xs">{item.pack_id ? `${item.pack_id} · ${item.pack_stage ?? ''}` : '—'}</td>
                    <td className="py-2">
                      <StatusPill tone={item.preflight_passed ? 'ok' : 'fail'}>{item.preflight_passed ? 'passed' : 'blocked'}</StatusPill>
                      {item.blockers.length > 0 && <ul className="mt-1 text-xs text-warn">{item.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-fg-2">Next gate: {result.next_gate}</p>
          </div>
        </SectionCard>
      )}
    </div>
  );
}
