.PHONY: install install-suite install-haxall aixocat-contract alfalfa-contract alfalfa-runtime-up alfalfa-runtime-smoke alfalfa-graph-smoke alfalfa-runtime-down bacnet-lab-contract bacnet-scale-runtime independent-bacnet-simulator-install independent-bacnet-simulator-contract environment-pack-contract buildingmotif-install buildingmotif-contract constrain-install constrain-contract ctrl-flow-install ctrl-flow-contract dflexlibs-contract g36-audit g36-audit-contract plant-controls-audit plant-controls-contract plant-job-contract haxall-contract nhaystack-contract niagara-alarm-contract niagara-binding-contract niagara-graphics-contract niagara-program-codegen-contract niagara-station-contract project-signal-contract integration-use-contract n4-hvac-library-contract open-control-library-contract open-fdd-contract pybog-examples-contract rumoca-install rumoca-contract suite-contract cerebras-smoke test lint demo demo-package record-demo serve clean boptest-contract boptest-smoke boptest-runtime-build boptest-runtime-up boptest-runtime-smoke boptest-graph-runtime boptest-scenario-runtime boptest-scenario-suite-runtime boptest-scale-runtime boptest-runtime-down volttron-install volttron-contract oce-contract cdl-oce-contract web-install web-build web-test web-lint web-sbom

.PHONY: alfalfa-product-smoke qualification-queue-up qualification-queue-down qualification-worker

.PHONY: bootstrap-full bootstrap-list doctor doctor-json queue-up queue-down full-stack-up full-stack-smoke full-stack-down contractor-workflow simulation-workflow test-minimal test-integration test-integration-lenient test-docker test-all

web-install:
	cd web && npm ci

web-build:
	cd web && npm run build && npm run size

web-test:
	cd web && npm test

web-lint:
	cd web && npm run lint && npm run typecheck

web-sbom:
	cd web && npm run sbom

# Override with `make install PYTHON=python3.13` when `python3` is a version the
# stack has not been proven on (3.14 hangs while loading the Brick ontology on macOS).
PYTHON ?= python3

install:
	@$(PYTHON) -c 'import sys; v=sys.version_info; ok=(3,11)<=v[:2]<(3,14); print(f"using Python {v.major}.{v.minor} at {sys.executable}"); sys.exit(0 if ok else 1)' \
		|| { echo "BACTalk supports Python 3.11 to 3.13; run: make install PYTHON=python3.13"; exit 1; }
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -e '.[test]'

install-suite:
	.venv/bin/python -m pip install -e '.[suite,test]'

install-haxall:
	cd ops/haxall && npm install

buildingmotif-install:
	python3.11 -m venv .buildingmotif-venv
	.buildingmotif-venv/bin/pip install .vendor/buildingmotif

buildingmotif-contract:
	PYTHONPATH=src .venv/bin/python scripts/verify_buildingmotif.py

alfalfa-contract:
	.venv/bin/python scripts/verify_alfalfa_contract.py

alfalfa-runtime-up:
	docker compose -f ops/alfalfa.compose.yml build worker
	docker compose -f ops/alfalfa.compose.yml up -d --scale worker=2 --wait

alfalfa-runtime-smoke:
	PYTHONPATH=src .venv/bin/python scripts/run_alfalfa_runtime.py

alfalfa-graph-smoke:
	PYTHONPATH=src .venv/bin/python scripts/run_alfalfa_graph.py

alfalfa-product-smoke: qualification-queue-up
	PYTHONPATH=src .venv/bin/python scripts/run_alfalfa_product.py

alfalfa-runtime-down:
	docker compose -f ops/alfalfa.compose.yml down

qualification-queue-up:
	docker compose -f ops/qualification-queue.compose.yml up -d --wait

qualification-queue-down:
	docker compose -f ops/qualification-queue.compose.yml down

qualification-worker:
	PYTHONPATH=src .venv/bin/python -m bactalk.cli qualification-worker

aixocat-contract:
	PYTHONPATH=src .venv/bin/python scripts/verify_aixocat.py

bacnet-lab-contract:
	PYTHONPATH=src .venv/bin/python scripts/verify_bacnet_lab.py

bacnet-scale-runtime:
	PYTHONPATH=src .venv/bin/python scripts/run_bacnet_scale.py

independent-bacnet-simulator-install:
	scripts/install_bacnet_simulator.sh

independent-bacnet-simulator-contract:
	cd .vendor/bacnet-simulator && ../../.bacnet-simulator-venv/bin/pytest -q tests/unit tests/integration/test_api.py tests/integration/test_sqlite_repos.py
	PYTHONPATH=src:.vendor/bacnet-simulator/src .bacnet-simulator-venv/bin/python scripts/verify_independent_bacnet_simulator.py

