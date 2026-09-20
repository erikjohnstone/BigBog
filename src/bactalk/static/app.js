const state = {
  runs: [], current: null, graph: null, report: null, volttron: null, nhaystack: null,
  bacnetLab: null, environment: null, alarmPlan: null, stationAssembly: null,
  bacnetProbe: null,
  deliverables: null,
  reference: null, readiness: null, capabilities: null,
  integrationAudit: null,
  zoom: 1, graphBounds: { width: 1920, height: 940 }, selectedNode: null,
  aiStatus: null, chatHistory: [],
};

const NODE_WIDTH = 196;

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
})[character]);

async function request(url, options = {}) {
  const response = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { message = (await response.json()).detail || message; } catch (_) { /* no JSON */ }
    throw new Error(message);
  }
  return response.json();
}

function toast(message) {
  const element = $('#toast');
  element.textContent = message;
  element.classList.remove('hidden');
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => element.classList.add('hidden'), 3500);
}

function statusLabel(status) {
  return { ready_for_review: 'Ready for review', approved: 'Approved', rejected: 'Rejected', failed: 'Tests failed' }[status] || status;
}

async function loadRuns(preferredId) {
  state.runs = await request('/api/runs');
  const empty = !state.runs.length;
  $('#empty-state').classList.toggle('hidden', !empty);
  $('#workspace').classList.toggle('hidden', empty);
  if (empty) return;
  const select = $('#run-select');
  select.innerHTML = state.runs.map(run => `<option value="${escapeHtml(run.id)}">${run.origin === 'ai_proposal' ? 'AI proposal · ' : ''}${escapeHtml(run.job.equipment_name)} · ${escapeHtml(run.id)}</option>`).join('');
  const selected = state.runs.find(run => run.id === preferredId) || state.runs[0];
  select.value = selected.id;
  await loadRun(selected.id);
}

async function loadRun(runId) {
  const record = await request(`/api/runs/${runId}`);
  const hasAlarmPlan = (record.deliverable_artifact_paths || []).some(path => path.endsWith('niagara-alarm-plan.json'));
  const [graph, report, volttron, nhaystack, bacnetLab, environment, alarmPlan, stationAssembly, deliverables] = await Promise.all([
    request(`/api/runs/${runId}/graph`),
    request(`/api/runs/${runId}/report`),
    record.volttron_manifest_path ? request(`/api/runs/${runId}/volttron-manifest`) : null,
    record.nhaystack_manifest_path ? request(`/api/runs/${runId}/nhaystack-manifest`) : null,
    record.bacnet_lab_manifest_path ? request(`/api/runs/${runId}/bacnet-lab-manifest`) : null,
    record.environment_manifest_path ? request(`/api/runs/${runId}/environment-manifest`) : null,
    hasAlarmPlan ? request(`/api/runs/${runId}/niagara-alarm-plan`) : null,
    record.station_assembly_manifest_path ? request(`/api/runs/${runId}/station-assembly`) : null,
    record.deliverable_manifest_path ? request(`/api/runs/${runId}/deliverables`) : null,
  ]);
  state.current = record;
  state.graph = graph;
  state.report = report;
  state.volttron = volttron;
  state.nhaystack = nhaystack;
  state.bacnetLab = bacnetLab;
  state.bacnetProbe = null;
  state.environment = environment;
  state.alarmPlan = alarmPlan;
  state.stationAssembly = stationAssembly;
  state.deliverables = deliverables;
  render();
}

function render() {
  const { current: run, graph, report } = state;
  $('#run-status').textContent = statusLabel(run.status);
  $('#run-status').className = `pill ${run.status}`;
  $('#artifact-hash').textContent = run.artifact_sha256;
  $('#job-name').textContent = run.job.name;
  $('#site-name').textContent = `${run.job.site} · ${run.job.equipment_name}`;
  $('#sequence-name').textContent = run.job.sequence.controller_id
    ? `${run.job.sequence.controller_id} · ${run.job.sequence.family.replaceAll('_', ' ')}`
    : run.job.sequence.family.replaceAll('_', ' ');
  $('#sequence-version').textContent = run.job.sequence.version;
  $('#block-count').textContent = graph.blocks.length;
  $('#link-count').textContent = graph.links.length;
  const passed = report.scenarios.filter(item => item.passed).length;
  $('#pass-count').textContent = `${passed}/${report.scenarios.length}`;
  $('#test-total').textContent = report.passed ? 'scenarios passed' : 'scenarios';
  $('#test-engine').textContent = report.engine;
  $('#graph-title').textContent = `${graph.name} wiresheet`;
  renderGraph(graph);
  renderAgentAttempts(run);
  renderTests(report);
  renderChanges(run.changes);
  renderDeliverables(state.deliverables);
  renderPoints(run.job.points);
  renderEdge(
    state.volttron,
    state.nhaystack,
    state.bacnetLab,
    state.environment,
    state.alarmPlan,
    state.stationAssembly,
  );
  renderReadiness(state.readiness);
  renderIntegrationAudit(state.integrationAudit);
  renderCapabilities(state.capabilities);
  renderReference(state.reference);
  renderApproval(run);
}

function nodeClass(kind) {
  if (kind.endsWith('_input')) return 'io source-only';
  if (kind.endsWith('_output')) return 'output';
  if (kind.endsWith('_const')) return 'io source-only';
  return 'logic';
}

