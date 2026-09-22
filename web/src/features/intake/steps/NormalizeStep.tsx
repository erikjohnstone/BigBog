import { useMutation, useQuery } from '@tanstack/react-query';
import { Link2, RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';

import { api } from '../../../api/client';
import type { BindingSuggestion, StationBindingSuggestions } from '../../../api/client';
import { Button, Input, NativeSelect, StatusPill } from '../../../design-system/primitives';
import { ErrorState, LoadingState } from '../../../design-system/states';
import { useIntake } from '../../../stores/intake';
import type { ConfirmedBinding } from '../../../stores/intake';
import { buildInspectForm, buildStationBindingsForm } from '../build-import-form';

/** Runs the server's point normalization and shows exactly what it mapped. */
export function NormalizeStep() {
  const draft = useIntake((state) => state.draft);
  const files = useIntake((state) => state.files);
  const inspection = useIntake((state) => state.inspection);
  const setInspection = useIntake((state) => state.setInspection);
  const update = useIntake((state) => state.update);

  const inspect = useMutation({
    mutationFn: () => api.inspectIntake(buildInspectForm(draft, files)),
    onSuccess: (result) => {
      setInspection(result);
      if (draft.sequenceFamily === 'AUTO' && result.selected_sequence_family) update({ sequenceFamily: result.selected_sequence_family });
    },
  });
  const { mutate } = inspect;

  useEffect(() => {
    if (!inspection && files.points && !inspect.isPending) mutate();
    // Run once per attached file set.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files.points, files.sequence]);

  if (inspect.isPending && !inspection) return <LoadingState label="Normalizing points" />;
  if (inspect.isError && !inspection) return <ErrorState title="The server rejected the documents" error={inspect.error} onRetry={() => mutate()} />;
  if (!inspection) return <ErrorState title="Nothing to normalize" error="Attach a points list first." />;

  const suggestions = inspection.sequence?.suggested_sequence_families ?? [];
  const ready = inspection.missing_required_points.length === 0 && Boolean(inspection.selected_sequence_family);

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-start gap-3">
        <div className="flex-1">
          <p className="eyebrow">Step 3</p>
          <h2 className="text-xl font-semibold tracking-tight">Review the normalized inputs</h2>
          <p className="text-sm text-fg-1 mt-1">Every point is canonicalized against the chosen family. Missing required points block the build until the list or the family changes.</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => mutate()} disabled={inspect.isPending}>
          <RefreshCw size={13} /> Re-run
        </Button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Metric label="Points" value={inspection.point_count} />
        <Metric label="BACnet mapped" value={inspection.mapped_bacnet_points} />
        <Metric label="Canonical mappings" value={inspection.canonical_point_mappings.length} />
        <Metric label="Missing required" value={inspection.missing_required_points.length} tone={inspection.missing_required_points.length ? 'fail' : 'ok'} />
      </div>

      <div className="panel p-4 flex flex-col gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium">Sequence family</span>
          {inspection.selected_sequence_family ? (
            <StatusPill tone="ok">{inspection.selected_sequence_family}</StatusPill>
          ) : (
            <StatusPill tone="warn">unresolved · choose one in Strategy</StatusPill>
          )}
          <StatusPill tone={ready ? 'ok' : 'warn'}>{ready ? 'ready to build' : 'not ready'}</StatusPill>
        </div>
        {suggestions.length > 0 && (
          <ul className="flex gap-2 flex-wrap text-xs">
            {suggestions.map((item) => (
              <li key={item.family}>
                <button type="button" className="chip hover:border-accent" onClick={() => update({ sequenceFamily: item.family })} title="Use this family">
                  {item.family} <span className="num text-fg-2 ml-1">{(item.confidence * 100).toFixed(0)}%</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {inspection.missing_required_points.length > 0 && (
          <p className="text-xs text-fail">
            Missing required points: <span className="font-mono">{inspection.missing_required_points.join(', ')}</span>
          </p>
        )}
      </div>

      <StationBindings />

      <div className="panel overflow-x-auto">
        <table className="w-full text-sm whitespace-nowrap">
          <thead className="text-left">
            <tr className="hairline-b">
              <th className="eyebrow px-4 h-8 font-semibold">Point</th>
              <th className="eyebrow px-4 h-8 font-semibold">Canonical</th>
              <th className="eyebrow px-4 h-8 font-semibold">Role</th>
              <th className="eyebrow px-4 h-8 font-semibold">Type</th>
              <th className="eyebrow px-4 h-8 font-semibold">Units</th>
              <th className="eyebrow px-4 h-8 font-semibold">BACnet</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line-1">
            {inspection.points.map((point) => {
              const mapping = inspection.canonical_point_mappings.find((item) => item.canonical_name === point.name || item.source_name === point.name);
              return (
                <tr key={point.name}>
                  <td className="px-4 h-8">
                    <span className="block">{point.label}</span>
                    <span className="block font-mono text-2xs text-fg-2">{(point as { source_name?: string | null }).source_name ?? point.name}</span>
                  </td>
                  <td className="px-4 font-mono text-xs">{mapping ? mapping.canonical_name : <span className="text-fg-2">as provided</span>}</td>
                  <td className="px-4 text-xs">{point.role}</td>
                  <td className="px-4 font-mono text-xs">{point.data_type}</td>
                  <td className="px-4 text-xs">{point.units ?? '—'}</td>
                  <td className="px-4 font-mono text-2xs">{point.bacnet_object ? `${point.bacnet_device_instance ?? '?'}:${point.bacnet_object}` : <span className="text-fg-2">unmapped</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Metric({ label, value, tone }: { label: string; value: number; tone?: 'ok' | 'fail' }) {
  return (
    <div className="panel p-3">
      <span className={`block text-2xl font-semibold num ${tone === 'fail' ? 'text-fail' : tone === 'ok' ? 'text-ok' : ''}`}>{value}</span>
      <span className="block text-xs text-fg-1">{label}</span>
    </div>
  );
}

/**
 * Station point binding: parses the attached station .bog as data, shows ranked
 * proxy-point suggestions per job point, and records only what the engineer
 * confirms. Nothing links without a confirmation; command points need an
 * explicit write priority between 2 and 16.
 */
function StationBindings() {
  const draft = useIntake((state) => state.draft);
  const files = useIntake((state) => state.files);
  const bindings = useIntake((state) => state.bindings);
  const confirmBinding = useIntake((state) => state.confirmBinding);
  // Keyed on the attached files, so a new station or points list re-reads
  // without effects or local state.
  const fileKey = (file: File | null) => (file ? `${file.name}:${file.size}:${file.lastModified}` : null);
  const suggest = useQuery({
    queryKey: ['station-bindings', fileKey(files.template), fileKey(files.points), draft.sequenceFamily],
    queryFn: () => api.stationBindings(buildStationBindingsForm(draft, files)),
    enabled: Boolean(files.template && files.points),
    staleTime: Infinity,
  });
  const result: StationBindingSuggestions | null = suggest.data ?? null;
  const mutate = () => void suggest.refetch();

  if (!files.template) {
    return (
      <div className="panel p-4 text-sm text-fg-1" role="region" aria-label="Station bindings">
        <span className="font-medium text-fg-0">Station points.</span> Attach a Niagara station template in Sources to link the program to its BACnet proxy points. Without one, the export carries writable Inputs and Outputs ready to link in Workbench.
      </div>
    );
  }
  if (suggest.isPending && !result) return <LoadingState label="Reading station points" />;
  if (suggest.isError && !result) return <ErrorState title="The station could not be read as data" error={suggest.error} onRetry={() => mutate()} />;
  if (!result) return null;

  const confirmedCount = Object.keys(bindings).length;
  return (
    <div className="panel flex flex-col gap-3 p-4" role="region" aria-label="Station bindings">
      <div className="flex items-center gap-2 flex-wrap">
        <Link2 size={14} />
        <span className="text-sm font-medium">Station points</span>
        <StatusPill tone="sim">{result.inventory.device_count} devices · {result.inventory.point_count} proxy points</StatusPill>
        <StatusPill tone={confirmedCount ? 'ok' : 'warn'}>{confirmedCount} confirmed</StatusPill>
        <span className="text-xs text-fg-2">Suggestions are ranked from names, BACnet object types, units and device grouping. Only confirmed rows link.</span>
      </div>
      <table className="w-full text-sm">
        <thead className="text-left">
          <tr className="hairline-b">
            <th className="eyebrow px-2 h-8 font-semibold">Job point</th>
            <th className="eyebrow px-2 h-8 font-semibold">Suggested proxy</th>
            <th className="eyebrow px-2 h-8 font-semibold">Why</th>
            <th className="eyebrow px-2 h-8 font-semibold">Priority</th>
            <th className="eyebrow px-2 h-8 font-semibold">Confirm</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line-1">
          {result.points.map((point) => (
            <BindingRow
              key={point.name}
              point={point.name}
              role={point.role}
              suggestions={result.suggestions[point.name] ?? []}
              confirmed={bindings[point.name] ?? null}
              onConfirm={(binding) => confirmBinding(point.name, binding)}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BindingRow({
  point,
  role,
  suggestions,
  confirmed,
  onConfirm,
}: {
  point: string;
  role: string;
  suggestions: BindingSuggestion[];
  confirmed: ConfirmedBinding | null;
  onConfirm: (binding: ConfirmedBinding | null) => void;
}) {
  const [choice, setChoice] = useState<string>(suggestions[0]?.ord ?? '');
  const isCommand = role === 'command' || role === 'setpoint';
  const [priority, setPriority] = useState<number>(suggestions[0]?.write_priority ?? 16);
  const selected = suggestions.find((item) => item.ord === choice) ?? null;
  const shortOrd = (ord: string) => ord.split('/').slice(-3).join('/');
  return (
    <tr>
      <td className="px-2 h-9 font-mono text-xs">{point}</td>
      <td className="px-2">
        {suggestions.length === 0 ? (
          <span className="text-xs text-fg-2">no candidate shares a name token</span>
        ) : (
          <NativeSelect aria-label={`Proxy for ${point}`} size="sm" value={choice} onChange={(event) => setChoice(event.target.value)} disabled={Boolean(confirmed)}>
            {suggestions.map((item) => (
              <option key={item.ord} value={item.ord}>
                {shortOrd(item.ord)} · {(item.score * 100).toFixed(0)}%
              </option>
            ))}
          </NativeSelect>
        )}
      </td>
      <td className="px-2 text-2xs text-fg-2">{selected?.reasons.join('; ') ?? '—'}</td>
      <td className="px-2">
        {isCommand ? (
          <Input aria-label={`Write priority for ${point}`} type="number" min={2} max={16} className="w-16" mono value={priority} onChange={(event) => setPriority(Number(event.target.value))} disabled={Boolean(confirmed)} />
        ) : (
          <span className="text-xs text-fg-2">read</span>
        )}
      </td>
      <td className="px-2">
        {confirmed ? (
          <Button variant="outline" size="sm" onClick={() => onConfirm(null)}>
            Unbind
          </Button>
        ) : (
          <Button size="sm" disabled={!selected || (isCommand && (priority < 2 || priority > 16))} onClick={() => selected && onConfirm({ niagara_ord: selected.ord, write_priority: isCommand ? priority : null })}>
            Confirm
          </Button>
        )}
      </td>
    </tr>
  );
}
