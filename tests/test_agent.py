from __future__ import annotations

from bactalk.agent import ProgrammingAgent
from bactalk.demo import demo_job
from bactalk.domain import ControlGraph, JobSpec, Link
from bactalk.domain import TestReport as ControlsTestReport
from bactalk.repository import RunRepository
from bactalk.sequences import build_g36_vav_reheat
from bactalk.service import WorkbenchService


class SeededFaultPlanner:
    def plan(self, job: JobSpec) -> ControlGraph:
        graph = build_g36_vav_reheat(job)
        bad_links: list[Link] = []
        for link in graph.links:
            if link.target == "HeatingError" and link.target_slot == "a":
                bad_links.append(link.model_copy(update={"source": "ZoneTemp"}))
            elif link.target == "HeatingError" and link.target_slot == "b":
                bad_links.append(link.model_copy(update={"source": "HeatingSetpoint"}))
            else:
                bad_links.append(link)
        return ControlGraph.model_validate({**graph.model_dump(mode="python"), "links": bad_links})

    def revise(
        self,
        job: JobSpec,
        graph: ControlGraph,
        report: ControlsTestReport,
    ) -> ControlGraph:
        assert "zone moves toward heating setpoint" in {
            item.name
            for scenario in report.scenarios
            for item in scenario.assertions
            if not item.passed
        }
        return build_g36_vav_reheat(job)


def test_agent_diagnoses_repairs_and_retests_seeded_fault() -> None:
    result = ProgrammingAgent(SeededFaultPlanner(), max_attempts=3).run(demo_job())

    assert [attempt.passed for attempt in result.attempts] == [False, True]
    assert "zone moves toward heating setpoint" in result.attempts[0].failed_assertions
    assert result.attempts[0].failures[0].observed
    assert len(result.attempts[0].graph_sha256) == 64
    assert result.attempts[0].changes == {"added": [], "modified": [], "removed": []}
    assert result.attempts[1].changes["removed"]
    assert result.attempts[1].changes["added"]
    assert result.report.passed is True


def test_repair_attempts_are_persisted_in_the_review_record(tmp_path) -> None:
    repository = RunRepository(tmp_path / "runs")
    service = WorkbenchService(repository)

    record = service.create_run(demo_job(), planner=SeededFaultPlanner())
    reloaded = repository.get(record.id)

    assert [attempt["passed"] for attempt in reloaded.agent_attempts] == [False, True]
    assert reloaded.agent_attempts[0]["failures"]
    assert reloaded.agent_attempts[1]["changes"]["added"]
    assert reloaded.agent_attempts[1]["changes"]["removed"]
    assert all(len(attempt["graph_sha256"]) == 64 for attempt in reloaded.agent_attempts)
