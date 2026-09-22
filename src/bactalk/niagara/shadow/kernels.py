"""Python ports of the ``bactalkG36`` Java kernels (docs/decisions/007).

The Java sources under ``niagara-module/bactalkG36/bactalkG36-rt/src/com/bactalk/
g36/kernel`` are the module's truth. Each class here mirrors one of them field
for field and operation for operation, so the two implementations produce the
same doubles on the same rows; ``tests/test_native_bog_shadow_kernels.py`` runs
both against the goldens and, when a JVM is present, against each other.

The ports keep Java's argument checks (finite inputs, monotonic time) so a
mistake in the runtime fails the same way in both backends.
"""

from __future__ import annotations

import math
from typing import Protocol

from bactalk.psychrometrics import wet_bulb

_MIN_WINDOW_SECONDS = 1.0e-5


def _finite(*values: float) -> bool:
    return all(math.isfinite(value) for value in values)


class Kernel(Protocol):
    """One kernel; ``step`` takes the absolute time then the inputs, in harness order."""

    def reset(self) -> None: ...

    def step(self, *args: float | bool) -> tuple[float | bool, ...]: ...


class PidWithReset:
    """State commits only when time advances, so several executions at one instant
    (an input change and the period tick) see the previous instant's state and the
    last one wins."""

    def __init__(
        self,
        controller_type: str,
        reverse_acting: bool,
        k: float,
        ti: float,
        td: float,
        r: float,
        ni: float,
        nd: float,
        y_min: float,
        y_max: float,
        xi_start: float,
        yd_start: float,
        y_reset: float,
    ) -> None:
        kind = controller_type.upper()
        if kind not in {"P", "PI", "PD", "PID"}:
            raise ValueError(f"unknown controller type {controller_type!r}")
        self.with_integral = kind in {"PI", "PID"}
        self.with_derivative = kind in {"PD", "PID"}
        self.reverse_acting = reverse_acting
        self.k = k
        self.ti = ti
        self.td = td
        self.r = r
        self.ni = ni
        self.nd = nd
        self.y_min = y_min
        self.y_max = y_max
        self.xi_start = xi_start
        self.yd_start = yd_start
        self.y_reset = y_reset
        self.reset()

    def reset(self) -> None:
        self.base_integral = self.xi_start
        self.base_derivative = 0.0
        self.base_previous_trigger = False
        self.base_time = math.nan
        self.pending_integral = self.xi_start
        self.pending_derivative = 0.0
        self.pending_previous_trigger = False
        self.last_time = math.nan
        self.first_instant = math.nan

    def step(
        self, time_seconds: float, setpoint: float, measurement: float, trigger: bool
    ) -> tuple[float]:
        if not _finite(time_seconds, setpoint, measurement):
            raise ValueError("PIDWithReset inputs must be finite")
        first_tick = math.isnan(self.last_time)
        if not first_tick and time_seconds < self.last_time:
            raise ValueError("PIDWithReset time must be monotonic")
        if first_tick:
            self.base_time = time_seconds
        elif time_seconds > self.last_time:
            self.base_integral = self.pending_integral
            self.base_derivative = self.pending_derivative
            self.base_previous_trigger = self.pending_previous_trigger
            self.base_time = self.last_time
        initial = first_tick or math.isnan(self.base_time)
        dt = time_seconds - self.base_time
        at_start = first_tick or (
            time_seconds == self.base_time
            and not math.isnan(self.first_instant)
            and time_seconds == self.first_instant
        )
        reverse_sign = 1.0 if self.reverse_acting else -1.0
        error = reverse_sign * (setpoint - measurement) / self.r
        proportional = self.k * error
        derivative_gain = self.k * self.td
        derivative_time = self.td / self.nd
        if self.with_derivative:
            derivative = (
                self.yd_start
                if at_start
                else (derivative_gain / derivative_time) * (error - self.base_derivative)
            )
        else:
            derivative = 0.0
        integral_output = self.base_integral if self.with_integral else 0.0
        proportional_derivative = proportional + derivative
        unlimited = proportional_derivative + integral_output
        output = (
            self.y_max
            if unlimited > self.y_max
            else (self.y_min if unlimited < self.y_min else unlimited)
        )
        if self.with_integral:
            rising_reset = trigger and not self.base_previous_trigger
            if rising_reset:
                self.pending_integral = self.y_reset - proportional_derivative
            else:
                anti_windup = (unlimited - output) / (self.k * self.ni)
                corrected_error = error - anti_windup
                self.pending_integral = integral_output + (self.k / self.ti) * corrected_error * dt
            self.pending_previous_trigger = trigger
        if self.with_derivative:
            if at_start:
                initial_state = (
                    error
                    if abs(derivative_gain) < 1.0e-15
                    else error - derivative_time * self.yd_start / derivative_gain
                )
            else:
                initial_state = self.base_derivative
            ratio = dt / derivative_time
            self.pending_derivative = (initial_state + ratio * error) / (1.0 + ratio)
        if not initial and not self.with_derivative:
            self.pending_derivative = self.base_derivative
        if first_tick:
            self.first_instant = time_seconds
        self.last_time = time_seconds
        return (output,)


