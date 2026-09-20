import { execFileSync } from 'node:child_process';
import { copyFile, mkdir, readdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium, expect } from '@playwright/test';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
const inputDir = path.join(root, 'artifacts', 'demo-inputs');
const outputDir = path.join(root, 'artifacts', 'demos');
const captureDir = path.join(outputDir, `capture-${Date.now()}`);
const baseURL = process.env.BACTALK_DEMO_URL ?? 'http://127.0.0.1:8011';

await mkdir(inputDir, { recursive: true });
await mkdir(captureDir, { recursive: true });
execFileSync(path.join(root, '.venv', 'bin', 'python'), [
  path.join(root, 'scripts', 'create_complex_demo_package.py'),
  '--output',
  inputDir,
], { cwd: root, env: { ...process.env, PYTHONPATH: path.join(root, 'src') } });

const projectPackage = path.join(inputDir, 'riverview-complex-building-project.json');
const stationTemplate = path.join(inputDir, 'riverview-contractor-station.bog');
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  acceptDownloads: true,
  colorScheme: 'light',
  deviceScaleFactor: 1,
  recordVideo: { dir: captureDir, size: { width: 1440, height: 900 } },
  viewport: { width: 1440, height: 900 },
});
const page = await context.newPage();
const pause = (milliseconds = 1500) => page.waitForTimeout(milliseconds);

try {
  await page.goto(`${baseURL}/next/projects/new`, { waitUntil: 'networkidle' });
  await expect(page.getByRole('heading', { name: /compile the full controls package/i })).toBeVisible();
  await pause(1800);

  await page.locator('#project-package').setInputFiles(projectPackage);
  await pause(900);
  await page.locator('#station-template').setInputFiles(stationTemplate);
  await expect(page.getByRole('heading', { name: /riverview integrated air and hydronic systems/i })).toBeVisible();
  await pause(2400);

  await page.getByRole('button', { name: /run system preflight/i }).click();
  await expect(page.getByText('System contract accepted for build')).toBeVisible();
  await pause(2800);

  await page.getByRole('button', { name: /build, assemble, and test/i }).click();
  await expect(page).toHaveURL(/\/next\/projects\/[a-z0-9]+$/, { timeout: 90_000 });
  await expect(page.getByRole('heading', { name: /riverview integrated air and hydronic systems/i, level: 1 })).toBeVisible();
  const projectId = page.url().split('/').at(-1);
  if (!projectId) throw new Error('The project build did not return a project id.');
  await pause(3200);

  await page.getByRole('heading', { name: 'System behavior passed' }).scrollIntoViewIfNeeded();
  await pause(2600);
  const vavCard = page.locator('article.topology-equipment').filter({ hasText: 'VAV_101' });
  await vavCard.getByRole('link', { name: /open program/i }).click();
  await expect(page.getByLabel(/read-only wiresheet/i)).toBeVisible();
  await pause(2800);

  await page.getByRole('button', { name: /ask ai engineer/i }).click();
  await expect(page.getByRole('dialog', { name: /work through this candidate/i })).toBeVisible();
  await pause(1500);
  await page.getByRole('button', { name: /explain this control program/i }).click();
  await expect(page.locator('.agent-message.assistant .agent-markdown')).toBeVisible({ timeout: 60_000 });
  await pause(4200);
  await page.getByRole('button', { name: 'Close', exact: true }).click();

  await page.getByRole('button', { name: /test lab/i }).click();
  await expect(page.getByRole('heading', { name: /candidate behavior passed/i })).toBeVisible();
  await pause(3000);
  await page.getByRole('button', { name: 'Simulation', exact: true }).click();
  await expect(page.getByRole('heading', { name: /prove the control program/i })).toBeVisible();
  await pause(2600);
  await page.getByRole('button', { name: /run independent loopback proof/i }).click();
  await expect(page.getByText('Protocol proof passed')).toBeVisible({ timeout: 45_000 });
  await pause(3200);

  await page.getByRole('button', { name: 'Graphics', exact: true }).click();
  await expect(page.getByRole('heading', { name: /operator experience/i })).toBeVisible();
  await pause(3200);
  await page.getByRole('button', { name: /review & release/i }).click();
  await expect(page.getByRole('heading', { name: /review the evidence/i })).toBeVisible();
  await page.getByText('Artifact inventory').scrollIntoViewIfNeeded();
  await pause(3200);

  await page.getByLabel('Projects').click();
  await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
  await page.locator(`a.project-card[href$="/projects/${projectId}"]`).click();
  await expect(page).toHaveURL(new RegExp(`/next/projects/${projectId}$`));
  await page.getByRole('heading', { name: /review and release the exact building candidate/i }).scrollIntoViewIfNeeded();
  await pause(2600);

  await page.getByLabel('Project reviewer name').fill('Demo Controls Engineer');
  const attestations = page.locator('.project-release-checks input[type="checkbox"]');
  for (let index = 0; index < await attestations.count(); index += 1) {
    await attestations.nth(index).check();
    await pause(450);
  }
  const approve = page.getByRole('button', { name: /approve entire building candidate/i });
  await expect(approve).toBeEnabled();
  await pause(1200);
  await approve.click();
  await expect(page.getByText('Approved and exportable')).toBeVisible({ timeout: 60_000 });
  await pause(2600);

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('link', { name: /download complete station bundle/i }).click();
  const download = await downloadPromise;
  await download.saveAs(path.join(outputDir, 'riverview-approved-station-bundle.zip'));
  await pause(2800);
} finally {
  await context.close();
  await browser.close();
}

const videos = (await readdir(captureDir)).filter((name) => name.endsWith('.webm'));
if (videos.length !== 1) throw new Error(`Expected one captured video, found ${videos.length}.`);
const webm = path.join(outputDir, 'bactalk-complex-contractor-workflow.webm');
const mp4 = path.join(outputDir, 'bactalk-complex-contractor-workflow.mp4');
await copyFile(path.join(captureDir, videos[0]), webm);
execFileSync('ffmpeg', [
  '-y',
  '-i', webm,
  '-c:v', 'libx264',
  '-preset', 'medium',
  '-crf', '20',
  '-pix_fmt', 'yuv420p',
  '-movflags', '+faststart',
  mp4,
], { stdio: 'inherit' });
console.log(mp4);
