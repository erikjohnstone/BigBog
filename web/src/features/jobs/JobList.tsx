import { Plus, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import type { RunSummary } from '../../api/client';
import { useRuns } from '../../api/queries';
import { cn } from '../../design-system/cn';
import { buttonClass, Input, StatusPill, runStatusTone } from '../../design-system/primitives';
import { EmptyState, ErrorState, LoadingState } from '../../design-system/states';

type Facet = 'all' | 'ready_for_review' | 'failed' | 'approved' | 'ai_proposal' | 'qualification';

const facets: Array<{ id: Facet; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'ready_for_review', label: 'Awaiting review' },
  { id: 'failed', label: 'Failed' },
  { id: 'approved', label: 'Approved' },
  { id: 'ai_proposal', label: 'AI proposals' },
  { id: 'qualification', label: 'With simulation evidence' },
];

function matchesFacet(run: RunSummary, facet: Facet): boolean {
  switch (facet) {
    case 'all':
      return true;
    case 'ai_proposal':
      return run.origin === 'ai_proposal';
    case 'qualification':
      return Boolean(run.boptest_verification_path || run.alfalfa_verification_path);
    default:
      return run.status === facet;
  }
}

/** One list for every job, replacing the duplicated studio/simulation indexes. */
export function JobList() {
  const runs = useRuns();
  const [params, setParams] = useSearchParams();
  const facet = (params.get('facet') as Facet | null) ?? 'all';
  const [query, setQuery] = useState('');

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (runs.data ?? [])
      .filter((run) => matchesFacet(run, facet))
      .filter(
        (run) =>
          !needle ||
          run.job.name.toLowerCase().includes(needle) ||
          run.job.equipment_name.toLowerCase().includes(needle) ||
          run.job.site.toLowerCase().includes(needle) ||
          run.id.startsWith(needle),
      );
  }, [runs.data, facet, query]);

  if (runs.isLoading) return <LoadingState label="Loading jobs" />;
  if (runs.isError) return <ErrorState error={runs.error} onRetry={() => runs.refetch()} />;

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-6xl mx-auto px-6 py-6 flex flex-col gap-4">
        <header className="flex items-center gap-3 flex-wrap">
          <h1 className="text-xl font-semibold tracking-tight">Jobs</h1>
          <span className="num text-fg-2">{rows.length}</span>
          <div className="flex-1" />
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-2" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Filter by name, equipment, site, id"
              aria-label="Filter jobs"
              className="pl-8 w-72"
            />
          </div>
          <Link to="/intake" className={buttonClass('primary', 'md')}>
            <Plus size={14} /> New job
          </Link>
        </header>

        <nav aria-label="Job facets" className="flex gap-1 flex-wrap">
          {facets.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setParams(item.id === 'all' ? {} : { facet: item.id })}
              aria-pressed={facet === item.id}
              className={cn(
                'h-7 px-2.5 rounded-pill text-xs border transition-colors duration-[var(--duration-micro)]',
                facet === item.id ? 'bg-bg-2 border-line-2 text-fg-0' : 'border-transparent text-fg-1 hover:bg-bg-2',
              )}
            >
              {item.label}
            </button>
          ))}
        </nav>

        {rows.length === 0 ? (
          <EmptyState
            title="No jobs match"
            detail={facet === 'all' && !query ? 'Create a job from contractor documents to start.' : 'Try another facet or filter.'}
            action={
              facet === 'all' && !query ? (
                <Link to="/intake" className={buttonClass('primary')}>
                  <Plus size={14} /> New job
                </Link>
              ) : undefined
            }
          />
        ) : (
          <div className="panel overflow-x-auto">
            <table className="w-full text-sm whitespace-nowrap">
              <thead className="text-left">
                <tr className="hairline-b">
                  <th className="eyebrow px-4 h-9 font-semibold">Job</th>
                  <th className="eyebrow px-4 h-9 font-semibold">Equipment</th>
                  <th className="eyebrow px-4 h-9 font-semibold">Sequence</th>
                  <th className="eyebrow px-4 h-9 font-semibold">Status</th>
                  <th className="eyebrow px-4 h-9 font-semibold">Evidence</th>
                  <th className="eyebrow px-4 h-9 font-semibold text-right">Id</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line-1">
                {rows.map((run) => (
                  <JobRow key={run.id} run={run} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function JobRow({ run }: { run: RunSummary }) {
  const status = runStatusTone(run.status);
  const evidence: string[] = [];
  if (run.bacnet_lab_manifest_path) evidence.push('BACnet lab');
  if (run.boptest_verification_path) evidence.push('BOPTEST');
  if (run.alfalfa_verification_path) evidence.push('Alfalfa');
  return (
    <tr className="hover:bg-bg-2 transition-colors">
      <td className="px-4 h-12">
        <Link to={`/jobs/${run.id}/build`} className="block">
          <span className="block truncate max-w-xs">{run.job.name}</span>
          <span className="block text-xs text-fg-2 truncate max-w-xs">{run.job.site}</span>
        </Link>
      </td>
      <td className="px-4 font-mono text-xs">{run.job.equipment_name}</td>
      <td className="px-4 text-xs text-fg-1">{run.job.sequence.family}</td>
      <td className="px-4">
        <span className="inline-flex gap-1.5">
          {run.origin === 'ai_proposal' && <StatusPill tone="sim">AI</StatusPill>}
          <StatusPill tone={status.tone}>{status.label}</StatusPill>
        </span>
      </td>
      <td className="px-4 text-xs text-fg-1">
        {evidence.length ? (
          <span className="inline-flex gap-1">
            {evidence.map((item) => (
              <StatusPill key={item} tone="sim" icon={null}>
                {item}
              </StatusPill>
            ))}
          </span>
        ) : (
          <span className="text-fg-2">Deterministic only</span>
        )}
      </td>
      <td className="px-4 text-right num text-fg-2">{run.id.slice(0, 8)}</td>
    </tr>
  );
}