function renderGraph(graph) {
  const incoming = {};
  const outgoing = {};
  graph.blocks.forEach(block => { incoming[block.id] = []; outgoing[block.id] = []; });
  graph.links.forEach(link => {
    if (!incoming[link.target].includes(link.target_slot)) incoming[link.target].push(link.target_slot);
    if (!outgoing[link.source].includes(link.source_slot)) outgoing[link.source].push(link.source_slot);
  });
  const dimensions = {};
  graph.blocks.forEach(block => {
    dimensions[block.id] = {
      width: NODE_WIDTH,
      height: Math.max(76, 52 + Math.max(incoming[block.id].length, outgoing[block.id].length) * 19),
    };
  });
  const nodes = $('#graph-nodes');
  nodes.innerHTML = graph.blocks.map(block => {
    const value = block.config.value ?? block.config.default;
    const size = dimensions[block.id];
    const inputPorts = incoming[block.id].map((slot, index) => `<span class="node-port input-port" style="top:${50 + index * 19}px" title="input ${escapeHtml(slot)}"><i></i><em>${escapeHtml(slot)}</em></span>`).join('');
    const outputPorts = outgoing[block.id].map((slot, index) => `<span class="node-port output-port" style="top:${50 + index * 19}px" title="output ${escapeHtml(slot)}"><em>${escapeHtml(slot)}</em><i></i></span>`).join('');
    return `<div class="graph-node ${nodeClass(block.kind)}" tabindex="0" role="button" style="left:${block.x}px;top:${block.y}px;width:${size.width}px;height:${size.height}px" data-node="${escapeHtml(block.id)}">
      <div class="node-kind">${escapeHtml(block.kind.replaceAll('_', ' '))}</div>
      <div class="node-title" title="${escapeHtml(block.id)}">${escapeHtml(block.label)}</div>
      ${value === undefined ? '' : `<div class="node-value">${escapeHtml(value)}</div>`}
      ${inputPorts}${outputPorts}
    </div>`;
  }).join('');
  const byId = Object.fromEntries(graph.blocks.map(block => [block.id, block]));
  const portY = (slots, slot) => 50 + Math.max(0, slots.indexOf(slot)) * 19;
  $('#graph-svg').innerHTML = `<defs><marker id="edge-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker></defs>` + graph.links.map(link => {
    const source = byId[link.source];
    const target = byId[link.target];
    const x1 = source.x + NODE_WIDTH;
    const y1 = source.y + portY(outgoing[source.id], link.source_slot);
    const x2 = target.x;
    const y2 = target.y + portY(incoming[target.id], link.target_slot);
    const bend = Math.max(35, (x2 - x1) * 0.48);
    return `<path class="graph-edge" marker-end="url(#edge-arrow)" d="M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}" />`;
  }).join('');
  const width = Math.max(1000, ...graph.blocks.map(block => block.x + NODE_WIDTH + 80));
  const height = Math.max(620, ...graph.blocks.map(block => block.y + dimensions[block.id].height + 80));
  state.graphBounds = { width, height };
  $('#graph-stage').style.width = `${width}px`;
  $('#graph-stage').style.height = `${height}px`;
  $('#graph-svg').setAttribute('width', width);
  $('#graph-svg').setAttribute('height', height);
  setGraphZoom(state.zoom);
  $$('.graph-node').forEach(element => {
    const select = () => selectNode(element.dataset.node);
    element.addEventListener('click', select);
    element.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') select(); });
  });
  if (state.selectedNode && byId[state.selectedNode]) selectNode(state.selectedNode);
}

function setGraphZoom(value) {
  state.zoom = Math.min(1.6, Math.max(0.35, value));
  const stage = $('#graph-stage');
  stage.style.transform = `scale(${state.zoom})`;
  $('#graph-stage-wrap').style.width = `${state.graphBounds.width * state.zoom}px`;
  $('#graph-stage-wrap').style.height = `${state.graphBounds.height * state.zoom}px`;
  $('#zoom-level').textContent = `${Math.round(state.zoom * 100)}%`;
}

function fitGraph() {
  const canvas = $('#graph-canvas');
  const scale = Math.min(
    (canvas.clientWidth - 30) / state.graphBounds.width,
    (canvas.clientHeight - 30) / state.graphBounds.height,
    1,
  );
  setGraphZoom(scale);
  canvas.scrollTo({ left: 0, top: 0, behavior: 'smooth' });
}

function selectNode(nodeId) {
  state.selectedNode = nodeId;
  $$('.graph-node').forEach(node => node.classList.toggle('selected', node.dataset.node === nodeId));
  const block = state.graph.blocks.find(item => item.id === nodeId);
  const incoming = state.graph.links.filter(link => link.target === nodeId);
  const outgoing = state.graph.links.filter(link => link.source === nodeId);
  $('#node-inspector').innerHTML = `<span class="panel-kicker">NODE INSPECTOR</span>
    <div class="inspector-kind">${escapeHtml(block.kind.replaceAll('_', ' '))}</div>
    <h3>${escapeHtml(block.label)}</h3><code>${escapeHtml(block.id)}</code>
    <dl><dt>Inputs</dt><dd>${incoming.map(link => `<span>${escapeHtml(link.target_slot)} <b>←</b> ${escapeHtml(link.source)}.${escapeHtml(link.source_slot)}</span>`).join('') || '<span>None</span>'}</dd>
    <dt>Outputs</dt><dd>${outgoing.map(link => `<span>${escapeHtml(link.source_slot)} <b>→</b> ${escapeHtml(link.target)}.${escapeHtml(link.target_slot)}</span>`).join('') || '<span>None</span>'}</dd>
    <dt>Configuration</dt><dd><pre>${escapeHtml(JSON.stringify(block.config, null, 2))}</pre></dd></dl>`;
}

