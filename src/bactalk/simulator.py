from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from bactalk.domain import (
    AcceptanceCase,
    AssertionResult,
    Block,
    BlockKind,
    ComparisonOperator,
    ControlGraph,
    DataType,
    FaultInjection,
    FaultKind,
    JobSpec,
    OutputExpectation,
    ScenarioResult,
    TestReport,
)


class FaultInjector:
    """Apply typed, deterministic input faults and retain scan-level evidence."""

    def __init__(self, graph: ControlGraph):
        self.input_types: dict[str, DataType] = {}
        self.defaults: dict[str, float | bool] = {}
        for block in graph.blocks:
            if block.kind == BlockKind.NUMERIC_INPUT:
                self.input_types[block.id] = DataType.NUMERIC
                self.defaults[block.id] = float(block.config.get("default", 0.0))
            elif block.kind == BlockKind.BOOLEAN_INPUT:
                self.input_types[block.id] = DataType.BOOLEAN
                self.defaults[block.id] = bool(block.config.get("default", False))
        self.state: dict[str, dict[str, Any]] = {}

    def _validate(self, faults: list[FaultInjection]) -> None:
        targets: set[str] = set()
        for fault in faults:
            data_type = self.input_types.get(fault.target)
            if data_type is None:
                raise ValueError(
                    f"fault {fault.id!r} target {fault.target!r} is not a graph input"
                )
            if fault.target in targets:
                raise ValueError(f"multiple active faults target input {fault.target!r}")
            targets.add(fault.target)
            if fault.kind in {FaultKind.BIAS, FaultKind.SCALE, FaultKind.DRIFT} and (
                data_type != DataType.NUMERIC
            ):
                raise ValueError(f"fault {fault.id!r} requires a numeric target")
            if fault.kind == FaultKind.INVERT and data_type != DataType.BOOLEAN:
                raise ValueError(f"fault {fault.id!r} requires a boolean target")
            if fault.kind in {FaultKind.FORCE, FaultKind.DROPOUT}:
                value_is_boolean = isinstance(fault.value, bool)
                if value_is_boolean != (data_type == DataType.BOOLEAN):
                    raise ValueError(
                        f"fault {fault.id!r} value type does not match target {fault.target!r}"
                    )
            if fault.quality_target is not None:
                if self.input_types.get(fault.quality_target) != DataType.BOOLEAN:
                    raise ValueError(
                        f"fault {fault.id!r} quality_target must be a Boolean graph input"
                    )

    def apply(
        self,
        inputs: dict[str, float | bool],
        faults: list[FaultInjection],
        *,
        step_seconds: float,
    ) -> tuple[dict[str, float | bool], dict[str, float | bool]]:
        self._validate(faults)
        active_ids = {fault.id for fault in faults}
        for fault_id in set(self.state) - active_ids:
            del self.state[fault_id]

        effective = dict(inputs)
        evidence: dict[str, float | bool] = {}
        for fault in faults:
            raw = inputs.get(fault.target, self.defaults[fault.target])
            signature = (
                fault.target,
                fault.kind.value,
                fault.value,
                fault.quality_target,
            )
            state = self.state.get(fault.id)
            if state is None or state["signature"] != signature:
                state = {
                    "signature": signature,
                    "captured": raw,
                    "elapsed": 0.0,
                }
                self.state[fault.id] = state
            state["elapsed"] = float(state["elapsed"]) + step_seconds

            if fault.kind in {FaultKind.STUCK, FaultKind.STALE}:
                applied: float | bool = state["captured"]
            elif fault.kind in {FaultKind.FORCE, FaultKind.DROPOUT}:
                if fault.value is None:
                    raise AssertionError("validated fault value is missing")
                applied = fault.value
            elif fault.kind == FaultKind.INVERT:
                applied = not bool(raw)
            elif fault.kind == FaultKind.BIAS:
                applied = float(raw) + float(fault.value)
            elif fault.kind == FaultKind.SCALE:
                applied = float(raw) * float(fault.value)
            elif fault.kind == FaultKind.DRIFT:
                applied = float(raw) + float(fault.value) * float(state["elapsed"])
            else:  # pragma: no cover - enum exhaustiveness guard
                raise ValueError(f"unsupported fault kind: {fault.kind}")

            effective[fault.target] = applied
            if fault.quality_target is not None:
                effective[fault.quality_target] = False
            prefix = f"fault.{fault.id}"
            evidence[f"{prefix}.active"] = True
            evidence[f"{prefix}.elapsed_seconds"] = float(state["elapsed"])
            evidence[f"{prefix}.raw"] = raw
            evidence[f"{prefix}.applied"] = applied
            if fault.quality_target is not None:
                evidence[f"effective.{fault.quality_target}"] = False
            evidence[f"effective.{fault.target}"] = applied
        return effective, evidence


