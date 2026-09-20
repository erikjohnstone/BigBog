from __future__ import annotations

from typing import Any

import httpx


class BoptestError(RuntimeError):
    pass


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
