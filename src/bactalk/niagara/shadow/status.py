"""Niagara status flags and status-carrying values (docs/niagara-semantics.md S-STATUS-*).

A ``BStatusValue`` in Niagara is a value plus a ``BStatus`` bit set. The Shadow
Runtime keeps the same shape: every slot carries a :class:`StatusValue` and the
flags are the eight documented ``BStatus`` bits.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag


class Status(IntFlag):
    """The ``BStatus`` bits as Niagara orders them (Niagara Developer Guide, ``BStatus``)."""

    OK = 0
    DISABLED = 0x0001
    FAULT = 0x0002
    DOWN = 0x0004
    ALARM = 0x0008
    STALE = 0x0010
    OVERRIDDEN = 0x0020
    NULL = 0x0040
    UNACKED_ALARM = 0x0080

    @property
    def valid(self) -> bool:
        """``BStatus.isValid``: not disabled, fault, down, stale or null (S-STATUS-2)."""

        return not self & (
            Status.DISABLED | Status.FAULT | Status.DOWN | Status.STALE | Status.NULL
        )

    def render(self) -> str:
        if self == Status.OK:
            return "{ok}"
        names = [flag.name.lower() for flag in Status if flag and flag in self and flag.name]
        return "{" + ",".join(names) + "}"


_STATUS_NAMES = {
    "ok": Status.OK,
    "disabled": Status.DISABLED,
    "fault": Status.FAULT,
    "down": Status.DOWN,
    "alarm": Status.ALARM,
    "stale": Status.STALE,
    "overridden": Status.OVERRIDDEN,
    "null": Status.NULL,
    "unackedalarm": Status.UNACKED_ALARM,
    "unacked_alarm": Status.UNACKED_ALARM,
}


def parse_status(text: str | None) -> Status:
    """Parse ``{null,fault}`` style text (or ``ok``/empty) into flags."""

    if text is None:
        return Status.OK
    body = text.strip().strip("{}").strip()
    if not body:
        return Status.OK
    flags = Status.OK
    for token in body.split(","):
        key = token.strip().lower()
        if not key:
            continue
        if key not in _STATUS_NAMES:
            raise ValueError(f"unknown status flag {token.strip()!r}")
        flags |= _STATUS_NAMES[key]
    return flags


@dataclass(frozen=True, slots=True)
class StatusValue:
    """A slot value with its status. ``value`` is a float for numeric slots, a bool otherwise."""

    value: float | bool
    status: Status = Status.OK

    @property
    def valid(self) -> bool:
        return self.status.valid

    @property
    def is_null(self) -> bool:
        return bool(self.status & Status.NULL)

    def with_status(self, status: Status) -> StatusValue:
        return StatusValue(self.value, status)

    def with_value(self, value: float | bool) -> StatusValue:
        return StatusValue(value, self.status)


NUMERIC_NULL = StatusValue(0.0, Status.NULL)
BOOLEAN_NULL = StatusValue(False, Status.NULL)


def numeric(value: float, status: Status = Status.OK) -> StatusValue:
    return StatusValue(float(value), status)


def boolean(value: bool, status: Status = Status.OK) -> StatusValue:
    return StatusValue(bool(value), status)


__all__ = [
    "BOOLEAN_NULL",
    "NUMERIC_NULL",
    "Status",
    "StatusValue",
    "boolean",
    "numeric",
    "parse_status",
]