function renderTests(report) {
  const coverage = report.coverage || {};
  const coveragePanel = $('#test-coverage');
  if (coverage.schema) {
    const gaps = (coverage.gaps || []).map(item => `<code>${escapeHtml(item)}</code>`).join('');
    coveragePanel.innerHTML = `<div><span class="panel-kicker">DECISION COVERAGE</span><strong>${escapeHtml(coverage.percent)}%</strong><p>${escapeHtml(coverage.interpretation)}</p></div>
      <div class="coverage-stat"><b>${escapeHtml(coverage.outcomes_observed)}/${escapeHtml(coverage.outcomes_possible)}</b><span>outcomes exercised</span></div>
      ${gaps ? `<details><summary>${escapeHtml(coverage.gaps.length)} untested paths</summary><div class="reference-artifacts">${gaps}</div></details>` : '<span class="check">✓ BOTH OUTCOMES COVERED</span>'}`;
    coveragePanel.classList.remove('hidden');
  } else {
    coveragePanel.innerHTML = '';
    coveragePanel.classList.add('hidden');
  }
  $('#scenario-list').innerHTML = report.scenarios.map(scenario => `
    <article class="scenario">
      <div class="scenario-head"><h3>${escapeHtml(scenario.name)}</h3><span class="check">${scenario.passed ? '✓ PASS' : '× FAIL'}</span></div>
      <div class="assertions">${scenario.assertions.map(item => `
        <div class="assertion"><b>${item.passed ? '✓' : '×'}</b><span>${escapeHtml(item.name)}</span><code>${escapeHtml(item.observed)} · ${escapeHtml(item.expected)}</code></div>
      `).join('')}</div>
    </article>
  `).join('');
}

function renderAgentAttempts(run) {
  const attempts = run.agent_attempts || [];
  const summary = $('#agent-loop-summary');
  const timeline = $('#agent-attempts');
  if (!attempts.length) {
    summary.innerHTML = '<strong>No agent execution record</strong><p>This legacy run predates attempt-level evidence.</p>';
    timeline.innerHTML = '';
    return;
  }
  const finalAttempt = attempts[attempts.length - 1];
  const repairs = Math.max(0, attempts.length - 1);
  summary.className = `agent-loop-summary ${finalAttempt.passed ? 'passed' : 'failed'}`;
  summary.innerHTML = `<div><span class="panel-kicker">SELF-TEST + REPAIR LOOP</span><strong>${attempts.length} ${attempts.length === 1 ? 'attempt' : 'attempts'} · ${repairs} ${repairs === 1 ? 'repair' : 'repairs'}</strong></div>
    <p>${finalAttempt.passed ? 'Deterministic acceptance tests pass. Human approval is still required.' : 'The repair budget ended with failing tests. This candidate cannot be approved.'}</p>`;
  timeline.innerHTML = attempts.map((attempt, index) => {
    const changeGroups = ['added', 'modified', 'removed'].flatMap(group =>
      (attempt.changes?.[group] || []).map(item => `<code><b>${escapeHtml(group)}</b> ${escapeHtml(item)}</code>`)
    );
    const failures = (attempt.failures || []).map(failure => `
      <div class="attempt-failure">
        <strong>${escapeHtml(failure.scenario)} · ${escapeHtml(failure.assertion)}</strong>
        <span>Observed: ${escapeHtml(failure.observed)}</span>
        <span>Expected: ${escapeHtml(failure.expected)}</span>
      </div>`).join('') || (attempt.failed_assertions || []).map(name => `
      <div class="attempt-failure"><strong>${escapeHtml(name)}</strong></div>`).join('');
    return `<article class="agent-attempt ${attempt.passed ? 'passed' : 'failed'}">
      <div class="attempt-head">
        <div><span>ATTEMPT ${escapeHtml(attempt.iteration)}</span><strong>${index === 0 ? 'Initial candidate' : 'Repaired candidate'}</strong></div>
        <span class="attempt-state">${attempt.passed ? '✓ PASS' : '× FAIL'}</span>
      </div>
      <div class="attempt-hash">GRAPH SHA-256 <code>${escapeHtml((attempt.graph_sha256 || 'not-recorded').slice(0, 16))}${attempt.graph_sha256 ? '…' : ''}</code></div>
      <div class="attempt-delta">${index === 0 ? '<code>Initial typed graph generated</code>' : (changeGroups.join('') || '<code>No structural graph changes</code>')}</div>
      ${failures ? `<div class="attempt-failures">${failures}</div>` : '<div class="attempt-pass-copy">All acceptance assertions passed.</div>'}
      ${!attempt.passed && index < attempts.length - 1 ? '<div class="repair-arrow">↓ failure evidence sent into bounded repair</div>' : ''}
    </article>`;
  }).join('');
}

function renderChanges(changes) {
  $('#change-list').innerHTML = ['added', 'modified', 'removed'].map(group => `
    <div class="change-group"><h3>${group} · ${(changes[group] || []).length}</h3>
      ${(changes[group] || []).map(item => `<code>${escapeHtml(item)}</code>`).join('') || '<code>None</code>'}
    </div>
  `).join('');
}

function renderDeliverables(manifest) {
  if (!manifest) return;
  $('#deliverable-summary').innerHTML = `<strong>${manifest.artifacts.length} signed review artifacts · deployment ${manifest.deployment_ready ? 'ready' : 'blocked'}</strong>
    <p>These files make missing Niagara target work explicit; a requirements manifest is not represented as a deployed extension.</p>`;
  $('#deliverable-coverage').innerHTML = Object.entries(manifest.coverage).map(([name, item]) => `
    <article class="reference-card">
      <div class="reference-head"><h3>${escapeHtml(name.replaceAll('_', ' '))}</h3><span class="installed-state">${item.emitted ? 'EMITTED' : 'MISSING'}</span></div>
      <p>${escapeHtml(item.target || 'No target artifact')}</p>
      <div class="reference-meta">${Object.entries(item).filter(([key, value]) => key !== 'target' && key !== 'emitted' && typeof value === 'boolean').map(([key, value]) => `<span>${value ? '✓' : '×'} ${escapeHtml(key.replaceAll('_', ' '))}</span>`).join('')}</div>
    </article>`).join('');
  $('#deliverable-blockers').innerHTML = `<div class="change-group"><h3>blocking gates · ${manifest.blocking_gates.length}</h3>${manifest.blocking_gates.map(item => `<code>${escapeHtml(item)}</code>`).join('')}</div>`;
}

