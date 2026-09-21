from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import httpx


class BoptestError(RuntimeError):
    pass


def _test_case_ids(payload: Any) -> list[str]:
    if not isinstance(payload, list):
        raise BoptestError("BOPTEST test-case catalog is not a list")
    result: list[str] = []
    for item in payload:
        if isinstance(item, str):
            value = item
        elif isinstance(item, dict):
            value = item.get("testcaseid")
        else:
            value = None
        if not isinstance(value, str) or not value.strip():
            raise BoptestError("BOPTEST test-case catalog contains an invalid identifier")
        result.append(value.strip())
    if len(result) != len(set(result)):
        raise BoptestError("BOPTEST test-case catalog contains duplicate identifiers")
    return sorted(result)


def _optional_number(value: Any, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise BoptestError(f"BOPTEST {label} is not numeric")
    try:
        result = float(value)
    except ValueError as exc:
        raise BoptestError(f"BOPTEST {label} is not numeric") from exc
    if not math.isfinite(result):
        raise BoptestError(f"BOPTEST {label} is not finite")
    return result


def _signal_contract(payload: Any, kind: str) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        raise BoptestError(f"BOPTEST {kind} catalog is not an object")
    result: list[dict[str, Any]] = []
    for name, raw_metadata in sorted(payload.items()):
        if not isinstance(name, str) or not name:
            raise BoptestError(f"BOPTEST {kind} catalog contains an invalid signal name")
        if not isinstance(raw_metadata, Mapping):
            raise BoptestError(f"BOPTEST {kind} {name!r} metadata is not an object")
        unit = raw_metadata.get("Unit")
        description = raw_metadata.get("Description")
        if unit is not None and not isinstance(unit, str):
            raise BoptestError(f"BOPTEST {kind} {name!r} unit is not text")
        if description is not None and not isinstance(description, str):
            raise BoptestError(f"BOPTEST {kind} {name!r} description is not text")
        result.append(
            {
                "name": name,
                "unit": unit,
                "description": description,
                "minimum": _optional_number(raw_metadata.get("Minimum"), f"{kind} {name} minimum"),
                "maximum": _optional_number(raw_metadata.get("Maximum"), f"{kind} {name} maximum"),
                "activation_signal": name.endswith("_activate"),
            }
        )
    return result


def discover_boptest_catalog(client: BoptestClient) -> dict[str, Any]:
    """Return the exact test cases advertised by one isolated BOPTEST service."""

    return {
        "schema": "bactalk.boptest-catalog/v1",
        "version": client.version(),
        "test_cases": _test_case_ids(client.test_cases()),
        "live_building_writes": False,
    }


def inspect_boptest_test_case(client: BoptestClient, test_case: str) -> dict[str, Any]:
    """Select one advertised case just long enough to inspect its exact I/O contract."""

    catalog = discover_boptest_catalog(client)
    if test_case not in catalog["test_cases"]:
        raise ValueError(f"BOPTEST test case {test_case!r} is not advertised by this service")
    test_id = client.select(test_case)
    stopped: Any = None
    try:
        measurements = _signal_contract(client.measurements(test_id), "measurement")
        inputs = _signal_contract(client.inputs(test_id), "input")
    finally:
        stopped = client.stop(test_id)
    if stopped != "OK":
        raise BoptestError(f"BOPTEST did not stop catalog inspection cleanly: {stopped!r}")
    return {
        "schema": "bactalk.boptest-test-case-contract/v1",
        "version": catalog["version"],
        "test_case": test_case,
        "measurements": measurements,
        "inputs": inputs,
        "measurement_count": len(measurements),
        "input_count": len(inputs),
        "clean_stop": True,
        "initialized": False,
        "live_building_writes": False,
    }


class BoptestClient:
    """Thin adapter around the BOPTEST REST API.

    The client is deliberately explicit: selecting and stopping a test case are
    separate calls, and control overrides are supplied by the caller. It does
    not discover or communicate with live BACnet networks.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=timeout)

    def _payload(self, response: httpx.Response) -> Any:
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type:
            return response.text
        body = response.json()
        if isinstance(body, dict) and "status" in body:
            if int(body["status"]) >= 400:
                raise BoptestError(body.get("message", "BOPTEST request failed"))
            return body.get("payload")
        return body

    def version(self) -> Any:
        return self._payload(self.client.get(f"{self.base_url}/version"))

    def test_cases(self) -> Any:
        return self._payload(self.client.get(f"{self.base_url}/testcases"))

    def select(self, test_case: str) -> str:
        payload = self._payload(
            self.client.post(f"{self.base_url}/testcases/{test_case}/select", json={})
        )
        if isinstance(payload, dict):
            test_id = payload.get("testid") or payload.get("test_id")
        else:
            test_id = payload
        if not test_id:
            raise BoptestError("BOPTEST did not return a test id")
        return str(test_id)

    def initialize(self, test_id: str, *, start_time: float, warmup_period: float) -> Any:
        return self._payload(
            self.client.put(
                f"{self.base_url}/initialize/{test_id}",
                json={"start_time": start_time, "warmup_period": warmup_period},
            )
        )

    def set_step(self, test_id: str, seconds: float) -> Any:
        return self._payload(
            self.client.put(f"{self.base_url}/step/{test_id}", json={"step": seconds})
        )

    def measurements(self, test_id: str) -> Any:
        return self._payload(self.client.get(f"{self.base_url}/measurements/{test_id}"))

    def inputs(self, test_id: str) -> Any:
        return self._payload(self.client.get(f"{self.base_url}/inputs/{test_id}"))

    def advance(self, test_id: str, overrides: dict[str, float | int]) -> Any:
        return self._payload(self.client.post(f"{self.base_url}/advance/{test_id}", json=overrides))

    def kpis(self, test_id: str) -> Any:
        return self._payload(self.client.get(f"{self.base_url}/kpi/{test_id}"))

    def stop(self, test_id: str) -> Any:
        return self._payload(self.client.put(f"{self.base_url}/stop/{test_id}"))

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> BoptestClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
