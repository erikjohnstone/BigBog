import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api } from '../../api/client';
import type { ProjectRecord } from '../../api/client';
import { keys } from '../../api/queries';
import { Button, Dialog, Field, Input } from '../../design-system/primitives';
import { explainDecisionError } from '../review/DecisionDialogs';

/** Project approval: one named engineer, one retained project digest, export only. */
export function ProjectApproveDialog({ project, open, onOpenChange }: { project: ProjectRecord; open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const [reviewer, setReviewer] = useState(() => {
    try {
      return localStorage.getItem('bactalk.reviewer') ?? '';
    } catch {
      return '';
    }
  });
  const approve = useMutation({
    mutationFn: () => api.approveProject(project.id, reviewer.trim()),
    onSuccess: async () => {
      await Promise.all([queryClient.invalidateQueries({ queryKey: keys.project(project.id) }), queryClient.invalidateQueries({ queryKey: keys.projects })]);
      onOpenChange(false);
    },
  });
  const explained = approve.isError ? explainDecisionError(approve.error) : null;
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Approve this project"
      description="Approval covers every equipment candidate and the assembled station together, against the project digest. It unlocks the project export only."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => approve.mutate()} disabled={reviewer.trim().length < 2 || approve.isPending}>
            {approve.isPending ? 'Approving…' : 'Approve project'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="raised px-3 py-2">
          <div className="text-2xs text-fg-2">Project digest</div>
          <div className="num text-xs text-fg-0 break-all">{project.artifact_sha256}</div>
        </div>
        <Field label="Reviewer" htmlFor="project-reviewer">
          <Input id="project-reviewer" value={reviewer} onChange={(event) => setReviewer(event.target.value)} placeholder="Full name" autoFocus />
        </Field>
        {explained && (
          <div role="alert" className="raised border-fail/50 px-3 py-2 text-sm">
            <p className="font-medium text-fail">{explained.title}</p>
            <p className="mt-0.5 text-xs text-fg-1 break-words">{explained.detail}</p>
          </div>
        )}
      </div>
    </Dialog>
  );
}