function renderPoints(points) {
  $('#points-table').innerHTML = points.map(point => `<tr>
    <td><strong>${escapeHtml(point.label)}</strong><br><code>${escapeHtml(point.name)}</code>${point.source_name ? `<br><small>source: ${escapeHtml(point.source_name)}</small>` : ''}</td>
    <td>${escapeHtml(point.role)}</td><td>${escapeHtml(point.data_type)}${point.units ? ` · ${escapeHtml(point.units)}` : ''}</td>
    <td><code>${point.bacnet_object ? `${escapeHtml(point.bacnet_device_instance || 'scan')} / ${escapeHtml(point.bacnet_object)}` : '—'}</code></td>
    <td><code>${escapeHtml(point.niagara_ord || 'unbound')}</code>${point.niagara_write_priority ? `<br><small>priority ${escapeHtml(point.niagara_write_priority)}</small>` : ''}</td>
    <td><code>${escapeHtml(point.brick_class || '—')}</code></td>
  </tr>`).join('');
}

function renderEdge(manifest, nhaystack, bacnetLab, environment, alarmPlan, stationAssembly) {
  const summary = $('#edge-summary');
  const devices = $('#edge-devices');
  const semantic = nhaystack ? `<article class="reference-card">
    <div class="reference-head"><div><span class="integration-state">${escapeHtml(nhaystack.mode)}</span><h3>Niagara semantic tags</h3></div><span class="installed-state">INSTALLER + READBACK</span></div>
    <p>${escapeHtml(nhaystack.tag_annotation_count)} exact-ORD tag annotations · ${escapeHtml(nhaystack.point_count)} points · ${escapeHtml(nhaystack.historized_point_count)} compiled histories · ${escapeHtml(nhaystack.record_count)} expected records</p>
    <p><code>${escapeHtml(nhaystack.equipment_ord)}</code>${nhaystack.site_ord ? `<br><code>${escapeHtml(nhaystack.site_ord)}</code>` : '<br><small>No site ORD declared; siteRef is intentionally omitted.</small>'}</p>
    <div class="reference-limit">${escapeHtml(nhaystack.runtime_gate)}</div>
  </article>` : '';
  const alarm = alarmPlan ? `<article class="reference-card">
    <div class="reference-head"><div><span class="integration-state">NIAGARA SDK PLAN</span><h3>Alarm extensions</h3></div><span class="installed-state">${escapeHtml(alarmPlan.extensions.length)} SOURCES</span></div>
    <p>${alarmPlan.extensions.map(item => `<code>${escapeHtml(item.point)} → ${escapeHtml(item.algorithm.type)}</code>`).join(' ') || 'No alarms declared.'}</p>
    <div class="reference-limit">Alarm class priority, acknowledgement, recipients, and routing remain licensed-runtime policy gates.</div>
  </article>` : '';
  const assembled = stationAssembly ? `<article class="reference-card">
    <div class="reference-head"><div><span class="integration-state">OFFLINE ASSEMBLY</span><h3>Workbench station package</h3></div><span class="installed-state">${escapeHtml(stationAssembly.action).toUpperCase()}</span></div>
    <p><code>${escapeHtml(stationAssembly.target_program_ord)}</code><br>${escapeHtml(stationAssembly.handle_rebase_count)} handles rebased · ${escapeHtml(stationAssembly.assembled_handle_count)} total handles</p>
    <div class="reference-limit">${escapeHtml(stationAssembly.runtime_gate)}</div>
  </article>` : '';
  const lab = bacnetLab ? `<article class="reference-card">
    <div class="reference-head"><div><span class="integration-state">${escapeHtml(bacnetLab.mode)}</span><h3>Fake building sandbox</h3></div><span class="installed-state">EXECUTABLE</span></div>
    <p>${escapeHtml(bacnetLab.devices.length)} virtual devices · ${escapeHtml(Object.keys(bacnetLab.point_index).length)} mapped points · acceptance result capture</p>
    <div class="reference-limit">Loopback only. MS/TP identity is mirrored over BACnet/IP; serial timing remains a hardware-in-loop gate.</div>
  </article>` : '';
  const contractorEnvironment = environment ? `<article class="reference-card">
    <div class="reference-head"><div><span class="integration-state">STATICALLY VALIDATED</span><h3>${escapeHtml(environment.environment.name)}</h3></div><span class="installed-state">${environment.compatibility.statically_compatible ? 'COMPATIBLE' : 'BLOCKED'}</span></div>
    <p>Niagara ${escapeHtml(environment.environment.niagara_version)} · ${escapeHtml(environment.environment.modules.length)} modules · ${escapeHtml(environment.custom_component_types.length)} typed custom components · ${escapeHtml(environment.environment.graphics_templates.length)} graphics templates</p>
    <div class="reference-limit">Assets and hashes are signed into the run. Exact execution still requires the licensed Niagara runtime matrix.</div>
  </article>` : '';
  $('#niagara-integrations').innerHTML = semantic + assembled + lab + contractorEnvironment + alarm;
  const manifestLink = $('#edge-manifest');
  manifestLink.hidden = !manifest;
  manifestLink.href = manifest ? `/api/runs/${state.current.id}/volttron-manifest` : '#';
  const probeButton = $('#probe-bacnet-lab');
  probeButton.hidden = !bacnetLab;
  const probeResult = $('#bacnet-probe-result');
  if (state.bacnetProbe) {
    const values = Object.entries(state.bacnetProbe.values || {}).map(([name, value]) =>
      `<code>${escapeHtml(name)} = ${escapeHtml(value)}</code>`
    ).join('');
    probeResult.innerHTML = `<div><span class="panel-kicker">LIVE LOOPBACK PROTOCOL PROOF</span><strong>✓ BAC0 read ${escapeHtml(state.bacnetProbe.point_count)} mapped points</strong><p>No live routes and no writes were permitted.</p></div><div class="probe-values">${values}</div>`;
    probeResult.classList.remove('hidden');
  } else {
    probeResult.innerHTML = '';
    probeResult.classList.add('hidden');
  }
  if (!manifest) {
    summary.innerHTML = '<strong>No BACnet scan attached</strong><p>This run has no VOLTTRON edge artifacts.</p>';
    devices.innerHTML = '';
    return;
  }
  const mapped = manifest.devices.reduce((total, device) => total + device.mapped_points, 0);
  summary.innerHTML = `<strong>Observation-only · ${mapped} mapped points</strong>
    <p>Every generated registry entry is forced read-only and included in the approval hash.</p>`;
  devices.innerHTML = manifest.devices.map(device => `<tr>
    <td><strong>${escapeHtml(device.device_name)}</strong><br><code>${escapeHtml(device.device_instance)}</code></td>
    <td>${escapeHtml(device.mapped_points)}</td>
    <td><code>${escapeHtml(device.registry_file)}</code></td>
    <td><code>${escapeHtml(device.config_file)}</code></td>
    <td><span class="readonly-badge">READ ONLY</span></td>
  </tr>`).join('');
}

