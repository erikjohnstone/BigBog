import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: true,
  retries: 1,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:8012',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium-desktop', use: { ...devices['Desktop Chrome'] } },
    {
      name: 'chromium-tablet',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 834, height: 1194 },
        hasTouch: true,
        isMobile: true,
      },
    },
  ],
  webServer: {
    command: 'cd .. && PYTHONPATH=src .venv/bin/uvicorn bactalk.api:create_app --factory --host 127.0.0.1 --port 8012',
    url: 'http://127.0.0.1:8012/api/health',
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
