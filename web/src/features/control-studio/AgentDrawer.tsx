import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowRight,
  Bot,
  CheckCircle2,
  CircleAlert,
  Code2,
  CornerDownLeft,
  FlaskConical,
  MessageSquareText,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { api, type ChatTurn, type RunDetail } from '../../api/client';

type AgentMessage = ChatTurn & {
  assumptions?: string[];
  candidate?: RunDetail | null;
};

const quickPrompts = [
  'Explain this control program and its safety interlocks.',
  'Where is the weakest test coverage in this candidate?',
  'Propose a safer change and create a separately tested candidate.',
];

function AgentDrawer({ open, onClose, run }: { open: boolean; onClose: () => void; run: RunDetail }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState('');
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const status = useQuery({ queryKey: ['ai-status'], queryFn: api.aiStatus });
  const send = useMutation({
    mutationFn: ({ message, history }: { message: string; history: ChatTurn[] }) => api.chat(run.id, message, history),
    onSuccess: (response) => {
      setMessages((current) => [...current, {
        role: 'assistant',
        content: response.message,
        assumptions: response.assumptions,
        candidate: response.new_run,
      }]);
      if (response.new_run) {
        queryClient.setQueryData(['run', response.new_run.id], response.new_run);
        queryClient.invalidateQueries({ queryKey: ['runs'] });
      }
    },
    onError: (error) => {
      setMessages((current) => [...current, {
        role: 'assistant',
        content: error instanceof Error ? error.message : 'The AI engineer could not complete this request.',
      }]);
    },
  });

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose, open]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, send.isPending]);

  if (!open) return null;
  const configured = Boolean(status.data?.configured);
  const submit = (message: string) => {
    const clean = message.trim();
    if (!clean || !configured || send.isPending) return;
    const history = messages.map(({ role, content }) => ({ role, content })).slice(-20);
    setMessages((current) => [...current, { role: 'user', content: clean }]);
    setDraft('');
    send.mutate({ message: clean, history });
  };

  return (
    <div className="agent-layer">
      <button aria-label="Close AI controls engineer" className="agent-scrim" onClick={onClose} type="button" />
      <div aria-labelledby="agent-title" aria-modal="true" className="agent-drawer" role="dialog">
        <header className="agent-drawer-head">
          <div className="agent-avatar"><Sparkles size={19} /></div>
          <div><span className="eyebrow">AI CONTROLS ENGINEER</span><h2 id="agent-title">Work through this candidate</h2></div>
          <button aria-label="Close" onClick={onClose} ref={closeRef} type="button"><X size={18} /></button>
        </header>

        <div className="agent-role-strip">
          <div><MessageSquareText size={15} /><span><small>Conversation</small><strong>{status.data?.roles.conversation.model ?? 'Not configured'}</strong></span></div>
          <ArrowRight size={13} />
          <div><Code2 size={15} /><span><small>Control proposal</small><strong>{status.data?.roles.coding.model ?? 'Not configured'}</strong></span></div>
        </div>

        <div className="agent-guardrail" role="note">
          <ShieldCheck size={17} />
          <span><strong>Proposal-only authority</strong>The chat model explains and routes. A separate coding model may propose a new graph; deterministic validation and tests decide whether it becomes reviewable.</span>
        </div>

        <div aria-live="polite" className="agent-messages" ref={scrollRef}>
          {!status.isLoading && !configured && (
            <div className="agent-unavailable">
              <CircleAlert size={22} />
              <strong>AI roles are not connected</strong>
              <span>Add the Cerebras key to the server’s local <code>.env</code>, keep chat and coding models separate, and restart BACTalk.</span>
            </div>
          )}
          {configured && messages.length === 0 && (
            <>
              <div className="agent-message assistant">
                <span><Bot size={14} />BACTalk</span>
                <p>I have the exact graph, source job, and retained test evidence for <strong>{run.job.equipment_name}</strong>. Ask for an explanation or a change. Any change becomes a separate tested candidate.</p>
              </div>
              <div className="agent-quick-prompts" aria-label="Suggested prompts">
                {quickPrompts.map((prompt) => <button key={prompt} onClick={() => submit(prompt)} type="button">{prompt}<ArrowRight size={13} /></button>)}
              </div>
            </>
          )}
          {messages.map((message, index) => (
            <div className={`agent-message ${message.role}`} key={`${message.role}-${index}`}>
              <span>{message.role === 'assistant' ? <Bot size={14} /> : null}{message.role === 'assistant' ? 'BACTalk' : 'You'}</span>
              {message.role === 'assistant'
                ? <div className="agent-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown></div>
                : <p>{message.content}</p>}
              {message.assumptions && message.assumptions.length > 0 && (
                <details><summary>Assumptions used</summary><ul>{message.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul></details>
              )}
              {message.candidate && <CandidateCard candidate={message.candidate} />}
            </div>
          ))}
          {send.isPending && <div className="agent-message assistant pending"><span><Bot size={14} />BACTalk</span><p><i /><i /><i /> Reading the graph, routing the request, and running deterministic gates…</p></div>}
        </div>

        <form className="agent-composer" onSubmit={(event) => { event.preventDefault(); submit(draft); }}>
          <label htmlFor="agent-message">Message the controls engineer</label>
          <textarea disabled={!configured || send.isPending} id="agent-message" maxLength={5000} onChange={(event) => setDraft(event.target.value)} placeholder="Explain the safeties, inspect coverage, or propose a tested change…" rows={4} value={draft} />
          <div><span>{draft.length}/5000 · Enter a precise engineering request</span><button disabled={!configured || !draft.trim() || send.isPending} type="submit">{send.isPending ? 'Working…' : 'Send'}<CornerDownLeft size={14} /></button></div>
        </form>
      </div>
    </div>
  );
}

function CandidateCard({ candidate }: { candidate: RunDetail }) {
  const passed = candidate.status === 'ready_for_review' || candidate.status === 'approved';
  return (
    <div className={`agent-candidate ${passed ? 'passed' : 'failed'}`}>
      {passed ? <CheckCircle2 size={18} /> : <CircleAlert size={18} />}
      <div><small>SEPARATE TESTED CANDIDATE</small><strong>{passed ? 'Ready for engineer review' : 'Tests failed · approval blocked'}</strong><code>{candidate.id} · {candidate.artifact_sha256.slice(0, 10)}</code></div>
      <Link to={`/studio/${candidate.id}/tests`}>Open evidence<FlaskConical size={14} /></Link>
    </div>
  );
}

export { AgentDrawer };
