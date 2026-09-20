import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import path from 'node:path';

test('enterprise shell exposes workflow and safety boundary', async ({ page }) => {
  await page.goto('/next/');

  await expect(page.getByRole('heading', { name: /what are we building/i })).toBeVisible();
  await expect(page.getByLabel('Programming workflow')).toContainText('Release');
  await expect(page.getByText('No live building writes').last()).toBeVisible();

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test('legacy workbench remains available during migration', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Programming runs' })).toBeVisible();
  await expect(page.getByRole('button', { name: /import contractor job/i })).toBeVisible();
});

test('contractor intake normalizes a real points list before build', async ({ page }) => {
  await page.goto('/next/intake');

  await expect(page.getByRole('heading', { name: /turn the job package/i })).toBeVisible();
  await page.getByLabel('Job name').fill('E2E intake validation');
  await page.getByLabel('Site').fill('Contractor test site');
  await page.getByLabel('Equipment identifier').fill('VAV_101');
  await page.getByLabel('Sequence strategy').selectOption('G36_VAV_REHEAT');
  await page.getByRole('button', { name: /attach source files/i }).click();

  await page.locator('input[name="points"]').setInputFiles(path.resolve('../examples/vav-reheat-points.csv'));
  await page.getByRole('button', { name: /inspect mapping/i }).click();

  await expect(page.getByRole('heading', { name: /review the normalized engineering inputs/i })).toBeVisible();
  await expect(page.getByText('Point contract is complete')).toBeVisible();
  await expect(page.getByText('9 points', { exact: true })).toBeVisible();
  await expect(page.getByText('Disabled', { exact: true })).toBeVisible();
  expect((await new AxeBuilder({ page }).exclude('[data-sonner-toaster]').analyze()).violations).toEqual([]);
});

test('real candidate opens across wiresheet, test, and review workspaces', async ({ page }) => {
  test.setTimeout(60_000);
  const response = await page.request.get('/api/runs');
  const runs = await response.json() as Array<{ id: string; status: string }>;
  const candidate = runs.find((run) => run.status === 'ready_for_review') ?? runs[0];
  test.skip(!candidate, 'A retained candidate is required for the integrated workspace test.');
  const detail = await (await page.request.get(`/api/runs/${candidate.id}`)).json();
  await page.route('**/api/ai/status', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      configured: true,
      provider: 'cerebras',
      authority: 'proposal-only',
      roles: {
        conversation: { configured: true, model: 'conversation-test-model', authority: 'explain-and-route-only' },
        coding: { configured: true, model: 'coding-test-model', authority: 'proposal-only' },
      },
    }),
  }));
  await page.route('**/api/runs/*/chat', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      message: '### Proposal routed\n\nThe coding model produced a separate candidate and the deterministic gates passed.',
      intent: 'propose_change',
      assumptions: ['The source candidate remains immutable.'],
      source_run_id: candidate.id,
      new_run: detail,
    }),
  }));

  await page.goto(`/next/studio/${candidate.id}/wiresheet`);
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.getByLabel(/read-only wiresheet/i)).toBeVisible();
  await expect(page.getByText('Offline engineering workspace')).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.getByRole('button', { name: /ask ai engineer/i }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('heading', { name: /work through this candidate/i })).toBeVisible();
  await expect(page.getByText('Proposal-only authority')).toBeVisible();
  await page.getByRole('button', { name: /propose a safer change/i }).click();
  await expect(page.getByRole('heading', { name: 'Proposal routed' })).toBeVisible();
  await expect(page.getByText('Ready for engineer review')).toBeVisible();
  await expect(page.getByRole('link', { name: /open evidence/i })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole('button', { name: 'Close', exact: true }).click();

  await page.getByRole('button', { name: /test lab/i }).click();
  await expect(page.getByRole('heading', { name: /candidate behavior/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Scenario evidence' })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.getByRole('button', { name: /review & release/i }).click();
  await expect(page.getByRole('heading', { name: /review the evidence/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: /exactly what the contractor receives/i })).toBeVisible();
  await expect(page.getByText('Integrity verified', { exact: true })).toBeVisible();
  await expect(page.getByText('Artifact inventory')).toBeVisible();
  await expect(page.getByText('Qualification boundaries')).toBeVisible();
  await expect(page.getByRole('button', { name: /approve exact candidate/i })).toBeDisabled();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  const approved = runs.find((run) => run.status === 'approved');
  if (approved) {
    await page.goto(`/next/studio/${approved.id}/review`);
    const targetDownload = page.getByRole('link', { name: /download deployable target/i });
    const bundleDownload = page.getByRole('link', { name: /download complete review bundle/i });
    await expect(targetDownload).toHaveAttribute('href', `/api/runs/${approved.id}/export`);
    await expect(bundleDownload).toHaveAttribute('href', `/api/runs/${approved.id}/review-bundle`);
    expect((await page.request.get(`/api/runs/${approved.id}/review-bundle`)).ok()).toBe(true);
  }

  const failed = runs.find((run) => run.status === 'failed');
  if (failed) {
    await page.goto(`/next/studio/${failed.id}/tests`);
    await expect(page.getByRole('heading', { name: 'Candidate behavior failed' })).toBeVisible();
    await page.getByRole('button', { name: /review & release/i }).click();
    await expect(page.getByText('Behavior gate blocked')).toBeVisible();
    await expect(page.getByRole('button', { name: /approve exact candidate/i })).toBeDisabled();
  }
});

test('whole-building topology and high-fidelity evidence are usable end to end', async ({ page }) => {
  test.setTimeout(90_000);
  const projects = await (await page.request.get('/api/projects')).json() as Array<{ id: string; project: { name: string } }>;
  test.skip(!projects.length, 'A retained whole-building project is required.');
  await page.goto(`/next/projects/${projects[0].id}`);
  await expect(page.getByRole('heading', { name: projects[0].project.name, level: 1 })).toBeVisible();
  await expect(page.locator('.topology-canvas')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'System behavior passed' })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  const runs = await (await page.request.get('/api/runs')).json() as Array<{
    id: string;
    bacnet_lab_manifest_path?: string | null;
    boptest_verification_path?: string | null;
  }>;
  const physicsRun = runs.find((run) => run.boptest_verification_path);
  test.skip(!physicsRun, 'A retained BOPTEST qualification is required.');
  if (!physicsRun) return;
  await page.goto(`/next/studio/${physicsRun.id}/simulation`);
  await expect(page.getByRole('heading', { name: 'bestest_air' })).toBeVisible();
  await expect(page.getByText('Physics passed')).toBeVisible();
  await expect(page.getByRole('img', { name: /BOPTEST closed-loop/i })).toBeVisible();
  await expect(page.getByText('Independent trajectory oracles')).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  const bacnetRun = runs.find((run) => run.bacnet_lab_manifest_path);
  test.skip(!bacnetRun, 'A retained virtual BACnet lab is required.');
  if (!bacnetRun) return;
  await page.route(`**/api/runs/${bacnetRun.id}/bacnet-lab/probe`, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      format: 'bactalk.bac0-probe-result.v1',
      passed: true,
      point_count: 3,
      values: { ZoneTemp: 76, DamperCommand: 0, ValveCommand: 0 },
      run_id: bacnetRun.id,
      lab_mode: 'isolated-loopback',
      live_network_routes_allowed: false,
    }),
  }));
  await page.goto(`/next/studio/${bacnetRun.id}/simulation`);
  await expect(page.getByRole('heading', { name: /isolated device/i })).toBeVisible();
  await expect(page.getByText('Hard network boundary')).toBeVisible();
  await page.getByRole('button', { name: /run independent loopback proof/i }).click();
  await expect(page.getByText('Protocol proof passed')).toBeVisible({ timeout: 30_000 });
  expect((await new AxeBuilder({ page }).exclude('[data-sonner-toaster]').analyze()).violations).toEqual([]);

  await page.goto(`/next/studio/${bacnetRun.id}/graphics`);
  await expect(page.getByRole('heading', { name: /operator experience/i })).toBeVisible();
  await expect(page.getByLabel(/graphics preview/i)).toBeVisible();
  await expect(page.getByText('PX target blocked')).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test('contractor can upload, preflight, compile, and assemble a complex building project', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const inputs = testInfo.outputPath('complex-project-inputs');
  execFileSync(path.resolve('../.venv/bin/python'), [
    path.resolve('../scripts/create_complex_demo_package.py'),
    '--output',
    inputs,
  ], {
    cwd: path.resolve('..'),
    env: { ...process.env, PYTHONPATH: path.resolve('../src') },
  });

  await page.goto('/next/projects/new');
  await expect(page.getByRole('heading', { name: /compile the full controls package/i })).toBeVisible();
  await page.locator('#project-package').setInputFiles(path.join(inputs, 'riverview-complex-building-project.json'));
  await page.locator('#station-template').setInputFiles(path.join(inputs, 'riverview-contractor-station.bog'));
  await expect(page.getByRole('heading', { name: /riverview integrated air and hydronic systems/i })).toBeVisible();
  await expect(page.getByText('6', { exact: true }).first()).toBeVisible();

  await page.getByRole('button', { name: /run system preflight/i }).click();
  await expect(page.getByText('System contract accepted for build')).toBeVisible();
  await expect(page.getByText('ahu-safety-cooling-v1')).toBeVisible();
  expect((await new AxeBuilder({ page }).exclude('[data-sonner-toaster]').analyze()).violations).toEqual([]);
  if (testInfo.project.name === 'chromium-tablet') return;

  await page.getByRole('button', { name: /build, assemble, and test/i }).click();
  await expect(page).toHaveURL(/\/next\/projects\/[a-z0-9]+$/, { timeout: 90_000 });
  await expect(page.getByRole('heading', { name: /riverview integrated air and hydronic systems/i, level: 1 })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'System behavior passed' })).toBeVisible();
  await expect(page.getByText('assembled-station.bog retained in this release')).toBeVisible();
  await expect(page.getByRole('button', { name: /approve entire building candidate/i })).toBeDisabled();
  expect((await new AxeBuilder({ page }).exclude('[data-sonner-toaster]').analyze()).violations).toEqual([]);

  const projectId = page.url().split('/').at(-1);
  const project = await (await page.request.get(`/api/projects/${projectId}`)).json() as {
    equipment_runs: Array<{ equipment_name: string; run_id: string }>;
  };
  const exhaust = project.equipment_runs.find((item) => item.equipment_name === 'EF_1');
  expect(exhaust).toBeTruthy();
  await page.goto(`/next/studio/${exhaust?.run_id}/tests`);
  await expect(page.getByText('2 injected fault activations')).toBeVisible();
  await expect(page.getByText('lost_fan_proof').first()).toBeVisible();
  await expect(page.getByText('Raw → effective → response')).toBeVisible();
  await expect(page.getByText('exhaust-fan-proof-safety-v1')).toBeVisible();
  await page.getByText('Review the full safety and failure matrix').click();
  await expect(page.getByText('actuator proof failure')).toBeVisible();
  expect((await new AxeBuilder({ page }).exclude('[data-sonner-toaster]').analyze()).violations).toEqual([]);
});

