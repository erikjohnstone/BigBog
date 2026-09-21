import { useQuery } from '@tanstack/react-query';
import { Download, Package } from 'lucide-react';

import type { ReleaseSummary } from '../../api/client';
import { ForbiddenState } from '../../design-system/states';
import { SectionCard } from '../shared/StageFrame';

/**
 * Ask the server whether the export is actually served. The route answers
 * GET only, so the probe opens the download and cancels the body as soon as
 * the status is known; nothing is stored.
 */
async function probeExport(url: string): Promise<{ ok: boolean; status: number }> {
  const response = await fetch(url, { cache: 'no-store' });
  await response.body?.cancel().catch(() => undefined);
  return { ok: response.ok, status: response.status };
}

/**
 * The hand-off to a licensed Workbench. Downloads exist only once the
 * server records an approval; a 403 renders as a refusal, never as a
 * broken link. The import boundary is repeated here, at the decision point.
 */
export function ExportHandoff({ summary }: { summary: ReleaseSummary }) {
  const approved = summary.status === 'approved' && summary.downloads.available && summary.downloads.target_url;
  const access = useQuery({
    queryKey: ['export-access', summary.run_id, summary.downloads.target_url],
    queryFn: () => probeExport(summary.downloads.target_url!),
    enabled: Boolean(approved),
    retry: false,
    staleTime: 60_000,
  });

  return (
    <SectionCard title="Hand-off">
      {!approved ? (
        <div className="px-4 py-3 text-sm flex flex-col gap-1">
          <p className="text-fg-1">Downloads unlock only after approval. The server enforces this.</p>
          <p className="text-xs text-fg-2">Approve the candidate on the Review stage against its digest; the approved target and the review bundle appear here.</p>
        </div>
      ) : access.data && !access.data.ok ? (
        <ForbiddenState compact title={access.data.status === 403 ? 'Export refused' : `Export unavailable (${access.data.status})`} detail="The server refused to serve the approved target for this session. Approval and export are decided server-side; check your role and the candidate's status." />
      ) : (
        <div className="px-4 py-3 text-sm flex flex-col gap-3">
          <div className="flex flex-wrap gap-3">
            <span className="raised inline-flex items-center gap-2 px-3 h-9">
              <a className="inline-flex items-center gap-2 text-accent" href={summary.downloads.target_url!} download>
                <Download size={14} /> Approved target
              </a>
              {summary.target.filename && <span className="num text-2xs text-fg-2">{summary.target.filename}</span>}
            </span>
            {summary.downloads.review_bundle_url && (
              <a className="raised inline-flex items-center gap-2 px-3 h-9 text-accent" href={summary.downloads.review_bundle_url} download>
                <Package size={14} /> Review bundle
              </a>
            )}
          </div>
          <ol className="list-decimal pl-5 text-xs text-fg-1 flex flex-col gap-0.5">
            <li>Download the approved target; its digest is recorded with the approval.</li>
            <li>Import it manually into a licensed Workbench. {summary.target.manual_import_required ? 'Manual import is required; nothing here deploys.' : ''}</li>
            <li>Field qualification is a separate, human step. {summary.target.licensed_runtime_qualified ? 'The target passed the licensed-runtime qualification tier.' : 'This candidate has not been qualified on a licensed runtime.'}</li>
          </ol>
          <p className="text-2xs text-fg-2">Live writes are never enabled. Approval does not authorize live deployment.</p>
        </div>
      )}
    </SectionCard>
  );
}
