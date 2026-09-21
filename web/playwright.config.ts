import { existsSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

import { defineConfig, devices } from '@playwright/test';

/**
 * Chromium executable to drive, or undefined to let Playwright use its own.
 *
 * Some machines provision browsers out of band (a prepared image, a locked-down
 * CI runner) where `playwright install` is unavailable or disallowed. When
 * PLAYWRIGHT_BROWSERS_PATH points at such a directory whose build number does
 * not match the pinned @playwright/test version, Playwright refuses to launch.
 * Resolving the binary explicitly lets the browser tests run there instead of
 * failing with an install prompt. Where nothing is provisioned this returns
 * undefined and normal Playwright behaviour applies.
 */
function provisionedChromium(): string | undefined {
  const explicit = process.env.BACTALK_CHROMIUM_PATH;
  if (explicit && existsSync(explicit)) return explicit;

  const root = process.env.PLAYWRIGHT_BROWSERS_PATH;
  if (!root || !existsSync(root)) return undefined;

  const candidates: string[] = [];
  for (const entry of readdirSync(root)) {
    if (!entry.startsWith('chromium')) continue;
    candidates.push(join(root, entry, 'chrome-linux', 'chrome'));
    candidates.push(join(root, entry, 'chrome-linux', 'headless_shell'));
    candidates.push(
      join(root, entry, 'chrome-mac', 'Chromium.app', 'Contents', 'MacOS', 'Chromium'),
    );
  }
  // Prefer a full browser over the headless shell: the suite renders charts
  // and runs accessibility checks against real layout.
  candidates.sort((a, b) => Number(a.includes('headless_shell')) - Number(b.includes('headless_shell')));
  return candidates.find((candidate) => existsSync(candidate));
}

const chromiumPath = provisionedChromium();
const launch = chromiumPath ? { executablePath: chromiumPath } : {};


export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
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
    { name: 'chromium-desktop', use: { ...devices['Desktop Chrome'], launchOptions: launch } },
    {
      name: 'chromium-tablet',
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: launch,
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
