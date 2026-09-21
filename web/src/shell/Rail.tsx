import { Boxes, Cable, FolderKanban, Home, Library, ShieldCheck } from 'lucide-react';
import type { ReactNode } from 'react';
import { NavLink } from 'react-router-dom';

import { cn } from '../design-system/cn';
import { useUi } from '../stores/ui';

interface RailItem {
  to: string;
  label: string;
  icon: ReactNode;
  end?: boolean;
}

const items: RailItem[] = [
  { to: '/', label: 'Home', icon: <Home size={18} strokeWidth={1.75} />, end: true },
  { to: '/jobs', label: 'Jobs', icon: <Boxes size={18} strokeWidth={1.75} /> },
  { to: '/projects', label: 'Projects', icon: <FolderKanban size={18} strokeWidth={1.75} /> },
  { to: '/libraries', label: 'Libraries', icon: <Library size={18} strokeWidth={1.75} /> },
  { to: '/connections', label: 'Connections', icon: <Cable size={18} strokeWidth={1.75} /> },
];

const adminItem: RailItem = { to: '/admin', label: 'Administration', icon: <ShieldCheck size={18} strokeWidth={1.75} /> };

/**
 * Icon rail that expands to labels on hover or focus. The expansion is a
 * width transition so the workspace reflows smoothly rather than jumping.
 */
export function Rail() {
  const expanded = useUi((state) => state.railExpanded);
  const setExpanded = useUi((state) => state.setRailExpanded);

  return (
    <nav
      aria-label="Primary"
      onMouseEnter={() => setExpanded(true)}
      onMouseLeave={() => setExpanded(false)}
      onFocusCapture={() => setExpanded(true)}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setExpanded(false);
      }}
      className={cn(
        'shrink-0 h-full flex flex-col bg-bg-1 hairline-r overflow-hidden',
        'transition-[width] duration-[var(--duration-layout)] ease-[var(--ease-out)]',
        expanded ? 'w-52' : 'w-14',
      )}
    >
      <div className="h-12 flex items-center px-3 gap-3 hairline-b">
        <Brand />
        <span
          className={cn(
            'text-sm font-semibold tracking-tight whitespace-nowrap transition-opacity duration-[var(--duration-micro)]',
            expanded ? 'opacity-100' : 'opacity-0',
          )}
        >
          BACTalk
        </span>
      </div>
      <ul className="flex-1 flex flex-col gap-0.5 p-2">
        {items.map((item) => (
          <RailLink key={item.to} item={item} expanded={expanded} />
        ))}
      </ul>
      <ul className="p-2 hairline-t">
        <RailLink item={adminItem} expanded={expanded} />
      </ul>
    </nav>
  );
}

function RailLink({ item, expanded }: { item: RailItem; expanded: boolean }) {
  return (
    <li>
      <NavLink
        to={item.to}
        end={item.end}
        aria-label={item.label}
        title={expanded ? undefined : item.label}
        className={({ isActive }) =>
          cn(
            'relative flex items-center gap-3 h-9 px-2.5 rounded-control text-sm whitespace-nowrap overflow-hidden',
            'transition-colors duration-[var(--duration-micro)]',
            isActive ? 'bg-bg-2 text-fg-0' : 'text-fg-1 hover:bg-bg-2 hover:text-fg-0',
          )
        }
      >
        {({ isActive }) => (
          <>
            {isActive && <span aria-hidden className="absolute left-0 top-2 bottom-2 w-0.5 rounded-pill bg-accent" />}
            <span className="shrink-0 w-5 flex justify-center">{item.icon}</span>
            <span className={cn('transition-opacity duration-[var(--duration-micro)]', expanded ? 'opacity-100' : 'opacity-0')}>
              {item.label}
            </span>
          </>
        )}
      </NavLink>
    </li>
  );
}

function Brand() {
  // A wiresheet glyph: three linked nodes. Uses currentColor so it inherits the theme.
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden className="shrink-0 text-accent">
      <path d="M6 7h5M11 7l3 5M14 12h4M11 17h5M11 17l3-5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" fill="none" />
      <rect x="3" y="4" width="4" height="6" rx="1.2" fill="currentColor" />
      <rect x="3" y="14" width="4" height="6" rx="1.2" fill="currentColor" />
      <rect x="17" y="9" width="4" height="6" rx="1.2" fill="currentColor" />
    </svg>
  );
}
