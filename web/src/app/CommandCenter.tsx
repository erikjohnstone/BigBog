import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Blocks,
  Bot,
  Building2,
  Cable,
  FilePlus2,
  FlaskConical,
  Gauge,
  Library,
  Search,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';

import { api } from '../api/client';

export type CommandMode = 'search' | 'agent';

type CommandItem = {
  id: string;
  label: string;
  detail: string;
  to: string;
  kind: string;
  icon: React.ReactNode;
};

const actions: CommandItem[] = [
  { id: 'home', label: 'Engineering command center', detail: 'Workspace status and reviews', to: '/', kind: 'Workspace', icon: <Gauge size={16} /> },
  { id: 'new', label: 'Start a contractor job', detail: 'Upload points, sequence, scan, and templates', to: '/intake', kind: 'Action', icon: <FilePlus2 size={16} /> },
  { id: 'projects', label: 'Whole-building projects', detail: 'Topology and cross-equipment evidence', to: '/projects', kind: 'Workspace', icon: <Building2 size={16} /> },
  { id: 'studio', label: 'Control Studio', detail: 'All retained equipment programs', to: '/studio', kind: 'Workspace', icon: <Blocks size={16} /> },
  { id: 'simulations', label: 'Simulation Center', detail: 'Deterministic, BACnet, and BOPTEST evidence', to: '/simulations', kind: 'Workspace', icon: <FlaskConical size={16} /> },
  { id: 'libraries', label: 'Library Workspace', detail: 'Installed controls and OSS sources', to: '/libraries', kind: 'Workspace', icon: <Library size={16} /> },
  { id: 'environments', label: 'Environment Workspace', detail: 'Contractor Niagara environments', to: '/environments', kind: 'Workspace', icon: <Cable size={16} /> },
];

export function CommandCenter({ mode, onClose }: { mode: CommandMode; onClose: () => void }) {
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const runs = useQuery({ queryKey: ['runs'], queryFn: api.runs });
  const projects = useQuery({ queryKey: ['projects'], queryFn: api.projects });
  const ai = useQuery({ queryKey: ['ai-status'], queryFn: api.aiStatus, enabled: mode === 'agent' });

  const items = useMemo<CommandItem[]>(() => {
    if (mode === 'agent') {
      return (runs.data ?? []).slice(0, 30).map((run) => ({
        id: `agent-${run.id}`,
        label: `Ask about ${run.job.equipment_name}`,
        detail: `${run.job.site} · ${run.job.name}`,
        to: `/studio/${run.id}/wiresheet?agent=1`,
        kind: run.status === 'ready_for_review' ? 'Awaiting review' : run.status.replaceAll('_', ' '),
        icon: <Bot size={16} />,
      }));
    }
    const runItems: CommandItem[] = (runs.data ?? []).map((run) => ({ id: `run-${run.id}`, label: run.job.equipment_name, detail: `${run.job.site} · ${run.job.name}`, to: `/studio/${run.id}/wiresheet`, kind: 'Program', icon: <Blocks size={16} /> }));
    const projectItems: CommandItem[] = (projects.data ?? []).map((record) => ({ id: `project-${record.id}`, label: record.project.name, detail: `${record.project.site} · ${record.project.equipment.length} equipment programs`, to: `/projects/${record.id}`, kind: 'Building', icon: <Building2 size={16} /> }));
    return [...actions, ...projectItems, ...runItems];
  }, [mode, projects.data, runs.data]);
  const filtered = items.filter((item) => !query.trim() || `${item.label} ${item.detail} ${item.kind}`.toLowerCase().includes(query.trim().toLowerCase())).slice(0, 40);

  useEffect(() => {
    input.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = previousOverflow; };
  }, []);
  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') onClose();
    if (event.key === 'ArrowDown') { event.preventDefault(); setActiveIndex((index) => Math.min(index + 1, Math.max(filtered.length - 1, 0))); }
    if (event.key === 'ArrowUp') { event.preventDefault(); setActiveIndex((index) => Math.max(index - 1, 0)); }
    if (event.key === 'Enter' && filtered[activeIndex]) { event.preventDefault(); navigate(filtered[activeIndex].to); onClose(); }
  };

  return (
    <div className="command-layer">
      <button aria-label="Close command center" className="command-scrim" onClick={onClose} type="button" />
      <section aria-labelledby="command-center-title" aria-modal="true" className="command-dialog" role="dialog">
        <header>
          <span className={mode === 'agent' ? 'command-mode-icon agent' : 'command-mode-icon'}>{mode === 'agent' ? <Sparkles size={18} /> : <Search size={18} />}</span>
          <div><span className="eyebrow">{mode === 'agent' ? 'AI CONTROLS ENGINEER' : 'GO ANYWHERE'}</span><h2 id="command-center-title">{mode === 'agent' ? 'Choose a program to work through' : 'Find anything in the workspace'}</h2></div>
          <button aria-label="Close" onClick={onClose} type="button"><X size={18} /></button>
        </header>
        {mode === 'agent' && <div className="command-agent-status"><ShieldCheck size={15} /><span><strong>{ai.data?.configured ? 'Proposal-only AI is ready' : 'AI provider unavailable'}</strong>{ai.data?.configured ? `${ai.data.roles.conversation.model} explains · ${ai.data.roles.coding.model} proposes code` : 'Configure the provider before opening a conversation.'}</span></div>}
        <label className="command-input"><Search size={18} /><span className="sr-only">{mode === 'agent' ? 'Filter programs' : 'Search workspace'}</span><input onChange={(event) => { setQuery(event.target.value); setActiveIndex(0); }} onKeyDown={onKeyDown} placeholder={mode === 'agent' ? 'Filter by equipment, site, or job…' : 'Search projects, equipment, jobs, and workspaces…'} ref={input} value={query} /><kbd>ESC</kbd></label>
        <div aria-label="Command results" className="command-results" role="listbox">
          {filtered.map((item, index) => <Link aria-selected={index === activeIndex} className={index === activeIndex ? 'active' : ''} key={item.id} onClick={onClose} onMouseEnter={() => setActiveIndex(index)} role="option" to={item.to}><span className="command-result-icon">{item.icon}</span><span><strong>{item.label}</strong><small>{item.detail}</small></span><b>{item.kind}</b></Link>)}
          {!filtered.length && <div className="command-empty"><Search size={22} /><strong>No workspace result</strong><span>Try an equipment name, site, project, or capability.</span></div>}
        </div>
        <footer><span><kbd>↑</kbd><kbd>↓</kbd> Move</span><span><kbd>↵</kbd> Open</span><span>{filtered.length} results</span></footer>
      </section>
    </div>
  );
}
