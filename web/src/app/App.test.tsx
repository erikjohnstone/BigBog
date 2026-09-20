import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';

const responses: Record<string, unknown> = {
  '/api/health': { status: 'ok', mode: 'offline-safe' },
  '/api/runs': [],
  '/api/system/readiness': { production_ready: false, policy: 'Evidence required', components: [] },
};

afterEach(() => vi.restoreAllMocks());

describe('BACTalk product shell', () => {
  it('shows the engineering workflow and safety boundary', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = typeof input === 'string' ? input : input.toString();
      return new Response(JSON.stringify(responses[path]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter><App /></MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByRole('heading', { name: /what are we building/i })).toBeInTheDocument();
    expect(screen.getByText('Offline engineering')).toBeInTheDocument();
    expect(screen.getByLabelText('Programming workflow')).toHaveTextContent(
      /Intake.*Build.*Test.*Review.*Release/,
    );
    expect(await screen.findByText('Offline', { selector: 'strong' })).toBeInTheDocument();
  });
});