class GraphInterpreter:
    """Deterministic Tier-1 evaluator for fast control-logic feedback."""

    def __init__(self, graph: ControlGraph):
        self.graph = graph
        self.state: dict[str, Any] = {}
        self.time = 0.0
        self.assert_events: list[dict[str, Any]] = []
        self.incoming: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
        for link in graph.links:
            self.incoming[link.target][link.target_slot] = (
                link.source,
                link.source_slot,
            )

    def evaluate(
        self,
        inputs: dict[str, float | bool],
        *,
        step_seconds: float = 1.0,
    ) -> dict[str, float | bool]:
        if step_seconds < 0:
            raise ValueError("step_seconds must be non-negative")
        self.time += step_seconds
        self.assert_events = []
        values: dict[str, float | bool] = {}
        deferred_unit_delays: list[Block] = []
        deferred_pre_blocks: list[Block] = []
        for block in self.graph.topological_order():
            if block.kind in {
                BlockKind.NUMERIC_UNIT_DELAY,
                BlockKind.BOOLEAN_PRE_HOST_TICK,
            }:
                args = {}
                if block.kind == BlockKind.NUMERIC_UNIT_DELAY:
                    deferred_unit_delays.append(block)
                else:
                    deferred_pre_blocks.append(block)
            else:
                args = {
                    slot: values[f"{source}.{source_slot}"]
                    for slot, (source, source_slot) in self.incoming.get(block.id, {}).items()
                }
            result = self._evaluate_block(block, args, inputs, step_seconds)
            if isinstance(result, dict):
                for output_slot, value in result.items():
                    values[f"{block.id}.{output_slot}"] = value
                primary_slot = next(iter(result))
                values[block.id] = result[primary_slot]
            else:
                values[block.id] = result
                values[f"{block.id}.out"] = result
        for block in deferred_unit_delays:
            source, source_slot = self.incoming[block.id]["in"]
            self._update_unit_delay(
                block,
                self._number(values[f"{source}.{source_slot}"]),
            )
        for block in deferred_pre_blocks:
            source, source_slot = self.incoming[block.id]["in"]
            self.state.setdefault(
                block.id,
                {"out": bool(block.config.get("initial", False))},
            )["out"] = bool(values[f"{source}.{source_slot}"])
        return values

    @staticmethod
    def _number(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"expected numeric value, received {value!r}")
        return float(value)

    def _evaluate_block(
        self,
        block: Block,
        args: dict[str, float | bool],
        inputs: dict[str, float | bool],
        step_seconds: float,
    ) -> float | bool | dict[str, float | bool]:
        kind = block.kind
        if kind in {BlockKind.NUMERIC_INPUT, BlockKind.BOOLEAN_INPUT}:
            return inputs.get(block.id, block.config.get("default", 0.0))
        if kind in {BlockKind.NUMERIC_CONST, BlockKind.BOOLEAN_CONST}:
            return block.config["value"]
        if kind in {BlockKind.NUMERIC_OUTPUT, BlockKind.BOOLEAN_OUTPUT}:
            return args["in"]
        if kind == BlockKind.ADD:
            return self._number(args["a"]) + self._number(args["b"])
        if kind == BlockKind.SUBTRACT:
            return self._number(args["a"]) - self._number(args["b"])
        if kind == BlockKind.MULTIPLY:
            return self._number(args["a"]) * self._number(args["b"])
        if kind == BlockKind.DIVIDE:
            numerator = self._number(args["a"])
            denominator = self._number(args["b"])
            if denominator == 0.0:
                if numerator == 0.0:
                    return math.nan
                return math.copysign(math.inf, numerator * math.copysign(1.0, denominator))
            return numerator / denominator
        if kind == BlockKind.MINIMUM:
            return min(self._number(args["a"]), self._number(args["b"]))
        if kind == BlockKind.MAXIMUM:
            return max(self._number(args["a"]), self._number(args["b"]))
        if kind == BlockKind.AVERAGE:
            return (self._number(args["a"]) + self._number(args["b"])) / 2.0
        if kind == BlockKind.GREATER_THAN:
            return self._number(args["a"]) > self._number(args["b"])
        if kind == BlockKind.GREATER_THAN_OR_EQUAL:
            return self._number(args["a"]) >= self._number(args["b"])
        if kind == BlockKind.LESS_THAN:
            return self._number(args["a"]) < self._number(args["b"])
        if kind == BlockKind.LESS_THAN_OR_EQUAL:
            return self._number(args["a"]) <= self._number(args["b"])
        if kind == BlockKind.EQUAL:
            return self._number(args["a"]) == self._number(args["b"])
        if kind == BlockKind.NOT_EQUAL:
            return self._number(args["a"]) != self._number(args["b"])
        if kind == BlockKind.AND:
            return bool(args["a"]) and bool(args["b"])
        if kind == BlockKind.OR:
            return bool(args["a"]) or bool(args["b"])
        if kind == BlockKind.XOR:
            return bool(args["a"]) != bool(args["b"])
        if kind == BlockKind.NOT:
            return not bool(args["in"])
        if kind == BlockKind.BOOLEAN_PRE_HOST_TICK:
            state = self.state.setdefault(
                block.id,
                {"out": bool(block.config.get("initial", False))},
            )
            return bool(state["out"])
        if kind == BlockKind.NUMERIC_SWITCH:
            return args["when_true"] if bool(args["selector"]) else args["when_false"]
        if kind == BlockKind.BOOLEAN_SWITCH:
            return args["when_true"] if bool(args["selector"]) else args["when_false"]
        if kind == BlockKind.BOOLEAN_DELAY:
            desired = bool(args["in"])
            state = self.state.setdefault(
                block.id,
                {
                    "out": bool(block.config.get("initial", False)),
                    "pending": bool(block.config.get("initial", False)),
                    "elapsed": 0.0,
                    "first_tick": True,
                },
            )
            if (
                bool(state["first_tick"])
                and desired
                and not bool(block.config.get("delay_on_init", True))
            ):
                state["out"] = True
                state["pending"] = True
                state["elapsed"] = float(block.config.get("on_delay_seconds", 0.0))
                state["first_tick"] = False
                return True
            state["first_tick"] = False
            if desired == state["out"]:
                state["elapsed"] = 0.0
                state["pending"] = desired
            elif desired != state["pending"]:
                state["pending"] = desired
                state["elapsed"] = 0.0
                delay_key = "on_delay_seconds" if desired else "off_delay_seconds"
                if float(block.config.get(delay_key, 0.0)) <= 0.0:
                    state["out"] = desired
            else:
                state["elapsed"] += step_seconds
                delay_key = "on_delay_seconds" if desired else "off_delay_seconds"
                if state["elapsed"] >= float(block.config.get(delay_key, 0.0)):
                    state["out"] = desired
                    state["elapsed"] = 0.0
            return bool(state["out"])
        if kind == BlockKind.ONE_SHOT:
            value = bool(args["in"])
            state = self.state.setdefault(
                block.id,
                {"previous": bool(block.config.get("initial", False))},
            )
            pulse = value and not state["previous"]
            state["previous"] = value
            return pulse
        if kind == BlockKind.BOOLEAN_FALLING_EDGE:
            value = bool(args["in"])
            state = self.state.setdefault(
                block.id,
                {"previous": bool(block.config.get("pre_u_start", False))},
            )
            pulse = bool(state["previous"]) and not value
            state["previous"] = value
            return pulse
        if kind == BlockKind.MOVING_AVERAGE:
            value = self._number(args["in"])
            window = float(block.config["window_seconds"])
            state = self.state.get(block.id)
            if state is None:
                state = {
                    "mu": 0.0,
                    "t_start": self.time,
                    "prev_t": self.time,
                    "points": [],
                }
                self.state[block.id] = state
            dt = max(0.0, self.time - float(state["prev_t"]))
            mu_now = float(state["mu"]) + value * dt
            points: list[tuple[float, float]] = state["points"]
            target = self.time - window
            mu_del = self._interpolate_integral(points, target, self.time, mu_now)
            if self.time >= float(state["t_start"]) + window:
                oldest = points[0][0] if points else float(state["t_start"])
                low = max(target, oldest, float(state["t_start"]))
                denominator = max(self.time - low, 1e-5)
            else:
                denominator = self.time - float(state["t_start"]) + 1e-3
            output = (mu_now - mu_del) / denominator
            while len(points) > 1 and points[1][0] <= target:
                points.pop(0)
            if points and points[-1][0] == self.time:
                points[-1] = (self.time, mu_now)
            else:
                points.append((self.time, mu_now))
            if len(points) > 64:
                points.pop(0)
            state["mu"] = mu_now
            state["prev_t"] = self.time
            return output
        if kind == BlockKind.BOOLEAN_INITIALIZATION:
            state = self.state.setdefault(block.id, {"initialized": False})
            if not bool(state["initialized"]):
                state["initialized"] = True
                return bool(block.config.get("initial", False))
            return bool(args["in"])
        if kind == BlockKind.NUMERIC_SAMPLER:
            value = self._number(args["in"])
            period = float(block.config["sample_period_seconds"])
            state = self.state.get(block.id)
            if state is None:
                t0 = round(math.floor(self.time / period) * period, 6)
                index = math.floor((self.time - t0) / period + 1e-9)
                self.state[block.id] = {
                    "held": value,
                    "t0": t0,
                    "last_index": index,
                }
                return value
            index = math.floor((self.time - float(state["t0"])) / period + 1e-9)
            if index > int(state["last_index"]):
                state["held"] = value
                state["last_index"] = index
            return float(state["held"])
        if kind == BlockKind.NUMERIC_UNIT_DELAY:
            initial = float(block.config.get("initial", 0.0))
            state = self.state.get(block.id)
            if state is None:
                return initial
            period = float(block.config["sample_period_seconds"])
            index = math.floor((self.time - float(state["t0"])) / period + 1e-9)
            if index > int(state["last_index"]):
                return float(state["staged"])
            return float(state["held"])
        if kind == BlockKind.PLANT_EQUIPMENT_AVAILABILITY:
            enable_heating = bool(args["enableHeating"])
            enable_cooling = bool(args["enableCooling"])
            available = bool(args["available"])
            off_time = float(block.config["off_time_seconds"])
            state = self.state.setdefault(
                block.id,
                {"mode": "available", "off_since": None},
            )
            # Modelica StateGraph transitions iterate at one event instant. Bound the
            # loop because this five-state graph can settle in at most four transitions.
            for _ in range(5):
                mode = str(state["mode"])
                next_mode = mode
                if mode == "available":
                    if not available:
                        next_mode = "unavailable"
                    elif enable_cooling:
                        next_mode = "cooling"
                    elif enable_heating:
                        next_mode = "heating"
                elif mode == "heating":
                    if not enable_heating:
                        next_mode = "off"
                        state["off_since"] = self.time
                    elif not available:
                        next_mode = "unavailable"
                elif mode == "cooling":
                    if not enable_cooling:
                        next_mode = "off"
                        state["off_since"] = self.time
                    elif not available:
                        next_mode = "unavailable"
                elif mode == "off":
                    off_since = float(state["off_since"])
                    if self.time - off_since >= off_time:
                        next_mode = "available"
                elif mode == "unavailable" and available:
                    next_mode = "available"
                if next_mode == mode:
                    break
                state["mode"] = next_mode
            mode = str(state["mode"])
            return {
                "heatingAvailable": mode in {"available", "heating"},
                "coolingAvailable": mode in {"available", "cooling"},
            }
        if kind == BlockKind.PLANT_ENABLE:
            request_count = self._number(args["requestCount"])
            outdoor_temperature = self._number(args["outdoorTemperature"])
            schedule_enabled = bool(args["scheduleEnabled"])
            if not bool(block.config["have_input_schedule"]):
                schedule = block.config["schedule"]
                period = float(schedule[-1][0])
                phase = self.time % period if period > 0 else self.time
                schedule_enabled = bool(schedule[0][1])
                for row in schedule:
                    if phase < float(row[0]):
                        break
                    schedule_enabled = bool(row[1])
            ignored = int(block.config["ignored_requests"])
            low_request = request_count <= ignored
            state = self.state.get(block.id)
            if state is None:
                state = {
                    "enabled": False,
                    "disabled_since": self.time,
                    "enabled_since": None,
                    "low_request_since": self.time if low_request else None,
                    "previous_time": self.time,
                }
                self.state[block.id] = state
            elif self.time < float(state["previous_time"]):
                raise ValueError("plant enable time must be monotonic")
            if low_request:
                if state["low_request_since"] is None:
                    state["low_request_since"] = self.time
            else:
                state["low_request_since"] = None
            low_request_passed = (
                state["low_request_since"] is not None
                and self.time - float(state["low_request_since"])
                >= float(block.config["low_request_time_seconds"])
            )
            heating = block.config["application"] == "Heating"
            lockout = float(block.config["outdoor_lockout"])
            hysteresis = float(block.config["outdoor_lockout_hysteresis"])
            outdoor_enable = (
                outdoor_temperature < lockout
                if heating
                else outdoor_temperature > lockout
            )
            outdoor_disable = (
                outdoor_temperature > lockout + hysteresis
                if heating
                else outdoor_temperature < lockout - hysteresis
            )
            minimum_time = float(block.config["minimum_state_time_seconds"])
            if not bool(state["enabled"]):
                disabled_long_enough = (
                    self.time - float(state["disabled_since"]) >= minimum_time
                )
                if (
                    disabled_long_enough
                    and schedule_enabled
                    and request_count > ignored
                    and outdoor_enable
                ):
                    state["enabled"] = True
                    state["enabled_since"] = self.time
            else:
                enabled_long_enough = (
                    self.time - float(state["enabled_since"]) >= minimum_time
                )
                if enabled_long_enough and (
                    not schedule_enabled or low_request_passed or outdoor_disable
                ):
                    state["enabled"] = False
                    state["disabled_since"] = self.time
            state["previous_time"] = self.time
            return bool(state["enabled"])
        if kind == BlockKind.PLANT_HRC_ENABLE:
            cooling_plant_enable = bool(args["coolingPlantEnable"])
            heating_plant_enable = bool(args["heatingPlantEnable"])
            hrc_status = bool(args["hrcStatus"])
            cooling_load = self._number(args["coolingLoad"])
            # Keep the heating input typed and finite even though the pinned source's
            # low-load branch connects QChiWatReq_flow to both low-load comparators.
            self._number(args["heatingLoad"])
            chilled_temperature = self._number(args["chilledLeavingTemperature"])
            heating_temperature = self._number(args["heatingLeavingTemperature"])
            cooling_mode = bool(args["coolingMode"])
            state = self.state.get(block.id)
            first_tick = state is None
            if state is None:
                state = {
                    "timers": {},
                    "high_cooling_load": False,
                    "high_heating_load": False,
                    "low_cooling_load": False,
                    "low_heating_load": False,
                    "previous_hrc_status": False,
                    "previous_all_enable": False,
                    "previous_disable": False,
                    "latch": False,
                    "enable_output": False,
                    "delay_started": None,
                    "previous_time": self.time,
                }
                self.state[block.id] = state
            elif self.time < float(state["previous_time"]):
                raise ValueError("HRC enable time must be monotonic")

            def timer(name: str, active: bool, threshold: float) -> bool:
                timers: dict[str, Any] = state["timers"]
                timer_state = timers.get(name)
                if timer_state is None:
                    timer_state = {
                        "entry_time": self.time,
                        "previous": False,
                        "passed": threshold <= 0.0,
                    }
                    timers[name] = timer_state
                previous = bool(timer_state["previous"])
                if active and not previous:
                    timer_state["entry_time"] = self.time
                    timer_state["passed"] = threshold <= 0.0
                elif active and self.time >= float(timer_state["entry_time"]) + threshold:
                    timer_state["passed"] = True
                elif not active:
                    timer_state["passed"] = False
                timer_state["previous"] = active
                return bool(timer_state["passed"])

            def greater_hysteresis(name: str, value: float, threshold: float) -> bool:
                hysteresis = 1e-4 * threshold
                previous = bool(state[name])
                output = (
                    value > threshold
                    if hysteresis < 1e-10
                    else value > threshold
                    if not previous
                    else value > threshold - hysteresis
                )
                state[name] = output
                return output

            def less_hysteresis(name: str, value: float, threshold: float) -> bool:
                hysteresis = 1e-4 * threshold
                previous = bool(state[name])
                output = (
                    value < threshold
                    if hysteresis < 1e-10
                    else value < threshold
                    if not previous
                    else value < threshold + hysteresis
                )
                state[name] = output
                return output

            previous_enable = bool(state["enable_output"])
            minimum_state_time = float(block.config["minimum_state_time_seconds"])
            sufficient_load_time = float(block.config["sufficient_load_time_seconds"])
            minimum_cooling_capacity = float(block.config["minimum_cooling_capacity"])
            minimum_heating_capacity = float(block.config["minimum_heating_capacity"])
            high_cooling_load = greater_hysteresis(
                "high_cooling_load", cooling_load, minimum_cooling_capacity
            )
            high_heating_load = greater_hysteresis(
                "high_heating_load",
                self._number(args["heatingLoad"]),
                minimum_heating_capacity,
            )
            all_enable = all(
                (
                    timer("cooling_plant", cooling_plant_enable, minimum_state_time),
                    timer("heating_plant", heating_plant_enable, minimum_state_time),
                    timer("disabled", not previous_enable, minimum_state_time),
                    timer("cooling_load", high_cooling_load, sufficient_load_time),
                    timer("heating_load", high_heating_load, sufficient_load_time),
                )
            )

            low_cooling_load = less_hysteresis(
                "low_cooling_load", cooling_load, minimum_cooling_capacity
            )
            # This intentionally mirrors the exact pinned Modelica connection rather
            # than substituting QHeaWatReq_flow for the source's QChiWatReq_flow link.
            low_heating_load = less_hysteresis(
                "low_heating_load", cooling_load, minimum_heating_capacity
            )
            hrc_falling_edge = bool(state["previous_hrc_status"]) and not hrc_status
            low_load_cycle_off = hrc_falling_edge and (
                low_cooling_load or low_heating_load
            )
            first_temperature_time = float(
                block.config["temperature_limit_1_time_seconds"]
            )
            second_temperature_time = float(
                block.config["temperature_limit_2_time_seconds"]
            )
            chilled_limit = float(block.config["minimum_chilled_supply_temperature"])
            heating_limit = float(block.config["maximum_heating_supply_temperature"])
            chilled_temperature_trip_1 = timer(
                "chilled_temperature_1",
                chilled_temperature < chilled_limit + 1.0,
                first_temperature_time,
            )
            chilled_temperature_trip_2 = timer(
                "chilled_temperature_2",
                chilled_temperature < chilled_limit,
                second_temperature_time,
            )
            chilled_temperature_trip = (
                chilled_temperature_trip_1 or chilled_temperature_trip_2
            )
            heating_temperature_trip_1 = timer(
                "heating_temperature_1",
                heating_temperature > heating_limit - 1.5,
                first_temperature_time,
            )
            heating_temperature_trip_2 = timer(
                "heating_temperature_2",
                heating_temperature > heating_limit,
                second_temperature_time,
            )
            heating_temperature_trip = (
                heating_temperature_trip_1 or heating_temperature_trip_2
            )
            disable = (
                not cooling_plant_enable
                or not heating_plant_enable
                or low_load_cycle_off
                or (previous_enable and not cooling_mode and chilled_temperature_trip)
                or (previous_enable and cooling_mode and heating_temperature_trip)
            )

            previous_all_enable = bool(state["previous_all_enable"])
            previous_disable = bool(state["previous_disable"])
            if first_tick:
                latch = not disable and all_enable
            elif (disable and not previous_disable) or (
                all_enable and not previous_all_enable
            ):
                latch = not disable and all_enable
            else:
                latch = bool(state["latch"])
            set_mode = latch and not bool(state["latch"])

            if first_tick:
                enable_output = latch
                delay_started = self.time if latch else None
            elif not latch:
                enable_output = False
                delay_started = None
            elif not bool(state["latch"]):
                enable_output = False
                delay_started = self.time
            else:
                delay_started = state["delay_started"]
                enable_output = bool(state["enable_output"])
                if (
                    not enable_output
                    and delay_started is not None
                    and self.time - float(delay_started) >= 5.0
                ):
                    enable_output = True

            state["previous_hrc_status"] = hrc_status
            state["previous_all_enable"] = all_enable
            state["previous_disable"] = disable
            state["latch"] = latch
            state["enable_output"] = enable_output
            state["delay_started"] = delay_started
            state["previous_time"] = self.time
            return {"enable": enable_output, "setMode": set_mode}
        if kind == BlockKind.PLANT_HRC_MODE_CONTROL:
            cooling_load = self._number(args["coolingLoad"])
            heating_load = self._number(args["heatingLoad"])
            evaporator_load = heating_load * (
                1.0 - 1.0 / float(block.config["heating_cop"])
            )
            state = self.state.setdefault(
                block.id,
                {"comparison": False, "cooling_mode": False},
            )
            comparison = (
                (not bool(state["comparison"]) and cooling_load < evaporator_load)
                or (
                    bool(state["comparison"])
                    and cooling_load < evaporator_load + 1.0
                )
            )
            state["comparison"] = comparison
            if bool(args["setMode"]):
                state["cooling_mode"] = comparison
            cooling_mode = bool(state["cooling_mode"])
            return {
                "coolingMode": cooling_mode,
                "supplySetpoint": (
                    self._number(args["chilledSetpoint"])
                    if cooling_mode
                    else self._number(args["heatingSetpoint"])
                ),
            }
        if kind == BlockKind.PLANT_STAGE_COMPLETION:
            equipment_count = int(block.config["equipment_count"])
            maximum_mask = (1 << equipment_count) - 1

            def mask(slot: str) -> int:
                value = self._number(args[slot])
                if not value.is_integer() or not 0 <= value <= maximum_mask:
                    raise ValueError(
                        f"stage completion {slot} must be an integer mask from 0 "
                        f"through {maximum_mask}"
                    )
                return int(value)

            command_mask = mask("commandMask")
            status_mask = mask("statusMask")
            stage_value = self._number(args["stage"])
            if not stage_value.is_integer() or stage_value < 0:
                raise ValueError("stage completion stage must be a non-negative integer")
            stage = int(stage_value)
            state = self.state.setdefault(
                block.id,
                {
                    "previous_command_mask": 0,
                    "previous_any_change": False,
                    "previous_pre_any_change": False,
                    "previous_stage": 0,
                    "previous_stage_change": False,
                    "change_latch": False,
                    "stage_latch": False,
                },
            )
            any_change = command_mask != int(state["previous_command_mask"])
            pre_any_change = bool(state["previous_any_change"])
            stage_change = stage != int(state["previous_stage"])
            change_latch = not stage_change and (
                (
                    pre_any_change
                    and not bool(state["previous_pre_any_change"])
                )
                or bool(state["change_latch"])
            )
            all_match = command_mask == status_mask
            change_and_match = change_latch and all_match
            stage_latch = not change_and_match and (
                (
                    stage_change
                    and not bool(state["previous_stage_change"])
                )
                or bool(state["stage_latch"])
            )
            completed = bool(state["stage_latch"]) and not stage_latch
            state["previous_command_mask"] = command_mask
            state["previous_any_change"] = any_change
            state["previous_pre_any_change"] = pre_any_change
            state["previous_stage"] = stage
            state["previous_stage_change"] = stage_change
            state["change_latch"] = change_latch
            state["stage_latch"] = stage_latch
            return {"inProgress": stage_latch, "completed": completed}
        if kind == BlockKind.PLANT_STAGE_INDEX:
            stage_count = int(block.config["stage_count"])
            maximum_mask = (1 << stage_count) - 1
            availability_value = self._number(args["availabilityMask"])
            if (
                not availability_value.is_integer()
                or not 0 <= availability_value <= maximum_mask
            ):
                raise ValueError(
                    "stage index availabilityMask must be an integer mask from 0 "
                    f"through {maximum_mask}"
                )
            availability_mask = int(availability_value)
            available = [
                stage
                for stage in range(1, stage_count + 1)
                if availability_mask & (1 << (stage - 1))
            ]
            state = self.state.setdefault(block.id, {"stage": 0, "elapsed": 0.0})
            stage = int(state["stage"])
            elapsed = float(state["elapsed"])
            if stage > 0:
                elapsed += step_seconds
            lead_enable = bool(args["leadEnable"])
            next_stage = stage
            if stage == 0:
                if lead_enable and available:
                    next_stage = available[0]
            else:
                higher = [value for value in available if value > stage]
                lower = [value for value in available if value < stage]
                active_available = stage in available
                runtime_met = elapsed >= float(
                    block.config["minimum_runtime_seconds"]
                )
                # The pinned StateGraph connects inter-stage transitions before
                # the stage-zero transition.  An unavailable active stage thus
                # advances immediately when a higher stage exists.
                if not active_available and higher:
                    next_stage = higher[0]
                elif runtime_met and not lead_enable:
                    next_stage = 0
                elif runtime_met and bool(args["stageUp"]) and higher:
                    next_stage = higher[0]
                elif runtime_met and bool(args["stageDown"]) and lower:
                    next_stage = lower[-1]
            if next_stage != stage:
                elapsed = 0.0
            state["stage"] = next_stage
            state["elapsed"] = elapsed
            return {"stage": float(next_stage)}
        if kind in {
            BlockKind.NUMERIC_CHANGED,
            BlockKind.NUMERIC_INCREASED,
            BlockKind.NUMERIC_DECREASED,
        }:
            value = self._number(args["in"])
            state = self.state.setdefault(
                block.id,
                {"previous": float(block.config.get("initial", 0.0))},
            )
            previous = float(state["previous"])
            state["previous"] = value
            if kind == BlockKind.NUMERIC_CHANGED:
                return value != previous
            if kind == BlockKind.NUMERIC_INCREASED:
                return value > previous
            return value < previous
        if kind in {BlockKind.NUMERIC_LATCH, BlockKind.BOOLEAN_LATCH}:
            default = 0.0 if kind == BlockKind.NUMERIC_LATCH else False
            state = self.state.setdefault(
                block.id,
                {"out": block.config.get("initial", default), "clock": False},
            )
            clock = bool(args["clock"])
            if clock and not state["clock"]:
                state["out"] = args["in"]
            state["clock"] = clock
            return state["out"]
        if kind == BlockKind.BOOLEAN_SET_RESET:
            set_value = bool(args["set"])
            clear = bool(args["clear"])
            state = self.state.setdefault(
                block.id,
                {"out": False, "previous_set": False},
            )
            output = not clear and (
                (set_value and not bool(state["previous_set"])) or bool(state["out"])
            )
            state["out"] = output
            state["previous_set"] = set_value
            return output
        if kind == BlockKind.HYSTERESIS:
            value = self._number(args["in"])
            state = self.state.setdefault(
                block.id,
                {"out": bool(block.config.get("initial", False))},
            )
            previous = bool(state["out"])
            output = (
                (not previous and value > float(block.config["u_high"]))
                or (previous and value >= float(block.config["u_low"]))
            )
            state["out"] = output
            return output
        if kind == BlockKind.BOOLEAN_TRUE_FALSE_HOLD:
            active = bool(args["in"])
            state = self.state.setdefault(
                block.id,
                {"initialized": False, "held": False, "elapsed": 0.0},
            )
            if not bool(state["initialized"]):
                state["initialized"] = True
                state["held"] = active
                state["elapsed"] = 0.0
                return active
            state["elapsed"] = float(state["elapsed"]) + step_seconds
            held = bool(state["held"])
            if active != held:
                duration_key = "true_hold_seconds" if held else "false_hold_seconds"
                required = max(0.0, float(block.config[duration_key]))
                if float(state["elapsed"]) >= required:
                    state["held"] = active
                    state["elapsed"] = 0.0
            return bool(state["held"])
        if kind == BlockKind.TIMER:
            active = bool(args["in"])
            threshold = float(block.config.get("threshold_seconds", 0.0))
            state = self.state.setdefault(
                block.id,
                {
                    "entry_time": 0.0,
                    "first_tick": True,
                    "previous_in": False,
                    "passed": threshold <= 0.0,
                },
            )
            previous_in = bool(state["previous_in"])
            first_tick = bool(state["first_tick"])
            if not active:
                elapsed = 0.0
            elif first_tick or not previous_in:
                elapsed = 0.0
            else:
                elapsed = self.time - float(state["entry_time"])
            if active and not previous_in:
                passed = threshold <= 0.0
            elif active and elapsed >= threshold:
                passed = True
            elif not active and previous_in:
                passed = False
            else:
                passed = bool(state["passed"])
            if active and (first_tick or not previous_in):
                state["entry_time"] = self.time
            state["first_tick"] = False
            state["previous_in"] = active
            state["passed"] = passed
            return {"elapsed": elapsed, "passed": passed}
        if kind == BlockKind.TIMER_WITH_RESET:
            active = bool(args["in"])
            reset = bool(args["reset"])
            threshold = float(block.config.get("threshold_seconds", 0.0))
            state = self.state.get(block.id)
            if state is None:
                entry_time = self.time
                passed = active and threshold <= 0.0
                state = {
                    "entry_time": entry_time,
                    "previous_in": active,
                    "previous_reset": reset,
                    "passed": passed,
                }
                self.state[block.id] = state
                return {
                    "elapsed": 0.0,
                    "passed": passed,
                }
            previous_in = bool(state["previous_in"])
            previous_reset = bool(state["previous_reset"])
            rising_input = active and not previous_in
            rising_reset = reset and not previous_reset
            entry_time = float(state["entry_time"])
            passed = bool(state["passed"])
            if rising_input or rising_reset:
                entry_time = self.time
                passed = active and threshold <= 0.0
            elif active and self.time >= entry_time + threshold:
                passed = True
            elif not active and previous_in:
                passed = False
            elapsed = self.time - entry_time if active else 0.0
            state["entry_time"] = entry_time
            state["previous_in"] = active
            state["previous_reset"] = reset
            state["passed"] = passed
            return {"elapsed": elapsed, "passed": passed}
        if kind == BlockKind.TIMER_ACCUMULATING:
            active = bool(args["in"])
            reset = bool(args["reset"])
            threshold = float(block.config.get("threshold_seconds", 0.0))
            state = self.state.setdefault(
                block.id,
                {
                    "elapsed": 0.0,
                    "previous_in": False,
                    "previous_reset": False,
                    "passed": threshold <= 0.0,
                },
            )
            elapsed = float(state["elapsed"])
            previous_in = bool(state["previous_in"])
            previous_reset = bool(state["previous_reset"])
            passed = bool(state["passed"])
            if reset and not previous_reset:
                elapsed = 0.0
                passed = threshold <= 0.0
            else:
                if previous_in:
                    elapsed += step_seconds
                # Preserve the pinned limiting case: if the input becomes false
                # exactly at the threshold, passed retains its prior value.
                if active and elapsed >= threshold:
                    passed = True
            state["elapsed"] = elapsed
            state["previous_in"] = active
            state["previous_reset"] = reset
            state["passed"] = passed
            return {"elapsed": elapsed, "passed": passed}
        if kind == BlockKind.BOOLEAN_ASSERT_WARNING:
            condition = bool(args["condition"])
            if not condition:
                self.assert_events.append(
                    {
                        "block_id": block.id,
                        "message": str(block.config["message"]),
                        "level": "warning",
                        "time_seconds": self.time,
                    }
                )
            return {"ok": condition}
        if kind in {
            BlockKind.TRIM_AND_RESPOND,
            BlockKind.TRIM_AND_RESPOND_HOLD,
        }:
            return self._trim_and_respond(block, args, step_seconds)
        if kind == BlockKind.RESET:
            value = self._number(args["in"])
            input_low = self._number(args["input_low"])
            input_high = self._number(args["input_high"])
            output_low = self._number(args["output_low"])
            output_high = self._number(args["output_high"])
            if input_high == input_low:
                raise ValueError(f"reset block {block.id} input range cannot be zero")
            ratio = min(1.0, max(0.0, (value - input_low) / (input_high - input_low)))
            return output_low + ratio * (output_high - output_low)
        if kind == BlockKind.PI_LOOP:
            output_min = float(block.config.get("output_min", 0.0))
            output_max = float(block.config.get("output_max", 100.0))
            disabled_output = float(block.config.get("disabled_output", output_min))
            state = self.state.setdefault(block.id, {"integral": 0.0})
            if not bool(args["enable"]):
                state["integral"] = 0.0
                return min(output_max, max(output_min, disabled_output))
            controlled = self._number(args["controlled_variable"])
            setpoint = self._number(args["setpoint"])
            # Direct action raises output as the measured value rises. Reverse
            # action raises output as the measured value falls below setpoint.
            error = controlled - setpoint if bool(args["direct"]) else setpoint - controlled
            proportional = float(block.config.get("proportional_constant", 1.0)) * error
            integral_delta = (
                float(block.config.get("integral_constant", 0.0)) * error * step_seconds
            )
            candidate_integral = float(state["integral"]) + integral_delta
            bias = float(block.config.get("bias", 0.0))
            raw = bias + proportional + candidate_integral
            output = min(output_max, max(output_min, raw))
            drives_further_high = raw > output_max and error > 0
            drives_further_low = raw < output_min and error < 0
            if not drives_further_high and not drives_further_low:
                state["integral"] = candidate_integral
            return output
        if kind == BlockKind.PID_WITH_RESET:
            controller_type = str(block.config.get("controller_type", "PI"))
            with_integral = controller_type in {"PI", "PID"}
            with_derivative = controller_type in {"PD", "PID"}
            k = float(block.config.get("k", 1.0))
            ti = float(block.config.get("ti", 0.5))
            td = float(block.config.get("td", 0.1))
            scale = float(block.config.get("r", 1.0))
            ni = float(block.config.get("ni", 0.9))
            nd = float(block.config.get("nd", 10.0))
            y_min = float(block.config.get("y_min", 0.0))
            y_max = float(block.config.get("y_max", 1.0))
            state = self.state.setdefault(
                block.id,
                {
                    "integral": float(block.config.get("xi_start", 0.0)),
                    "derivative": 0.0,
                    "first_tick": True,
                    "previous_trigger": False,
                },
            )
            reverse_sign = 1.0 if bool(block.config.get("reverse_acting", True)) else -1.0
            error = reverse_sign * (
                self._number(args["setpoint"]) - self._number(args["measurement"])
            ) / scale
            proportional = k * error
            derivative_gain = k * td
            derivative_time = td / nd
            if with_derivative:
                derivative = (
                    float(block.config.get("yd_start", 0.0))
                    if state["first_tick"]
                    else (derivative_gain / derivative_time)
                    * (error - float(state["derivative"]))
                )
            else:
                derivative = 0.0
            integral = float(state["integral"]) if with_integral else 0.0
            proportional_derivative = proportional + derivative
            unlimited = proportional_derivative + integral
            output = y_max if unlimited > y_max else y_min if unlimited < y_min else unlimited

            if with_integral:
                rising_reset = bool(args["trigger"]) and not bool(state["previous_trigger"])
                if rising_reset:
                    state["integral"] = float(
                        block.config.get("y_reset", block.config.get("xi_start", 0.0))
                    ) - proportional_derivative
                else:
                    anti_windup = (unlimited - output) / (k * ni)
                    corrected_error = error - anti_windup
                    state["integral"] = integral + (k / ti) * corrected_error * (
                        0.0 if state["first_tick"] else step_seconds
                    )
                state["previous_trigger"] = bool(args["trigger"])
            if with_derivative:
                if state["first_tick"]:
                    derivative_state = (
                        error
                        if abs(derivative_gain) < 1e-15
                        else error
                        - derivative_time
                        * float(block.config.get("yd_start", 0.0))
                        / derivative_gain
                    )
                else:
                    derivative_state = float(state["derivative"])
                dt = 0.0 if state["first_tick"] else step_seconds
                ratio = dt / derivative_time
                state["derivative"] = (derivative_state + ratio * error) / (1.0 + ratio)
            state["first_tick"] = False
            return output
        raise ValueError(f"unsupported block kind: {kind}")

    def _trim_and_respond(
        self,
        block: Block,
        args: dict[str, float | bool],
        step_seconds: float,
    ) -> float:
        """Execute the source-bound G36 trim/respond recurrence, including hold."""

        config = block.config
        initial = float(config["initial_setpoint"])
        minimum = float(config["minimum_setpoint"])
        maximum = float(config["maximum_setpoint"])
        period = float(config["sample_period_seconds"])
        delay = float(config["delay_seconds"]) + period
        requests = self._number(args["request_count"])
        device_on = bool(args["device_on"])
        state = self.state.setdefault(
            block.id,
            {
                "delay_out": False,
                "delay_pending": False,
                "delay_elapsed": 0.0,
                "sampler_initialized": False,
                "sampler_held": 0.0,
                "sampler_t0": 0.0,
                "sampler_last_index": -1,
                "unit_initialized": False,
                "unit_held": initial,
                "unit_staged": initial,
                "unit_t0": 0.0,
                "unit_last_index": -1,
                "hold_initialized": False,
                "hold_out": False,
                "hold_elapsed": 0.0,
                "hold_latch": False,
                "sample_trigger_last_index": -1,
            },
        )

        hold_reset = False
        if bool(config.get("hold_enabled", False)):
            hold_input = bool(args["hold"])
            if not bool(state["hold_initialized"]):
                state["hold_initialized"] = True
                state["hold_out"] = hold_input
                state["hold_elapsed"] = 0.0
            else:
                state["hold_elapsed"] = float(state["hold_elapsed"]) + step_seconds
                if hold_input != bool(state["hold_out"]):
                    required = (
                        float(config["hold_duration_seconds"])
                        if bool(state["hold_out"])
                        else 0.0
                    )
                    if float(state["hold_elapsed"]) >= required:
                        state["hold_out"] = hold_input
                        state["hold_elapsed"] = 0.0
            trigger_index = math.floor(self.time / period + 1e-9)
            sample_trigger = trigger_index > int(state["sample_trigger_last_index"])
            if sample_trigger:
                state["sample_trigger_last_index"] = trigger_index
                # CDL.Logical.Latch is clear-dominant when both inputs are true.
                state["hold_latch"] = bool(state["hold_out"])
            hold_reset = bool(state["hold_latch"])

        if device_on == bool(state["delay_out"]):
            state["delay_elapsed"] = 0.0
            state["delay_pending"] = device_on
        elif device_on != bool(state["delay_pending"]):
            state["delay_pending"] = device_on
            state["delay_elapsed"] = 0.0
            if not device_on or delay <= 0.0:
                state["delay_out"] = device_on
        else:
            state["delay_elapsed"] = float(state["delay_elapsed"]) + step_seconds
            active_delay = delay if device_on else 0.0
            if float(state["delay_elapsed"]) >= active_delay:
                state["delay_out"] = device_on
                state["delay_elapsed"] = 0.0

        if not bool(state["sampler_initialized"]):
            sampler_t0 = round(math.floor(self.time / period) * period, 6)
            sample_index = math.floor((self.time - sampler_t0) / period + 1e-9)
            state["sampler_initialized"] = True
            state["sampler_t0"] = sampler_t0
            state["sampler_last_index"] = sample_index
            state["sampler_held"] = requests
        else:
            sample_index = math.floor(
                (self.time - float(state["sampler_t0"])) / period + 1e-9
            )
            if sample_index > int(state["sampler_last_index"]):
                state["sampler_last_index"] = sample_index
                state["sampler_held"] = requests
        sampled_requests = float(state["sampler_held"])

        unit_due = False
        if not bool(state["unit_initialized"]):
            unit_output = initial
        else:
            unit_index = math.floor(
                (self.time - float(state["unit_t0"])) / period + 1e-9
            )
            unit_due = unit_index > int(state["unit_last_index"])
            unit_output = float(
                state["unit_staged"] if unit_due else state["unit_held"]
            )

        request_delta = sampled_requests - float(config["ignored_requests"])
        respond_amount = float(config["respond_amount"])
        response = math.copysign(
            min(
                abs(respond_amount) * request_delta,
                abs(float(config["maximum_response"])),
            ),
            respond_amount,
        )
        if hold_reset:
            net_reset = 0.0
        elif not bool(state["delay_out"]):
            net_reset = 0.0
        elif request_delta > 0.0:
            net_reset = float(config["trim_amount"]) + response
        else:
            net_reset = float(config["trim_amount"])
        candidate = max(minimum, min(maximum, unit_output + net_reset))
        output = candidate if device_on else initial

        if not bool(state["unit_initialized"]):
            unit_t0 = round(math.floor(self.time / period) * period, 6)
            state["unit_initialized"] = True
            state["unit_t0"] = unit_t0
            state["unit_last_index"] = math.floor(
                (self.time - unit_t0) / period + 1e-9
            )
            state["unit_staged"] = output
        elif unit_due:
            state["unit_last_index"] = math.floor(
                (self.time - float(state["unit_t0"])) / period + 1e-9
            )
            state["unit_held"] = float(state["unit_staged"])
            state["unit_staged"] = output
        return output

    @staticmethod
    def _interpolate_integral(
        points: list[tuple[float, float]], target: float, now: float, mu_now: float
    ) -> float:
        if not points:
            return mu_now
        if target <= points[0][0]:
            return points[0][1]
        previous = points[0]
        for point in points[1:]:
            if target <= point[0]:
                span = point[0] - previous[0]
                if span == 0:
                    return point[1]
                return previous[1] + (point[1] - previous[1]) * ((target - previous[0]) / span)
            previous = point
        span = now - previous[0]
        if span == 0:
            return mu_now
        return previous[1] + (mu_now - previous[1]) * ((target - previous[0]) / span)

    def _update_unit_delay(self, block: Block, value: float) -> None:
        period = float(block.config["sample_period_seconds"])
        state = self.state.get(block.id)
        if state is None:
            t0 = round(math.floor(self.time / period) * period, 6)
            index = math.floor((self.time - t0) / period + 1e-9)
            initial = float(block.config.get("initial", 0.0))
            exact = math.isclose(self.time, t0 + index * period, abs_tol=1e-9)
            self.state[block.id] = {
                "held": initial,
                "staged": value if exact else initial,
                "t0": t0,
                "last_index": index,
            }
            return
        index = math.floor((self.time - float(state["t0"])) / period + 1e-9)
        if index > int(state["last_index"]):
            state["held"] = state["staged"]
            state["staged"] = value
            state["last_index"] = index


