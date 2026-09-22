import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

type Run = { id: string; status: string; origin: string; job: { name: string; equipment_name: string } };
type Report = { engine: string; passed: boolean; scenarios: Array<{ name: string; passed: boolean; assertions: unknown[]; samples: Array<Record<string, unknown>> }> };

async function axe(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
}

const META = new Set(['step', 'phase', 'phase_step', 'minute', 'scenario']);

/** A tiny, valid wiresheet preview the way the server renders one. */
function folderSvg(name: string): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 80" width="160" height="80"><rect x="4" y="4" width="152" height="72" rx="4" fill="#1b1f27" stroke="#8b5cf6"/><text x="12" y="24" font-size="10" fill="#e5e7eb">${name}</text><rect x="12" y="36" width="56" height="28" rx="2" fill="#2a2f3a" stroke="#6b7280"/><rect x="92" y="36" width="56" height="28" rx="2" fill="#2a2f3a" stroke="#6b7280"/><line x1="68" y1="50" x2="92" y2="50" stroke="#a78bfa"/></svg>`;
}

test('shadow runtime evidence streams, loads onto the clock, previews folders, and blocks approval and export', async ({ page }) => {
  test.setTimeout(90_000);
  const runs = (await (await page.request.get('/api/runs')).json()) as Run[];
  const candidate = runs.find((run) => run.job.equipment_name === 'EF_1') ?? runs.find((run) => run.status === 'ready_for_review') ?? runs[0];
  test.skip(!candidate, 'A retained candidate is required.');

  // The fixture reuses the candidate's real report so the trace axis, phases, and samples are genuine.
  const report = (await (await page.request.get(`/api/runs/${candidate.id}/report`)).json()) as Report;
  const scenario = report.scenarios.find((item) => item.samples.length > 0) ?? report.scenarios[0];
  expect(scenario, 'the candidate report needs at least one scenario').toBeTruthy();
  const signal = Object.keys(scenario.samples[0] ?? {}).find((key) => !META.has(key) && !key.includes('.')) ?? 'yDam';
  const divergenceTime = 2;
  const evidence = {
    schema: 'bactalk.shadow-qualification/v1',
    status: 'fail',
    run_id: candidate.id,
    tier: 'bog-simulated',
    engine: 'Niagara Shadow Runtime (bog-simulated, policy default, kernels python)',
    policy: 'default',
    kernel_backend: 'python',
    band_set: 'default',
    bog_sha256: 'a'.repeat(64),
    artifact_sha256_before_qualification: 'b'.repeat(64),
    approval_allowed: false,
    live_building_writes: false,
    report: { ...report, engine: 'Niagara Shadow Runtime (bog-simulated, policy default, kernels python)' },
    differential: {
      schema: 'bactalk.three-way-differential/v1',
      controller_id: 'TerminalUnits.Reheat.Controller',
      passed: false,
      reference_available: true,
      engines: { shadow: 'Niagara Shadow Runtime', interpreter: report.engine, reference: 'Open Control Engine 1.0' },
      cases: report.scenarios.map((item, index) => ({
        name: item.name,
        passed: index !== report.scenarios.indexOf(scenario),
        legs_available: ['shadow', 'interpreter', 'reference'],
        signals: [
          {
            signal,
            passed: index !== report.scenarios.indexOf(scenario),
            band: { kind: 'numeric', atolx: 2.0, atoly: 0.02, rationale: 'default numeric band', source: 'default' },
            legs: {
              'shadow-vs-interpreter': { leg: 'shadow-vs-interpreter', passed: index !== report.scenarios.indexOf(scenario), max_error: index !== report.scenarios.indexOf(scenario) ? 0 : 0.2, first_violation_time: index !== report.scenarios.indexOf(scenario) ? null : divergenceTime, engine: 'pure' },
            },
          },
        ],
        first_divergence: index !== report.scenarios.indexOf(scenario) ? null : { time_seconds: divergenceTime, block: signal, slot: 'out', shadow: 0.5, interpreter: 0.7, band: 0.02 },
      })),
      failing_cases: [scenario.name],
    },
    reference: { [scenario.name]: { [signal]: { times: [0, 1, 2, 3], values: [0.1, 0.2, 0.3, 0.4] } } },
  };

  const now = new Date().toISOString();
  const job = {
    schema_version: 'bactalk.qualification-job/v3',
    id: 'job-shadow-e2e',
    broker_job_id: 'rq-shadow-e2e',
    run_id: candidate.id,
    candidate_artifact_sha256: null,
    kind: 'shadow',
    transport: 'shadow_runtime',
    status: 'queued',
    model_filename: null,
    model_sha256: null,
    request_sha256: 'a'.repeat(64),
    input_sha256: 'b'.repeat(64),
    created_at: now,
    updated_at: now,
    started_at: null,
    completed_at: null,
    heartbeat_at: null,
    lease_expires_at: null,
    worker_id: null,
    actor_id: null,
    tenant_id: null,
    progress: { phase: 'queued', completed_steps: 0, total_steps: 3, percent: 0 },
    cancellation_requested: false,
    error: null,
    result_artifact_sha256: null,
    qualification_passed: null,
  };
  const event = (status: string, phase: string, completed: number, passed: boolean | null) =>
    `event: progress\ndata: ${JSON.stringify({ id: job.id, status, progress: { phase, completed_steps: completed, total_steps: 3, percent: (completed / 3) * 100 }, heartbeat_at: now, updated_at: now, error: null, qualification_passed: passed, result_artifact_sha256: passed === null ? null : 'c'.repeat(64), cancellation_requested: false })}\n\n`;
  await page.route(`**/api/runs/${candidate.id}/qualification-jobs/latest`, (route) => route.fulfill({ json: job }));
  await page.route('**/api/qualification-jobs/job-shadow-e2e', (route) => route.fulfill({ json: { ...job, status: 'succeeded', qualification_passed: false } }));
  await page.route('**/api/qualification-jobs/job-shadow-e2e/events', (route) =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: event('running', 'executing_bog', 2, null) + event('succeeded', 'complete', 3, false) }),
  );
  await page.route(`**/api/runs/${candidate.id}/verify/shadow`, (route) => route.fulfill({ json: evidence }));
  await page.route(`**/api/runs/${candidate.id}/niagara-previews`, (route) =>
    route.fulfill({ json: { schema: 'bactalk.niagara-previews/v1', folders: [{ name: 'Inputs', svg: folderSvg('Inputs') }, { name: 'Logic', svg: folderSvg('Logic') }] } }),
  );
  const realSummary = (await (await page.request.get(`/api/runs/${candidate.id}/release-summary`)).json()) as Record<string, unknown>;
  await page.route(`**/api/runs/${candidate.id}/release-summary`, (route) =>
    route.fulfill({ json: { ...realSummary, shadow: { available: true, passed: false, tier: 'bog-simulated', failing_cases: [scenario.name] } } }),
  );

  await page.goto(`/jobs/${candidate.id}/test`);
  await page.getByRole('tab', { name: 'Simulation' }).click();
  const progress = page.getByTestId('job-progress');
  await expect(progress).toHaveAttribute('data-status', 'succeeded');
  await expect(progress.getByText('Shadow Runtime · shadow runtime')).toBeVisible();
  await expect(progress.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100');

  // The enqueue form is small and marked bog-simulated; nothing here is a Niagara runtime qualification.
  await page.getByRole('button', { name: 'Shadow Runtime', exact: true }).click();
  const form = page.getByRole('form', { name: 'Shadow Runtime qualification' });
  await expect(form.getByLabel('Policy')).toHaveValue('default');
  await expect(form.getByRole('button', { name: 'Enqueue Shadow Runtime' })).toBeEnabled();
  await form.getByRole('button', { name: 'Close' }).click();

  // Retained Shadow Runtime evidence: verdict, tier, and the failing scenario's first divergence.
  const region = page.getByRole('region', { name: 'Shadow Runtime evidence' });
  await expect(region.getByText('Shadow Runtime failed')).toBeVisible();
  await expect(region.getByText('bog-simulated', { exact: true })).toBeVisible();
  await expect(region).toContainText(`t=${divergenceTime} s · block ${signal}.out shadow 0.50 vs interpreter 0.70 (band 0.02)`);

  // Loading it switches the shared clock and the band assertion is listed.
  await region.getByRole('button', { name: 'Load onto the clock' }).click();
  await expect(page.getByRole('combobox', { name: 'Clock source' })).toHaveValue('shadow');
  await expect(page.getByTestId('trends').getByText('Qualification failed', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Assertions' }).click();
  await expect(page.getByRole('tabpanel')).toContainText(`${scenario.name}: ${signal} within band`);
  await expect(page.getByRole('listbox', { name: 'Signals' })).toContainText(`${signal} reference`);
  await axe(page);

  // The Build stage previews every Niagara folder of the exported .bog.
  await page.getByRole('navigation', { name: 'Job stages' }).getByRole('link', { name: /Build/ }).click();
  const folders = page.getByRole('region', { name: 'Niagara folders' });
  await expect(folders).toBeVisible();
  await expect(folders.getByRole('img', { name: /^Niagara folder / })).toHaveCount(2);
  await expect(folders.getByRole('img', { name: 'Niagara folder Inputs' })).toBeVisible();

  // The Review stage shows the surface and the failing case blocks approval.
  await page.getByRole('navigation', { name: 'Job stages' }).getByRole('link', { name: /Review/ }).click();
  await expect(page.getByRole('heading', { name: 'Shadow Runtime', exact: true })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: 'Acknowledge Shadow Runtime' })).toBeVisible();
  await expect(page.getByText(`Shadow Runtime — ${scenario.name}: first divergence at t=${divergenceTime} s in ${signal}.out`)).toBeVisible();

  // And the Release stage says export is blocked.
  await page.getByRole('navigation', { name: 'Job stages' }).getByRole('link', { name: /Release/ }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Export is blocked' })).toContainText('the Shadow Runtime failed 1 scenario (bog-simulated evidence)');
});