class TrueDelay:
    def __init__(self, delay_seconds: float, delay_on_init: bool) -> None:
        if delay_seconds < 0.0:
            raise ValueError("TrueDelay delay must be non-negative")
        self.delay_seconds = delay_seconds
        self.delay_on_init = delay_on_init
        self.reset()

    def reset(self) -> None:
        self.initialized = False
        self.previous_input = False
        self.held = False
        self.timer = 0.0
        self.previous_time = math.nan

    def step(self, time_seconds: float, value: bool) -> tuple[bool]:
        if not math.isfinite(time_seconds):
            raise ValueError("TrueDelay time must be finite")
        if not math.isnan(self.previous_time) and time_seconds < self.previous_time:
            raise ValueError("TrueDelay time must be monotonic")
        if not value:
            output = False
            next_timer = 0.0
        elif not self.initialized:
            if self.delay_on_init and self.delay_seconds > 0.0:
                output = False
                next_timer = 0.0
            else:
                output = True
                next_timer = self.delay_seconds
        elif self.held:
            output = True
            next_timer = self.delay_seconds
        elif not self.previous_input:
            output = self.delay_seconds <= 0.0
            next_timer = 0.0
        else:
            next_timer = self.timer + time_seconds - self.previous_time
            output = next_timer >= self.delay_seconds
        self.initialized = True
        self.previous_input = value
        self.held = output
        self.timer = next_timer
        self.previous_time = time_seconds
        return (output,)


class Timer:
    def __init__(self, threshold_seconds: float) -> None:
        self.threshold_seconds = threshold_seconds
        self.reset()

    def reset(self) -> None:
        self.initialized = False
        self.entry_time = 0.0
        self.previous_time = math.nan
        self.previous_input = False
        self.passed = self.threshold_seconds <= 0.0
        self.elapsed_output = 0.0
        self.passed_output = self.threshold_seconds <= 0.0

    def step(self, time_seconds: float, value: bool) -> tuple[float, bool]:
        if not math.isfinite(time_seconds):
            raise ValueError("Timer time must be finite")
        if not math.isnan(self.previous_time) and time_seconds < self.previous_time:
            raise ValueError("Timer time must be monotonic")
        if not value or not self.initialized or not self.previous_input:
            elapsed = 0.0
        else:
            elapsed = time_seconds - self.entry_time
        if value and not self.previous_input:
            next_passed = self.threshold_seconds <= 0.0
        elif value and elapsed >= self.threshold_seconds:
            next_passed = True
        elif not value and self.previous_input:
            next_passed = False
        else:
            next_passed = self.passed
        if value and (not self.initialized or not self.previous_input):
            self.entry_time = time_seconds
        self.initialized = True
        self.previous_time = time_seconds
        self.previous_input = value
        self.passed = next_passed
        self.elapsed_output = elapsed
        self.passed_output = next_passed
        return (elapsed, next_passed)


class TimerWithReset:
    def __init__(self, threshold_seconds: float) -> None:
        self.threshold_seconds = threshold_seconds
        self.reset()

    def reset(self) -> None:
        self.initialized = False
        self.entry_time = 0.0
        self.previous_time = math.nan
        self.previous_input = False
        self.previous_reset = False
        self.elapsed_output = 0.0
        self.passed_output = False

    def step(self, time_seconds: float, value: bool, reset_input: bool) -> tuple[float, bool]:
        if not math.isfinite(time_seconds):
            raise ValueError("TimerWithReset time must be finite")
        if not math.isnan(self.previous_time) and time_seconds < self.previous_time:
            raise ValueError("TimerWithReset time must be monotonic")
        if not self.initialized:
            self.entry_time = time_seconds
            self.elapsed_output = 0.0
            self.passed_output = value and self.threshold_seconds <= 0.0
            self.initialized = True
        else:
            rising_input = value and not self.previous_input
            rising_reset = reset_input and not self.previous_reset
            if rising_input or rising_reset:
                self.entry_time = time_seconds
                self.passed_output = value and self.threshold_seconds <= 0.0
            elif value and time_seconds >= self.entry_time + self.threshold_seconds:
                self.passed_output = True
            elif not value and self.previous_input:
                self.passed_output = False
            self.elapsed_output = time_seconds - self.entry_time if value else 0.0
        self.previous_time = time_seconds
        self.previous_input = value
        self.previous_reset = reset_input
        return (self.elapsed_output, self.passed_output)


class TimerAccumulating:
    def __init__(self, threshold_seconds: float) -> None:
        self.threshold_seconds = threshold_seconds
        self.reset()

    def reset(self) -> None:
        self.initialized = False
        self.previous_time = math.nan
        self.previous_input = False
        self.previous_reset = False
        self.elapsed_output = 0.0
        self.passed_output = self.threshold_seconds <= 0.0

    def step(self, time_seconds: float, value: bool, reset_input: bool) -> tuple[float, bool]:
        if not math.isfinite(time_seconds):
            raise ValueError("TimerAccumulating time must be finite")
        if not math.isnan(self.previous_time) and time_seconds < self.previous_time:
            raise ValueError("TimerAccumulating time must be monotonic")
        if not self.initialized:
            self.initialized = True
        elif reset_input and not self.previous_reset:
            self.elapsed_output = 0.0
            self.passed_output = self.threshold_seconds <= 0.0
        else:
            if self.previous_input:
                self.elapsed_output += time_seconds - self.previous_time
            if value and self.elapsed_output >= self.threshold_seconds:
                self.passed_output = True
        self.previous_time = time_seconds
        self.previous_input = value
        self.previous_reset = reset_input
        return (self.elapsed_output, self.passed_output)