async function probeBacnetLab() {
  if (!state.current || !state.bacnetLab) return;
  const button = $('#probe-bacnet-lab');
  button.disabled = true;
  button.textContent = 'Starting virtual device…';
  try {
    state.bacnetProbe = await request(`/api/runs/${state.current.id}/bacnet-lab/probe`, {
      method: 'POST',
    });
    renderEdge(
      state.volttron,
      state.nhaystack,
      state.bacnetLab,
      state.environment,
      state.alarmPlan,
      state.stationAssembly,
    );
    toast(`BAC0 read ${state.bacnetProbe.point_count} points from the virtual controller.`);
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = 'Talk to virtual BACnet device';
  }
}

function renderIntegrationAudit(audit) {
  if (!audit) return;
  $('#integration-audit').innerHTML = `<strong>${escapeHtml(audit.bound_component_count)}/${escapeHtml(audit.pinned_component_count)} pinned components have an explicit use boundary</strong><p>${escapeHtml(audit.policy)}</p>`;
  $('#integration-audit-components').innerHTML = audit.components.map(component => `<article class="reference-card">
    <div class="reference-head"><div><span class="integration-state">${escapeHtml(component.mode)}</span><h3>${escapeHtml(component.id)}</h3></div><span class="installed-state">${component.bound ? 'BOUND' : 'UNBOUND'}</span></div>
    <p>${escapeHtml(component.product_path || 'No product path')}</p>
    <div class="reference-meta"><code>${escapeHtml(component.proof || 'No proof')}</code><span>${escapeHtml(component.license || '')}</span></div>
  </article>`).join('');
}

function renderReference(reference) {
  if (!reference) return;
  const summary = reference.summary;
  $('#reference-summary').innerHTML = `
    <div><strong>${escapeHtml(summary.modelica_control_files)}</strong><span>CDL / controls source files</span></div>
    <div><strong>${escapeHtml(summary.executable_cdl_blocks)}</strong><span>executable CDL blocks</span></div>
    <div><strong>${escapeHtml(summary.g36_cxf_fixtures)}</strong><span>G36 CXF fixtures</span></div>
    <div><strong>${escapeHtml(summary.independent_verification_rules)}</strong><span>verification rules</span></div>`;
  $('#reference-components').innerHTML = reference.components.map(component => {
    const groups = Object.entries(component.groups || {}).map(([name, count]) => `<span>${escapeHtml(name)} <b>${escapeHtml(count)}</b></span>`).join('');
    const artifacts = (component.artifacts || []).slice(0, 14).map(item => {
      const name = typeof item === 'string' ? item : item.name;
      return `<code>${escapeHtml(name)}</code>`;
    }).join('');
    return `<article class="reference-card">
      <div class="reference-head"><div><span class="integration-state">${escapeHtml(component.integration_status)}</span><h3>${escapeHtml(component.name)}</h3></div><span class="installed-state">${component.installed ? 'INSTALLED' : 'MISSING'}</span></div>
      <p>${escapeHtml(component.role)}</p>
      <div class="reference-meta"><code>${escapeHtml((component.revision || 'unversioned').slice(0, 12))}</code><span>${escapeHtml(component.license)}</span><b>${escapeHtml(component.artifact_count)} artifacts</b></div>
      ${component.block_count ? `<div class="reference-callout">${escapeHtml(component.block_count)} public blocks · ${escapeHtml(component.stateful_block_count)} stateful</div>` : ''}
      ${groups ? `<div class="reference-groups">${groups}</div>` : ''}
      ${artifacts ? `<details><summary>Sample coverage</summary><div class="reference-artifacts">${artifacts}</div></details>` : ''}
      <div class="reference-limit">${escapeHtml(component.limitations)}</div>
    </article>`;
  }).join('');
}

function renderReadiness(readiness) {
  if (!readiness) return;
  const ready = readiness.production_ready;
  const selected = readiness.components.filter(component => component.selected);
  const wired = selected.filter(component => ['product-wired', 'target-compiled', 'verified', 'field-qualified', 'production-supported'].includes(component.stage)).length;
  $('#readiness-banner').className = `readiness-banner ${ready ? 'ready' : 'blocked'}`;
  $('#readiness-banner').innerHTML = `<div><span>${ready ? 'PRODUCTION READY' : 'PRODUCTION GATE OPEN'}</span><strong>${ready ? 'All selected components qualified' : 'Not production-ready — blockers are visible below'}</strong></div><p>${escapeHtml(readiness.policy)}</p>`;
  $('#readiness-components').innerHTML = `<div class="readiness-count"><strong>${wired}/${selected.length}</strong><span>selected components product-wired or beyond</span></div>` + selected.map(component => `
    <article class="readiness-row">
      <div><strong>${escapeHtml(component.name)}</strong><span>${escapeHtml(component.role)}</span></div>
      <code class="stage-badge stage-${escapeHtml(component.stage)}">${escapeHtml(component.stage)}</code>
      <p>${escapeHtml(component.blocker || 'No recorded blocker at this stage.')}</p>
    </article>`).join('');
}

