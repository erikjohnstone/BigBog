import { ChevronDown, ChevronRight, FolderTree } from 'lucide-react';
import { useMemo, useState } from 'react';

import { useNiagaraPreviews } from '../../api/queries';
import { StatusPill } from '../../design-system/primitives';
import { MissingEvidence } from '../../design-system/states';

/**
 * An SVG document as an image source. The previews are hundreds of elements
 * each; as `<img>` the browser rasterizes them once and caches the bitmap,
 * so scrubbing the wiresheet next door never pays for them frame by frame.
 * The SVG comes from our own server, rendered from the retained artifact.
 */
function svgSource(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

/**
 * Wiresheet previews of the exported .bog, one per Niagara folder. The
 * server renders each folder from the artifact itself, so what is shown is
 * the exported station layout, not the editable control graph.
 */
export function NiagaraFolders({ runId, defaultOpen = true }: { runId: string; defaultOpen?: boolean }) {
  const previews = useNiagaraPreviews(runId);
  const [open, setOpen] = useState(defaultOpen);
  const available = previews.data?.state === 'available' ? previews.data.data : undefined;
  const cards = useMemo(() => (available ? available.folders.map((folder) => ({ name: folder.name, src: svgSource(folder.svg) })) : []), [available]);
  return (
    <section aria-label="Niagara folders" className="flex flex-col min-h-0 hairline-t">
      <header className="sticky top-0 z-10 bg-bg-1 hairline-b px-3 h-9 flex items-center gap-2 shrink-0">
        <button type="button" className="inline-flex items-center gap-1.5 text-fg-1 hover:text-fg-0" onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-controls={`niagara-folders-${runId}`}>
          {open ? <ChevronDown size={12} aria-hidden /> : <ChevronRight size={12} aria-hidden />}
          <FolderTree size={12} aria-hidden />
          <span className="eyebrow">Niagara folders</span>
        </button>
        {cards.length > 0 && <span className="num text-fg-2">{cards.length}</span>}
        <span className="flex-1" />
        <StatusPill tone="sim" icon={null}>
          exported .bog
        </StatusPill>
      </header>
      {open && (
        <div id={`niagara-folders-${runId}`} className="overflow-auto min-h-0">
          {previews.isLoading ? (
            <p className="px-3 py-3 text-xs text-fg-2">Loading previews…</p>
          ) : previews.data?.state !== 'available' ? (
            <MissingEvidence kind="Niagara preview" state={previews.data?.state === 'invalid' ? 'invalid' : 'missing'} detail={previews.data?.state === 'invalid' ? previews.data.message : 'No wiresheet previews were rendered for this candidate. They appear once the .bog is exported.'} />
          ) : cards.length === 0 ? (
            <p className="px-3 py-3 text-xs text-fg-2">The exported .bog has no folders to preview.</p>
          ) : (
            <ul className="p-3 grid gap-3 grid-cols-[repeat(auto-fill,minmax(11rem,1fr))]" aria-label="Folder previews">
              {cards.map((card) => (
                <li key={card.name} className="raised flex flex-col min-w-0 overflow-hidden">
                  <span className="px-2 h-7 flex items-center font-mono text-2xs text-fg-1 truncate hairline-b" title={card.name}>
                    {card.name}
                  </span>
                  <a href={card.src} target="_blank" rel="noreferrer" className="block bg-bg-0 p-1" title={`Open the ${card.name} wiresheet preview full size`}>
                    <img src={card.src} alt={`Niagara folder ${card.name}`} className="w-full h-auto max-h-48 object-contain object-top" loading="lazy" decoding="async" />
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