class TrueFalseHold:
    def __init__(self, true_hold_seconds: float, false_hold_seconds: float) -> None:
        self.true_hold_seconds = true_hold_seconds
        self.false_hold_seconds = false_hold_seconds
        self.reset()

    def reset(self) -> None:
        self.initialized = False
        self.held = False
        self.elapsed = 0.0
        self.previous_time = math.nan

    def step(self, time_seconds: float, value: bool) -> tuple[bool]:
        if not math.isfinite(time_seconds):
            raise ValueError("TrueFalseHold time must be finite")
        if not math.isnan(self.previous_time) and time_seconds < self.previous_time:
            raise ValueError("TrueFalseHold time must be monotonic")
        if not self.initialized:
            self.initialized = True
            self.held = value
            self.elapsed = 0.0
            self.previous_time = time_seconds
            return (self.held,)
        self.elapsed += time_seconds - self.previous_time
        self.previous_time = time_seconds
        if value != self.held:
            required = max(0.0, self.true_hold_seconds if self.held else self.false_hold_seconds)
            if self.elapsed >= required:
                self.held = value
                self.elapsed = 0.0
        return (self.held,)


class Pre:
    def __init__(self, initial: bool) -> None:
        self.initial = initial
        self.previous = initial

    def reset(self) -> None:
        self.previous = self.initial

    def step(self, time_seconds: float, current: bool) -> tuple[bool]:
        output = self.previous
        self.previous = current
        return (output,)


class UnitDelay:
    def __init__(self, sample_period_seconds: float, initial: float) -> None:
        if not sample_period_seconds > 0.0:
            raise ValueError("UnitDelay period must be positive")
        self.sample_period_seconds = sample_period_seconds
        self.initial = initial
        self.reset()

    def reset(self) -> None:
        self.initialized = False
        self.held = self.initial
        self.staged = self.initial
        self.t0 = 0.0
        self.last_index = 0
        self.previous_time = math.nan

    def step(self, time_seconds: float, value: float) -> tuple[float]:
        if not _finite(time_seconds, value):
            raise ValueError("UnitDelay inputs must be finite")
        if not math.isnan(self.previous_time) and time_seconds < self.previous_time:
            raise ValueError("UnitDelay time must be monotonic")
        period = self.sample_period_seconds
        if not self.initialized:
            self.t0 = math.floor(time_seconds / period) * period
            self.last_index = int(math.floor((time_seconds - self.t0) / period + 1.0e-9))
            boundary = self.t0 + self.last_index * period
            self.staged = value if abs(time_seconds - boundary) <= 1.0e-9 else self.initial
            self.initialized = True
            self.previous_time = time_seconds
            return (self.initial,)
        index = int(math.floor((time_seconds - self.t0) / period + 1.0e-9))
        if index > self.last_index:
            self.held = self.staged
            self.staged = value
            self.last_index = index
        elif abs(time_seconds - (self.t0 + self.last_index * period)) <= 1.0e-9:
            self.staged = value  # still at the sample instant: the last input wins
        self.previous_time = time_seconds
        return (self.held,)


class FirstOrderHold:
    def __init__(self, sample_period_seconds: float) -> None:
        if not sample_period_seconds > 0.0:
            raise ValueError("FirstOrderHold period must be positive")
        self.sample_period_seconds = sample_period_seconds
        self.reset()

    def reset(self) -> None:
        self.initialized = False
        self.t0 = 0.0
        self.last_index = 0
        self.t_sample = 0.0
        self.u_sample = 0.0
        self.pre_u_sample = 0.0
        self.slope = 0.0
        self.previous_time = math.nan

    def step(self, time_seconds: float, value: float) -> tuple[float]:
        if not _finite(time_seconds, value):
            raise ValueError("FirstOrderHold inputs must be finite")
        if not math.isnan(self.previous_time) and time_seconds < self.previous_time:
            raise ValueError("FirstOrderHold time must be monotonic")
        period = self.sample_period_seconds
        if not self.initialized:
            # Java: Math.rint(Math.floor(t / p) * p * 1e6) / 1e6
            self.t0 = _rint(math.floor(time_seconds / period) * period * 1.0e6) / 1.0e6
            self.last_index = int(math.floor((time_seconds - self.t0) / period + 1.0e-9))
            self.t_sample = self.t0
            self.u_sample = value
            self.pre_u_sample = value
            self.slope = 0.0
            self.initialized = True
            self.previous_time = time_seconds
            return (value,)
        index = int(math.floor((time_seconds - self.t0) / period + 1.0e-9))
        due = index > self.last_index
        same_instant = (not due) and abs(time_seconds - self.t_sample) <= 1.0e-9
        output = (
            self.u_sample
            if due
            else self.pre_u_sample + self.slope * (time_seconds - self.t_sample)
        )
        if due:
            previous = self.u_sample
            self.last_index = index
            self.t_sample = time_seconds
            self.u_sample = value
            self.pre_u_sample = previous
            self.slope = (
                0.0 if time_seconds <= self.t0 + period / 2.0 else (value - previous) / period
            )
        elif same_instant:
            self.u_sample = value
            self.slope = (
                0.0
                if time_seconds <= self.t0 + period / 2.0
                else (value - self.pre_u_sample) / period
            )
        self.previous_time = time_seconds
        return (output,)