environment-pack-contract:
	PYTHONPATH=src .venv/bin/pytest -q tests/test_environment_pack.py

constrain-install:
	python3.11 -m venv .constrain-venv
	.constrain-venv/bin/pip install -e .vendor/constrain

constrain-contract:
	PYTHONPATH=src .constrain-venv/bin/python scripts/verify_constrain.py

ctrl-flow-install:
	scripts/install_ctrl_flow.sh

ctrl-flow-contract:
	PYTHONPATH=src .venv/bin/python scripts/verify_ctrl_flow.py
	PYTHONPATH=src .venv/bin/python scripts/verify_ctrl_flow_planning.py
# The upstream parser reads the moParser JVM's output as JSON, so any JVM
# startup banner corrupts it. JAVA_TOOL_OPTIONS is commonly set in corporate
# and proxied environments and makes every JVM print "Picked up
# JAVA_TOOL_OPTIONS: ...". The parser reads local files and opens no network
# connection, so unsetting it here loses no TLS or proxy configuration.
	MODELICA_DEPENDENCIES=$(CURDIR)/.vendor/ctrl-flow-dependencies env -u JAVA_TOOL_OPTIONS -u _JAVA_OPTIONS npm --prefix .vendor/ctrl-flow-dev/server test -- --runInBand tests/integration/parser/template.test.ts

dflexlibs-contract:
	.venv/bin/python scripts/verify_dflexlibs.py

open-control-library-contract:
	.venv/bin/python scripts/verify_open_control_library.py

n4-hvac-library-contract:
	PYTHONPATH=src .venv/bin/python scripts/verify_n4_hvac_library.py

haxall-contract:
	.venv/bin/python scripts/verify_haxall.py

nhaystack-contract:
	PYTHONPATH=src .venv/bin/python scripts/verify_nhaystack.py

niagara-alarm-contract:
	PYTHONPATH=src .venv/bin/python scripts/verify_niagara_alarms.py

niagara-binding-contract:
	PYTHONPATH=src .venv/bin/python scripts/verify_niagara_bindings.py

niagara-graphics-contract:
	PYTHONPATH=src .venv/bin/python scripts/verify_niagara_graphics.py

niagara-program-codegen-contract:
	PYTHONPATH=src .venv/bin/pytest -q tests/test_niagara_program_codegen.py

niagara-station-contract:
	PYTHONPATH=src .venv/bin/python scripts/verify_niagara_station.py

project-signal-contract:
	PYTHONPATH=src .venv/bin/python scripts/verify_project_signals.py

integration-use-contract:
	PYTHONPATH=src .venv/bin/python scripts/verify_integration_use.py

open-fdd-contract:
	.venv/bin/python scripts/verify_open_fdd.py

pybog-examples-contract:
	.venv/bin/python scripts/verify_pybog_examples.py

suite-contract:
	PYTHONPATH=src .venv/bin/python scripts/verify_suite.py

cerebras-smoke:
	PYTHONPATH=src .venv/bin/python scripts/verify_cerebras_roles.py

test:
	.venv/bin/pytest

boptest-contract:
	.venv/bin/python scripts/verify_boptest_contract.py

boptest-smoke:
	.venv/bin/python scripts/run_boptest_smoke.py

boptest-runtime-build:
	cd .vendor/boptest && docker compose -f docker-compose.yml -f ../../ops/boptest.compose.override.yml build worker web provision

boptest-runtime-up:
	cd .vendor/boptest && docker compose -f docker-compose.yml -f ../../ops/boptest.compose.override.yml up -d web worker
	cd .vendor/boptest && docker compose -f docker-compose.yml -f ../../ops/boptest.compose.override.yml run --rm --no-deps provision

boptest-runtime-smoke:
	PYTHONPATH=src .venv/bin/python scripts/run_boptest_smoke.py --output .bactalk/boptest-runtime-evidence.json

boptest-graph-runtime: qualification-queue-up
	PYTHONPATH=src .venv/bin/python scripts/verify_boptest_graph_runtime.py

boptest-scenario-runtime: qualification-queue-up
	PYTHONPATH=src .venv/bin/python scripts/verify_boptest_graph_runtime.py --time-period peak_cool_day --electricity-price dynamic --temperature-uncertainty medium --solar-uncertainty low --seed 42 --output .bactalk/boptest-scenario-runtime-evidence.json

boptest-scenario-suite-runtime: qualification-queue-up
	PYTHONPATH=src .venv/bin/python scripts/verify_boptest_graph_runtime.py --suite --output .bactalk/boptest-scenario-suite-runtime-evidence.json

boptest-scale-runtime:
	PYTHONPATH=src .venv/bin/python scripts/run_boptest_scale.py

