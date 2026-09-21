import { expect, test } from '@playwright/test';

type Run = { id: string; status: string; job: { equipment_name: string } };

/**
 * Pixel baselines for the three engineering graphics at a fixed cursor.
 * Motion is reduced so flow dashes, fan impellers, and halos are static;
 * the clock is parked at the last scan so every value is deterministic.
 * Baselines live beside this file and are refreshed deliberately with
 * `npx playwright test visual --update-snapshots`.
 */
test.use({ reducedMotion: 'reduce', colorScheme: 'dark', viewport: { width: 1440, height: 900 } });

async function candidate(page: import('@playwright/test').Page, equipment: string) {
  const runs = (await (await page.request.get('/api/runs')).json()) as Run[];
  return runs.find((run) => run.job.equipment_name === equipment && run.status === 'ready_for_review') ?? runs.find((run) => run.job.equipment_name === equipment);
}

async function parkClock(page: import('@playwright/test').Page) {
  await page.getByRole('slider', { name: 'Scan position' }).focus();
  await page.keyboard.press('End');
  await page.waitForTimeout(400);
}

test('wiresheet at the last scan', async ({ page }) => {
  const run = await candidate(page, 'EF_1');
  test.skip(!run, 'The exhaust-fan demo candidate is required.');
  await page.goto(`/jobs/${run!.id}/build`);
  const sheet = page.getByRole('application', { name: 'Wiresheet' });
  await expect(sheet).toBeVisible();
  await page.keyboard.press('f');
  await parkClock(page);
  await expect(sheet).toHaveScreenshot('wiresheet-ef1.png', { maxDiffPixelRatio: 0.02, animations: 'disabled' });
});

test('schematic and trends at the last scan', async ({ page }) => {
  const run = await candidate(page, 'AHU_1');
  test.skip(!run, 'The AHU demo candidate is required.');
  await page.goto(`/jobs/${run!.id}/test`);
  const toggle = page.getByRole('button', { name: /^Schematic$/ });
  if ((await toggle.getAttribute('aria-pressed')) !== 'true') await toggle.click();
  const schematic = page.getByRole('img', { name: /air handling unit|points|vav|exhaust|pump/i }).first();
  await expect(schematic).toBeVisible();
  await parkClock(page);
  await expect(schematic).toHaveScreenshot('schematic-ahu1.png', { maxDiffPixelRatio: 0.02, animations: 'disabled' });
  const pane = page.locator('.uplot').first();
  await expect(pane).toBeVisible();
  await expect(pane).toHaveScreenshot('trend-ahu1.png', { maxDiffPixelRatio: 0.02, animations: 'disabled' });
  await expect(page.getByRole('group', { name: 'Master timeline' })).toHaveScreenshot('timeline-ahu1.png', { maxDiffPixelRatio: 0.02, animations: 'disabled' });
});
