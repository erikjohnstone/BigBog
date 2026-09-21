import { useEffect } from 'react';
import type { ReactNode } from 'react';

import { CommandPalette } from './CommandPalette';
import { Rail } from './Rail';
import { TopBar } from './TopBar';
import { useUi } from '../stores/ui';

/**
 * The application frame: an icon rail on the left, a slim top bar, and the
 * routed workspace filling the rest. The frame never scrolls; workspaces own
 * their own scrolling so canvases and timelines can fill the viewport.
 */
export function Shell({ children }: { children: ReactNode }) {
  const openCommand = useUi((state) => state.openCommand);
  const closeCommand = useUi((state) => state.closeCommand);
  const commandMode = useUi((state) => state.commandMode);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const meta = event.metaKey || event.ctrlKey;
      if (meta && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        if (commandMode) closeCommand();
        else openCommand(event.shiftKey ? 'agent' : 'search');
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [commandMode, openCommand, closeCommand]);

  return (
    <div className="h-dvh w-full flex bg-bg-0 text-fg-0 overflow-hidden">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:z-50 focus:top-2 focus:left-2 focus:px-3 focus:py-2 focus:bg-accent focus:text-accent-fg focus:rounded-control"
      >
        Skip to content
      </a>
      <Rail />
      <div className="flex-1 min-w-0 flex flex-col">
        <TopBar />
        <main id="main" className="flex-1 min-h-0 flex flex-col">
          {children}
        </main>
      </div>
      <CommandPalette />
    </div>
  );
}
