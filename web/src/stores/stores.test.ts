import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '../api/client';
import { composeMessage, historyFor, useAssistant } from './assistant';
import { EMPTY_SELECTIONS, emptyDesign, reachableSteps, useDesign } from './design';
import type { DesignState } from './design';
import { emptyDraft, useIntake } from './intake';
import { linkKey, useSelection } from './selection';
import { useTrends } from './trends';
import { useUi } from './ui';

describe('trends store', () => {
  beforeEach(() => {
    sessionStorage.clear();
    useTrends.setState({ byTrace: {} });
  });

  it('ensures defaults once and persists them for the session', () => {
    const defaults = vi.fn(() => ({ panes: [{ id: 'p1', title: '°F', unit: '°F', signalIds: ['a'] }], ribbon: ['b'] }));
    const first = useTrends.getState().ensure('t1', defaults);
    const second = useTrends.getState().ensure('t1', defaults);
    expect(second).toBe(first);
    expect(defaults).toHaveBeenCalledTimes(1);
    expect(JSON.parse(sessionStorage.getItem('bactalk.trends.v1')!).t1.ribbon).toEqual(['b']);
  });

  it('toggles booleans on the ribbon and numerics onto a matching-unit pane or a new one', () => {
    useTrends.getState().ensure('t1', () => ({ panes: [{ id: 'p1', title: '°F', unit: '°F', signalIds: ['a'] }], ribbon: [] }));
    const store = useTrends.getState();
    store.toggleSignal('t1', 'on', { kind: 'boolean' });
    store.toggleSignal('t1', 'temp2', { kind: 'numeric', unit: '°F' });
    store.toggleSignal('t1', 'psi', { kind: 'numeric', unit: 'inH2O' });
    let trends = useTrends.getState().byTrace.t1;
    expect(trends.ribbon).toEqual(['on']);
    expect(trends.panes[0].signalIds).toEqual(['a', 'temp2']);
    expect(trends.panes[1]).toMatchObject({ title: 'inH2O', unit: 'inH2O', signalIds: ['psi'] });
    // Toggling off removes the signal, and an emptied pane disappears.
    store.toggleSignal('t1', 'on', { kind: 'boolean' });
    store.toggleSignal('t1', 'psi', { kind: 'numeric', unit: 'inH2O' });
    trends = useTrends.getState().byTrace.t1;
    expect(trends.ribbon).toEqual([]);
    expect(trends.panes).toHaveLength(1);
    // An explicit pane wins over unit matching.
    store.toggleSignal('t1', 'psi', { kind: 'numeric', unit: 'inH2O', paneId: 'p1' });
    expect(useTrends.getState().byTrace.t1.panes[0].signalIds).toContain('psi');
    store.removePane('t1', 'p1');
    expect(useTrends.getState().byTrace.t1.panes).toEqual([]);
    store.reset('t1', () => ({ panes: [], ribbon: ['x'] }));
    expect(useTrends.getState().byTrace.t1.ribbon).toEqual(['x']);
    // Unknown traces are ignored rather than created.
    store.toggleSignal('nope', 'a', { kind: 'numeric' });
    expect(useTrends.getState().byTrace.nope).toBeUndefined();
  });
});

describe('selection store', () => {
  beforeEach(() => useSelection.getState().clear());

  it('replaces, adds, and toggles block and signal selections', () => {
    const store = useSelection.getState();
    store.selectBlocks(['a', 'b']);
    store.selectBlocks(['c'], 'add');
    store.selectBlocks(['a'], 'toggle');
    expect([...useSelection.getState().blockIds]).toEqual(['b', 'c']);
    store.selectSignals(['s1']);
    store.selectSignals(['s1', 's2'], 'toggle');
    expect([...useSelection.getState().signalIds]).toEqual(['s2']);
    store.setAssertion('x');
    store.setHover('b');
    store.setHover('b');
    store.setHighlight(['a'], [linkKey('a', 'out', 'b', 'in')]);
    expect(useSelection.getState()).toMatchObject({ assertionId: 'x', hoverBlockId: 'b' });
    expect([...useSelection.getState().highlightedLinkKeys]).toEqual(['a.out->b.in']);
    store.clear();
    expect(useSelection.getState().blockIds.size).toBe(0);
    expect(useSelection.getState().assertionId).toBeNull();
  });
});

describe('design store', () => {
  beforeEach(() => useDesign.setState({ byTemplate: {} }));

  it('returns the shared empty state, patches per template, and resets', () => {
    expect(useDesign.getState().get('vav')).toBe(emptyDesign);
    expect(useDesign.getState().get('vav').selections).toBe(EMPTY_SELECTIONS);
    useDesign.getState().patch('vav', { reviewer: 'Jordan' });
    useDesign.getState().patch('vav', (current) => ({ candidate: { ...current.candidate, name: 'VAV-12' } }));
    expect(useDesign.getState().get('vav')).toMatchObject({ reviewer: 'Jordan', candidate: { name: 'VAV-12' } });
    expect(useDesign.getState().get('ahu')).toBe(emptyDesign);
    useDesign.getState().reset('vav');
    expect(useDesign.getState().get('vav')).toBe(emptyDesign);
  });

  it('opens later steps only as gates are retained', () => {
    const gated = (patch: Partial<DesignState>) => [...reachableSteps({ ...emptyDesign, ...patch })];
    expect(gated({})).toEqual(['configure', 'brief', 'points', 'sequence']);
    expect(gated({ sequenceReconciliation: {} as DesignState['sequenceReconciliation'] })).toContain('review');
    expect(gated({ review: { ready_for_independent_oracle_authoring: true } as DesignState['review'] })).toContain('oracles');
    expect(gated({ review: { ready_for_independent_oracle_authoring: false } as DesignState['review'] })).not.toContain('oracles');
    expect(gated({ approval: { ready_for_graph_generation: true } as DesignState['approval'] })).toContain('preflight');
    expect(gated({ preflight: { ready_for_candidate_generation: true } as DesignState['preflight'] })).toContain('candidate');
  });
});

