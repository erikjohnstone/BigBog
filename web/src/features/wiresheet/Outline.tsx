import { useMemo } from 'react';

import { cn } from '../../design-system/cn';
import { useSelection } from '../../stores/selection';
import { FAMILIES, familyColor, familyLabel } from './graph-model';
import type { BlockNode, Family } from './graph-model';

/** Blocks grouped by family; clicking pans the sheet to the block. */
export function Outline({ nodes, onFocus }: { nodes: BlockNode[]; onFocus: (id: string) => void }) {
  const selected = useSelection((state) => state.blockIds);
  const groups = useMemo(() => {
    const map = new Map<Family, BlockNode[]>();
    for (const node of nodes) {
      if (node.data.diff === 'removed') continue;
      map.set(node.data.family, [...(map.get(node.data.family) ?? []), node]);
    }
    return FAMILIES.filter((family) => map.has(family)).map((family) => ({
      family,
      nodes: (map.get(family) ?? []).sort((a, b) => a.data.rank - b.data.rank || a.id.localeCompare(b.id)),
    }));
  }, [nodes]);

  return (
    <nav aria-label="Block outline" className="h-full overflow-auto text-sm">
      <header className="sticky top-0 z-10 bg-bg-1 hairline-b px-3 h-9 flex items-center gap-2">
        <span className="eyebrow">Outline</span>
        <span className="num text-fg-2">{nodes.filter((node) => node.data.diff !== 'removed').length}</span>
      </header>
      {groups.map((group) => (
        <section key={group.family} className="py-1">
          <h2 className="px-3 h-7 flex items-center gap-2 text-2xs uppercase tracking-wider text-fg-2 font-medium">
            <span className="size-1.5 rounded-pill" style={{ background: familyColor(group.family) }} aria-hidden />
            {familyLabel[group.family]}
            <span className="num">{group.nodes.length}</span>
          </h2>
          <ul>
            {group.nodes.map((node) => (
              <li key={node.id}>
                <button
                  type="button"
                  onClick={() => onFocus(node.id)}
                  aria-current={selected.has(node.id) ? 'true' : undefined}
                  className={cn(
                    'w-full text-left flex items-center gap-2 px-3 h-7 hover:bg-bg-2',
                    selected.has(node.id) && 'bg-accent-soft text-fg-0',
                  )}
                >
                  <span className="truncate flex-1 min-w-0 text-xs">{node.data.label}</span>
                  {node.data.coverage && (
                    <span className={cn('size-1.5 rounded-pill shrink-0', node.data.coverage.bothOutcomes ? 'bg-ok' : 'bg-warn')} aria-hidden />
                  )}
                  {node.data.diff && (
                    <span className={cn('text-2xs font-mono', node.data.diff === 'added' ? 'text-accent' : 'text-warn')}>
                      {node.data.diff === 'added' ? '+' : '~'}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </nav>
  );
}
