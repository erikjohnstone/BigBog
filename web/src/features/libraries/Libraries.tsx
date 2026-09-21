import { Compass } from 'lucide-react';
import { Link } from 'react-router-dom';

import { useCtrlFlowTemplates, useLibraryCatalogs } from '../../api/queries';
import { buttonClass } from '../../design-system/primitives';
import { ErrorState, LoadingState } from '../../design-system/states';
import { KeyValue, SectionCard, StageFrame } from '../shared/StageFrame';

const names: Record<string, string> = {
  g36: 'ASHRAE Guideline 36 controllers',
  plant: 'Plant control controllers',
  faults: 'Open Control fault library',
  aixocat: 'aixocat patterns',
  niagara: 'Niagara programs',
  ctrlFlow: 'ctrl-flow design templates',
};

/** Library catalogs with provenance. The template browser arrives in Phase 9. */
export function Libraries() {
  const catalogs = useLibraryCatalogs();
  const templates = useCtrlFlowTemplates();
  if (catalogs.isLoading) return <LoadingState label="Loading libraries" />;
  if (catalogs.isError || !catalogs.data) return <ErrorState error={catalogs.error ?? 'Libraries unavailable'} onRetry={() => catalogs.refetch()} />;

  return (
    <StageFrame>
      <header>
        <p className="eyebrow">Reference stack</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Libraries</h1>
      </header>
      <SectionCard title="Design templates" aside={<Link to="/intake/design" className={buttonClass('outline', 'sm')}><Compass size={13} /> Design with a template</Link>}>
        {templates.data?.templates.length ? (
          <ul className="divide-y divide-line-1">
            {templates.data.templates.map((template) => (
              <li key={template.id} className="flex items-center gap-3 px-4 h-10 text-sm">
                <span className="truncate">{template.name}</span>
                <span className="font-mono text-2xs text-fg-2 truncate">{template.id}</span>
                <span className="flex-1" />
                <Link to={`/intake/design/${encodeURIComponent(template.id)}/configure`} className="text-xs text-accent whitespace-nowrap">
                  Design with this template
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-4 py-3 text-sm text-fg-2">No ctrl-flow templates are installed; the full bootstrap adds them.</p>
        )}
      </SectionCard>
      {Object.entries(catalogs.data).map(([id, catalog]) => {
        const entries = Object.entries(catalog).filter(([, value]) => Array.isArray(value));
        return (
          <SectionCard key={id} title={names[id] ?? id}>
            <KeyValue
              items={[
                ...(catalog.source ? [{ label: 'Source', value: <span className="font-mono text-xs">{catalog.source}</span> }] : []),
                ...(catalog.license ? [{ label: 'License', value: catalog.license }] : []),
                ...(catalog.schema ? [{ label: 'Schema', value: <span className="font-mono text-xs">{catalog.schema}</span> }] : []),
                ...entries.map(([key, value]) => ({
                  label: key.replaceAll('_', ' '),
                  value: <span className="num">{(value as unknown[]).length}</span>,
                })),
              ]}
            />
          </SectionCard>
        );
      })}
    </StageFrame>
  );
}
