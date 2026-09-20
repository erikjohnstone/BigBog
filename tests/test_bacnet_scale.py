from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import pytest

from bactalk.integrations.bacnet_scale import BacnetScaleProfile, BacnetScaleRunner


def _free_udp_range(count: int) -> int:
    for start in range(30_000, 60_000 - count):
        sockets: list[socket.socket] = []
        try:
            for port in range(start, start + count):
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.bind(("127.0.0.1", port))
                sockets.append(sock)
            return start
        except OSError:
            continue
        finally:
            for sock in sockets:
                sock.close()
    raise RuntimeError("could not reserve a local UDP test range")


def test_real_udp_scale_runner_reads_writes_and_recovers(tmp_path: Path) -> None:
    profile = BacnetScaleProfile(
        devices=3,
        analog_inputs_per_device=2,
        binary_inputs_per_device=1,
        analog_outputs_per_device=1,
        binary_outputs_per_device=1,
        poll_rounds=2,
        cov_subscriptions=3,
        cov_burst_rounds=2,
        concurrency=2,
        base_port=_free_udp_range(4),
        request_timeout_seconds=2.0,
        outage_timeout_seconds=0.1,
    )
    evidence = asyncio.run(BacnetScaleRunner(profile, tmp_path).run())

    assert evidence["status"] == "pass", evidence["errors"]
    assert evidence["profile"]["total_points"] == 15
    assert evidence["results"]["devices_discovered"] == 3
    assert evidence["results"]["read_requests_passed"] == 6
    assert evidence["results"]["properties_read"] == 30
    assert evidence["results"]["writes_verified"] == 3
    assert evidence["results"]["cov_subscriptions_verified"] == 3
    assert evidence["results"]["cov_notifications_verified"] == 6
    assert evidence["results"]["outage_detected"] is True
    assert evidence["results"]["recovery_verified"] is True
    assert not evidence["errors"]


def test_scale_profile_rejects_a_profile_without_writable_analog_output() -> None:
    with pytest.raises(ValueError, match="analog output"):
        BacnetScaleProfile(analog_outputs_per_device=0)