@dataclass(frozen=True)
class Scenario:
    name: str
    initial_temp: float
    occupied: bool
    ambient_temp: float
    steps: int = 30


class VavPlantSimulator:
    """Small closed-loop thermal model used before BOPTEST/Niagara testing.

    It is intentionally conservative and cannot establish product compliance;
    it catches wiring, sign, enable, clamping, and obvious response errors.
    """

    def __init__(self, graph: ControlGraph):
        self.controller = GraphInterpreter(graph)

    def run_scenario(
        self, scenario: Scenario
    ) -> tuple[list[dict[str, float | bool]], dict[str, float | bool]]:
        zone_temp = scenario.initial_temp
        samples: list[dict[str, float | bool]] = []
        output: dict[str, float | bool] = {}
        for minute in range(scenario.steps):
            output = self.controller.evaluate(
                {
                    "ZoneTemp": zone_temp,
                    "CoolingSetpoint": 74.0,
                    "HeatingSetpoint": 70.0,
                    "Occupied": scenario.occupied,
                }
            )
            damper = float(output["DamperCommand"])
            valve = float(output["ValveCommand"])
            envelope = (scenario.ambient_temp - zone_temp) * 0.012
            cooling = (damper / 100.0) * 0.18 if scenario.occupied else 0.0
            # Reheat must overcome the cold-deck airflow and the envelope in the
            # winter case. The coefficient represents discharge-air heat, not
            # a standalone room heater.
            heating = (valve / 100.0) * 0.58 if scenario.occupied else 0.0
            zone_temp += envelope - cooling + heating
            samples.append(
                {
                    "minute": float(minute),
                    "ZoneTemp": round(zone_temp, 3),
                    "DamperCommand": round(damper, 3),
                    "ValveCommand": round(valve, 3),
                    "CoolingDemand": round(float(output["CoolingDemand"]), 3),
                    "HeatingDemand": round(float(output["HeatingDemand"]), 3),
                }
            )
        return samples, output


