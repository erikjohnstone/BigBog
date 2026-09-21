import { Moon, Search, Sparkles, Sun, SunMoon } from 'lucide-react';
import { useLocation } from 'react-router-dom';

import { useHealth, useSecurityStatus } from '../api/queries';
import { Button, Kbd, StatusPill, Tooltip } from '../design-system/primitives';
import { useTheme } from '../design-system/theme';
import { useUi } from '../stores/ui';

/**
 * Slim top bar: where you are, what runtime boundary you are in, search, the
 * AI launcher, and theme. The environment badge is never a vague green dot;
 * it names the boundary the server reports.
 */
export function TopBar() {
  const openCommand = useUi((state) => state.openCommand);
  const health = useHealth();
  const security = useSecurityStatus();
  const { resolved, choice, setChoice } = useTheme();
  const location = useLocation();

  const crumb = crumbFor(location.pathname);
  const mode = health.data?.mode;
  const liveWrites = security.data?.live_writes_enabled;

  return (
    <header className="h-12 shrink-0 flex items-center gap-3 px-4 bg-bg-1 hairline-b">
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-sm text-fg-1 truncate">{crumb}</span>
      </div>

      <div className="flex-1" />

      <Tooltip
        content={
          liveWrites
            ? 'This runtime can write to a live building.'
            : 'Offline engineering. Nothing here can command equipment; exports still require licensed Workbench import.'
        }
      >
        <span role="status" aria-label="Environment" className="inline-flex">
          <StatusPill tone={liveWrites ? 'fail' : 'offline'} icon={null}>
            {health.isLoading ? 'Checking runtime…' : liveWrites ? 'LIVE WRITES ENABLED' : `Offline · ${mode ?? 'engineering'}`}
          </StatusPill>
        </span>
      </Tooltip>

      <Button variant="outline" size="sm" onClick={() => openCommand('search')} aria-label="Search everything">
        <Search size={14} />
        <span className="hidden md:inline">Search</span>
        <Kbd className="hidden md:inline-flex">⌘K</Kbd>
      </Button>

      <Button variant="primary" size="sm" onClick={() => openCommand('agent')}>
        <Sparkles size={14} />
        <span className="hidden md:inline">Ask BACTalk</span>
      </Button>

      <Tooltip content={`Theme: ${choice === 'system' ? `system (${resolved})` : choice}. Click to cycle.`}>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Change theme"
          onClick={() => setChoice(choice === 'system' ? (resolved === 'dark' ? 'light' : 'dark') : choice === 'dark' ? 'light' : 'system')}
        >
          {choice === 'system' ? <SunMoon size={16} /> : resolved === 'dark' ? <Moon size={16} /> : <Sun size={16} />}
        </Button>
      </Tooltip>
    </header>
  );
}

function crumbFor(pathname: string): string {
  if (pathname === '/') return 'Home';
  if (pathname.startsWith('/jobs/')) return 'Jobs';
  if (pathname.startsWith('/jobs')) return 'Jobs';
  if (pathname.startsWith('/intake/design')) return 'Intake · Design from template';
  if (pathname.startsWith('/intake')) return 'Intake';
  if (pathname.startsWith('/projects')) return 'Projects';
  if (pathname.startsWith('/libraries')) return 'Libraries';
  if (pathname.startsWith('/connections')) return 'Connections';
  if (pathname.startsWith('/admin')) return 'Administration';
  return 'BACTalk';
}