boptest-runtime-down:
	cd .vendor/boptest && docker compose -f docker-compose.yml -f ../../ops/boptest.compose.override.yml down

volttron-install:
	python3.11 -m venv .volttron-venv
	.volttron-venv/bin/pip install -r ops/volttron/requirements.txt

volttron-contract:
	PYTHONPATH=src .volttron-venv/bin/python scripts/verify_volttron_contract.py

oce-contract:
	PYTHONPATH=src .venv/bin/python scripts/verify_open_control_engine.py

cdl-oce-contract:
	PYTHONPATH=src .venv/bin/python scripts/verify_cdl_oce_pipeline.py

g36-audit:
	PYTHONPATH=src .venv/bin/python scripts/audit_g36_library.py --workers 4

g36-audit-contract:
	PYTHONPATH=src .venv/bin/pytest -q tests/test_g36_audit.py

plant-controls-contract:
	PYTHONPATH=src .venv/bin/python scripts/verify_plant_controls.py

plant-job-contract:
	PYTHONPATH=src .venv/bin/python scripts/verify_plant_job.py

plant-controls-audit:
	PYTHONPATH=src .venv/bin/python scripts/audit_plant_controls.py

rumoca-contract:
	PYTHONPATH=src .venv/bin/python scripts/verify_rumoca.py

rumoca-install:
	scripts/install_rumoca.sh

# ---------------------------------------------------------------------------
# Bootstrap, diagnosis, and the full local stack
# ---------------------------------------------------------------------------

# Reconstruct the entire pinned stack from ops/stack.lock.json. Idempotent:
# rerunning skips everything already installed. See docs in scripts/bootstrap.py.
bootstrap-full:
	python3 scripts/bootstrap.py

bootstrap-list:
	python3 scripts/bootstrap.py --list

# Report prerequisites, pinned-revision drift, and exact remediation.
doctor:
	python3 scripts/doctor.py

doctor-json:
	python3 scripts/doctor.py --json --output .bactalk/doctor-report.json

# The durable qualification queue. Prefers the pinned container; falls back to
# a loopback-only native redis-server when no container registry is reachable,
# so the worker plane can still be proven on a restricted host.
queue-up:
	PYTHONPATH=src python3 scripts/queue_service.py up

queue-down:
	PYTHONPATH=src python3 scripts/queue_service.py down

full-stack-up:
	PYTHONPATH=src .venv/bin/python scripts/full_stack.py up

full-stack-smoke:
	PYTHONPATH=src .venv/bin/python scripts/full_stack.py smoke

# Prove the contractor workflow through the real HTTP API: intake -> mapping ->
# candidate -> deterministic tests -> review -> approval -> export, with the
# pre-approval gate and tamper detection asserted.
contractor-workflow:
	PYTHONPATH=src .venv/bin/python scripts/verify_contractor_workflow.py

# Prove the simulation qualification lane: durable queue, real out-of-process
# worker, digest binding, orphan fail-closed, pyfunnel grading, the loopback
# BACnet control boundary, and the physics tiers when they are reachable.
simulation-workflow:
	PYTHONPATH=src .venv/bin/python scripts/verify_simulation_workflow.py

full-stack-down:
	PYTHONPATH=src .venv/bin/python scripts/full_stack.py down

# ---------------------------------------------------------------------------
# Test tiers (see pyproject [tool.pytest.ini_options] markers)
# ---------------------------------------------------------------------------

# Runs on a bare `make install`: no optional extras, no vendored upstreams.
test-minimal:
	.venv/bin/pytest -m minimal

# Everything that does not need a container runtime or a licensed runtime.
# This is what must pass after `make bootstrap-full`. BACTALK_REQUIRE_FULL_STACK
# turns an unmet requirement into a failure instead of a skip, so a missing
# vendored source cannot hide a regression behind a green run.
test-integration:
	BACTALK_REQUIRE_FULL_STACK=1 .venv/bin/pytest -m "not docker and not licensed"

# The same tier without the strict gate, for a partially bootstrapped machine.
test-integration-lenient:
	.venv/bin/pytest -m "not docker and not licensed"

# Requires a container runtime with registry access.
test-docker:
	.venv/bin/pytest -m docker

test-all:
	.venv/bin/pytest -m "not licensed"

lint:
	.venv/bin/ruff check src tests scripts

demo:
	.venv/bin/bactalk demo --output .bactalk/runs

demo-package:
	PYTHONPATH=src .venv/bin/python scripts/create_complex_demo_package.py --output artifacts/demo-inputs

record-demo: demo-package web-build
	cd web && node scripts/record-complex-workflow.mjs

serve:
	.venv/bin/bactalk serve --reload

clean:
	.venv/bin/bactalk clean --output .bactalk/runs