def _rint(value: float) -> float:
    """Java ``Math.rint``: round half to even."""

    return float(round(value))


class MovingAverage:
    """Checkpoints of the running integral are kept for the whole window (no ring cap)."""

    def __init__(self, window_seconds: float, checkpoint_capacity: int = 64) -> None:
        if checkpoint_capacity < 2:
            raise ValueError("MovingAverage needs at least two checkpoints")
        self.window_seconds = window_seconds
        self.reset()

    def reset(self) -> None:
        self.mu = 0.0
        self.start_time = 0.0
        self.previous_time = math.nan
        self.times: list[float] = []
        self.mus: list[float] = []

    def _prune(self, cutoff: float) -> None:
        while len(self.times) > 1 and self.times[1] <= cutoff:
            self.times.pop(0)
            self.mus.pop(0)

    def _store(self, time_seconds: float, mu_now: float) -> None:
        if self.times and self.times[-1] == time_seconds:
            self.mus[-1] = mu_now
            return
        self.times.append(time_seconds)
        self.mus.append(mu_now)

    def _mu_at(self, target: float, time_seconds: float, mu_now: float) -> float:
        if not self.times:
            return mu_now
        first_time = self.times[0]
        first_mu = self.mus[0]
        if target <= first_time:
            return first_mu
        previous_time = first_time
        previous_mu = first_mu
        for next_time, next_mu in zip(self.times[1:], self.mus[1:], strict=True):
            if target <= next_time:
                denominator = next_time - previous_time
                return (
                    next_mu
                    if denominator == 0.0
                    else previous_mu
                    + (next_mu - previous_mu) * ((target - previous_time) / denominator)
                )
            previous_time = next_time
            previous_mu = next_mu
        if target <= time_seconds:
            denominator = time_seconds - previous_time
            return (
                mu_now
                if denominator == 0.0
                else previous_mu + (mu_now - previous_mu) * ((target - previous_time) / denominator)
            )
        return mu_now

    def step(self, time_seconds: float, value: float) -> tuple[float]:
        if not _finite(time_seconds, value):
            raise ValueError("MovingAverage inputs must be finite")
        first_tick = math.isnan(self.previous_time)
        if not first_tick and time_seconds < self.previous_time:
            raise ValueError("MovingAverage time must be monotonic")
        delta = max(self.window_seconds, _MIN_WINDOW_SECONDS)
        start = time_seconds if first_tick else self.start_time
        dt = 0.0 if first_tick else time_seconds - self.previous_time
        mu_now = self.mu + value * dt
        target = time_seconds - delta
        delayed_mu = self._mu_at(target, time_seconds, mu_now)
        if time_seconds >= start + delta:
            retained_low = self.times[0] if self.times else start
            low = max(max(target, retained_low), start)
            denominator = max(time_seconds - low, _MIN_WINDOW_SECONDS)
        else:
            denominator = time_seconds - start + 1.0e-3
        output = (mu_now - delayed_mu) / denominator
        if first_tick:
            self.start_time = time_seconds
        self._prune(target)
        self._store(time_seconds, mu_now)
        self.mu = mu_now
        self.previous_time = time_seconds
        return (output,)