function renderCapabilities(capabilities) {
  if (!capabilities) return;
  const summary = capabilities.summary;
  $('#capability-summary').innerHTML = `
    <div><strong>${escapeHtml(summary.installed_packs)}</strong><span>installed compiler packs</span></div>
    <div><strong>${escapeHtml(summary.production_supported_packs)}</strong><span>production-supported packs</span></div>
    <div><strong>${escapeHtml(summary.catalogued_equipment_families)}</strong><span>catalogued families</span></div>
    <div><strong>${escapeHtml(summary.target_compiled_families)}</strong><span>target-compiled families</span></div>`;
  $('#capability-packs').innerHTML = capabilities.packs.map(pack => {
    const artifacts = Object.entries(pack.artifact_coverage).map(([name, covered]) => `<span class="coverage ${covered ? 'covered' : 'missing'}">${covered ? '✓' : '×'} ${escapeHtml(name.replaceAll('_', ' '))}</span>`).join('');
    const verification = Object.entries(pack.verification_coverage).map(([name, covered]) => `<span class="coverage ${covered ? 'covered' : 'missing'}">${covered ? '✓' : '×'} ${escapeHtml(name.replaceAll('_', ' '))}</span>`).join('');
    const release = pack.release_assessment;
    const blockers = release.blocking_gate_ids.map(name => `<code>${escapeHtml(name)}</code>`).join('');
    return `<article class="reference-card capability-card">
      <div class="reference-head"><div><span class="integration-state">${escapeHtml(pack.status)}</span><h3>${escapeHtml(pack.name)}</h3></div><code class="stage-badge stage-${escapeHtml(pack.stage)}">${escapeHtml(pack.stage)}</code></div>
      <p>${escapeHtml(pack.sequence_families.join(' · '))}</p>
      <div class="reference-callout">Production gates: ${escapeHtml(release.passed_gates)}/${escapeHtml(release.total_gates)} passed</div>
      <h4>Artifacts</h4><div class="coverage-grid">${artifacts}</div>
      <h4>Verification</h4><div class="coverage-grid">${verification}</div>
      <details><summary>${escapeHtml(release.blocking_gate_ids.length)} release blockers</summary><div class="reference-artifacts">${blockers}</div></details>
      <div class="reference-limit">${pack.limitations.map(item => escapeHtml(item)).join('<br>')}</div>
    </article>`;
  }).join('');
  $('#equipment-families').innerHTML = `<h4>Equipment-family build matrix</h4><div class="family-grid">` + capabilities.families.map(family => `
    <div class="family-row"><strong>${escapeHtml(family.name)}</strong><code class="stage-badge stage-${escapeHtml(family.stage)}">${escapeHtml(family.stage)}</code><span>${escapeHtml(family.blocker || '')}</span></div>`).join('') + '</div>';
}

function renderApproval(run) {
  const approved = run.status === 'approved';
  const rejected = run.status === 'rejected';
  $('#approval-icon').textContent = approved ? '✓' : rejected ? '×' : '!';
  $('#approval-title').textContent = approved
    ? `Approved by ${run.approval.reviewer}`
    : rejected ? `Rejected by ${run.rejection.reviewer}` : 'Human review required';
  $('#approval-detail').textContent = approved
    ? `Artifact locked to ${run.artifact_sha256.slice(0, 12)}…`
    : rejected ? (run.rejection.reason || 'Candidate retained for audit and cannot be exported.')
      : 'Confirm the wiresheet, exact diff, and test evidence before accepting or rejecting.';
  $('#approve').classList.toggle('hidden', approved || rejected);
  $('#reject').classList.toggle('hidden', approved || rejected);
  $('#reviewer').classList.toggle('hidden', approved || rejected);
  const exportLink = $('#export');
  const sourcePackage = run.target_artifact_kind === 'niagara_program_source_package';
  exportLink.textContent = sourcePackage ? 'Export source package' : 'Export .bog';
  exportLink.href = approved ? `/api/runs/${run.id}/export` : '#';
  exportLink.classList.toggle('disabled', !approved);
  exportLink.setAttribute('aria-disabled', String(!approved));
  const bundleLink = $('#bundle');
  bundleLink.href = approved ? `/api/runs/${run.id}/review-bundle` : '#';
  bundleLink.classList.toggle('disabled', !approved);
  bundleLink.setAttribute('aria-disabled', String(!approved));
}

