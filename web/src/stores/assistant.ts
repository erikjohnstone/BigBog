/**
 * AI thread state, keyed by run. Messages survive closing the panel and
 * navigating between stages; they persist for the browser session. The
 * assistant only ever explains or proposes; nothing here applies a change.
 */

import { create } from 'zustand';

import { api } from '../api/client';
import type { ChatTurn } from '../api/client';

export interface ContextChip {
  id: string;
  label: string;
  /** The line prepended to the message so the model sees what the engineer sees. */
  text: string;
}

export interface ProposalSummary {
  runId: string;
  status: string;
  changes: { added: string[]; modified: string[]; removed: string[] };
  reportPassed: boolean | null | undefined;
  parentRunId: string | null | undefined;
}

export interface ThreadMessage {
  id: string;
  role: 'user' | 'assistant' | 'error';
  content: string;
  at: string;
  intent?: 'answer' | 'propose_change';
  assumptions?: string[];
  proposal?: ProposalSummary | null;
  context?: ContextChip[];
}

export interface Thread {
  messages: ThreadMessage[];
  pending: boolean;
}

interface AssistantState {
  threads: Record<string, Thread>;
  send: (runId: string, text: string, context: ContextChip[]) => Promise<void>;
  clear: (runId: string) => void;
}

const KEY = 'bactalk.assistant.v1';
const HISTORY_LIMIT = 20;

function readAll(): Record<string, Thread> {
  try {
    const raw = sessionStorage.getItem(KEY);
    const parsed = raw ? (JSON.parse(raw) as Record<string, Thread>) : {};
    for (const thread of Object.values(parsed)) thread.pending = false;
    return parsed;
  } catch {
    return {};
  }
}

function persist(threads: Record<string, Thread>): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(threads));
  } catch {
    // Session storage can be unavailable; the thread just does not persist.
  }
}

let counter = 0;
function nextId(): string {
  counter += 1;
  return `${Date.now().toString(36)}-${counter}`;
}

export function composeMessage(text: string, context: ContextChip[]): string {
  if (context.length === 0) return text;
  return `${context.map((chip) => `[Context] ${chip.text}`).join('\n')}\n\n${text}`;
}

export function historyFor(thread: Thread | undefined): ChatTurn[] {
  if (!thread) return [];
  return thread.messages
    .filter((message) => message.role === 'user' || message.role === 'assistant')
    .slice(-HISTORY_LIMIT)
    .map((message) => ({ role: message.role as 'user' | 'assistant', content: message.content }));
}

export const useAssistant = create<AssistantState>((set, get) => ({
  threads: readAll(),

  async send(runId, text, context) {
    const trimmed = text.trim();
    if (!trimmed) return;
    const current = get().threads[runId] ?? { messages: [], pending: false };
    if (current.pending) return;
    const history = historyFor(current);
    const userMessage: ThreadMessage = { id: nextId(), role: 'user', content: composeMessage(trimmed, context), at: new Date().toISOString(), context };
    const withUser = { messages: [...current.messages, userMessage], pending: true };
    set({ threads: { ...get().threads, [runId]: withUser } });
    persist(get().threads);
    try {
      const response = await api.chat(runId, userMessage.content, history);
      const reply: ThreadMessage = {
        id: nextId(),
        role: 'assistant',
        content: response.message,
        at: new Date().toISOString(),
        intent: response.intent,
        assumptions: response.assumptions,
        proposal: response.new_run
          ? {
              runId: response.new_run.id,
              status: response.new_run.status,
              changes: response.new_run.changes,
              reportPassed: (response.new_run as { report_passed?: boolean | null }).report_passed,
              parentRunId: response.new_run.parent_run_id,
            }
          : null,
      };
      const latest = get().threads[runId] ?? withUser;
      set({ threads: { ...get().threads, [runId]: { messages: [...latest.messages, reply], pending: false } } });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'The assistant did not answer.';
      const latest = get().threads[runId] ?? withUser;
      set({
        threads: {
          ...get().threads,
          [runId]: { messages: [...latest.messages, { id: nextId(), role: 'error', content: message, at: new Date().toISOString() }], pending: false },
        },
      });
    }
    persist(get().threads);
  },

  clear(runId) {
    const threads = { ...get().threads };
    delete threads[runId];
    set({ threads });
    persist(threads);
  },
}));