class TrimAndRespond:
    def __init__(
        self,
        initial_setpoint: float,
        minimum_setpoint: float,
        maximum_setpoint: float,
        delay_seconds: float,
        sample_period_seconds: float,
        ignored_requests: float,
        trim_amount: float,
        respond_amount: float,
        maximum_response: float,
        hold_enabled: bool = False,
        hold_duration_seconds: float = 0.0,
    ) -> None:
        if not sample_period_seconds > 0.0:
            raise ValueError("TrimAndRespond sample period must be positive")
        self.initial_setpoint = initial_setpoint
        self.minimum_setpoint = minimum_setpoint
        self.maximum_setpoint = maximum_setpoint
        self.delay_seconds = delay_seconds
        self.sample_period_seconds = sample_period_seconds
        self.ignored_requests = ignored_requests
        self.trim_amount = trim_amount
        self.respond_amount = respond_amount
        self.maximum_response = maximum_response
        self.hold_enabled = hold_enabled
        self.hold_duration_seconds = hold_duration_seconds
        self.reset()

    def reset(self) -> None:
        self.delay_out = False
        self.delay_pending = False
        self.delay_elapsed = 0.0
        self.sampler_initialized = False
        self.sampler_held = 0.0
        self.sampler_t0 = 0.0
        self.sampler_last_index = -1
        self.unit_initialized = False
        self.unit_held = self.initial_setpoint
        self.unit_staged = self.initial_setpoint
        self.unit_t0 = 0.0
        self.unit_last_index = -1
        self.previous_time = math.nan
        self.hold_initialized = False
        self.hold_out = False
        self.hold_elapsed = 0.0
        self.hold_latch = False
        self.sample_trigger_last_index = -1

    def step(
        self, time_seconds: float, request_count: float, device_on: bool, hold: bool = False
    ) -> tuple[float]:
        if not _finite(time_seconds, request_count):
            raise ValueError("TrimAndRespond inputs must be finite")
        first_tick = math.isnan(self.previous_time)
        if not first_tick and time_seconds < self.previous_time:
            raise ValueError("TrimAndRespond time must be monotonic")
        dt = 0.0 if first_tick else time_seconds - self.previous_time
        period = self.sample_period_seconds
        true_delay = self.delay_seconds + period
        hold_reset = False
        if self.hold_enabled:
            if not self.hold_initialized:
                self.hold_initialized = True
                self.hold_out = hold
                self.hold_elapsed = 0.0
            else:
                self.hold_elapsed += dt
                if hold != self.hold_out:
                    required_hold = self.hold_duration_seconds if self.hold_out else 0.0
                    if self.hold_elapsed >= required_hold:
                        self.hold_out = hold
                        self.hold_elapsed = 0.0
            trigger_index = int(math.floor(time_seconds / period + 1.0e-9))
            if trigger_index > self.sample_trigger_last_index:
                self.sample_trigger_last_index = trigger_index
                self.hold_latch = self.hold_out
            hold_reset = self.hold_latch

        if device_on == self.delay_out:
            self.delay_elapsed = 0.0
            self.delay_pending = device_on
        elif device_on != self.delay_pending:
            self.delay_pending = device_on
            self.delay_elapsed = 0.0
            if not device_on or true_delay <= 0.0:
                self.delay_out = device_on
        else:
            self.delay_elapsed += dt
            active_delay = true_delay if device_on else 0.0
            if self.delay_elapsed >= active_delay:
                self.delay_out = device_on
                self.delay_elapsed = 0.0

        if not self.sampler_initialized:
            self.sampler_t0 = math.floor(time_seconds / period) * period
            self.sampler_last_index = int(
                math.floor((time_seconds - self.sampler_t0) / period + 1.0e-9)
            )
            self.sampler_initialized = True
            self.sampler_held = request_count
        else:
            sample_index = int(math.floor((time_seconds - self.sampler_t0) / period + 1.0e-9))
            if sample_index > self.sampler_last_index:
                self.sampler_last_index = sample_index
                self.sampler_held = request_count
            elif abs(time_seconds - (self.sampler_t0 + self.sampler_last_index * period)) <= 1.0e-9:
                self.sampler_held = request_count  # still at the sample instant: last input wins

        unit_due = False
        if not self.unit_initialized:
            unit_output = self.initial_setpoint
        else:
            unit_index = int(math.floor((time_seconds - self.unit_t0) / period + 1.0e-9))
            unit_due = unit_index > self.unit_last_index
            unit_output = self.unit_staged if unit_due else self.unit_held

        request_delta = self.sampler_held - self.ignored_requests
        response = math.copysign(
            min(abs(self.respond_amount) * request_delta, abs(self.maximum_response)),
            self.respond_amount,
        )
        if hold_reset:
            net_reset = 0.0
        elif not self.delay_out:
            net_reset = 0.0
        elif request_delta > 0.0:
            net_reset = self.trim_amount + response
        else:
            net_reset = self.trim_amount
        candidate = max(self.minimum_setpoint, min(self.maximum_setpoint, unit_output + net_reset))
        output = candidate if device_on else self.initial_setpoint

        if not self.unit_initialized:
            self.unit_t0 = math.floor(time_seconds / period) * period
            self.unit_initialized = True
            self.unit_last_index = int(math.floor((time_seconds - self.unit_t0) / period + 1.0e-9))
            self.unit_staged = output
        elif unit_due:
            self.unit_last_index = int(math.floor((time_seconds - self.unit_t0) / period + 1.0e-9))
            self.unit_held = self.unit_staged
            self.unit_staged = output
        elif abs(time_seconds - (self.unit_t0 + self.unit_last_index * period)) <= 1.0e-9:
            self.unit_staged = output  # still at the sample instant: the last execution wins
        self.previous_time = time_seconds
        return (output,)


class BooleanInitialization:
    def __init__(self, initial: bool) -> None:
        self.initial = initial
        self.first = True

    def reset(self) -> None:
        self.first = True

    def step(self, time_seconds: float, value: bool) -> tuple[bool]:
        if self.first:
            self.first = False
            return (self.initial,)
        return (value,)


class NumericChange:
    def __init__(self, mode: str, initial: float) -> None:
        key = mode.upper()
        if key not in {"CHANGED", "INCREASED", "DECREASED"}:
            raise ValueError(f"unknown change mode {mode!r}")
        self.mode = key
        self.initial = initial
        self.previous = initial

    def reset(self) -> None:
        self.previous = self.initial

    def step(self, time_seconds: float, current: float) -> tuple[bool]:
        if not math.isfinite(current):
            raise ValueError("change-detector input must be finite")
        if self.mode == "INCREASED":
            result = current > self.previous
        elif self.mode == "DECREASED":
            result = current < self.previous
        else:
            result = current != self.previous
        self.previous = current
        return (result,)


