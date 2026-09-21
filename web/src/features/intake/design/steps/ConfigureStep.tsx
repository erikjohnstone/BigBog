import { useMemo } from 'react';

import { useCtrlFlowConfiguration } from '../../../../api/queries';
import { NativeSelect, StatusPill } from '../../../../design-system/primitives';
import { ErrorState, LoadingState } from '../../../../design-system/states';
import { EMPTY_SELECTIONS, useDesign } from '../../../../stores/design';

/** Schema-driven configuration: every visible choice the template exposes. */
export function ConfigureStep({ templateId }: { templateId: string }) {
  const selections = useDesign((store) => store.byTemplate[templateId]?.selections ?? EMPTY_SELECTIONS);
  const patch = useDesign((store) => store.patch);
  const configuration = useCtrlFlowConfiguration(templateId, selections);
  const groups = useMemo(() => {
    const map = new Map<string, NonNullable<typeof configuration.data>['fields']>();
    for (const field of configuration.data?.fields ?? []) {
      const key = ((field as { groups?: string[] }).groups ?? ['Configuration']).slice(1).join(' › ') || 'Configuration';
      map.set(key, [...(map.get(key) ?? []), field]);
    }
    return [...map.entries()];
  }, [configuration.data]);

  if (configuration.isLoading && !configuration.data) return <LoadingState label="Evaluating the template" />;
  if (configuration.isError || !configuration.data) return <ErrorState error={configuration.error ?? 'Configuration unavailable'} onRetry={() => configuration.refetch()} />;
  const data = configuration.data;

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-start gap-3 flex-wrap">
        <div className="flex-1 min-w-64">
          <p className="eyebrow">Gate 1</p>
          <h2 className="text-xl font-semibold tracking-tight">{data.template.name}</h2>
          <p className="text-sm text-fg-1 mt-1">Choices are evaluated by the LBNL linkage semantics; dependent options appear as you choose. Rejected selections are listed, never silently dropped.</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <StatusPill tone="neutral" icon={null}>{data.accepted_selection_count} accepted</StatusPill>
          {data.rejected_selection_count > 0 && <StatusPill tone="warn">{data.rejected_selection_count} rejected</StatusPill>}
          <span className="num text-fg-2 self-center" title="Configuration digest">{data.configuration_digest.slice(0, 12)}</span>
        </div>
      </div>
      {groups.map(([group, fields]) => (
        <div key={group} className="panel">
          <header className="px-4 h-9 flex items-center hairline-b">
            <h3 className="text-sm font-medium">{group}</h3>
          </header>
          <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-3">
            {fields.map((field) => {
              const choices = field.choices ?? [];
              const booleans = field.boolean_choices ?? [];
              const value = field.value === null || field.value === undefined ? '' : String(field.value);
              return (
                <label key={field.selection_path} className="flex flex-col gap-1 text-xs text-fg-1">
                  <span className="truncate" title={field.selection_path}>
                    {field.name}
                  </span>
                  {choices.length > 0 || booleans.length > 0 ? (
                    <NativeSelect
                      value={value}
                      onChange={(event) => {
                        const raw = event.target.value;
                        const next = booleans.length > 0 ? raw === 'true' : raw;
                        patch(templateId, (current) => ({ selections: { ...current.selections, [field.selection_path]: next }, brief: null }));
                      }}
                      aria-label={field.name}
                    >
                      {booleans.map((choice) => (
                        <option key={String(choice)} value={String(choice)}>
                          {choice ? 'Yes' : 'No'}
                        </option>
                      ))}
                      {choices.map((choice) => (
                        <option key={choice.value} value={choice.value}>
                          {choice.label}
                        </option>
                      ))}
                    </NativeSelect>
                  ) : (
                    <span className="font-mono text-2xs text-fg-2">{value || '—'}</span>
                  )}
                  <span className="font-mono text-2xs text-fg-2 truncate">{field.instance_path}</span>
                </label>
              );
            })}
          </div>
        </div>
      ))}
      {data.rejected_selections.length > 0 && (
        <div className="rounded-panel border border-warn/40 bg-warn-soft p-3 text-xs">
          <strong>Rejected selections</strong>
          <ul className="mt-1 font-mono">
            {data.rejected_selections.map((item, index) => (
              <li key={index}>{JSON.stringify(item)}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