def _assertion(name: str, passed: bool, observed: Any, expected: str) -> AssertionResult:
    return AssertionResult(name=name, passed=passed, observed=str(observed), expected=expected)


def _compare(
    observed: float | bool,
    operator: ComparisonOperator,
    expected: float | bool,
    upper: float | None,
    tolerance: float,
) -> bool:
    if isinstance(expected, bool):
        if operator == ComparisonOperator.EQUAL:
            return observed is expected
        if operator == ComparisonOperator.NOT_EQUAL:
            return observed is not expected
        return False
    if isinstance(observed, bool):
        return False
    actual = float(observed)
    target = float(expected)
    if operator == ComparisonOperator.EQUAL:
        return abs(actual - target) <= tolerance
    if operator == ComparisonOperator.NOT_EQUAL:
        return abs(actual - target) > tolerance
    if operator == ComparisonOperator.GREATER_THAN:
        return actual > target
    if operator == ComparisonOperator.GREATER_THAN_OR_EQUAL:
        return actual + tolerance >= target
    if operator == ComparisonOperator.LESS_THAN:
        return actual < target
    if operator == ComparisonOperator.LESS_THAN_OR_EQUAL:
        return actual - tolerance <= target
    if operator == ComparisonOperator.BETWEEN:
        if upper is None:
            return False
        return target - tolerance <= actual <= upper + tolerance
    raise ValueError(f"unsupported comparison operator: {operator}")