class Round:
    """``numeric_round``: CDL RealToInteger, round half away from zero. Stateless."""

    def reset(self) -> None:
        return None

    def step(self, time_seconds: float, value: float) -> tuple[float]:
        if not _finite(time_seconds, value):
            raise ValueError("Round inputs must be finite")
        rounded = math.floor(value + 0.5) if value > 0.0 else math.ceil(value - 0.5)
        return (float(rounded),)


class IntegratorWithReset:
    """``numeric_integrator_with_reset``: CDL.Reals.IntegratorWithReset as the reference
    engine discretises it. A step returns the state the previous instant left, then takes
    a forward-Euler step of ``gain * input`` over the time since the previous instant (none
    on the first) or loads the reset value on a rising trigger. A second step at the same
    instant recomputes from that instant's inputs, so a resample never integrates twice."""

    def __init__(self, gain: float, initial: float) -> None:
        if not _finite(gain, initial):
            raise ValueError("IntegratorWithReset needs finite gain and start")
        self.gain = gain
        self.initial = initial
        self.reset()

    def reset(self) -> None:
        self.state = self.initial
        self.previous_time = math.nan
        self.previous_trigger = False
        self.instant = math.nan
        self.instant_state = self.initial
        self.instant_previous_time = math.nan
        self.instant_previous_trigger = False

    def step(
        self, time_seconds: float, value: float, reset_value: float, trigger: bool
    ) -> tuple[float]:
        if time_seconds != self.instant:
            self.instant = time_seconds
            self.instant_state = self.state
            self.instant_previous_time = self.previous_time
            self.instant_previous_trigger = self.previous_trigger
        dt = (
            0.0
            if math.isnan(self.instant_previous_time)
            else time_seconds - self.instant_previous_time
        )
        if trigger and not self.instant_previous_trigger:
            self.state = reset_value
        else:
            self.state = self.instant_state + self.gain * value * dt
        self.previous_time = time_seconds
        self.previous_trigger = trigger
        return (self.instant_state,)


class OnCounter:
    """``numeric_on_counter``: CDL.Integers.OnCounter as the reference engine discretises
    it. A step returns the count the previous instant left; the first instant only records
    the inputs, later ones add one on a rising trigger and return to the start on a rising
    reset (reset wins). A second step at the same instant recomputes from its inputs."""

    def __init__(self, initial: float) -> None:
        if not _finite(initial) or initial != round(initial):
            raise ValueError("OnCounter needs an integer start value")
        self.initial = float(initial)
        self.reset()

    def reset(self) -> None:
        self.count = self.initial
        self.previous_trigger = False
        self.previous_reset = False
        self.history = False
        self.instant = math.nan
        self.instant_count = self.initial
        self.instant_trigger = False
        self.instant_reset = False
        self.instant_history = False

    def step(self, time_seconds: float, trigger: bool, reset_input: bool) -> tuple[float]:
        if time_seconds != self.instant:
            self.instant = time_seconds
            self.instant_count = self.count
            self.instant_trigger = self.previous_trigger
            self.instant_reset = self.previous_reset
            self.instant_history = self.history
        self.count = self.instant_count
        if self.instant_history and (
            (trigger and not self.instant_trigger) or (reset_input and not self.instant_reset)
        ):
            self.count = self.initial if reset_input else self.instant_count + 1.0
        self.previous_trigger = trigger
        self.previous_reset = reset_input
        self.history = True
        return (self.instant_count,)


class WetBulb:
    """``wet_bulb_temperature``: CDL Psychrometrics.WetBulb_TDryBulPhi (stateless)."""

    def reset(self) -> None:
        return None

    def step(self, time_seconds: float, dry_bulb: float, relative_humidity: float) -> tuple[float]:
        return (wet_bulb(dry_bulb, relative_humidity),)


class LimitSlewRate:
    """``numeric_limit_slew_rate``: CDL.Reals.LimitSlewRate as the reference engine
    discretises it. The first execution passes the input through; each later one takes
    an implicit first-order lag toward the input over the elapsed time and clamps the
    change to ``fallingSlewRate * dt .. raisingSlewRate * dt``."""

    def __init__(self, raising: float, falling: float, td_seconds: float, enable: bool) -> None:
        if not raising > 0.0 or not falling < 0.0 or not td_seconds > 0.0:
            raise ValueError("LimitSlewRate needs raising > 0, falling < 0 and Td > 0")
        self.raising = raising
        self.falling = falling
        self.td_seconds = td_seconds
        self.enable = enable
        self.reset()

    def reset(self) -> None:
        self.y = math.nan
        self.previous_time = math.nan

    def step(self, time_seconds: float, value: float) -> tuple[float]:
        if not _finite(time_seconds, value):
            raise ValueError("LimitSlewRate inputs must be finite")
        if not self.enable or math.isnan(self.previous_time):
            self.y = value
        else:
            dt = time_seconds - self.previous_time
            if dt > 0.0:
                alpha = dt / self.td_seconds
                filtered = (self.y + alpha * value) / (1.0 + alpha)
                change = min(max(filtered - self.y, self.falling * dt), self.raising * dt)
                self.y = self.y + change
        self.previous_time = time_seconds
        return (self.y,)


