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
  const landmarks: Array<[string, () => import('@playwright/test').Locator]> = [
    ['Intake', () => page.getByRole('heading', { name: 'Job', exact: true })],
    ['Test', () => page.getByRole('group', { name: 'Master timeline' })],
    ['Review', () => page.getByRole('heading', { name: 'Decision', exact: true })],
    ['Release', () => page.getByRole('heading', { name: 'Release', exact: true })],
  ];
  for (const [label, landmark] of landmarks) {
    await stages.getByRole('link', { name: new RegExp(`^\\d ${label}`) }).click();
    await expect(landmark().first()).toBeVisible();
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

test('wiresheet draws declared ports, animates values on the shared clock, and jumps to assertions', async ({ page }) => {
  test.setTimeout(60_000);
  const runs = (await (await page.request.get('/api/runs')).json()) as Run[];
  // Prefer a generic-engine candidate whose report carries per-block samples.
  const candidate =
    runs.find((run) => run.job.equipment_name === 'AHU_1') ?? runs.find((run) => run.status === 'ready_for_review') ?? runs[0];
  test.skip(!candidate, 'A retained candidate is required.');
  const graph = (await (await page.request.get(`/api/runs/${candidate.id}/graph`)).json()) as {
    blocks: Array<{ id: string; kind: string; label: string }>;
    links: Array<{ source: string; source_slot: string; target: string; target_slot: string }>;
  };
  const catalog = (await (await page.request.get('/api/block-catalog')).json()) as {
    kinds: Array<{ kind: string; inputs: Array<{ name: string }>; outputs: Array<{ name: string }> }>;
  };

  await page.goto(`/next/jobs/${candidate.id}/build`);
  const sheet = page.getByRole('application', { name: 'Wiresheet' });
  await expect(sheet).toBeVisible();
  await expect(page.locator('.react-flow__node')).toHaveCount(graph.blocks.length);
  await expect(page.locator('.react-flow__edge')).toHaveCount(graph.links.length);

  // Ports come from the catalog, including inputs that no link feeds.
  const withInputs = graph.blocks.find((block) => (catalog.kinds.find((kind) => kind.kind === block.kind)?.inputs.length ?? 0) > 0);
  if (withInputs) {
    const spec = catalog.kinds.find((kind) => kind.kind === withInputs.kind)!;
    const node = page.locator(`.react-flow__node[data-id="${withInputs.id}"]`);
    for (const port of spec.inputs) await expect(node.locator(`.react-flow__handle[data-handleid="${port.name}"]`)).toHaveCount(1);
    for (const port of spec.outputs) await expect(node.locator(`.react-flow__handle[data-handleid="${port.name}"]`)).toHaveCount(1);
  }

  // Values on the sheet follow the clock: step forward and the readout moves.
  const readout = page.getByRole('group', { name: 'Playback' }).getByText(/\d+\/\d+/);
  const before = await readout.textContent();
  await sheet.focus();
  await page.keyboard.press(']');
  await expect(readout).not.toHaveText(before ?? '');
  await page.getByRole('slider', { name: 'Scan position' }).focus();
  await page.keyboard.press('End');
  // Chips only update at a legible zoom (level of detail), so zoom to a block first.
  await page.getByRole('textbox', { name: 'Find block' }).fill(graph.blocks[0].id);
  await page.keyboard.press('Enter');
  const chip = page.locator(`.react-flow__node[data-id="${graph.blocks[0].id}"] .chip`).first();
  await expect(chip).not.toHaveText('—');

  // Outline → inspector → jump highlights the upstream path.
  const output = graph.blocks.find((block) => block.kind.endsWith('_output'));
  if (output) {
    await page.getByRole('navigation', { name: 'Block outline' }).getByRole('button', { name: output.label, exact: true }).click();
    await expect(page.getByRole('heading', { name: output.label, exact: true })).toBeVisible();
    const jump = page.getByRole('button', { name: /^Jump$/ }).first();
    if (await jump.count()) {
      await jump.click();
      await expect(page.locator(`.react-flow__node[data-id="${output.id}"].selected`)).toHaveCount(1);
    }
  }
  await axe(page);
});

test('an AI proposal renders as a ghost diff over the parent wiresheet', async ({ page }) => {
  test.setTimeout(60_000);
  const runs = (await (await page.request.get('/api/runs')).json()) as Run[];
  const candidate = runs.find((run) => run.status === 'ready_for_review') ?? runs[0];
  test.skip(!candidate, 'A retained candidate is required.');
  const detail = (await (await page.request.get(`/api/runs/${candidate.id}`)).json()) as Record<string, unknown>;
  const graph = (await (await page.request.get(`/api/runs/${candidate.id}/graph`)).json()) as {
    name: string;
    blocks: Array<{ id: string; kind: string; label: string; x: number; y: number; config: Record<string, unknown> }>;
    links: Array<{ source: string; source_slot: string; target: string; target_slot: string }>;
  };
  const constBlock = graph.blocks.find((block) => block.kind === 'numeric_const') ?? graph.blocks[0];
  // The parent had one extra block and a different constant; the child (this
  // run) removed the block and changed the value.
  const parentGraph = {
    ...graph,
    blocks: [
      ...graph.blocks.map((block) => (block.id === constBlock.id ? { ...block, config: { ...block.config, value: 999 } } : block)),
      { id: 'GhostOnly', kind: 'numeric_const', label: 'Removed by proposal', x: 40, y: 900, config: { value: 1 } },
    ],
  };
  await page.route(`**/api/runs/${candidate.id}`, (route) =>
    route.fulfill({ json: { ...detail, origin: 'ai_proposal', parent_run_id: 'parent-mock', changes: { added: [], modified: [`block:${constBlock.id}`], removed: ['block:GhostOnly', 'block:NotReallyThere'] } } }),
  );
  await page.route('**/api/runs/parent-mock/graph', (route) => route.fulfill({ json: parentGraph }));

  await page.goto(`/next/jobs/${candidate.id}/build`);
  await expect(page.getByText(/AI proposal · from parent-m/)).toBeVisible();
  await page.getByRole('button', { name: /compare with parent/i }).click();
  await expect(page.getByText(/1 removed, 1 changed/)).toBeVisible();
  // Off-screen nodes are not rendered; fit the view so the ghost is on it.
  await page.getByRole('application', { name: 'Wiresheet' }).focus();
  await page.keyboard.press('f');
  await expect(page.locator('.wiresheet-node[data-diff="removed"]')).toHaveCount(1);
  await expect(page.locator('.wiresheet-node[data-diff="modified"]')).toHaveCount(1);
  // The server listed a change the graphs do not show; the UI says so rather than hiding it.
  await expect(page.getByText(/1 server-listed changes not visible/)).toBeVisible();
  await page.getByRole('navigation', { name: 'Block outline' }).getByRole('button', { name: constBlock.label }).first().click();
  await expect(page.getByRole('heading', { name: 'Proposed change' })).toBeVisible();
  await expect(page.getByText('999')).toBeVisible();
  await axe(page);
});

test('wiresheet scrubs a 500-block synthetic sheet without dropping frames', async ({ page }) => {
  test.setTimeout(90_000);
  const runs = (await (await page.request.get('/api/runs')).json()) as Run[];
  test.skip(runs.length === 0, 'A retained candidate is required.');
  const base = runs[0];
  const detail = (await (await page.request.get(`/api/runs/${base.id}`)).json()) as Record<string, unknown>;
  const BLOCKS = 500;
  const SCANS = 200;
  const blocks = Array.from({ length: BLOCKS }, (_, i) => ({
    id: `B${i}`,
    kind: i % 10 === 0 ? 'numeric_input' : i % 10 === 9 ? 'numeric_output' : 'add',
    label: `Block ${i}`,
    x: 40 + (i % 25) * 230,
    y: 50 + Math.floor(i / 25) * 120,
    config: {},
  }));
  const links = blocks.slice(1).map((block, i) => ({ source: `B${i}`, source_slot: 'out', target: block.id, target_slot: block.kind === 'numeric_output' ? 'in' : 'a' }));
  const samples = Array.from({ length: SCANS }, (_, s) => {
    const sample: Record<string, number> = { step: s + 1 };
    for (let i = 0; i < BLOCKS; i += 1) sample[`B${i}`] = Math.sin((s + i) / 7) * 100;
    return sample;
  });
  await page.route(`**/api/runs/${base.id}/graph`, (route) => route.fulfill({ json: { name: 'Synthetic', blocks, links, metadata: {} } }));
  await page.route(`**/api/runs/${base.id}/report`, (route) =>
    route.fulfill({ json: { engine: 'synthetic', passed: true, coverage: null, scenarios: [{ name: 'perf', passed: true, assertions: [], samples }] } }),
  );
  await page.route(`**/api/runs/${base.id}`, (route) => route.fulfill({ json: { ...detail, job: { ...(detail.job as object), acceptance_tests: [{ name: 'perf', repeat: SCANS, step_seconds: 1, expectations: [], faults: [], timeline: [] }] } } }));

  await page.goto(`/next/jobs/${base.id}/build`);
  await expect(page.locator('.react-flow__node').first()).toBeVisible();
  await page.waitForTimeout(1800);

  const measure = () =>
    page.evaluate(async (scans) => {
    const frame = () =>
      new Promise<number>((resolve) => {
        const start = performance.now();
        requestAnimationFrame(() => resolve(performance.now() - start));
      });
    const idle: number[] = [];
    for (let i = 0; i < 60; i += 1) idle.push(await frame());
    const slider = document.querySelector<HTMLInputElement>('input[aria-label="Scan position"]')!;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    const scrub: number[] = [];
    for (let i = 0; i < scans; i += 1) {
      setter.call(slider, String(i));
      slider.dispatchEvent(new Event('input', { bubbles: true }));
      scrub.push(await frame());
    }
    return { idle, scrub };
  }, SCANS);
  const p = (values: number[], q: number) => [...values].sort((a, b) => a - b)[Math.floor(values.length * q)];
  const report = (label: string, idle: number[], scrub: number[]) =>
    console.log(
      `[perf] ${label}: idle median ${p(idle, 0.5).toFixed(1)}ms p95 ${p(idle, 0.95).toFixed(1)}ms · scrub median ${p(scrub, 0.5).toFixed(1)}ms p95 ${p(scrub, 0.95).toFixed(1)}ms`,
    );

  // Software-rendered headless Chromium is not the 16.7 ms target hardware;
  // the release gate in phase 10 runs this on a real GPU. Here the scrub cost
  // on top of an idle frame must stay small at both levels of detail.
  const overview = await measure();
  report('500 blocks, whole sheet in view', overview.idle, overview.scrub);
  expect(p(overview.scrub, 0.95) - p(overview.idle, 0.95)).toBeLessThan(20);

  await page.getByRole('textbox', { name: 'Find block' }).fill('Block 250');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(600);
  const zoomed = await measure();
  report('500 blocks, zoomed to legible chips', zoomed.idle, zoomed.scrub);
  expect(p(zoomed.scrub, 0.95) - p(zoomed.idle, 0.95)).toBeLessThan(20);
});

test('test stage puts timeline, trends, and evidence on one clock', async ({ page }) => {
  test.setTimeout(60_000);
  const runs = (await (await page.request.get('/api/runs')).json()) as Run[];
  const candidate = runs.find((run) => run.job.equipment_name === 'EF_1') ?? runs.find((run) => run.status === 'ready_for_review') ?? runs[0];
  test.skip(!candidate, 'A retained candidate is required.');
  const report = (await (await page.request.get(`/api/runs/${candidate.id}/report`)).json()) as {
    scenarios: Array<{ assertions: Array<{ name: string }> }>;
  };
  const assertionCount = report.scenarios.reduce((sum, scenario) => sum + scenario.assertions.length, 0);

  await page.goto(`/next/jobs/${candidate.id}/test`);
  await expect(page.getByRole('group', { name: 'Master timeline' })).toBeVisible();
  await expect(page.getByRole('listbox', { name: 'Signals' })).toBeVisible();
  // A numeric pane, or boolean lanes when the sequence has no numeric signals.
  await expect(page.locator('.uplot, [aria-label="Boolean state lanes"]').first()).toBeVisible();

  // Every assertion from the report is listed, none dropped.
  await expect(page.getByRole('tabpanel')).toContainText(`of ${assertionCount} assertions passed`);

  // Clicking an assertion moves the shared clock.
  const readout = page.getByRole('group', { name: 'Playback' }).getByText(/\d+\/\d+/);
  await page.getByRole('slider', { name: 'Scan position' }).focus();
  await page.keyboard.press('Home');
  const before = await readout.textContent();
  const last = page.getByRole('tabpanel').getByRole('button', { name: /observed/ }).last();
  await last.click();
  await expect(last).toHaveAttribute('aria-current', 'true');
  await expect(readout).not.toHaveText(before ?? '');

  // Rail toggles a signal off and on.
  const option = page.getByRole('listbox', { name: 'Signals' }).getByRole('option').first();
  const wasOn = (await option.getAttribute('aria-selected')) === 'true';
  await option.click();
  await expect(option).toHaveAttribute('aria-selected', String(!wasOn));
  await option.click();
  await expect(option).toHaveAttribute('aria-selected', String(wasOn));

  for (const tab of ['Decision coverage', 'Faults', 'Qualification', 'Data']) {
    await page.getByRole('tab', { name: tab }).click();
    await expect(page.getByRole('tabpanel')).toBeVisible();
  }
  await axe(page);
});

test('schematic builds from the job and animates from the clock', async ({ page }) => {
  test.setTimeout(60_000);
  const runs = (await (await page.request.get('/api/runs')).json()) as Run[];
  const candidate = runs.find((run) => run.job.equipment_name === 'AHU_1') ?? runs[0];
  test.skip(!candidate, 'A retained candidate is required.');
  await page.goto(`/next/jobs/${candidate.id}/test`);
  const toggle = page.getByRole('button', { name: /^Schematic$/ });
  if ((await toggle.getAttribute('aria-pressed')) !== 'true') await toggle.click();
  const schematic = page.getByRole('img', { name: /air handling unit|points|vav|exhaust|pump/i }).first();
  await expect(schematic).toBeVisible();
  // Bound symbols carry live values once the clock moves.
  await page.getByRole('slider', { name: 'Scan position' }).focus();
  await page.keyboard.press('End');
  const value = schematic.locator('[data-slot="dischargeTemp"] [data-live-value]');
  await expect(value).not.toHaveText('—');
  const fan = schematic.locator('[data-slot="fanCommand"]').first();
  await expect(fan).toHaveAttribute('data-on', /true|false/);
  // Bindings are inspectable and overridable.
  await page.getByRole('button', { name: /bound$/ }).click();
  await expect(page.getByRole('combobox', { name: 'Signal for Supply fan command' })).toBeVisible();
  await page.keyboard.press('Escape');
  await axe(page);
});

test('project system map draws equipment, relationships, and bindings', async ({ page }) => {
  const projects = (await (await page.request.get('/api/projects')).json()) as Array<{ id: string; project: { name: string; equipment: unknown[] } }>;
  test.skip(projects.length === 0, 'A retained project is required.');
  await page.goto(`/next/projects/${projects[0].id}`);
  const map = page.getByRole('group', { name: `System map for ${projects[0].project.name}` });
  await expect(map).toBeVisible();
  await expect(map.getByRole('button')).toHaveCount(projects[0].project.equipment.length);
  await axe(page);
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
  await expect(palette).toBeVisible();
  await palette.click();
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