def _expected_text(expectation: OutputExpectation) -> str:
    if expectation.operator == ComparisonOperator.BETWEEN:
        return f"between {expectation.value} and {expectation.upper}"
    return f"{expectation.operator.value} {expectation.value} ± {expectation.tolerance}"


def _evaluate_expectations(
    label: str,
    expectations: list[OutputExpectation],
    values: dict[str, float | bool],
    block_ids: set[str],
) -> list[AssertionResult]:
    assertions: list[AssertionResult] = []
    for expectation in expectations:
        if expectation.target not in block_ids:
            raise ValueError(
                f"acceptance case {label!r} references unknown block {expectation.target!r}"
            )
        observed = values[expectation.target]
        assertions.append(
            _assertion(
                f"{label}: {expectation.target}",
                _compare(
                    observed,
                    expectation.operator,
                    expectation.value,
                    expectation.upper,
                    expectation.tolerance,
                ),
                observed,
                _expected_text(expectation),
            )
        )
    return assertions


def _fault_coverage(
    cases: list[AcceptanceCase],
    results: list[ScenarioResult],
) -> dict[str, Any]:
    declarations: list[dict[str, Any]] = []
    recovery_phases: list[str] = []
    for case in cases:
        if case.timeline:
            previous_had_fault = False
            for phase in case.timeline:
                if previous_had_fault and not phase.faults:
                    recovery_phases.append(f"{case.name} / {phase.name}")
                for fault in phase.faults:
                    declarations.append(
                        {
                            "case": case.name,
                            "phase": phase.name,
                            "id": fault.id,
                            "kind": fault.kind.value,
                            "target": fault.target,
                            "quality_target": fault.quality_target,
                        }
                    )
                previous_had_fault = bool(phase.faults)
        else:
            for fault in case.faults:
                declarations.append(
                    {
                        "case": case.name,
                        "phase": None,
                        "id": fault.id,
                        "kind": fault.kind.value,
                        "target": fault.target,
                        "quality_target": fault.quality_target,
                    }
                )
    fault_case_names = {item["case"] for item in declarations}
    scenario_status = {result.name: result.passed for result in results}
    return {
        "schema": "bactalk-fault-injection-coverage/v1",
        "activation_count": len(declarations),
        "fault_case_count": len(fault_case_names),
        "fault_cases_passed": sum(bool(scenario_status.get(name)) for name in fault_case_names),
        "kinds": sorted({str(item["kind"]) for item in declarations}),
        "targets": sorted({str(item["target"]) for item in declarations}),
        "quality_targets": sorted(
            {
                str(item["quality_target"])
                for item in declarations
                if item["quality_target"] is not None
            }
        ),
        "recovery_phases": recovery_phases,
        "declarations": declarations,
        "interpretation": (
            "Declared faults were injected into the signed acceptance trajectories."
            if declarations
            else "No fault behavior was exercised by this acceptance suite."
        ),
    }


