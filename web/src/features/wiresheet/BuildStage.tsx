import { useMemo } from 'react';

import type { RunDetail } from '../../api/client';
import { useGraph } from '../../api/queries';
import { ErrorState, LoadingState } from '../../design-system/states';
import { KeyValue, SectionCard, StageFrame } from '../shared/StageFrame';

/**
 * Build stage. Phase 2 replaces this outline with the animated wiresheet;
 * until then it lists exactly what the retained control graph contains.
 */
export function BuildStage({ run }: { run: RunDetail }) {
  const graph = useGraph(run.id);
  const byKind = useMemo(() => {
    const map = new Map<string, number>();
    for (const block of graph.data?.blocks ?? []) map.set(block.kind, (map.get(block.kind) ?? 0) + 1);
    return [...map.entries()].sort((a, b) => b[1] - a[1]);
  }, [graph.data]);

  if (graph.isLoading) return <LoadingState label="Loading control graph" />;
  if (graph.isError || !graph.data) return <ErrorState error={graph.error ?? 'Graph unavailable'} onRetry={() => graph.refetch()} />;

  return (
    <StageFrame wide>
      <SectionCard title={graph.data.name}>
        <KeyValue
          items={[
            { label: 'Blocks', value: <span className="num">{graph.data.blocks.length}</span> },
            { label: 'Links', value: <span className="num">{graph.data.links.length}</span> },
            { label: 'Artifact', value: <span className="num">{run.artifact_sha256}</span> },
          ]}
        />
      </SectionCard>
      <SectionCard title="Blocks by kind">
        <ul className="divide-y divide-line-1">
          {byKind.map(([kind, count]) => (
            <li key={kind} className="flex items-center justify-between px-4 h-9 text-sm">
              <span className="font-mono text-xs">{kind}</span>
              <span className="num text-fg-2">{count}</span>
            </li>
          ))}
        </ul>
      </SectionCard>
      <SectionCard title="Blocks">
        <ul className="divide-y divide-line-1">
          {graph.data.blocks.map((block) => (
            <li key={block.id} className="flex items-center gap-3 px-4 h-9 text-sm">
              <span className="font-mono text-xs text-fg-2 w-40 truncate">{block.id}</span>
              <span className="truncate">{block.label}</span>
              <span className="flex-1" />
              <span className="font-mono text-2xs text-fg-2">{block.kind}</span>
            </li>
          ))}
        </ul>
      </SectionCard>
    </StageFrame>
  );
}
