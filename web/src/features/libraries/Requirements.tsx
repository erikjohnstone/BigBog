import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import type { ProtocolRequirement, ProtocolSequence } from '../../api/client';
import { api } from '../../api/client';
import { keys, useProtocolSequence, useProtocolSequences } from '../../api/queries';
import { Button, Field, Input, StatusPill } from '../../design-system/primitives';
import type { Tone } from '../../design-system/primitives';
import { ErrorState, LoadingState } from '../../design-system/states';
import { KeyValue, SectionCard, StageFrame } from '../shared/StageFrame';

function gateTone(status: string): Tone {
  if (status === 'approved') return 'ok';
  if (status === 'stale') return 'warn';
  return 'neutral';
}

function outcomeText(outcome: ProtocolRequirement['outcomes'][number]): string {
  const symbol: Record<string, string> = { eq: '=', ne: '≠', gt: '>', gte: '≥', lt: '<', lte: '≤', between: 'in' };
  const value = typeof outcome.value === 'boolean' ? String(outcome.value) : outcome.value.toString();
  const upper = outcome.upper !== undefined && outcome.upper !== null ? `..${outcome.upper}` : '';
  const tolerance = outcome.tolerance ? ` ±${outcome.tolerance}` : '';
  return `${outcome.point} ${symbol[outcome.operator] ?? outcome.operator} ${value}${upper}${tolerance}`;
}

function conditionText(condition: ProtocolRequirement['conditions'][number]): string {
  const symbol: Record<string, string> = { eq: '=', ne: '≠', gt: '>', gte: '≥', lt: '<', lte: '≤', between: 'in' };
  const deadband = condition.deadband ? ` (deadband ${condition.deadband})` : '';
  return `${condition.point} ${symbol[condition.operator] ?? condition.operator} ${String(condition.value)}${deadband}`;
}

/** Tier 5: a contractor's specification section becomes a drafted requirement set. */
function CustomSequenceForm() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [title, setTitle] = useState('');
  const [equipment, setEquipment] = useState('CUSTOM_1');
  const [spec, setSpec] = useState('');
  const draft = useMutation({
    mutationFn: () => api.createCustomSequence({ title: title.trim(), equipment_name: equipment.trim(), spec_text: spec }),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: keys.protocolSequences });
      navigate(`/libraries/requirements/${encodeURIComponent(created.sequence_id)}`);
    },
  });
  const ready = title.trim().length >= 3 && /^[A-Za-z_][A-Za-z0-9_]*$/.test(equipment.trim()) && spec.trim().length >= 20;
  return (
    <SectionCard title="Custom sequence from a specification section (Tier 5)">
      <div className="px-4 py-3 space-y-3 text-sm">
        <p className="text-fg-2">
          Paste the specification section. The AI drafts a numbered, cited requirement set from it; you approve the exact
          digest, then the program is drafted from the approved requirements only, tested under the protocol, and the run is
          labelled custom, job-specific.
        </p>
        <Field label="Title" htmlFor="custom-title">
          <Input id="custom-title" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Kitchen hood interlock" />
        </Field>
        <Field label="Equipment name" htmlFor="custom-equipment" hint="Identifier used in the station and project bindings">
          <Input id="custom-equipment" mono value={equipment} onChange={(event) => setEquipment(event.target.value)} />
        </Field>
        <Field label="Specification section" htmlFor="custom-spec">
          <textarea
            id="custom-spec"
            className="w-full min-h-40 rounded-md border border-line-1 bg-bg-1 p-2 font-mono text-xs"
            value={spec}
            onChange={(event) => setSpec(event.target.value)}
            placeholder="3.4 KITCHEN HOOD EXHAUST INTERLOCK ..."
          />
        </Field>
        {draft.isError ? <p className="text-fail">{(draft.error as Error).message}</p> : null}
        <Button variant="primary" onClick={() => draft.mutate()} disabled={!ready || draft.isPending}>
          {draft.isPending ? 'Drafting…' : 'Draft requirements'}
        </Button>
      </div>
    </SectionCard>
  );
}

