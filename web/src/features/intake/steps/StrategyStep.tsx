import { useMemo, useState } from 'react';

import { useLibraryCatalogs } from '../../../api/queries';
import { cn } from '../../../design-system/cn';
import { Field, Input, NativeSelect } from '../../../design-system/primitives';
import { useIntake } from '../../../stores/intake';
import { AcceptanceTestsEditor } from '../editors/AcceptanceTestsEditor';
import { JsonDisclosure } from '../editors/JsonDisclosure';
import { KeyValueEditor } from '../editors/KeyValueEditor';
import { controllerRows, families, familyById } from '../families';

export function StrategyStep({ errors }: { errors: Record<string, string> }) {
  const draft = useIntake((state) => state.draft);
  const inspection = useIntake((state) => state.inspection);
  const update = useIntake((state) => state.update);
  const catalogs = useLibraryCatalogs();
  const family = familyById(draft.sequenceFamily);
  const [controllerQuery, setControllerQuery] = useState('');
  const controllers = useMemo(() => {
    if (!family?.library) return [];
    const rows = controllerRows(family.library === 'g36' ? catalogs.data?.g36 : catalogs.data?.plant).filter((row) => !row.fixture);
    const needle = controllerQuery.trim().toLowerCase();
    return (needle ? rows.filter((row) => row.id.toLowerCase().includes(needle) || row.name.toLowerCase().includes(needle)) : rows).slice(0, 60);
  }, [family, catalogs.data, controllerQuery]);
  const pointNames = inspection?.points.map((point) => point.name) ?? [];

  return (
    <section className="flex flex-col gap-6">
      <div>
        <p className="eyebrow">Step 4</p>
        <h2 className="text-xl font-semibold tracking-tight">Choose the programming strategy</h2>
        <p className="text-sm text-fg-1 mt-1">A family decides which typed program is generated and which simulator tests it. Library lanes translate a pinned LBNL controller exactly.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-2" role="radiogroup" aria-label="Sequence family">
        {families.map((item) => {
          const selected = draft.sequenceFamily === item.id;
          return (
            <button
              key={item.id}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => update({ sequenceFamily: item.id, controllerId: item.library ? draft.controllerId : '' })}
              className={cn('text-left rounded-panel border p-3 hover:bg-bg-2', selected ? 'border-accent bg-accent-soft/40' : 'border-line-1')}
            >
              <span className="block text-sm font-medium">{item.label}</span>
              <span className="block text-2xs text-fg-2 mt-0.5">{item.detail}</span>
              <span className="block font-mono text-2xs text-fg-2 mt-1">{item.id}</span>
            </button>
          );
        })}
      </div>

      {family?.library && (
        <div className="panel p-4 flex flex-col gap-3">
          <Field label="Exact controller id" hint={`From the pinned ${family.library === 'g36' ? 'Guideline 36' : 'plant controls'} library.`} error={errors.controllerId} htmlFor="intake-controller">
            <div className="flex flex-col gap-2">
              <Input placeholder="Filter controllers" value={controllerQuery} onChange={(event) => setControllerQuery(event.target.value)} aria-label="Filter controllers" />
              <NativeSelect id="intake-controller" value={draft.controllerId} onChange={(event) => update({ controllerId: event.target.value })}>
                <option value="">Choose a controller…</option>
                {controllers.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.id} · {row.family}
                  </option>
                ))}
              </NativeSelect>
            </div>
          </Field>
          <Field label="Execution semantics" htmlFor="intake-profile">
            <NativeSelect id="intake-profile" value={draft.executionProfile} onChange={(event) => update({ executionProfile: event.target.value as 'modelica_exact' | 'host_tick_v1' })}>
              <option value="modelica_exact">Modelica exact</option>
              <option value="host_tick_v1">Niagara host tick · explicit sampled profile</option>
            </NativeSelect>
          </Field>
        </div>
      )}

      <div className="panel p-4 flex flex-col gap-2">
        <h3 className="text-sm font-medium">Sequence parameters</h3>
        <p className="text-2xs text-fg-2">Tunable values the family reads, such as loop spans, minimum positions, and alarm limits.</p>
        <KeyValueEditor rows={draft.parameters} onChange={(parameters) => update({ parameters })} keyPlaceholder="minimum_damper_pct" valuePlaceholder="20" />
        <JsonDisclosure<Record<string, unknown>>
          value={Object.fromEntries(draft.parameters.filter((row) => row.key.trim()).map((row) => [row.key.trim(), Number.isFinite(Number(row.value)) && row.value.trim() !== '' ? Number(row.value) : row.value]))}
          onCommit={(value) => update({ parameters: Object.entries(value).map(([key, item]) => ({ key, value: typeof item === 'string' ? item : JSON.stringify(item) })) })}
          validate={(parsed) => (parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : 'Parameters must be a JSON object.')}
        />
      </div>

      <div className="panel p-4 flex flex-col gap-2">
        <h3 className="text-sm font-medium">
          Acceptance tests <span className="text-2xs text-fg-2 font-normal">{family?.requiresTests ? 'required for AI custom' : 'optional; the family ships its own'}</span>
        </h3>
        <AcceptanceTestsEditor cases={draft.acceptanceTests} onChange={(acceptanceTests) => update({ acceptanceTests })} pointNames={pointNames} error={errors.acceptanceTests ?? Object.entries(errors).find(([key]) => key.startsWith('acceptanceTests.'))?.[1]} />
      </div>

      <div className="panel p-4 flex flex-col gap-2">
        <h3 className="text-sm font-medium">Deliverable requirements</h3>
        <p className="text-2xs text-fg-2">Shop profile, alarms, histories, and graphics the deliverable must carry. Leave empty for the family defaults.</p>
        <JsonDisclosure<Record<string, unknown>>
          label="Deliverable requirements JSON"
          value={(() => {
            try {
              return JSON.parse(draft.deliverableRequirements || '{}') as Record<string, unknown>;
            } catch {
              return {};
            }
          })()}
          onCommit={(value) => update({ deliverableRequirements: JSON.stringify(value, null, 2) })}
          validate={(parsed) => (parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : 'Deliverable requirements must be a JSON object.')}
        />
        {errors.deliverableRequirements && <p role="alert" className="text-2xs text-fail">{errors.deliverableRequirements}</p>}
      </div>
    </section>
  );
}
