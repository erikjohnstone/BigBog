import { useLibraryCatalogs } from '../../api/queries';
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
  if (catalogs.isLoading) return <LoadingState label="Loading libraries" />;
  if (catalogs.isError || !catalogs.data) return <ErrorState error={catalogs.error ?? 'Libraries unavailable'} onRetry={() => catalogs.refetch()} />;

  return (
    <StageFrame>
      <header>
        <p className="eyebrow">Reference stack</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Libraries</h1>
      </header>
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
