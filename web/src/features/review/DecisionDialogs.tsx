import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { ApiError, api } from '../../api/client';
import type { RunDetail } from '../../api/client';
import { keys } from '../../api/queries';
import { Button, Dialog, Field, Input, Textarea } from '../../design-system/primitives';

const REVIEWER_KEY = 'bactalk.reviewer';

function readReviewer(): string {
  try {
    return localStorage.getItem(REVIEWER_KEY) ?? '';
  } catch {
    return '';
  }
}

function rememberReviewer(name: string): void {
  try {
    localStorage.setItem(REVIEWER_KEY, name);
  } catch {
    // convenience only
  }
}

/** Turn an approval or rejection failure into what the reviewer should do next. */
export function explainDecisionError(error: unknown): { title: string; detail: string; reload: boolean } {
  if (error instanceof ApiError) {
    if (error.status === 412) return { title: 'The artifact changed since you opened this review', detail: error.message, reload: true };
    if (error.status === 409) return { title: 'This candidate cannot take that decision', detail: error.message, reload: true };
    if (error.status === 403 || error.status === 401) return { title: 'Not permitted', detail: error.message, reload: false };
    if (error.status === 422) return { title: 'The request was incomplete', detail: error.message, reload: false };
    return { title: 'The server refused the decision', detail: error.message, reload: false };
  }
  return { title: 'The decision did not reach the server', detail: error instanceof Error ? error.message : String(error), reload: false };
}

function useDecision(run: RunDetail, onDone: () => void) {
  const queryClient = useQueryClient();
  return {
    settle: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.run(run.id) }),
        queryClient.invalidateQueries({ queryKey: keys.runs }),
        queryClient.invalidateQueries({ queryKey: keys.releaseSummary(run.id) }),
      ]);
      onDone();
    },
    reload: () => {
      void queryClient.invalidateQueries({ queryKey: keys.run(run.id) });
      void queryClient.invalidateQueries({ queryKey: keys.releaseSummary(run.id) });
      onDone();
    },
  };
}

function DecisionError({ error, onReload }: { error: unknown; onReload: () => void }) {
  const explained = explainDecisionError(error);
  return (
    <div role="alert" className="raised border-fail/50 px-3 py-2 text-sm">
      <p className="font-medium text-fail">{explained.title}</p>
      <p className="mt-0.5 text-xs text-fg-1 break-words">{explained.detail}</p>
      {explained.reload && (
        <Button size="xs" variant="outline" className="mt-2" onClick={onReload}>
          Reload the candidate
        </Button>
      )}
    </div>
  );
}

/**
 * Approval is bound to the digest the reviewer inspected: the request carries
 * the artifact_sha256 loaded when the page opened, and the server refuses it
 * (412) if the candidate changed underneath.
 */
export function ApproveDialog({ run, inspectedDigest, open, onOpenChange, selfAsserted }: { run: RunDetail; inspectedDigest: string; open: boolean; onOpenChange: (open: boolean) => void; selfAsserted: boolean }) {
  const [reviewer, setReviewer] = useState(readReviewer);
  const { settle, reload } = useDecision(run, () => onOpenChange(false));
  const approve = useMutation({
    mutationFn: () => api.approve(run.id, { reviewer: selfAsserted ? reviewer.trim() : null, artifact_sha256: inspectedDigest }),
    onSuccess: async () => {
      if (selfAsserted) rememberReviewer(reviewer.trim());
      await settle();
    },
  });
  const digestChanged = run.artifact_sha256 !== inspectedDigest;
  const ready = !digestChanged && (!selfAsserted || reviewer.trim().length >= 2);
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Approve this candidate"
      description="Approval is recorded against the exact digest below by a named engineer. It unlocks export only; it never enables a live write."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => approve.mutate()} disabled={!ready || approve.isPending}>
            {approve.isPending ? 'Approving…' : 'Approve'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="raised px-3 py-2">
          <div className="text-2xs text-fg-2">Artifact digest you inspected</div>
          <div className="num text-xs text-fg-0 break-all">{inspectedDigest}</div>
          {digestChanged && (
            <p className="mt-2 text-xs text-warn">The candidate changed since this page opened. Reload before approving.</p>
          )}
        </div>
        {selfAsserted ? (
          <Field label="Reviewer" hint="Local-development authentication is active, so the reviewer name is self-asserted. With authentication enabled it comes from your token." htmlFor="approve-reviewer">
            <Input id="approve-reviewer" value={reviewer} onChange={(event) => setReviewer(event.target.value)} placeholder="Full name" autoFocus />
          </Field>
        ) : (
          <p className="text-xs text-fg-2">The reviewer identity comes from your authenticated session.</p>
        )}
        {approve.isError && <DecisionError error={approve.error} onReload={reload} />}
      </div>
    </Dialog>
  );
}

export function RejectDialog({ run, open, onOpenChange, selfAsserted }: { run: RunDetail; open: boolean; onOpenChange: (open: boolean) => void; selfAsserted: boolean }) {
  const [reviewer, setReviewer] = useState(readReviewer);
  const [reason, setReason] = useState('');
  const { settle, reload } = useDecision(run, () => onOpenChange(false));
  const reject = useMutation({
    mutationFn: () => api.reject(run.id, { reviewer: selfAsserted ? reviewer.trim() : null, reason: reason.trim() || null }),
    onSuccess: async () => {
      if (selfAsserted) rememberReviewer(reviewer.trim());
      await settle();
    },
  });
  const ready = !selfAsserted || reviewer.trim().length >= 2;
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Reject this candidate"
      description="Rejection is recorded with your name and reason. The candidate stays retained as evidence; a new candidate is needed to continue."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="danger" onClick={() => reject.mutate()} disabled={!ready || reject.isPending}>
            {reject.isPending ? 'Rejecting…' : 'Reject'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {selfAsserted ? (
          <Field label="Reviewer" htmlFor="reject-reviewer">
            <Input id="reject-reviewer" value={reviewer} onChange={(event) => setReviewer(event.target.value)} placeholder="Full name" autoFocus />
          </Field>
        ) : (
          <p className="text-xs text-fg-2">The reviewer identity comes from your authenticated session.</p>
        )}
        <Field label="Reason" hint="What the next candidate must change. Up to 2,000 characters." htmlFor="reject-reason">
          <Textarea id="reject-reason" rows={4} maxLength={2000} value={reason} onChange={(event) => setReason(event.target.value)} />
        </Field>
        {reject.isError && <DecisionError error={reject.error} onReload={reload} />}
      </div>
    </Dialog>
  );
}
