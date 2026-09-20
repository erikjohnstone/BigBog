from pathlib import Path

from bactalk.integrations.open_control_engine import OpenControlEngine


def main() -> None:
    fixture = Path(
        ".vendor/open-control-engine/crates/oce-cxf/tests/fixtures/g36/"
        "cooling_only_controller.jsonld"
    )
    result = OpenControlEngine().inspect(fixture)
    assert result["block_count"] > 0
    assert result["point_count"] > 0
    economizer = Path(
        ".vendor/open-control-engine/crates/oce-cxf/tests/fixtures/g36/"
        "ahu_economizer.jsonld"
    )
    root = "http://example.org#g36.ahu_economizer"
    temperature_difference = f"{root}.returnMinusOutdoor.y"
    latch = f"{root}.enableLatch.y"
    damper = f"{root}.damperSwitch.y"
    trace = OpenControlEngine().simulate(
        economizer,
        samples=[
            {
                "time": 0.0,
                "inputs": {
                    f"{root}.return_air_temp": 24.0,
                    f"{root}.outdoor_air_temp": 18.0,
                    f"{root}.operating_mode": 1,
                },
            },
            {
                "time": 60.0,
                "inputs": {
                    f"{root}.return_air_temp": 24.0,
                    f"{root}.outdoor_air_temp": 19.0,
                    f"{root}.operating_mode": 1,
                },
            },
            {
                "time": 180.0,
                "inputs": {
                    f"{root}.return_air_temp": 24.0,
                    f"{root}.outdoor_air_temp": 27.0,
                    f"{root}.operating_mode": 1,
                },
            },
        ],
        collect=[temperature_difference, latch, damper],
    )
    assert trace["schema"] == "bactalk.oce-trace/v1"
    assert trace["sample_count"] == 3
    assert [sample["outputs"][temperature_difference]["value"] for sample in trace["trace"]] == [
        6.0,
        5.0,
        -3.0,
    ]
    assert [sample["outputs"][latch]["value"] for sample in trace["trace"]] == [
        True,
        True,
        False,
    ]
    assert [sample["outputs"][damper]["value"] for sample in trace["trace"]] == [
        1.0,
        1.0,
        0.2,
    ]
    print(
        "Open Control Engine contract: OK "
        f"({result['block_count']} blocks, {result['stateful_blocks']} stateful, "
        f"{result['point_count']} points; native G36 economizer trajectory passed)"
    )


if __name__ == "__main__":
    main()