class RisingEdge:
    """``one_shot``: one execution true per rising edge, judged between executions."""

    def __init__(self, initial: bool) -> None:
        self.initial = initial
        self.previous = initial

    def reset(self) -> None:
        self.previous = self.initial

    def step(self, time_seconds: float, value: bool) -> tuple[bool]:
        pulse = value and not self.previous
        self.previous = value
        return (pulse,)


class FallingEdge:
    def __init__(self, initial: bool) -> None:
        self.initial = initial
        self.previous = initial

    def reset(self) -> None:
        self.previous = self.initial

    def step(self, time_seconds: float, value: bool) -> tuple[bool]:
        pulse = self.previous and not value
        self.previous = value
        return (pulse,)


class SetReset:
    """Clear-dominant latch (``CDL.Logical.Latch``): set on a rising edge of ``set``."""

    def __init__(self) -> None:
        self.output = False
        self.previous_set = False

    def reset(self) -> None:
        self.output = False
        self.previous_set = False

    def step(self, time_seconds: float, set_input: bool, clear: bool) -> tuple[bool]:
        next_output = (not clear) and ((set_input and not self.previous_set) or self.output)
        self.output = next_output
        self.previous_set = set_input
        return (next_output,)


class Sampler:
    def __init__(self, sample_period_seconds: float) -> None:
        if not sample_period_seconds > 0.0:
            raise ValueError("Sampler period must be positive")
        self.sample_period_seconds = sample_period_seconds
        self.reset()

    def reset(self) -> None:
        self.initialized = False
        self.held = 0.0
        self.t0 = 0.0
        self.last_index = 0
        self.previous_time = math.nan

    def step(self, time_seconds: float, value: float) -> tuple[float]:
        if not _finite(time_seconds, value):
            raise ValueError("Sampler inputs must be finite")
        if not math.isnan(self.previous_time) and time_seconds < self.previous_time:
            raise ValueError("Sampler time must be monotonic")
        period = self.sample_period_seconds
        if not self.initialized:
            self.t0 = math.floor(time_seconds / period) * period
            self.last_index = int(math.floor((time_seconds - self.t0) / period + 1.0e-9))
            self.held = value
            self.initialized = True
        else:
            index = int(math.floor((time_seconds - self.t0) / period + 1.0e-9))
            if index > self.last_index:
                self.last_index = index
                self.held = value
            elif abs(time_seconds - (self.t0 + self.last_index * period)) <= 1.0e-9:
                self.held = value  # still at the sample instant: the last input wins
        self.previous_time = time_seconds
        return (self.held,)


class SampleTrigger:
    def __init__(self, period_seconds: float, shift_seconds: float) -> None:
        if not period_seconds > 0.0:
            raise ValueError("SampleTrigger period must be positive")
        self.period_seconds = period_seconds
        self.phase_seconds = (
            shift_seconds - math.floor(shift_seconds / period_seconds) * period_seconds
        )
        self.reset()

    def reset(self) -> None:
        self.last_index = -1
        self.previous_time = math.nan

    def step(self, time_seconds: float) -> tuple[bool]:
        if not math.isfinite(time_seconds):
            raise ValueError("SampleTrigger time must be finite")
        if not math.isnan(self.previous_time) and time_seconds < self.previous_time:
            raise ValueError("SampleTrigger time must be monotonic")
        index = int(math.floor((time_seconds - self.phase_seconds) / self.period_seconds + 1.0e-9))
        fired = index > self.last_index
        if fired:
            self.last_index = index
        self.previous_time = time_seconds
        return (fired,)


class Hysteresis:
    def __init__(self, u_low: float, u_high: float, initial: bool) -> None:
        if not u_high > u_low:
            raise ValueError("Hysteresis needs uHigh > uLow")
        self.u_low = u_low
        self.u_high = u_high
        self.initial = initial
        self.output = initial

    def reset(self) -> None:
        self.output = self.initial

    def step(self, time_seconds: float, value: float) -> tuple[bool]:
        if not math.isfinite(value):
            raise ValueError("Hysteresis input must be finite")
        self.output = (not self.output and value > self.u_high) or (
            self.output and value >= self.u_low
        )
        return (self.output,)


# --- harness-compatible construction ---------------------------------------------


def _num(params: dict[str, object], key: str, fallback: float | None = None) -> float:
    value = params.get(key)
    if value is None:
        if fallback is None:
            raise ValueError(f"missing parameter {key}")
        return fallback
    return float(value)  # type: ignore[arg-type]