function CustomActions({ sequence }: { sequence: ProtocolSequence }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const custom = sequence.custom;
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: keys.protocolSequence(sequence.sequence_id) });
    await queryClient.invalidateQueries({ queryKey: keys.protocolSequences });
  };
  const program = useMutation({ mutationFn: () => api.draftCustomProgram(sequence.sequence_id), onSuccess: refresh });
  const adequacy = useMutation({
    mutationFn: () => api.runCustomAdequacy(sequence.sequence_id, { mutants: 0, invariant_sequences: 1000 }),
    onSuccess: refresh,
  });
  const run = useMutation({
    mutationFn: () => api.createCustomRun(sequence.sequence_id),
    onSuccess: (created) => navigate(`/jobs/${encodeURIComponent(created.id)}/test`),
  });
  if (!custom) return null;
  const error = program.error ?? adequacy.error ?? run.error;
  return (
    <SectionCard title="Custom sequence (job-specific)">
      <KeyValue
        items={[
          { label: 'Specification', value: `${custom.spec_filename} · sha256 ${custom.spec_sha256.slice(0, 16)}…` },
          { label: 'Drafted by', value: Object.entries(custom.drafted_by).map(([role, model]) => `${role}: ${model}`).join(', ') || '—' },
          { label: 'Program', value: custom.has_program ? 'drafted from the approved requirements' : 'not drafted yet' },
        ]}
      />
      {custom.assumptions.length ? (
        <div className="px-4 pb-2">
          <p className="text-xs uppercase tracking-wider text-fg-2 mb-1">Assumptions the drafter made</p>
          <ul className="list-disc pl-5 text-sm space-y-1">{custom.assumptions.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      ) : null}
      {custom.questions.length ? (
        <div className="px-4 pb-2">
          <p className="text-xs uppercase tracking-wider text-fg-2 mb-1">Questions the drafter left open</p>
          <ul className="list-disc pl-5 text-sm space-y-1">{custom.questions.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      ) : null}
      <div className="px-4 pb-3 flex flex-wrap gap-2 items-center">
        <Button variant="secondary" size="sm" onClick={() => program.mutate()} disabled={sequence.gate_g_eng !== 'approved' || program.isPending}>
          {program.isPending ? 'Drafting…' : 'Draft program'}
        </Button>
        <Button variant="secondary" size="sm" onClick={() => adequacy.mutate()} disabled={!custom.has_program || adequacy.isPending}>
          {adequacy.isPending ? 'Checking…' : 'Run adequacy (no mutants)'}
        </Button>
        <Button variant="primary" size="sm" onClick={() => run.mutate()} disabled={!custom.has_program || run.isPending}>
          {run.isPending ? 'Creating…' : 'Create programming run'}
        </Button>
        {sequence.gate_g_eng !== 'approved' ? <span className="text-xs text-fg-2">Approve the requirements first; the program is drafted from approved requirements only.</span> : null}
        {error ? <span className="text-xs text-fail">{(error as Error).message}</span> : null}
      </div>
    </SectionCard>
  );
}

/** The list of Tier 3+ sequences with their Gate G-ENG status. */
function SequenceList() {
  const sequences = useProtocolSequences();
  if (sequences.isPending) return <LoadingState label="Loading requirement sets" />;
  if (sequences.isError) return <ErrorState error={sequences.error} />;
  return (
    <StageFrame label="Requirements">
      <SectionCard title="Requirement sets (Test Generation Protocol)">
        <p className="px-4 py-3 text-sm text-fg-2">
          Tiers 3 and up have no LBNL reference. Each sequence starts as a numbered, cited requirement set; the test author
          builds every scenario from it and a qualified engineer approves the exact digest (Gate G-ENG). Until then the
          candidate cannot be approved or exported.
        </p>
        <ul className="divide-y divide-line-1">
          {sequences.data.items.map((item) => (
            <li key={item.sequence_id} className="flex items-center gap-3 px-4 h-10 text-sm">
              <Link to={`/libraries/requirements/${encodeURIComponent(item.sequence_id)}`} className="truncate text-accent">
                {item.title}
              </Link>
              <span className="font-mono text-2xs text-fg-2 truncate">
                Tier {item.tier} · {item.requirements} requirements · {item.invariants} invariants · {item.scenarios} scenarios
                {item.gaps ? ` · ${item.gaps} open questions` : ''}
              </span>
              {typeof item.label === 'string' ? <span className="text-2xs text-fg-2 truncate">{item.label}</span> : null}
              <span className="flex-1" />
              {item.accepted !== undefined && item.accepted !== null ? (
                <StatusPill tone={item.accepted ? 'ok' : 'warn'}>{item.accepted ? 'adequacy accepted' : 'adequacy not met'}</StatusPill>
              ) : null}
              <StatusPill tone={gateTone(item.gate_g_eng)}>Gate G-ENG {item.gate_g_eng}</StatusPill>
            </li>
          ))}
        </ul>
      </SectionCard>
      <CustomSequenceForm />
    </StageFrame>
  );
}

function AdequacyCard({ sequence }: { sequence: ProtocolSequence }) {
  const adequacy = sequence.adequacy;
  if (!adequacy) {
    return (
      <SectionCard title="Adequacy">
        <p className="px-4 py-3 text-sm text-fg-2">No adequacy report is retained for this sequence; run scripts/protocol_adequacy.py.</p>
      </SectionCard>
    );
  }
  const mutation = adequacy.mutation;
  const legs = Object.entries(adequacy.differential);
  return (
    <SectionCard
      title="Adequacy (as measured)"
      aside={
        <StatusPill tone={adequacy.accepted ? 'ok' : 'warn'}>
          {adequacy.accepted ? 'accepted' : 'not accepted'}
          {sequence.adequacy_current ? '' : ' · stale digest'}
        </StatusPill>
      }
    >
      <KeyValue
        items={[
          { label: 'Scenarios', value: `${adequacy.suite.count} run, ${adequacy.suite.failed} failed` },
          {
            label: 'Decision coverage',
            value: `${adequacy.decisions.percent ?? '—'} %${adequacy.decisions.gaps?.length ? ` (gaps: ${adequacy.decisions.gaps.join(', ')})` : ''}`,
          },
          {
            label: 'Invariants',
            value: `${adequacy.invariants.violations} violations on ${adequacy.invariants.steps_checked} steps of ${adequacy.invariants.sequences} randomised sequences (${adequacy.invariant_sequences_required} required)`,
          },
          {
            label: 'Shadow vs interpreter (D3)',
            value: legs.length
              ? legs.map(([leg, result]) => `${leg}: ${result.passed ? 'agree' : `disagree on ${result.failing_cases.slice(0, 3).join(', ')}`} (${result.policy}, ${result.band_set} bands)`).join('; ')
              : 'not run',
          },
          {
            label: 'Mutation (D4)',
            value: mutation && mutation.catch_rate !== undefined
              ? `${(mutation.catch_rate * 100).toFixed(1)} % of ${mutation.sample} sampled mutants caught (target ${(adequacy.mutation_target * 100).toFixed(0)} %, ${mutation.policy} policy)`
              : mutation?.blocker ?? 'not run',
          },
        ]}
      />
      {adequacy.questions.length ? (
        <div className="px-4 pb-3">
          <p className="text-xs uppercase tracking-wider text-fg-2 mb-1">Questions for the engineer</p>
          <ul className="list-disc pl-5 text-sm space-y-1">
            {adequacy.questions.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </SectionCard>
  );
}

function ApproveCard({ sequence }: { sequence: ProtocolSequence }) {
  const queryClient = useQueryClient();
  const [reviewer, setReviewer] = useState('');
  const [note, setNote] = useState('');
  const approve = useMutation({
    mutationFn: () =>
      api.approveProtocolRequirements(sequence.sequence_id, {
        reviewer: reviewer.trim() || undefined,
        requirements_digest: sequence.requirements_digest,
        note: note.trim() || undefined,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: keys.protocolSequence(sequence.sequence_id) });
      await queryClient.invalidateQueries({ queryKey: keys.protocolSequences });
    },
  });
  if (sequence.approval) {
    return (
      <SectionCard title="Gate G-ENG">
        <KeyValue
          items={[
            { label: 'Status', value: <StatusPill tone="ok">approved</StatusPill> },
            { label: 'Reviewer', value: sequence.approval.reviewer },
            { label: 'Approved at', value: sequence.approval.approved_at },
            { label: 'Digest', value: <span className="font-mono text-xs">{sequence.requirements_digest}</span> },
            { label: 'Note', value: sequence.approval.note ?? '—' },
          ]}
        />
      </SectionCard>
    );
  }
  return (
    <SectionCard title="Gate G-ENG: approve this exact requirement set" aside={<StatusPill tone={gateTone(sequence.gate_g_eng)}>{sequence.gate_g_eng}</StatusPill>}>
      <div className="px-4 py-3 space-y-3 text-sm">
        <p className="text-fg-2">
          Approval is bound to digest <span className="font-mono text-xs">{sequence.requirements_digest.slice(0, 16)}…</span>. It says the
          requirements are what you want built; it is not Niagara runtime qualification. Read the open questions first: each is a place
          where the requirements do not decide.
        </p>
        {sequence.gate_g_eng === 'stale' ? (
          <p className="text-warn">An earlier digest of this sequence was approved; the requirements changed since and need a new approval.</p>
        ) : null}
        <Field label="Reviewer" htmlFor="protocol-reviewer" hint="Your name, or leave empty when signed in">
          <Input id="protocol-reviewer" value={reviewer} onChange={(event) => setReviewer(event.target.value)} placeholder="Controls engineer" />
        </Field>
        <Field label="Note" htmlFor="protocol-note">
          <Input id="protocol-note" value={note} onChange={(event) => setNote(event.target.value)} placeholder="What was checked against the guideline" />
        </Field>
        {approve.isError ? <p className="text-fail">{(approve.error as Error).message}</p> : null}
        <Button variant="primary" onClick={() => approve.mutate()} disabled={approve.isPending}>
          {approve.isPending ? 'Approving…' : 'Approve requirements'}
        </Button>
      </div>
    </SectionCard>
  );
}

function RequirementRow({ requirement, scenarios }: { requirement: ProtocolRequirement; scenarios: number }) {
  const citation = requirement.citation;
  return (
    <li className="px-4 py-3 space-y-1">
      <div className="flex items-center gap-2 text-sm">
        <span className="font-mono text-xs text-fg-2">{requirement.id}</span>
        <span className="font-medium">{requirement.title}</span>
        <StatusPill tone="info" icon={null}>
          {requirement.kind}
        </StatusPill>
        <span className="flex-1" />
        <span className="text-xs text-fg-2">{scenarios} scenarios</span>
      </div>
      <p className="text-sm">{requirement.text}</p>
      <p className="text-xs text-fg-2">
        {citation.document} {citation.section}
        {citation.paragraph ? ` (${citation.paragraph})` : ''} · {citation.fidelity}
        {citation.note ? ` · ${citation.note}` : ''}
      </p>
      <p className="text-xs font-mono text-fg-1">
        {requirement.assumes.length ? `assumes ${requirement.assumes.join(', ')}; ` : ''}
        {requirement.conditions.length ? `when ${requirement.conditions.map(conditionText).join(' and ')}` : 'whenever the context holds'}
        {requirement.timing.delay_seconds ? ` for ${requirement.timing.delay_seconds} s` : ''}
        {' → '}
        {requirement.outcomes.map(outcomeText).join(', ')}
        {requirement.otherwise.length ? `; otherwise ${requirement.otherwise.map(outcomeText).join(', ')}` : ''}
        {requirement.timing.release_seconds ? ` (releases after ${requirement.timing.release_seconds} s)` : ''}
      </p>
    </li>
  );
}

function SequenceDetail({ sequenceId }: { sequenceId: string }) {
  const sequence = useProtocolSequence(sequenceId);
  if (sequence.isPending) return <LoadingState label="Loading requirement set" />;
  if (sequence.isError) return <ErrorState error={sequence.error} />;
  const data = sequence.data;
  return (
    <StageFrame label="Requirements" wide>
      <SectionCard
        title={data.title}
        aside={
          <span className="flex items-center gap-2">
            <StatusPill tone={gateTone(data.gate_g_eng)}>Gate G-ENG {data.gate_g_eng}</StatusPill>
            <a
              href={`/api/protocol/sequences/${encodeURIComponent(data.sequence_id)}/test-plan`}
              className="text-xs text-accent"
              target="_blank"
              rel="noreferrer"
            >
              Test plan (markdown)
            </a>
          </span>
        }
      >
        <KeyValue
          items={[
            { label: 'Sequence', value: <span className="font-mono text-xs">{data.sequence_id}</span> },
            { label: 'Tier', value: String(data.tier) },
            { label: 'Label', value: typeof data.label === 'string' ? data.label : '—' },
            {
              label: 'Configuration',
              value:
                data.configuration && typeof data.configuration === 'object'
                  ? `${(data.configuration as { label?: string }).label ?? 'default'} ${JSON.stringify((data.configuration as { options?: unknown }).options ?? {})}`
                  : 'default',
            },
            { label: 'Version', value: data.version },
            { label: 'Requirements digest', value: <span className="font-mono text-xs break-all">{data.requirements_digest}</span> },
            { label: 'Sources', value: data.requirements.sources.map((source) => `${source.document}, ${source.edition}`).join('; ') },
            { label: 'Test plan', value: `${data.plan.scenarios} scenarios (${data.plan.kinds.join(', ')}) generated by ${data.plan.generator}` },
          ]}
        />
        {data.requirements.notes ? <p className="px-4 pb-3 text-sm text-fg-2">{data.requirements.notes}</p> : null}
      </SectionCard>
      <CustomActions sequence={data} />
      <AdequacyCard sequence={data} />
      <ApproveCard sequence={data} />
      <SectionCard title={`Requirements (${data.requirements.requirements.length})`}>
        <ul className="divide-y divide-line-1">
          {data.requirements.requirements.map((requirement) => (
            <RequirementRow key={requirement.id} requirement={requirement} scenarios={data.plan.per_requirement[requirement.id] ?? 0} />
          ))}
        </ul>
      </SectionCard>
      <SectionCard title={`Invariants (${data.requirements.invariants.length})`}>
        <ul className="divide-y divide-line-1">
          {data.requirements.invariants.map((invariant) => (
            <li key={invariant.id} className="px-4 py-2 text-sm">
              <span className="font-mono text-xs text-fg-2 mr-2">{invariant.id}</span>
              {invariant.text}
              <span className="font-mono text-xs text-fg-1">
                {' '}
                {invariant.when.length ? `when ${invariant.when.map(conditionText).join(' and ')} ` : ''}
                → {invariant.then.map(outcomeText).join(', ')}
              </span>
            </li>
          ))}
        </ul>
      </SectionCard>
      {data.plan.gaps.length ? (
        <SectionCard title={`Gaps the test author could not close (${data.plan.gaps.length})`}>
          <ul className="divide-y divide-line-1">
            {data.plan.gaps.map((gap) => (
              <li key={`${gap.requirement_id}-${gap.kind}-${gap.question}`} className="px-4 py-2 text-sm">
                <span className="font-mono text-xs text-fg-2 mr-2">{gap.requirement_id}</span>
                <span className="text-fg-2 mr-2">{gap.kind.replace(/_/g, ' ')}:</span>
                {gap.question}
              </li>
            ))}
          </ul>
        </SectionCard>
      ) : null}
    </StageFrame>
  );
}

export function Requirements() {
  const { sequenceId } = useParams<{ sequenceId?: string }>();
  return sequenceId ? <SequenceDetail sequenceId={sequenceId} /> : <SequenceList />;
}
