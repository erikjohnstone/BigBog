import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { TooltipProvider } from '@radix-ui/react-tooltip';
import { Toaster } from 'sonner';

import { App } from './app/App';
import '@xyflow/react/dist/style.css';
import './design-system/tokens.css';
import './app/app.css';
import './features/control-studio/control-studio.css';
import './features/control-studio/simulation-lab.css';
import './features/control-studio/graphics-studio.css';
import './features/intake/intake-studio.css';
import './features/projects/project-workspace.css';
import './features/projects/project-intake.css';
import './features/workspaces/workspace-pages.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={300}>
        <BrowserRouter basename="/next">
          <App />
          <Toaster position="bottom-right" richColors />
        </BrowserRouter>
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
);