def run_generic_acceptance_suite(graph: ControlGraph, cases: list[AcceptanceCase]) -> TestReport:
    block_ids = {block.id for block in graph.blocks}
    results: list[ScenarioResult] = []
    for case in cases:
        interpreter = GraphInterpreter(graph)
        fault_injector = FaultInjector(graph)
        samples: list[dict[str, float | bool]] = []
        values: dict[str, float | bool] = {}
        assertions: list[AssertionResult] = []
        if case.timeline:
            current_inputs: dict[str, float | bool] = {}
            scan = 0
            for phase_index, phase in enumerate(case.timeline, start=1):
                current_inputs.update(phase.inputs)
                primed_inputs, _ = fault_injector.apply(
                    current_inputs,
                    phase.faults,
                    step_seconds=0.0,
                )
                interpreter.evaluate(primed_inputs, step_seconds=0.0)
                for phase_step in range(1, phase.repeat + 1):
                    scan += 1
                    effective_inputs, fault_evidence = fault_injector.apply(
                        current_inputs,
                        phase.faults,
                        step_seconds=phase.step_seconds,
                    )
                    values = interpreter.evaluate(
                        effective_inputs,
                        step_seconds=phase.step_seconds,
                    )
                    samples.append(
                        {
                            "step": float(scan),
                            "phase": float(phase_index),
                            "phase_step": float(phase_step),
                            **current_inputs,
                            **fault_evidence,
                            **values,
                        }
                    )
                assertions.extend(
                    _evaluate_expectations(
                        f"{case.name} / {phase.name}",
                        phase.expectations,
                        values,
                        block_ids,
                    )
                )
        else:
            primed_inputs, _ = fault_injector.apply(
                case.inputs,
                case.faults,
                step_seconds=0.0,
            )
            interpreter.evaluate(primed_inputs, step_seconds=0.0)
            for index in range(case.repeat):
                effective_inputs, fault_evidence = fault_injector.apply(
                    case.inputs,
                    case.faults,
                    step_seconds=case.step_seconds,
                )
                values = interpreter.evaluate(
                    effective_inputs,
                    step_seconds=case.step_seconds,
                )
                samples.append(
                    {
                        "step": float(index + 1),
                        **case.inputs,
                        **fault_evidence,
                        **values,
                    }
                )
        assertions.extend(
            _evaluate_expectations(
                case.name,
                case.expectations,
                values,
                block_ids,
            )
        )
        results.append(
            ScenarioResult(
                name=case.name,
                passed=all(item.passed for item in assertions),
                assertions=assertions,
                samples=samples,
            )
        )
    coverage = _decision_coverage(graph, results)
    coverage["fault_injection"] = _fault_coverage(cases, results)
    return TestReport(
        passed=all(scenario.passed for scenario in results),
        scenarios=results,
        engine="BACTalk equipment-neutral stateful and fault-injection simulator (Tier 1)",
        coverage=coverage,
    )


