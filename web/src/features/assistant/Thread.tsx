import { Bot, Send, Sparkles, Trash2, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';

import type { RunDetail } from '../../api/client';
import { useAiStatus, useGraph } from '../../api/queries';
import { cn } from '../../design-system/cn';
import { Button, StatusPill } from '../../design-system/primitives';
import { useAssistant } from '../../stores/assistant';
import { useSelection } from '../../stores/selection';
import { useTrace } from '../../stores/trace';
import { useTimeCursor } from '../../stores/timeCursor';
import { useUi } from '../../stores/ui';
import type { Stage } from '../../stores/ui';
import { traceIdForRun } from '../../trace/build-trace';
import { AttemptsTimeline } from './AttemptsTimeline';
import { buildContextChips } from './context';
import { Markdown } from './markdown';
import { ProposalCard } from './ProposalCard';

/**
 * The AI thread docked beside every stage. It knows what the engineer is
 * looking at, explains, and routes change requests to the coding model,
 * whose output is always a separate candidate.
 */
export function Thread({ run, stage }: { run: RunDetail; stage: Stage }) {
  const status = useAiStatus();
  const graph = useGraph(run.id);
  const trace = useTrace(traceIdForRun(run.id));
  const thread = useAssistant((state) => state.threads[run.id]);
  const send = useAssistant((state) => state.send);
  const clear = useAssistant((state) => state.clear);
  const setAssistantOpen = useUi((state) => state.setAssistantOpen);
  const draft = useUi((state) => state.assistantDraft);
  const setDraft = useUi((state) => state.setAssistantDraft);
  const blockIds = useSelection((state) => state.blockIds);
  const assertionId = useSelection((state) => state.assertionId);
  const index = useTimeCursor((state) => state.index);
  const t = useTimeCursor((state) => state.t);
  const traceId = useTimeCursor((state) => state.traceId);
  const [text, setText] = useState('');
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const list = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  // A question typed in the ⌘⇧K palette lands here once.
  const [consumedDraft, setConsumedDraft] = useState<string | null>(null);
  if (draft && draft !== consumedDraft) {
    setConsumedDraft(draft);
    setText(draft);
    setDraft(null);
  }

  const chips = useMemo(
    () => buildContextChips({ blockIds, assertionId }, { index, t, traceId }, trace, graph.data, stage).filter((chip) => !removed.has(chip.id)),
    [blockIds, assertionId, index, t, traceId, trace, graph.data, stage, removed],
  );

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight });
  }, [thread?.messages.length, thread?.pending]);

  const configured = status.data?.configured ?? false;
  const reason = status.data?.unavailable_reason ?? (status.isError ? 'AI status is unavailable.' : null);
  const conversation = status.data?.roles.conversation;
  const coding = status.data?.roles.coding;

  const submit = () => {
    if (!text.trim() || thread?.pending || !configured) return;
    void send(run.id, text, chips);
    setText('');
    setRemoved(new Set());
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <aside className="h-full flex flex-col bg-bg-1 min-w-0" aria-label="Assistant">
      <header className="flex items-center gap-2 px-3 h-9 hairline-b shrink-0">
        <Sparkles size={14} className="text-accent" />
        <span className="text-sm font-medium">Assistant</span>
        <span className="flex-1" />
        {thread && thread.messages.length > 0 && (
          <Button size="icon" variant="ghost" className="size-7" onClick={() => clear(run.id)} aria-label="Clear thread" title="Clear this job's thread">
            <Trash2 size={13} />
          </Button>
        )}
        <Button size="icon" variant="ghost" className="size-7" onClick={() => setAssistantOpen(false)} aria-label="Close assistant">
          <X size={14} />
        </Button>
      </header>

      <div className="px-3 py-2 hairline-b text-2xs flex flex-col gap-1" aria-label="Assistant authority">
        <div className="flex items-center gap-2">
          <StatusPill tone={configured ? 'info' : 'offline'} icon={null}>{configured ? 'proposal-only' : 'unavailable'}</StatusPill>
          <span className="text-fg-2 truncate">
            {conversation?.model ? `${conversation.model} explains and routes` : 'conversation model not configured'}
          </span>
        </div>
        <div className="text-fg-2 truncate">{coding?.model ? `${coding.model} proposes separate candidates; BACTalk tests them` : 'coding model not configured'}</div>
        {reason && <div className="text-warn">{reason}</div>}
      </div>

      <AttemptsTimeline attempts={run.agent_attempts} />

      <div ref={list} className="flex-1 min-h-0 overflow-auto px-3 py-3 flex flex-col gap-3" role="log" aria-live="polite" aria-label="Messages">
        {(!thread || thread.messages.length === 0) && (
          <div className="text-sm text-fg-2 flex flex-col gap-2">
            <p>Ask why a block behaves the way it does, what a failing assertion means, or request a change. Changes come back as separate candidates you can preview as a ghost diff and open to review.</p>
            <p className="text-2xs">Nothing you say here writes to a building or applies to this run.</p>
          </div>
        )}
        {thread?.messages.map((message) => (
          <div key={message.id} className={cn('flex flex-col gap-1', message.role === 'user' ? 'items-end' : 'items-start')}>
            {message.role === 'user' && message.context && message.context.length > 0 && (
              <div className="flex gap-1 flex-wrap justify-end">
                {message.context.map((chip) => (
                  <span key={chip.id} className="chip">{chip.label}</span>
                ))}
              </div>
            )}
            <div
              className={cn(
                'max-w-[92%] rounded-panel px-3 py-2 text-sm',
                message.role === 'user' && 'bg-accent-soft text-fg-0',
                message.role === 'assistant' && 'bg-bg-2 border border-line-1',
                message.role === 'error' && 'bg-fail-soft border border-fail/30 text-fail',
              )}
            >
              {message.role === 'user' ? (
                <p className="whitespace-pre-wrap">{message.content.replace(/^\[Context\][^\n]*\n?/gm, '').trim()}</p>
              ) : message.role === 'error' ? (
                <p>{message.content}</p>
              ) : (
                <>
                  <Markdown source={message.content} />
                  {message.intent === 'propose_change' && message.proposal && <ProposalCard proposal={message.proposal} assumptions={message.assumptions} />}
                  {message.intent === 'propose_change' && !message.proposal && (
                    <p className="mt-2 text-xs text-warn">The model wanted to propose a change but no candidate was produced.</p>
                  )}
                  {message.intent === 'answer' && message.assumptions && message.assumptions.length > 0 && (
                    <ul className="mt-2 text-2xs text-fg-2 list-disc pl-4">
                      {message.assumptions.map((assumption) => (
                        <li key={assumption}>{assumption}</li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </div>
          </div>
        ))}
        {thread?.pending && (
          <div className="flex items-center gap-2 text-xs text-fg-2">
            <Bot size={14} className="animate-pulse" /> Thinking…
          </div>
        )}
      </div>

      <footer className="hairline-t p-2 flex flex-col gap-1.5 shrink-0">
        <div className="flex gap-1 flex-wrap" aria-label="Context sent with the next message">
          {chips.map((chip) => (
            <button
              key={chip.id}
              type="button"
              className="chip hover:border-line-2"
              onClick={() => setRemoved((current) => new Set([...current, chip.id]))}
              title={`${chip.text} Click to remove.`}
            >
              {chip.label} <X size={10} className="ml-1 opacity-70" />
            </button>
          ))}
        </div>
        <div className="flex items-end gap-2">
          <textarea
            ref={input}
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={onKeyDown}
            rows={2}
            placeholder={configured ? 'Ask about this candidate, or request a change…' : 'The assistant is not configured'}
            disabled={!configured || thread?.pending}
            aria-label="Message the assistant"
            className="flex-1 min-w-0 resize-none rounded-control bg-bg-2 border border-line-1 px-2.5 py-1.5 text-sm outline-none focus-visible:border-accent disabled:opacity-60"
          />
          <Button variant="primary" size="icon" onClick={submit} disabled={!configured || thread?.pending || !text.trim()} aria-label="Send">
            <Send size={14} />
          </Button>
        </div>
      </footer>
    </aside>
  );
}
