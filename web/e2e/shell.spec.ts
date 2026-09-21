import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

type Run = { id: string; status: string; origin: string; job: { name: string; equipment_name: string } };

async function axe(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
}

test('shell exposes the workspaces, the environment boundary, and both themes', async ({ page }) => {
  await page.goto('/next/');
  await expect(page.getByRole('heading', { name: /program, test, and release building controls/i })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible();
  await expect(page.getByLabel('Environment')).toContainText(/offline/i);
  await expect(page.getByText(/nothing here writes to a live building/i)).toBeVisible();
  await axe(page);

  // Theme is a first-class choice, not a fixed dark canvas.
  const html = page.locator('html');
  await page.getByRole('button', { name: /theme/i }).click();
  await expect(html).toHaveAttribute('data-theme', /dark|light/);
  const first = await html.getAttribute('data-theme');
  await page.getByRole('button', { name: /theme/i }).click();
  await expect(html).toHaveAttribute('data-theme', first === 'dark' ? 'light' : 'dark');
  await axe(page);
});

test('legacy workbench remains available during migration', async ({ page }) => {
  await page.goto('/');
  // Exact match: an empty run store also renders "No programming runs yet",
  // which a substring match would ambiguously resolve to.
  await expect(page.getByRole('heading', { name: 'Programming runs', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /import contractor job/i })).toBeVisible();
});

test('jobs list facets real candidates and opens every stage', async ({ page }) => {
  test.setTimeout(60_000);
  const runs = (await (await page.request.get('/api/runs')).json()) as Run[];
  const candidate = runs.find((run) => run.status === 'ready_for_review') ?? runs[0];
  test.skip(!candidate, 'A retained candidate is required.');

  await page.goto('/next/jobs');
  await expect(page.getByRole('heading', { name: 'Jobs' })).toBeVisible();
  await page.getByRole('button', { name: 'Awaiting review' }).click();
  await expect(page).toHaveURL(/facet=ready_for_review/);
  await page.getByLabel('Filter jobs').fill(candidate.id.slice(0, 8));
  await page.getByRole('link', { name: candidate.job.name }).first().click();
  await expect(page).toHaveURL(new RegExp(`/next/jobs/${candidate.id}/build`));
  await axe(page);

  const stages = page.getByRole('navigation', { name: 'Job stages' });
  for (const [label, heading] of [
    ['Intake', 'Job'],
    ['Test', 'Deterministic tests'],
    ['Review', 'Decision'],
    ['Release', 'Release'],
  ] as const) {
    await stages.getByRole('link', { name: new RegExp(`^\\d ${label}`) }).click();
    await expect(page.getByRole('heading', { name: heading, exact: true }).first()).toBeVisible();
    await axe(page);
  }

  const approved = runs.find((run) => run.status === 'approved');
  if (approved) {
    await page.goto(`/next/jobs/${approved.id}/release`);
    await expect(page.getByRole('link', { name: 'Approved target' })).toHaveAttribute('href', `/api/runs/${approved.id}/export`);
    await expect(page.getByRole('link', { name: 'Review bundle' })).toHaveAttribute('href', `/api/runs/${approved.id}/review-bundle`);
    expect((await page.request.get(`/api/runs/${approved.id}/review-bundle`)).ok()).toBe(true);
  }

  const failed = runs.find((run) => run.status === 'failed');
  if (failed) {
    await page.goto(`/next/jobs/${failed.id}/test`);
    await expect(page.getByText('Failed', { exact: true }).first()).toBeVisible();
    await page.goto(`/next/jobs/${failed.id}/release`);
    await expect(page.getByText(/downloads unlock only after approval/i)).toBeVisible();
  }
});

test('legacy studio and simulation links redirect into the stage model', async ({ page }) => {
  const runs = (await (await page.request.get('/api/runs')).json()) as Run[];
  test.skip(runs.length === 0, 'A retained candidate is required.');
  await page.goto(`/next/studio/${runs[0].id}/tests`);
  await expect(page).toHaveURL(new RegExp(`/next/jobs/${runs[0].id}/test$`));
  await page.goto('/next/simulations');
  await expect(page).toHaveURL(/\/next\/jobs\?facet=qualification$/);
  await page.goto('/next/system');
  await expect(page).toHaveURL(/\/next\/admin$/);
});

test('command palette reaches jobs and the agent mode', async ({ page }) => {
  const runs = (await (await page.request.get('/api/runs')).json()) as Run[];
  test.skip(runs.length === 0, 'A retained candidate is required.');
  await page.goto('/next/');
  await page.keyboard.press('ControlOrMeta+k');
  const palette = page.getByRole('combobox');
  await expect(palette).toBeFocused();
  await palette.fill(runs[0].job.name);
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(new RegExp(`/next/jobs/${runs[0].id}/build`));
  await page.keyboard.press('Escape');
  await axe(page);
});

test('projects, libraries, connections, and administration render real data', async ({ page }) => {
  await page.goto('/next/projects');
  await expect(page.getByRole('heading', { name: 'Projects' })).toBeVisible();
  const projects = (await (await page.request.get('/api/projects')).json()) as Array<{ id: string; project: { name: string } }>;
  if (projects.length > 0) {
    await page.getByRole('link', { name: new RegExp(projects[0].project.name) }).first().click();
    await expect(page.getByRole('heading', { name: 'Equipment candidates' })).toBeVisible();
  }
  await axe(page);

  await page.goto('/next/libraries');
  await expect(page.getByRole('heading', { name: 'Libraries' })).toBeVisible();
  await expect(page.getByRole('heading', { name: /guideline 36/i })).toBeVisible();
  await axe(page);

  await page.goto('/next/connections');
  await expect(page.getByRole('heading', { name: 'Connections' })).toBeVisible();
  await expect(page.getByText(/approval never enables live writes/i)).toBeVisible();
  await axe(page);

  await page.goto('/next/admin');
  await expect(page.getByRole('heading', { name: 'Administration' })).toBeVisible();
  await expect(page.getByText('live writes off')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Integration maturity' })).toBeVisible();
  await axe(page);
});

// Rebuilt in later phases of the UI rewrite. Each is skipped by name so the
// missing coverage is visible in every report until the journey returns.
test.fixme('contractor intake normalizes a real points list before build (guided intake, phase 6)', async () => {});
test.fixme('AI proposal renders as a ghost diff and opens the candidate (phase 5)', async () => {});
test.fixme('whole-building topology and high-fidelity evidence on one clock (phases 3, 4, 9)', async () => {});
test.fixme('contractor can upload, preflight, compile, and assemble a complex building project (phase 9)', async () => {});
test.fixme('ctrl-flow design pipeline from template to candidate (phase 6)', async () => {});