describe('intake store', () => {
  beforeEach(() => {
    localStorage.clear();
    useIntake.getState().reset();
  });

  it('persists the text draft, keeps files in memory, and clears inspection when sources change', () => {
    const store = useIntake.getState();
    store.update({ name: 'North wing', equipmentName: 'VAV_12' });
    expect(JSON.parse(localStorage.getItem('bactalk.intake.draft.v1')!)).toMatchObject({ name: 'North wing', equipmentName: 'VAV_12' });
    store.setInspection({ schema: 'x' } as unknown as NonNullable<ReturnType<typeof useIntake.getState>['inspection']>);
    store.setFile('template', new File(['x'], 't.bog'));
    expect(useIntake.getState().inspection).not.toBeNull();
    store.setFile('points', new File(['a,b'], 'points.csv'));
    expect(useIntake.getState().inspection).toBeNull();
    expect(useIntake.getState().files.points?.name).toBe('points.csv');
    store.reset();
    expect(useIntake.getState().draft).toEqual(emptyDraft);
    expect(localStorage.getItem('bactalk.intake.draft.v1')).toBeNull();
  });
});

describe('ui store', () => {
  beforeEach(() => localStorage.clear());

  it('tracks the palette, assistant, rail, schematic, and panel sizes', () => {
    const store = useUi.getState();
    store.openCommand('agent');
    expect(useUi.getState().commandMode).toBe('agent');
    store.closeCommand();
    expect(useUi.getState().commandMode).toBeNull();
    store.toggleAssistant();
    expect(useUi.getState().assistantOpen).toBe(true);
    store.setAssistantOpen(false);
    store.setAssistantDraft('why did the damper close?');
    store.setRailExpanded(true);
    store.setSchematicOpen(false);
    expect(localStorage.getItem('bactalk.schematic.open')).toBe('false');
    store.savePanelSizes('test:outer', { top: 60, evidence: 40 });
    expect(JSON.parse(localStorage.getItem('bactalk.layout.v1')!)).toEqual({ 'test:outer': { top: 60, evidence: 40 } });
    store.resetPanelSizes('test:outer');
    expect(useUi.getState().panelSizes).toEqual({});
    expect(useUi.getState()).toMatchObject({ assistantOpen: false, assistantDraft: 'why did the damper close?', railExpanded: true, schematicOpen: false });
  });
});

describe('assistant store', () => {
  beforeEach(() => {
    sessionStorage.clear();
    useAssistant.setState({ threads: {} });
  });
  afterEach(() => vi.restoreAllMocks());

  it('prefixes context lines and keeps the last twenty turns as history', () => {
    expect(composeMessage('why?', [{ id: 'c', label: 'Block', text: 'Selected block Damper' }])).toBe('[Context] Selected block Damper\n\nwhy?');
    expect(composeMessage('why?', [])).toBe('why?');
    const messages = Array.from({ length: 25 }, (_, i) => ({ id: String(i), role: i % 2 ? ('assistant' as const) : ('user' as const), content: `m${i}`, at: '' }));
    const history = historyFor({ messages: [...messages, { id: 'e', role: 'error', content: 'boom', at: '' }], pending: false });
    expect(history).toHaveLength(20);
    expect(history[19]).toEqual({ role: 'user', content: 'm24' });
    expect(historyFor(undefined)).toEqual([]);
  });

  it('records the reply with its proposal, and an error turn when the call fails', async () => {
    const chat = vi.spyOn(api, 'chat').mockResolvedValueOnce({
      message: 'Raising the minimum position.',
      intent: 'propose_change',
      assumptions: ['occupied mode'],
      new_run: { id: 'r2', status: 'ready_for_review', changes: { added: [], modified: ['block:Min'], removed: [] }, parent_run_id: 'r1' },
    } as unknown as Awaited<ReturnType<typeof api.chat>>);
    await useAssistant.getState().send('r1', '  raise the min  ', [{ id: 'c', label: 'Phase', text: 'Phase cooling' }]);
    expect(chat).toHaveBeenCalledWith('r1', '[Context] Phase cooling\n\nraise the min', []);
    const thread = useAssistant.getState().threads.r1;
    expect(thread.pending).toBe(false);
    expect(thread.messages.map((m) => m.role)).toEqual(['user', 'assistant']);
    expect(thread.messages[1]).toMatchObject({ intent: 'propose_change', proposal: { runId: 'r2', parentRunId: 'r1' } });
    expect(JSON.parse(sessionStorage.getItem('bactalk.assistant.v1')!).r1.messages).toHaveLength(2);

    vi.spyOn(api, 'chat').mockRejectedValueOnce(new Error('provider offline'));
    await useAssistant.getState().send('r1', 'again', []);
    expect(useAssistant.getState().threads.r1.messages.at(-1)).toMatchObject({ role: 'error', content: 'provider offline' });
    // Blank input and in-flight threads are ignored.
    await useAssistant.getState().send('r1', '   ', []);
    expect(useAssistant.getState().threads.r1.messages).toHaveLength(4);
    useAssistant.getState().clear('r1');
    expect(useAssistant.getState().threads.r1).toBeUndefined();
  });
});