let loadedControllerLibrary = null;
async function loadLibraryControllerOptions(library) {
  if (loadedControllerLibrary === library) return;
  const root = library === 'plant_controls' ? 'plant-controls' : 'g36';
  const catalog = await request(`/api/library/${root}/controllers`);
  $('#library-controller-options').innerHTML = catalog.controllers
    .filter(item => !item.validation_fixture && (library !== 'plant_controls' || item.product_status !== 'source_catalog_only'))
    .map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`)
    .join('');
  loadedControllerLibrary = library;
}

function syncPlantLibraryFields() {
  const form = $('#import-form');
  const family = form.elements.sequence_family.value;
  const library = family === 'LBNL_PLANT_CONTROLLER'
    ? 'plant_controls' : family === 'LBNL_G36_CONTROLLER' ? 'g36' : '';
  const selected = Boolean(library);
  $$('.controller-library-field').forEach(item => item.classList.toggle('hidden', !selected));
  form.elements.sequence_library.value = library;
  form.elements.controller_id.required = selected;
  if (selected) {
    if (form.elements.sequence_parameters.value.includes('loop_span_f')) {
      form.elements.sequence_parameters.value = '{}';
    }
    loadLibraryControllerOptions(library).catch(error => toast(error.message));
  } else {
    form.elements.controller_id.value = '';
  }
}

async function downloadLibraryJobTemplate() {
  const form = $('#import-form');
  const controllerId = form.elements.controller_id.value.trim();
  if (!controllerId) { toast('Choose a plant controller first.'); return; }
  let parameters;
  try {
    parameters = JSON.parse(form.elements.sequence_parameters.value || '{}');
  } catch (_) {
    toast('Sequence parameters must be valid JSON before generating the interface.');
    return;
  }
  const profile = form.elements.execution_profile.value;
  const root = form.elements.sequence_library.value === 'plant_controls'
    ? 'plant-controls' : 'g36';
  const template = await request(
    `/api/library/${root}/controllers/${encodeURIComponent(controllerId)}/job-template?execution_profile=${encodeURIComponent(profile)}`,
    { method: 'POST', body: JSON.stringify({ parameters }) },
  );
  const blob = new Blob([template.points_csv], { type: 'text/csv;charset=utf-8' });
  const href = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = href;
  link.download = `${controllerId.replaceAll('.', '-')}-points.csv`;
  link.click();
  URL.revokeObjectURL(href);
  toast(`Downloaded ${template.points.length} exact interface points. Author tests for all ${template.acceptance_output_targets.length} outputs.`);
}

async function createDemo(path = '/api/runs/demo/generalist') {
  const buttons = $$('#new-generalist-demo, .generalist-demo-trigger');
  buttons.forEach(button => { button.disabled = true; button.textContent = 'Building…'; });
  try {
    const run = await request(path, { method: 'POST' });
    await loadRuns(run.id);
    toast('Niagara artifact generated and all Tier-1 tests completed.');
  } catch (error) {
    toast(error.message);
  } finally {
    buttons.forEach(button => { button.disabled = false; button.textContent = button.id === 'new-generalist-demo' ? '＋ Build AHU demo' : 'Build AHU demo'; });
  }
}

async function loadAIStatus() {
  state.aiStatus = await request('/api/ai/status');
  const status = $('#ai-status');
  if (state.aiStatus.configured) {
    status.className = 'ai-status configured';
    const chatModel = state.aiStatus.roles?.conversation?.model || state.aiStatus.model;
    const codingModel = state.aiStatus.roles?.coding?.model || state.aiStatus.model;
    status.textContent = `Cerebras connected · chat ${chatModel} · code ${codingModel} · proposal-only`;
  } else {
    status.className = 'ai-status';
    status.textContent = 'Not configured · add CEREBRAS_API_KEY to the server .env file';
  }
}

async function loadReferenceStack() {
  [state.reference, state.readiness, state.capabilities, state.integrationAudit] = await Promise.all([
    request('/api/reference-stack'),
    request('/api/system/readiness'),
    request('/api/capability-packs'),
    request('/api/system/integration-audit'),
  ]);
  renderReadiness(state.readiness);
  renderCapabilities(state.capabilities);
  renderIntegrationAudit(state.integrationAudit);
  renderReference(state.reference);
}

function setChatOpen(open) {
  $('#chat-drawer').classList.toggle('open', open);
  $('#chat-drawer').setAttribute('aria-hidden', String(!open));
  $('#chat-scrim').classList.toggle('hidden', !open);
  if (open) $('#chat-input').focus();
}

function appendChat(role, content, options = {}) {
  const message = document.createElement('div');
  message.className = `chat-message ${role}${options.pending ? ' pending' : ''}`;
  message.textContent = content;
  $('#chat-messages').append(message);
  $('#chat-messages').scrollTop = $('#chat-messages').scrollHeight;
  return message;
}

async function sendChat(event) {
  event.preventDefault();
  const input = $('#chat-input');
  const message = input.value.trim();
  if (!message || !state.current) return;
  const priorHistory = state.chatHistory.slice(-20);
  state.chatHistory.push({ role: 'user', content: message });
  appendChat('user', message);
  input.value = '';
  const pending = appendChat('assistant', 'Analyzing the graph and test oracle…', { pending: true });
  $('#send-chat').disabled = true;
  try {
    const response = await request(`/api/runs/${state.current.id}/chat`, {
      method: 'POST',
      body: JSON.stringify({ message, history: priorHistory }),
    });
    pending.remove();
    state.chatHistory.push({ role: 'assistant', content: response.message });
    appendChat('assistant', response.message);
    if (response.assumptions.length) appendChat('system', `Assumptions: ${response.assumptions.join(' · ')}`);
    if (response.new_run) {
      appendChat('system', `Created tested candidate ${response.new_run.id}. Review its exact diff and evidence, then approve or reject it.`);
      await loadRuns(response.new_run.id);
    }
  } catch (error) {
    pending.remove();
    appendChat('error', error.message);
  } finally {
    $('#send-chat').disabled = false;
  }
}

async function importJob(event) {
  event.preventDefault();
  const submit = $('#submit-import');
  submit.disabled = true;
  submit.textContent = 'Building and testing…';
  try {
    const response = await fetch('/api/runs/import', {
      method: 'POST',
      body: new FormData($('#import-form')),
    });
    if (!response.ok) {
      let message = `Import failed (${response.status})`;
      try { message = (await response.json()).detail || message; } catch (_) { /* no JSON */ }
      throw new Error(message);
    }
    const run = await response.json();
    $('#import-dialog').close();
    $('#import-form').reset();
    syncPlantLibraryFields();
    await loadRuns(run.id);
    toast(run.target_artifact_kind === 'niagara_program_source_package'
      ? 'Contractor inputs validated, tested, and packaged for licensed Workbench compilation.'
      : 'Contractor inputs validated, compiled, diffed, and tested.');
  } catch (error) {
    toast(error.message);
  } finally {
    submit.disabled = false;
    submit.textContent = 'Build and test';
  }
}

async function inspectIntake() {
  const form = $('#import-form');
  const points = form.elements.points_file.files[0];
  if (!points) { toast('Choose a points CSV or XLSX file first.'); return; }
  const payload = new FormData();
  payload.append('points_file', points);
  payload.append('sequence_family', form.elements.sequence_family.value);
  const sequence = form.elements.sequence_document.files[0];
  if (sequence) payload.append('sequence_document', sequence);
  const button = $('#inspect-intake');
  button.disabled = true;
  button.textContent = 'Inspecting…';
  try {
    const response = await fetch('/api/intake/inspect', { method: 'POST', body: payload });
    if (!response.ok) {
      let message = `Inspection failed (${response.status})`;
      try { message = (await response.json()).detail || message; } catch (_) { /* no JSON */ }
      throw new Error(message);
    }
    const inspection = await response.json();
    const aliases = inspection.canonical_point_mappings.map(item =>
      `<code>${escapeHtml(item.source_name)} → ${escapeHtml(item.canonical_name)}</code>`
    ).join('');
    const missing = inspection.missing_required_points.map(item => `<code>${escapeHtml(item)}</code>`).join('');
    const rows = inspection.points.slice(0, 12).map(point => `<tr>
      <td><code>${escapeHtml(point.name)}</code>${point.source_name ? `<br><small>${escapeHtml(point.source_name)}</small>` : ''}</td>
      <td>${escapeHtml(point.role)}</td><td>${escapeHtml(point.data_type)}</td>
      <td><code>${escapeHtml(point.bacnet_object || '—')}</code></td></tr>`).join('');
    const preview = $('#intake-preview');
    preview.innerHTML = `<div class="intake-preview-head"><strong>${inspection.point_count} points normalized</strong><span>${inspection.mapped_bacnet_points} BACnet mappings · ${escapeHtml(inspection.selected_sequence_family || 'sequence not resolved')}</span></div>
      ${aliases ? `<div class="intake-mapping"><b>Canonical aliases</b>${aliases}</div>` : ''}
      ${missing ? `<div class="intake-missing"><b>Missing required points</b>${missing}</div>` : '<div class="intake-ready">✓ Required pack points are present</div>'}
      <div class="table-wrap"><table><thead><tr><th>Point</th><th>Role</th><th>Type</th><th>BACnet</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    preview.classList.remove('hidden');
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = 'Inspect mapping';
  }
}