def _bool(params: dict[str, object], key: str, fallback: bool) -> bool:
    value = params.get(key)
    if value is None:
        return fallback
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def build_kernel(name: str, params: dict[str, object]) -> Kernel:
    """Construct a kernel from the same parameter names ``KernelHarness`` accepts."""

    if name == "PidWithReset":
        return PidWithReset(
            str(params.get("controllerType", "PI")),
            _bool(params, "reverseActing", False),
            _num(params, "k"),
            _num(params, "ti"),
            _num(params, "td"),
            _num(params, "r", 1.0),
            _num(params, "ni", 0.9),
            _num(params, "nd", 10.0),
            _num(params, "yMin"),
            _num(params, "yMax"),
            _num(params, "xiStart", 0.0),
            _num(params, "ydStart", 0.0),
            _num(params, "yReset", 0.0),
        )
    if name == "TrueDelay":
        return TrueDelay(_num(params, "delaySeconds"), _bool(params, "delayOnInit", False))
    if name == "Timer":
        return Timer(_num(params, "thresholdSeconds", 0.0))
    if name == "TimerWithReset":
        return TimerWithReset(_num(params, "thresholdSeconds", 0.0))
    if name == "TimerAccumulating":
        return TimerAccumulating(_num(params, "thresholdSeconds", 0.0))
    if name == "TrueFalseHold":
        return TrueFalseHold(_num(params, "trueHoldSeconds"), _num(params, "falseHoldSeconds"))
    if name == "Pre":
        return Pre(_bool(params, "initial", False))
    if name == "UnitDelay":
        return UnitDelay(_num(params, "samplePeriodSeconds"), _num(params, "initial", 0.0))
    if name == "FirstOrderHold":
        return FirstOrderHold(_num(params, "samplePeriodSeconds"))
    if name == "MovingAverage":
        return MovingAverage(_num(params, "windowSeconds"))
    if name == "TrimAndRespond":
        return TrimAndRespond(
            _num(params, "initialSetpoint"),
            _num(params, "minimumSetpoint"),
            _num(params, "maximumSetpoint"),
            _num(params, "delaySeconds"),
            _num(params, "samplePeriodSeconds"),
            _num(params, "ignoredRequests"),
            _num(params, "trimAmount"),
            _num(params, "respondAmount"),
            _num(params, "maximumResponse"),
            _bool(params, "holdEnabled", False),
            _num(params, "holdDurationSeconds", 0.0),
        )
    if name == "BooleanInitialization":
        return BooleanInitialization(_bool(params, "initial", False))
    if name == "NumericChange":
        return NumericChange(str(params.get("mode", "changed")), _num(params, "initial", 0.0))
    if name == "RisingEdge":
        return RisingEdge(_bool(params, "initial", False))
    if name == "Round":
        return Round()
    if name == "IntegratorWithReset":
        return IntegratorWithReset(_num(params, "gain", 1.0), _num(params, "initial", 0.0))
    if name == "OnCounter":
        return OnCounter(_num(params, "initial", 0.0))
    if name == "WetBulb":
        return WetBulb()
    if name == "LimitSlewRate":
        return LimitSlewRate(
            _num(params, "raisingSlewRate"),
            _num(params, "fallingSlewRate"),
            _num(params, "tdSeconds"),
            _bool(params, "enable", True),
        )
    if name == "FallingEdge":
        return FallingEdge(_bool(params, "initial", False))
    if name == "SetReset":
        return SetReset()
    if name == "Sampler":
        return Sampler(_num(params, "samplePeriodSeconds"))
    if name == "SampleTrigger":
        return SampleTrigger(_num(params, "periodSeconds"), _num(params, "shiftSeconds", 0.0))
    if name == "Hysteresis":
        return Hysteresis(
            _num(params, "uLow"), _num(params, "uHigh"), _bool(params, "initial", False)
        )
    raise ValueError(f"unknown kernel {name}")


KERNEL_NAMES: tuple[str, ...] = (
    "PidWithReset",
    "TrueDelay",
    "Timer",
    "TimerWithReset",
    "TimerAccumulating",
    "TrueFalseHold",
    "Pre",
    "UnitDelay",
    "FirstOrderHold",
    "MovingAverage",
    "TrimAndRespond",
    "BooleanInitialization",
    "NumericChange",
    "RisingEdge",
    "FallingEdge",
    "SetReset",
    "Sampler",
    "SampleTrigger",
    "Hysteresis",
    "Round",
    "LimitSlewRate",
    "IntegratorWithReset",
    "OnCounter",
    "WetBulb",
)


def format_row(values: tuple[float | bool, ...]) -> str:
    """Render a step result the way ``KernelHarness`` prints it (booleans as true/false)."""

    return ",".join(
        ("true" if v else "false") if isinstance(v, bool) else repr(float(v)) for v in values
    )


__all__ = [
    "LimitSlewRate",
    "IntegratorWithReset",
    "OnCounter",
    "WetBulb",
    "KERNEL_NAMES",
    "BooleanInitialization",
    "FallingEdge",
    "FirstOrderHold",
    "Hysteresis",
    "Kernel",
    "MovingAverage",
    "NumericChange",
    "PidWithReset",
    "Pre",
    "RisingEdge",
    "Round",
    "SampleTrigger",
    "Sampler",
    "SetReset",
    "Timer",
    "TimerAccumulating",
    "TimerWithReset",
    "TrimAndRespond",
    "TrueDelay",
    "TrueFalseHold",
    "UnitDelay",
    "build_kernel",
    "format_row",
]
