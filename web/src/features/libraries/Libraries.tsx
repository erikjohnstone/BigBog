import { Compass, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import type { Catalog } from '../../api/client';
import type { CoverageProof, LibraryCoverage } from '../../api/client';
import { useCtrlFlowTemplates, useLibraryCatalogs, useLibraryCoverage, useProtocolSequences } from '../../api/queries';
import { Input, StatusPill, buttonClass } from '../../design-system/primitives';
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

type Entry = Record<string, unknown>;

/** Columns worth showing for any catalog entry, in priority order. */
const COLUMNS: Array<{ key: string; label: string }> = [
  { key: 'family', label: 'Family' },
  { key: 'group', label: 'Group' },
  { key: 'kind', label: 'Kind' },
  { key: 'method', label: 'Method' },
  { key: 'declaration', label: 'Declaration' },
  { key: 'product_status', label: 'Product status' },
  { key: 'status', label: 'Status' },
  { key: 'ir_translation_status', label: 'IR' },
  { key: 'niagara_translation_status', label: 'Niagara' },
  { key: 'translatable', label: 'Translatable' },
  { key: 'runtime_qualified', label: 'Runtime qualified' },
  { key: 'validation_fixture', label: 'Validation fixture' },
  { key: 'program_object_count', label: 'Program objects' },
  { key: 'input_count', label: 'Inputs' },
  { key: 'output_count', label: 'Outputs' },
];

function cell(value: unknown) {
  if (value === null || value === undefined || value === '') return <span className="text-fg-2">—</span>;
  if (typeof value === 'boolean' || value === 'True' || value === 'False') {
    const on = value === true || value === 'True';
    return (
      <StatusPill tone={on ? 'ok' : 'neutral'} icon={null}>
        {on ? 'yes' : 'no'}
      </StatusPill>
    );
  }
  if (typeof value === 'string' && /^(verified|proven|production|complete|qualified|ready)/i.test(value)) return <StatusPill tone="ok" icon={null}>{value}</StatusPill>;
  if (typeof value === 'string' && /^(catalog|blocked|unsupported|missing|not|failed|pending)/i.test(value)) return <StatusPill tone="warn" icon={null}>{value}</StatusPill>;
  if (typeof value === 'object') return <span className="text-fg-2">{Array.isArray(value) ? `${value.length} items` : 'object'}</span>;
  return <span>{String(value)}</span>;
}

function CatalogTable({ entries, query, label }: { entries: Entry[]; query: string; label: string }) {
  const columns = useMemo(() => COLUMNS.filter((column) => entries.some((entry) => entry[column.key] !== undefined)).slice(0, 5), [entries]);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return entries;
    return entries.filter((entry) => JSON.stringify([entry.id, entry.name, entry.filename, entry.family, entry.group]).toLowerCase().includes(needle));
  }, [entries, query]);
  const shown = filtered.slice(0, 200);
  return (
    <div className="overflow-auto max-h-[30rem] outline-none focus-visible:[box-shadow:inset_0_0_0_2px_var(--accent)]" tabIndex={0} role="region" aria-label={`${label} entries`}>
      <table className="w-full text-sm">
        <thead className="text-left sticky top-0 bg-bg-1">
          <tr className="hairline-b">
            <th className="eyebrow px-4 h-8 font-semibold">Entry</th>
            {columns.map((column) => (
              <th key={column.key} className="eyebrow px-4 h-8 font-semibold whitespace-nowrap">
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line-1">
          {shown.map((entry, index) => (
            <tr key={String(entry.id ?? entry.filename ?? index)}>
              <td className="px-4 py-1.5 min-w-56">
                <span className="block truncate text-fg-0">{String(entry.name ?? entry.filename ?? entry.id ?? '')}</span>
                <span className="block font-mono text-2xs text-fg-2 truncate">{String(entry.id ?? entry.relative_path ?? '')}</span>
              </td>
              {columns.map((column) => (
                <td key={column.key} className="px-4 py-1.5 text-xs whitespace-nowrap">
                  {cell(entry[column.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="px-4 py-2 text-2xs text-fg-2">
        {filtered.length === entries.length ? `${entries.length} entries` : `${filtered.length} of ${entries.length} entries`}
        {filtered.length > shown.length ? ` · first ${shown.length} shown, refine the filter` : ''}
      </p>
    </div>
  );
}

function CatalogCard({ id, catalog }: { id: string; catalog: Catalog }) {
  const [query, setQuery] = useState('');
  const lists = Object.entries(catalog).filter((pair): pair is [string, Entry[]] => Array.isArray(pair[1]) && pair[1].length > 0 && typeof pair[1][0] === 'object');
  const scalars = Object.entries(catalog).filter(([key, value]) => !['schema', 'source', 'license'].includes(key) && (typeof value === 'number' || typeof value === 'boolean'));
  return (
    <SectionCard
      title={names[id] ?? id}
      aside={
        <span className="inline-flex items-center gap-2">
          {catalog.license && <StatusPill tone="neutral" icon={null}>{catalog.license}</StatusPill>}
          {lists.length > 0 && (
            <span className="relative">
              <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-fg-2" aria-hidden />
              <Input aria-label={`Filter ${names[id] ?? id}`} className="pl-6 h-7 text-xs w-48" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter entries" />
            </span>
          )}
        </span>
      }
    >
      <KeyValue
        items={[
          ...(catalog.source ? [{ label: 'Source', value: <span className="font-mono text-xs">{catalog.source}</span> }] : []),
          ...(catalog.schema ? [{ label: 'Schema', value: <span className="font-mono text-xs">{catalog.schema}</span> }] : []),
          ...(typeof catalog.scope === 'string' ? [{ label: 'Scope', value: <span className="text-xs">{catalog.scope}</span> }] : []),
          ...(typeof catalog.support_policy === 'string' ? [{ label: 'Support policy', value: <span className="text-xs">{catalog.support_policy}</span> }] : []),
          ...(typeof catalog.policy === 'string' ? [{ label: 'Policy', value: <span className="text-xs">{catalog.policy}</span> }] : []),
          ...(typeof catalog.execution_path === 'string' ? [{ label: 'Execution path', value: <span className="font-mono text-xs">{catalog.execution_path}</span> }] : []),
          ...scalars.map(([key, value]) => ({ label: key.replaceAll('_', ' '), value: typeof value === 'boolean' ? cell(value) : <span className="num">{String(value)}</span> })),
        ]}
      />
      {lists.map(([key, entries]) => (
        <div key={key} className="hairline-t">
          <CatalogTable entries={entries} query={query} label={`${names[id] ?? id} ${key.replaceAll('_', ' ')}`} />
        </div>
      ))}
    </SectionCard>
  );
}

function proofCell(proof: CoverageProof): { tone: 'ok' | 'fail' | 'warn' | 'neutral'; text: string; title: string } {
  if (proof.passed) return { tone: 'ok', text: 'pass', title: 'passed' };
  if (proof.blocker) return { tone: 'neutral', text: 'blocked', title: proof.blocker };
  if (typeof proof.catch_rate === 'number') return { tone: 'warn', text: `${(proof.catch_rate * 100).toFixed(0)} %`, title: `${proof.caught ?? '?'} of ${proof.sample ?? '?'} mutants caught; target 95 %` };
  if (proof.failing_cases?.length) return { tone: 'fail', text: 'fail', title: proof.failing_cases.join(', ') };
  if (proof.errors?.length) return { tone: 'fail', text: 'fail', title: proof.errors[0] };
  if (proof.blockers?.length) return { tone: 'fail', text: 'fail', title: proof.blockers[0] };
  return { tone: 'fail', text: 'fail', title: 'failed' };
}

/**
 * D1–D4 per library configuration, from the committed coverage report
 * (scripts/coverage_report.py). Every cell that is not a pass carries its reason
 * in the title; a blocked row is a configuration the toolchain refused.
 */
/** Tier 3+ sequences built under the Test Generation Protocol, with Gate G-ENG. */
function ProtocolSequences() {
  const sequences = useProtocolSequences();
  return (
    <SectionCard
      title="Requirements (Tier 3+, Test Generation Protocol)"
      aside={
        <Link to="/libraries/requirements" className="text-xs text-accent">
          Open
        </Link>
      }
    >
      {sequences.data?.items.length ? (
        <ul className="divide-y divide-line-1">
          {sequences.data.items.map((item) => (
            <li key={item.sequence_id} className="flex items-center gap-3 px-4 h-10 text-sm">
              <span className="truncate">{item.title}</span>
              <span className="font-mono text-2xs text-fg-2 truncate">Tier {item.tier} · {item.requirements} requirements · {item.scenarios} scenarios</span>
              <span className="flex-1" />
              <StatusPill tone={item.gate_g_eng === 'approved' ? 'ok' : item.gate_g_eng === 'stale' ? 'warn' : 'neutral'}>
                Gate G-ENG {item.gate_g_eng}
              </StatusPill>
              <Link to={`/libraries/requirements/${encodeURIComponent(item.sequence_id)}`} className="text-xs text-accent whitespace-nowrap">
                Review
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="px-4 py-3 text-sm text-fg-2">No Tier 3 sequences yet.</p>
      )}
    </SectionCard>
  );
}

function CoverageMatrix({ coverage }: { coverage: LibraryCoverage }) {
  const summary = coverage.summary;
  return (
    <SectionCard
      title="Library coverage (D1–D4)"
      aside={
        <span className="inline-flex items-center gap-2 text-xs">
          <StatusPill tone={summary.all_four === summary.configurations ? 'ok' : 'warn'}>{summary.all_four}/{summary.configurations} pass all four</StatusPill>
          {summary.blocked > 0 && <StatusPill tone="neutral">{summary.blocked} blocked</StatusPill>}
          <StatusPill tone="sim">bog-simulated</StatusPill>
        </span>
      }
    >
      <p className="px-4 py-2 text-xs text-fg-2">D1 native by default · D2 statically valid · D3 Shadow Runtime, interpreter and reference agree · D4 {coverage.mutation_sample} seeded mutants caught at ≥ {(coverage.mutation_target * 100).toFixed(0)} %. Tier 1 expectations are cited from the guideline; Tier 2 expectations are reference-derived.</p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm whitespace-nowrap" aria-label="Library coverage matrix">
          <thead className="text-left">
            <tr className="hairline-b">
              {['Configuration', 'Controller', 'Variant', 'Tier', 'Scenarios', 'D1', 'D2', 'D3', 'D4'].map((label) => (
                <th key={label} className="eyebrow px-4 h-8 font-semibold">{label}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line-1">
            {coverage.items.map((item) => (
              <tr key={item.id}>
                <td className="px-4 h-8 font-mono text-xs">{item.id}</td>
                <td className="px-4 text-xs">{item.controller}</td>
                <td className="px-4 text-xs text-fg-1">
                  <span className="inline-flex items-center gap-2">
                    {item.variant}
                    {item.release === 'pre-release' && (
                      <span title="From an unreleased Modelica Buildings commit (master); not in a tagged release yet">
                        <StatusPill tone="warn">pre-release</StatusPill>
                      </span>
                    )}
                  </span>
                </td>
                <td className="px-4 num text-xs">{item.tier}</td>
                <td className="px-4 num text-xs">{item.scenarios ?? '—'}</td>
                {([item.d1, item.d2, item.d3, item.d4] as CoverageProof[]).map((proof, index) => {
                  const cell = proofCell(proof);
                  return (
                    <td key={index} className="px-4" title={cell.title}>
                      <StatusPill tone={cell.tone}>{cell.text}</StatusPill>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}

/** Library catalogs with provenance and a browsable, filterable entry list per catalog. */
export function Libraries() {
  const catalogs = useLibraryCatalogs();
  const templates = useCtrlFlowTemplates();
  const coverage = useLibraryCoverage();
  if (catalogs.isLoading) return <LoadingState label="Loading libraries" />;
  if (catalogs.isError || !catalogs.data) return <ErrorState error={catalogs.error ?? 'Libraries unavailable'} onRetry={() => catalogs.refetch()} />;

  return (
    <StageFrame wide>
      <header>
        <p className="eyebrow">Reference stack</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Libraries</h1>
        <p className="mt-2 text-sm text-fg-1">Pinned open references with their provenance. Presence in a catalog is not deployability; each entry states how far its evidence path goes.</p>
      </header>
      <SectionCard
        title="Design templates"
        aside={
          <Link to="/intake/design" className={buttonClass('outline', 'sm')}>
            <Compass size={13} /> Design with a template
          </Link>
        }
      >
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
      <ProtocolSequences />
      {coverage.data?.state === 'available' ? (
        <CoverageMatrix coverage={coverage.data.data} />
      ) : (
        <SectionCard title="Library coverage (D1–D4)">
          <p className="px-4 py-3 text-sm text-fg-2">No coverage report is committed for this build; run scripts/coverage_report.py.</p>
        </SectionCard>
      )}
      {Object.entries(catalogs.data).map(([id, catalog]) => (
        <CatalogCard key={id} id={id} catalog={catalog} />
      ))}
    </StageFrame>
  );
}