_BOOLEAN_DECISION_KINDS = {
    BlockKind.GREATER_THAN,
    BlockKind.GREATER_THAN_OR_EQUAL,
    BlockKind.LESS_THAN,
    BlockKind.LESS_THAN_OR_EQUAL,
    BlockKind.EQUAL,
    BlockKind.NOT_EQUAL,
    BlockKind.AND,
    BlockKind.OR,
    BlockKind.XOR,
    BlockKind.NOT,
    BlockKind.BOOLEAN_DELAY,
    BlockKind.ONE_SHOT,
    BlockKind.NUMERIC_CHANGED,
    BlockKind.NUMERIC_INCREASED,
    BlockKind.NUMERIC_DECREASED,
}


def _decision_coverage(
    graph: ControlGraph,
    results: list[ScenarioResult],
) -> dict[str, Any]:
    """Report whether both outcomes of every binary decision were exercised."""

    samples = [sample for result in results for sample in result.samples]
    decisions: list[tuple[str, str]] = [
        (block.id, block.id) for block in graph.blocks if block.kind in _BOOLEAN_DECISION_KINDS
    ]
    for block in graph.blocks:
        if block.kind not in {BlockKind.NUMERIC_SWITCH, BlockKind.BOOLEAN_SWITCH}:
            continue
        selector = next(
            link.source
            for link in graph.links
            if link.target == block.id and link.target_slot == "selector"
        )
        decisions.append((f"{block.id}.selector", selector))

    entries: list[dict[str, Any]] = []
    observed_outcomes = 0
    for decision_id, sample_key in decisions:
        observed = sorted({bool(sample[sample_key]) for sample in samples if sample_key in sample})
        observed_outcomes += len(observed)
        entries.append(
            {
                "decision": decision_id,
                "observed": observed,
                "both_outcomes": len(observed) == 2,
            }
        )
    possible = len(entries) * 2
    percentage = 100.0 if possible == 0 else round(100 * observed_outcomes / possible, 1)
    gaps = [item["decision"] for item in entries if not item["both_outcomes"]]
    return {
        "schema": "bactalk-decision-coverage/v1",
        "decision_count": len(entries),
        "outcomes_observed": observed_outcomes,
        "outcomes_possible": possible,
        "percent": percentage,
        "fully_covered": not gaps,
        "gaps": gaps,
        "decisions": entries,
        "interpretation": (
            "Both true and false outcomes were exercised for every typed decision."
            if not gaps
            else "Passing assertions leave one or more typed decision outcomes unexercised."
        ),
    }