$('#new-generalist-demo').addEventListener('click', () => createDemo());
$$('.generalist-demo-trigger').forEach(button => button.addEventListener('click', () => createDemo()));
$('#open-chat').addEventListener('click', () => setChatOpen(true));
$('#close-chat').addEventListener('click', () => setChatOpen(false));
$('#chat-scrim').addEventListener('click', () => setChatOpen(false));
$('#chat-form').addEventListener('submit', sendChat);
$('#zoom-in').addEventListener('click', () => setGraphZoom(state.zoom + 0.1));
$('#zoom-out').addEventListener('click', () => setGraphZoom(state.zoom - 0.1));
$('#zoom-fit').addEventListener('click', fitGraph);
$('#import-job').addEventListener('click', () => $('#import-dialog').showModal());
$('#close-import').addEventListener('click', () => $('#import-dialog').close());
$('#cancel-import').addEventListener('click', () => $('#import-dialog').close());
$('#import-form').addEventListener('submit', importJob);
$('#import-form').elements.sequence_family.addEventListener('change', syncPlantLibraryFields);
$('#download-controller-template').addEventListener('click', () => downloadLibraryJobTemplate().catch(error => toast(error.message)));
$('#inspect-intake').addEventListener('click', inspectIntake);
$('#probe-bacnet-lab').addEventListener('click', probeBacnetLab);
$('#import-form').addEventListener('change', () => $('#intake-preview').classList.add('hidden'));
$('#run-select').addEventListener('change', event => loadRun(event.target.value).catch(error => toast(error.message)));
$('#approve').addEventListener('click', async () => {
  const reviewer = $('#reviewer').value.trim();
  if (reviewer.length < 2) { toast('Enter the reviewer’s name before approving.'); return; }
  try {
    state.current = await request(`/api/runs/${state.current.id}/approve`, {
      method: 'POST', body: JSON.stringify({ reviewer }),
    });
    render();
    toast(state.current.target_artifact_kind === 'niagara_program_source_package'
      ? 'Artifact approved. The immutable Niagara source package is now available.'
      : 'Artifact approved. The immutable .bog export is now available.');
  } catch (error) { toast(error.message); }
});
$('#reject').addEventListener('click', async () => {
  const reviewer = $('#reviewer').value.trim();
  if (reviewer.length < 2) { toast('Enter the reviewer’s name before rejecting.'); return; }
  try {
    state.current = await request(`/api/runs/${state.current.id}/reject`, {
      method: 'POST', body: JSON.stringify({ reviewer }),
    });
    render();
    toast('Candidate rejected and retained in the audit trail.');
  } catch (error) { toast(error.message); }
});

$$('.tab').forEach(tab => tab.addEventListener('click', () => {
  $$('.tab').forEach(item => item.classList.toggle('active', item === tab));
  $$('.tab-panel').forEach(panel => panel.classList.add('hidden'));
  $(`#${tab.dataset.tab}-panel`).classList.remove('hidden');
}));

let panStart = null;
$('#graph-canvas').addEventListener('pointerdown', event => {
  if (event.target.closest('.graph-node')) return;
  const canvas = $('#graph-canvas');
  panStart = { x: event.clientX, y: event.clientY, left: canvas.scrollLeft, top: canvas.scrollTop };
  canvas.classList.add('panning');
  canvas.setPointerCapture(event.pointerId);
});
$('#graph-canvas').addEventListener('pointermove', event => {
  if (!panStart) return;
  const canvas = $('#graph-canvas');
  canvas.scrollLeft = panStart.left - (event.clientX - panStart.x);
  canvas.scrollTop = panStart.top - (event.clientY - panStart.y);
});
$('#graph-canvas').addEventListener('pointerup', event => {
  panStart = null;
  $('#graph-canvas').classList.remove('panning');
  $('#graph-canvas').releasePointerCapture(event.pointerId);
});

syncPlantLibraryFields();
Promise.all([loadRuns(), loadAIStatus(), loadReferenceStack()]).catch(error => toast(error.message));