test('installed controls libraries and contractor environments are transparent', async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto('/next/libraries');
  await expect(page.getByRole('heading', { name: 'Library Workspace' })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('Guideline 36 Controls').first()).toBeVisible();
  await expect(page.getByText('Installed and API-bound')).toBeVisible();
  await page.getByLabel('Search current library').fill('Economizer');
  await expect(page.getByText(/Economizer/i).first()).toBeVisible();
  await page.getByRole('button', { name: /HVAC System Configurator/i }).first().click();
  await expect(page.getByText('System design, evaluated by LBNL semantics')).toBeVisible();
  await expect(page.getByLabel('System template')).toBeVisible();
  await page.getByRole('button', { name: 'Generate programming brief' }).click();
  await expect(page.getByText('Engineering brief ready')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('Required points', { exact: true })).toBeVisible();
  await expect(page.getByText('Test scenarios', { exact: true })).toBeVisible();
  await expect(page.getByText('Why this is not deployable yet')).toBeVisible();
  const ctrlFlowTemplate = 'Buildings.Templates.AirHandlersFans.VAVMultiZone';
  const brief = await (await page.request.post(
    `/api/library/ctrl-flow/templates/${ctrlFlowTemplate}/programming-brief`,
    { data: { selections: {} } },
  )).json() as { point_requirements: { points: Array<{ id: string; label: string; data_type: string; role: string; units: string | null; required: boolean }> } };
  const pointsCsv = [
    'name,label,data_type,role,units,default,required',
    ...brief.point_requirements.points.filter((point) => point.required).map((point) => [
      point.id,
      point.id,
      point.data_type,
      point.role,
      point.units ?? '',
      point.data_type === 'boolean' ? 'false' : '0',
      'true',
    ].join(',')),
  ].join('\n');
  await page.locator('.ctrl-flow-upload input[type="file"]').setInputFiles({
    name: 'ahu-points.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(pointsCsv),
  });
  await page.getByRole('button', { name: 'Check points' }).click();
  await expect(page.getByText('Point contract satisfied')).toBeVisible({ timeout: 30_000 });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.goto('/next/environments');
  await expect(page.getByRole('heading', { name: 'Environment Workspace' })).toBeVisible();
  await expect(page.getByText('Custom contractor environments are first-class inputs')).toBeVisible();
  await expect(page.getByText('Inspection only · never executed')).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test('global command center and AI launcher route into real work', async ({ page }) => {
  const runs = await (await page.request.get('/api/runs')).json() as Array<{ id: string; job: { equipment_name: string } }>;
  test.skip(!runs.length, 'A retained program is required for command routing.');
  if (!runs.length) return;

  await page.goto('/next/');
  await page.getByRole('button', { name: /search projects/i }).click();
  await expect(page.getByRole('dialog', { name: /find anything/i })).toBeVisible();
  await page.getByPlaceholder(/search projects/i).fill(runs[0].job.equipment_name);
  await page.locator(`a[role="option"][href$="/studio/${runs[0].id}/wiresheet"]`).click();
  await expect(page).toHaveURL(new RegExp(`/next/studio/${runs[0].id}/wiresheet`));

  await page.keyboard.press('Meta+K');
  await expect(page.getByRole('dialog', { name: /find anything/i })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: /find anything/i })).not.toBeVisible();

  await page.getByRole('button', { name: 'Ask BACTalk' }).click();
  await expect(page.getByRole('dialog', { name: /choose a program/i })).toBeVisible();
  await page.locator(`a[role="option"][href$="/studio/${runs[0].id}/wiresheet?agent=1"]`).click();
  await expect(page.getByRole('dialog', { name: /work through this candidate/i })).toBeVisible();
  await expect(page.getByText('Proposal-only authority')).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test('administration exposes integration proof and qualification boundaries', async ({ page }) => {
  await page.goto('/next/system');
  await expect(page.getByRole('heading', { name: 'Administration' })).toBeVisible();
  await expect(page.getByText('Control plane verified')).toBeVisible();
  await expect(page.getByText('Offline only')).toBeVisible();
  await expect(page.getByRole('heading', { name: /what is installed, wired, compiled/i })).toBeVisible();
  await expect(page.getByRole('table')).toContainText('IBPSA BOPTEST');
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