def run_acceptance_suite(graph: ControlGraph, job: JobSpec | None = None) -> TestReport:
    if job is not None:
        from bactalk.validation import validate_job_graph_contract

        validate_job_graph_contract(job, graph)
    if job is not None and job.acceptance_tests:
        return run_generic_acceptance_suite(graph, job.acceptance_tests)
    if graph.metadata.get("sequence_family") != "G36_VAV_REHEAT":
        raise ValueError(
            "custom control graphs require acceptance_tests; "
            "the agent is not allowed to grade its own work without an oracle"
        )
    interpreter = GraphInterpreter(graph)
    plant = VavPlantSimulator(graph)
    results: list[ScenarioResult] = []
    parameters = graph.metadata.get("parameters", {})
    minimum_damper = float(parameters.get("minimum_damper_pct", 20.0))
    high_temp_limit = float(parameters.get("high_zone_temp_f", 80.0))

    cooling_samples, cooling_final = plant.run_scenario(
        Scenario("occupied cooling response", 78.0, True, 85.0)
    )
    cooling_assertions = [
        _assertion(
            "zone moves toward cooling setpoint",
            float(cooling_samples[-1]["ZoneTemp"]) < 78.0,
            cooling_samples[-1]["ZoneTemp"],
            "< 78.0 °F",
        ),
        _assertion(
            "occupied damper minimum is maintained",
            min(float(sample["DamperCommand"]) for sample in cooling_samples) >= minimum_damper,
            min(float(sample["DamperCommand"]) for sample in cooling_samples),
            f">= {minimum_damper}%",
        ),
        _assertion(
            "cooling command remains bounded",
            0.0 <= float(cooling_final["CoolingDemand"]) <= 100.0,
            cooling_final["CoolingDemand"],
            "0..100%",
        ),
        _assertion(
            "cooling demand responds above setpoint",
            max(float(sample["CoolingDemand"]) for sample in cooling_samples) > 0.0,
            max(float(sample["CoolingDemand"]) for sample in cooling_samples),
            "> 0%",
        ),
        _assertion(
            "heating remains off during cooling",
            max(float(sample["HeatingDemand"]) for sample in cooling_samples) == 0.0,
            max(float(sample["HeatingDemand"]) for sample in cooling_samples),
            "0%",
        ),
    ]
    results.append(
        ScenarioResult(
            name="occupied cooling response",
            passed=all(item.passed for item in cooling_assertions),
            assertions=cooling_assertions,
            samples=cooling_samples,
        )
    )

    heating_samples, heating_final = plant.run_scenario(
        Scenario("occupied heating response", 65.0, True, 35.0)
    )
    heating_assertions = [
        _assertion(
            "zone moves toward heating setpoint",
            float(heating_samples[-1]["ZoneTemp"]) > 65.0,
            heating_samples[-1]["ZoneTemp"],
            "> 65.0 °F",
        ),
        _assertion(
            "heating command remains bounded",
            0.0 <= float(heating_final["HeatingDemand"]) <= 100.0,
            heating_final["HeatingDemand"],
            "0..100%",
        ),
        _assertion(
            "cooling remains off during heating",
            max(float(sample["CoolingDemand"]) for sample in heating_samples) == 0.0,
            max(float(sample["CoolingDemand"]) for sample in heating_samples),
            "0%",
        ),
    ]
    results.append(
        ScenarioResult(
            name="occupied heating response",
            passed=all(item.passed for item in heating_assertions),
            assertions=heating_assertions,
            samples=heating_samples,
        )
    )

    unoccupied = interpreter.evaluate(
        {
            "ZoneTemp": 82.0,
            "CoolingSetpoint": 74.0,
            "HeatingSetpoint": 70.0,
            "Occupied": False,
        }
    )
    unoccupied_assertions = [
        _assertion(
            "damper is disabled",
            unoccupied["DamperCommand"] == 0.0,
            unoccupied["DamperCommand"],
            "0%",
        ),
        _assertion(
            "reheat is disabled",
            unoccupied["ValveCommand"] == 0.0,
            unoccupied["ValveCommand"],
            "0%",
        ),
        _assertion(
            "alarm is occupancy-gated",
            unoccupied["HighZoneTempAlarm"] is False,
            unoccupied["HighZoneTempAlarm"],
            "false",
        ),
    ]
    results.append(
        ScenarioResult(
            name="unoccupied shutdown",
            passed=all(item.passed for item in unoccupied_assertions),
            assertions=unoccupied_assertions,
            samples=[],
        )
    )

    alarm = interpreter.evaluate(
        {
            "ZoneTemp": max(82.0, high_temp_limit + 2.0),
            "CoolingSetpoint": 74.0,
            "HeatingSetpoint": 70.0,
            "Occupied": True,
        }
    )
    alarm_assertions = [
        _assertion(
            "high temperature alarm activates",
            alarm["HighZoneTempAlarm"] is True,
            alarm["HighZoneTempAlarm"],
            "true",
        ),
        _assertion(
            "cooling saturates", alarm["CoolingDemand"] == 100.0, alarm["CoolingDemand"], "100%"
        ),
    ]
    results.append(
        ScenarioResult(
            name="occupied high temperature alarm",
            passed=all(item.passed for item in alarm_assertions),
            assertions=alarm_assertions,
            samples=[],
        )
    )

    deadband = interpreter.evaluate(
        {
            "ZoneTemp": 72.0,
            "CoolingSetpoint": 74.0,
            "HeatingSetpoint": 70.0,
            "Occupied": True,
        }
    )
    deadband_assertions = [
        _assertion(
            "cooling is zero in deadband",
            deadband["CoolingDemand"] == 0.0,
            deadband["CoolingDemand"],
            "0%",
        ),
        _assertion(
            "heating is zero in deadband",
            deadband["HeatingDemand"] == 0.0,
            deadband["HeatingDemand"],
            "0%",
        ),
        _assertion(
            "occupied minimum is maintained in deadband",
            deadband["DamperCommand"] == minimum_damper,
            deadband["DamperCommand"],
            f"{minimum_damper}%",
        ),
        _assertion(
            "high temperature alarm remains clear below limit",
            deadband["HighZoneTempAlarm"] is False,
            deadband["HighZoneTempAlarm"],
            "false",
        ),
    ]
    results.append(
        ScenarioResult(
            name="occupied deadband and false-alarm check",
            passed=all(item.passed for item in deadband_assertions),
            assertions=deadband_assertions,
            samples=[],
        )
    )

    return TestReport(
        passed=all(scenario.passed for scenario in results),
        scenarios=results,
        engine="BACTalk deterministic VAV plant simulator (Tier 1)",
    )
