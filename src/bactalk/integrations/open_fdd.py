from __future__ import annotations

from typing import Any

from bactalk.optional_dependencies import OPEN_FDD


class OpenFddError(RuntimeError):
    pass


class OpenFddVerifier:
    """Execute selected Open-FDD rules against normalized time-series rows."""

    def verify(
        self,
        *,
        rule_id: str,
        equipment_id: str,
        equipment_kind: str,
        equipment_type: str,
        poll_seconds: float,
        rows: list[dict[str, Any]],
        parameters: dict[str, Any] | None = None,
        require_operational_gates: bool = True,
    ) -> dict[str, Any]:
        try:
            import pandas as pd
            OPEN_FDD.require()
            from open_fdd.rules.runner import RULES_BY_ID, run_cookbook_rule
        except ImportError as exc:  # pragma: no cover - installation guard
            raise OpenFddError("install BACTalk with the 'fdd' extra") from exc
        rule = RULES_BY_ID.get(rule_id)
        if rule is None:
            raise OpenFddError(f"unknown Open-FDD rule: {rule_id}")
        if not rows:
            raise OpenFddError("rows must not be empty")
        normalized: list[dict[str, Any]] = []
        timestamps: list[str] = []
        for row in rows:
            if "timestamp" not in row:
                raise OpenFddError("each row must include a timestamp")
            copy = dict(row)
            timestamps.append(str(copy.pop("timestamp")))
            normalized.append(copy)
        try:
            index = pd.to_datetime(timestamps, utc=True)
        except (TypeError, ValueError) as exc:
            raise OpenFddError("rows contain an invalid timestamp") from exc
        frame = pd.DataFrame(normalized, index=index)
        result = run_cookbook_rule(
            rule,
            frame,
            equipment_id=equipment_id,
            equipment_kind=equipment_kind,
            equipment_type=equipment_type,
            poll_seconds=poll_seconds,
            params_by_rule={rule_id: parameters or {}},
            require_operational_gates=require_operational_gates,
        )
        return result.to_dict()
