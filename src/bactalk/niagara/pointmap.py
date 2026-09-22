"""Suggest matches between a job's canonical points and a station's proxy points (N5).

Suggestions are scored from normalised names, an abbreviation dictionary, the
BACnet object type, units and device grouping. They are suggestions only: a
human confirms every binding in the intake UI, and nothing links without a
confirmed ``niagara_ord`` on the point.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from bactalk.domain import DataType, PointRole, PointSpec
from bactalk.niagara.station_points import StationPoint

# Field abbreviations seen on real BACnet points, expanded to canonical tokens.
ABBREVIATIONS: Mapping[str, tuple[str, ...]] = {
    "zn": ("zone",),
    "zone": ("zone",),
    "rm": ("zone", "room"),
    "spc": ("zone", "space"),
    "t": ("temp",),
    "tmp": ("temp",),
    "temp": ("temp",),
    "temperature": ("temp",),
    "sa": ("supply", "air"),
    "sat": ("supply", "air", "temp"),
    "da": ("discharge", "air"),
    "dat": ("discharge", "air", "temp"),
    "dis": ("discharge",),
    "sup": ("supply",),
    "ra": ("return", "air"),
    "rat": ("return", "air", "temp"),
    "oa": ("outside", "air"),
    "oat": ("outside", "air", "temp"),
    "oad": ("outside", "air", "damper"),
    "out": ("outside",),
    "ma": ("mixed", "air"),
    "mat": ("mixed", "air", "temp"),
    "mix": ("mixed",),
    "sp": ("setpoint",),
    "stpt": ("setpoint",),
    "set": ("setpoint",),
    "setpt": ("setpoint",),
    "clg": ("cooling",),
    "cool": ("cooling",),
    "coo": ("cooling",),
    "htg": ("heating",),
    "heat": ("heating",),
    "hea": ("heating",),
    "dmpr": ("damper",),
    "dpr": ("damper",),
    "dam": ("damper",),
    "damper": ("damper",),
    "pos": ("position",),
    "cmd": ("command",),
    "fb": ("feedback",),
    "vlv": ("valve",),
    "val": ("valve",),
    "rht": ("reheat", "valve"),
    "rh": ("reheat",),
    "flow": ("flow",),
    "flo": ("flow",),
    "cfm": ("flow",),
    "afl": ("flow",),
    "vol": ("flow",),
    "dsp": ("duct", "static", "pressure"),
    "dp": ("static", "pressure"),
    "sp_stat": ("static", "pressure"),
    "stat": ("static",),
    "press": ("pressure",),
    "pres": ("pressure",),
    "duc": ("duct",),
    "fan": ("fan",),
    "sf": ("supply", "fan"),
    "sfan": ("supply", "fan"),
    "rf": ("return", "fan"),
    "ef": ("exhaust", "fan"),
    "rel": ("relief",),
    "sts": ("status",),
    "stat_": ("status",),
    "status": ("status",),
    "occ": ("occupied",),
    "occupied": ("occupied",),
    "ope": ("operation",),
    "mod": ("mode",),
    "mode": ("mode",),
    "win": ("window",),
    "co2": ("co2",),
    "ppm": ("co2",),
    "req": ("request",),
    "ala": ("alarm",),
    "alm": ("alarm",),
    "eco": ("economizer",),
    "hw": ("hot", "water"),
    "hot": ("hot",),
    "chw": ("chilled", "water"),
    "pla": ("plant",),
    "plant": ("plant",),
    "ovr": ("override",),
    "ove": ("override",),
    "en": ("enable",),
    "ena": ("enable",),
    "spd": ("speed",),
    "speed": ("speed",),
    "min": ("minimum",),
    "max": ("maximum",),
    "adj": ("adjusted",),
    "eff": ("effective",),
    "bre": ("breathing",),
    "are": ("area",),
    "pop": ("population",),
    "off": ("off",),
    "on": ("on",),
    "tem": ("temp",),
    "zon": ("zone",),
    "res": ("reset",),
    "sen": ("sensor",),
    "lea": ("leak",),
    "lo": ("low",),
    "low": ("low",),
    "fre": ("freeze",),
    "frz": ("freeze",),
    "pre": ("pressure",),
    "wat": ("water",),
    "y": (),
    "u": (),
}

_SPLIT = re.compile(r"[^A-Za-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def tokens(name: str) -> tuple[str, ...]:
    """Lower-case canonical tokens of a point name, abbreviations expanded."""

    parts: list[str] = []
    for chunk in _SPLIT.split(name):
        if not chunk:
            continue
        for piece in _CAMEL.split(chunk):
            piece = piece.strip()
            if not piece:
                continue
            key = piece.lower()
            if key.isdigit():
                continue  # instance numbers say which box, not what the point is
            if key.startswith("u1") and len(key) > 2:
                key = key[2:]
            elif key.startswith("y1") and len(key) > 2:
                key = key[2:]
            parts.extend(ABBREVIATIONS.get(key, (key,)))
    return tuple(parts)


def _data_type_of(point: PointSpec) -> str:
    return point.data_type.value


@dataclass(frozen=True)
class BindingSuggestion:
    point: str
    ord: str
    device: str
    score: float
    reasons: tuple[str, ...]
    data_type: str | None
    bacnet_object: str | None
    writable: bool
    write_priority: int | None
    """Proposed priority for command points (never 1, never implicit)."""

    def to_dict(self) -> dict[str, object]:
        return {
            "point": self.point,
            "ord": self.ord,
            "device": self.device,
            "score": round(self.score, 3),
            "reasons": list(self.reasons),
            "data_type": self.data_type,
            "bacnet_object": self.bacnet_object,
            "writable": self.writable,
            "write_priority": self.write_priority,
        }


def _score(
    point: PointSpec,
    candidate: StationPoint,
    device_hint: str | None,
    canonical_tokens: tuple[str, ...],
) -> tuple[float, tuple[str, ...]]:
    reasons: list[str] = []
    score = 0.0
    candidate_tokens = tokens(candidate.name)
    overlap = Counter(canonical_tokens) & Counter(candidate_tokens)
    if not overlap:
        # A match with no shared name token would be a guess, not a suggestion.
        return 0.0, ("no name token in common",)
    shared = sum(overlap.values())
    union = len(set(canonical_tokens) | set(candidate_tokens))
    jaccard = shared / union if union else 0.0
    score += 0.6 * jaccard
    reasons.append(f"name tokens {sorted(overlap)} ({jaccard:.2f})")
    if canonical_tokens == candidate_tokens:
        score += 0.15
        reasons.append("exact token match")
    if candidate.data_type == _data_type_of(point):
        score += 0.15
        reasons.append(f"same data type ({candidate.data_type})")
    elif candidate.data_type is not None:
        score -= 0.3
        reasons.append(f"data type differs ({candidate.data_type} vs {point.data_type.value})")
    wants_writable = point.role in {PointRole.COMMAND, PointRole.SETPOINT}
    if wants_writable and candidate.writable:
        score += 0.1
        reasons.append("writable object for a command")
    elif wants_writable and not candidate.writable:
        score -= 0.25
        reasons.append("command needs a writable object")
    elif (
        not wants_writable
        and candidate.writable
        and candidate.object_type
        in {
            "analogOutput",
            "binaryOutput",
        }
    ):
        score -= 0.1
        reasons.append("sensor mapped to an output object")
    if point.units and candidate.units:
        if point.units.lower() == candidate.units.lower():
            score += 0.1
            reasons.append("units agree")
    if device_hint and device_hint == candidate.device:
        score += 0.1
        reasons.append(f"same device as the other matches ({device_hint})")
    return max(score, 0.0), tuple(reasons)


def suggest_bindings(
    points: Iterable[PointSpec],
    inventory_points: Sequence[StationPoint],
    *,
    limit: int = 3,
    minimum_score: float = 0.35,
    default_write_priority: int = 16,
) -> dict[str, list[BindingSuggestion]]:
    """Ranked candidates per job point; empty when nothing clears ``minimum_score``."""

    job_points = list(points)
    # First pass to find the device most matches land on; second pass uses it.
    device_hint: str | None = None
    for round_index in range(2):
        results: dict[str, list[BindingSuggestion]] = {}
        device_votes: Counter[str] = Counter()
        for point in job_points:
            canonical = tokens(point.name)
            scored = []
            for candidate in inventory_points:
                score, reasons = _score(point, candidate, device_hint, canonical)
                if score >= minimum_score:
                    scored.append((score, candidate, reasons))
            scored.sort(key=lambda item: (-item[0], item[1].ord))
            wants_writable = point.role in {PointRole.COMMAND, PointRole.SETPOINT}
            results[point.name] = [
                BindingSuggestion(
                    point=point.name,
                    ord=candidate.ord,
                    device=candidate.device,
                    score=score,
                    reasons=reasons,
                    data_type=candidate.data_type,
                    bacnet_object=candidate.bacnet_object,
                    writable=candidate.writable,
                    write_priority=(
                        point.niagara_write_priority or default_write_priority
                        if wants_writable
                        else None
                    ),
                )
                for score, candidate, reasons in scored[:limit]
            ]
            if scored:
                device_votes[scored[0][1].device] += 1
        if round_index == 0 and device_votes:
            device_hint = device_votes.most_common(1)[0][0]
        else:
            break
    return results


def apply_bindings(
    points: Sequence[PointSpec],
    confirmed: Mapping[str, Mapping[str, object]],
) -> list[PointSpec]:
    """Return points with confirmed ``niagara_ord``/``niagara_write_priority`` set.

    ``confirmed`` maps a point name to ``{"niagara_ord": ..., "write_priority": ...}``.
    A command point without an explicit priority, or with priority 1, is refused.
    """

    updated: list[PointSpec] = []
    for point in points:
        entry = confirmed.get(point.name)
        if entry is None:
            updated.append(point)
            continue
        ord_value = entry.get("niagara_ord")
        if not isinstance(ord_value, str) or not ord_value.startswith("station:|slot:/"):
            raise ValueError(f"binding for {point.name} needs a station:|slot:/ ORD")
        priority = entry.get("write_priority")
        wants_writable = point.role in {PointRole.COMMAND, PointRole.SETPOINT}
        if wants_writable:
            if priority is None:
                raise ValueError(
                    f"command point {point.name} needs an explicit write priority (2-16)"
                )
            priority = int(priority)  # type: ignore[arg-type]
            if priority < 2 or priority > 16:
                raise ValueError(
                    f"command point {point.name}: write priority {priority} is not allowed "
                    "(never 1, never implicit)"
                )
        else:
            priority = None
        updated.append(
            point.model_copy(update={"niagara_ord": ord_value, "niagara_write_priority": priority})
        )
    return updated


__all__ = [
    "ABBREVIATIONS",
    "BindingSuggestion",
    "DataType",
    "apply_bindings",
    "suggest_bindings",
    "tokens",
]
