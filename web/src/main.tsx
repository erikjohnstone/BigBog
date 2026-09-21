import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { Toaster } from 'sonner';

import { App } from './app/App';
import { ThemeProvider } from './design-system/theme';
import { TooltipProvider } from './design-system/primitives/tooltip';

import './design-system/fonts';
import './design-system/tokens.css';
import './app/app.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <TooltipProvider delay={300}>
          <BrowserRouter>
            <App />
            <Toaster position="bottom-right" theme="system" toastOptions={{ className: 'floating text-sm' }} />
          </BrowserRouter>
        </TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
);
