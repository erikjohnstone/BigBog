"""Niagara unit facets.

A Niagara `BUnit` is encoded inside a `b:Facets` string as
``units=u:<name>;<symbol>;<dimension>;<scale-and-offset>;`` where the dimension is
an SI exponent list such as ``(K)`` or ``(m-1)(kg)(s-2)`` and the last field holds
``*<scale>`` and/or ``+<offset>`` to the SI base. Every encoding in
:data:`NIAGARA_UNITS` marked ``harvested`` was copied verbatim from a real station
or module file in the pinned vendored sources (provenance recorded per entry).
Entries marked ``derived`` follow the same grammar for units no vendored file
happens to use and must be confirmed at Gate G-WB.

The unit strings a job declares (``PointSpec.units``) are free text from
contractors: ``°F``, ``degF``, ``%``, ``inH2O``, ``cfm`` and so on.
:func:`resolve_unit` maps those aliases onto one Niagara unit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Provenance = Literal["harvested", "derived"]


@dataclass(frozen=True)
class NiagaraUnit:
    name: str
    symbol: str
    dimension: str
    scale: str
    provenance: Provenance
    source: str

    @property
    def encoding(self) -> str:
        """The value of the ``units`` facet, without the ``u:`` prefix."""
        return f"{self.name};{self.symbol};{self.dimension};{self.scale};"

    def facet(self) -> str:
        return f"units=u:{self.encoding}"


_HVAC = ".vendor/n4-hvac-optimization-blocks/bog_files/*.bog"
_NH = ".vendor/nhaystack/nhaystack-rt/srcTest/stations/importTestStation.xml"

NIAGARA_UNITS: dict[str, NiagaraUnit] = {
    unit.name: unit
    for unit in (
        NiagaraUnit(
            "fahrenheit", "°F", "(K)", "*0.5555555555555556+255.37222222222223", "harvested", _HVAC
        ),
        NiagaraUnit("percent", "%", "", "", "harvested", _NH),
        NiagaraUnit("inches of water", "in/wc", "(m-1)(kg)(s-2)", "*248.84", "harvested", _NH),
        NiagaraUnit(
            "cubic feet per minute", "cfm", "(m3)(s-1)", "*4.719474432E-4", "harvested", _NH
        ),
        NiagaraUnit(
            "pounds per square inch", "psi", "(m-1)(kg)(s-2)", "*6894.75729", "harvested", _HVAC
        ),
        NiagaraUnit("parts per million", "ppm", "", "*1.0E-6", "harvested", _NH),
        NiagaraUnit("volt", "V", "(m2)(kg)(s-3)(A-1)", "", "harvested", _NH),
        NiagaraUnit("ampere", "A", "(A)", "", "harvested", _NH),
        NiagaraUnit("hertz", "Hz", "(s-1)", "", "harvested", _NH),
        NiagaraUnit("lux", "lx", "(m-2)(cd)", "", "harvested", _NH),
        NiagaraUnit("square foot", "ft²", "(m2)", "*0.092903", "harvested", _NH),
        NiagaraUnit("btus per hour", "BTU/hr", "(m2)(kg)(s-3)", "*0.292875", "harvested", _NH),
        # Derived from the Niagara unit database grammar; confirm at Gate G-WB.
        NiagaraUnit("celsius", "°C", "(K)", "+273.15", "derived", "BUnit grammar; SI offset"),
        NiagaraUnit("kelvin", "K", "(K)", "", "derived", "BUnit grammar; SI base"),
        NiagaraUnit(
            "fahrenheit degrees",
            "°F",
            "(K)",
            "*0.5555555555555556",
            "derived",
            "BUnit grammar; delta",
        ),
        NiagaraUnit("kelvin degrees", "K", "(K)", "", "derived", "BUnit grammar; delta"),
        NiagaraUnit("pascal", "Pa", "(m-1)(kg)(s-2)", "", "derived", "BUnit grammar; SI base"),
        NiagaraUnit("kilopascal", "kPa", "(m-1)(kg)(s-2)", "*1000.0", "derived", "BUnit grammar"),
        NiagaraUnit(
            "cubic meters per second", "m³/s", "(m3)(s-1)", "", "derived", "BUnit grammar; SI base"
        ),
        NiagaraUnit(
            "cubic meters per hour",
            "m³/h",
            "(m3)(s-1)",
            "*2.777777777777778E-4",
            "derived",
            "BUnit grammar",
        ),
        NiagaraUnit("liters per second", "L/s", "(m3)(s-1)", "*0.001", "derived", "BUnit grammar"),
        NiagaraUnit(
            "gallons per minute", "gpm", "(m3)(s-1)", "*6.30901964E-5", "derived", "BUnit grammar"
        ),
        NiagaraUnit("kilowatt", "kW", "(m2)(kg)(s-3)", "*1000.0", "derived", "BUnit grammar"),
        NiagaraUnit("watt", "W", "(m2)(kg)(s-3)", "", "derived", "BUnit grammar; SI base"),
        NiagaraUnit(
            "kilowatt hour", "kWh", "(m2)(kg)(s-2)", "*3600000.0", "derived", "BUnit grammar"
        ),
        NiagaraUnit("second", "s", "(s)", "", "derived", "BUnit grammar; SI base"),
        NiagaraUnit("minute", "min", "(s)", "*60.0", "derived", "BUnit grammar"),
        NiagaraUnit("hour", "h", "(s)", "*3600.0", "derived", "BUnit grammar"),
        NiagaraUnit("percent relative humidity", "%RH", "", "", "derived", "BUnit grammar"),
        NiagaraUnit("degrees angular", "°", "", "", "derived", "BUnit grammar"),
        NiagaraUnit(
            "revolutions per minute",
            "rpm",
            "(s-1)",
            "*0.016666666666666666",
            "derived",
            "BUnit grammar",
        ),
        NiagaraUnit(
            "feet per minute", "ft/min", "(m)(s-1)", "*0.00508", "derived", "BUnit grammar"
        ),
    )
}

# Contractor spellings → Niagara unit name. Keys are compared after lowering the
# case and removing spaces, underscores and dots, so "°F", "deg F" and "degF" agree.
_ALIAS_GROUPS: dict[str, tuple[str, ...]] = {
    "fahrenheit": ("°f", "degf", "f", "fahrenheit"),
    "celsius": ("°c", "degc", "c", "celsius"),
    "kelvin": ("k", "kelvin"),
    "fahrenheit degrees": ("δ°f", "deltaf", "δf", "deltadegf"),
    "percent": ("%", "percent", "pct"),
    "percent relative humidity": ("%rh", "rh"),
    "inches of water": ("inh2o", "in/wc", "inwc", "inchesofwater", "in-wg", "inwg", "inh₂o"),
    "pascal": ("pa", "pascal"),
    "kilopascal": ("kpa",),
    "pounds per square inch": ("psi", "psig"),
    "cubic feet per minute": ("cfm", "ft3/min", "ft³/min"),
    "cubic meters per second": ("m3/s", "m³/s"),
    "cubic meters per hour": ("m3/h", "m³/h"),
    "liters per second": ("l/s", "lps"),
    "gallons per minute": ("gpm",),
    "parts per million": ("ppm",),
    "volt": ("v", "volt", "volts"),
    "ampere": ("a", "amp", "amps", "ampere"),
    "hertz": ("hz", "hertz"),
    "lux": ("lux", "lx"),
    "square foot": ("ft2", "ft²", "sqft"),
    "btus per hour": ("btu/hr", "btuh", "btu/h"),
    "kilowatt": ("kw",),
    "watt": ("w", "watt"),
    "kilowatt hour": ("kwh",),
    "second": ("s", "sec", "seconds"),
    "minute": ("min", "minutes"),
    "hour": ("h", "hr", "hours"),
    "degrees angular": ("deg", "°"),
    "revolutions per minute": ("rpm",),
    "feet per minute": ("fpm", "ft/min"),
}
_ALIASES: dict[str, str] = {
    alias: name for name, aliases in _ALIAS_GROUPS.items() for alias in aliases
}


def _normalize(declared: str) -> str:
    return declared.strip().lower().replace(" ", "").replace("_", "").replace(".", "")


def resolve_unit(declared: str | None) -> NiagaraUnit | None:
    """The Niagara unit for a contractor's unit string, or None when unknown or blank."""
    if declared is None or not declared.strip():
        return None
    key = _normalize(declared)
    name = _ALIASES.get(key)
    if name is None:
        lowered = declared.strip().lower()
        name = lowered if lowered in NIAGARA_UNITS else None
    return NIAGARA_UNITS.get(name) if name else None


NULL_UNIT_FACET = "units=u:null;;;;"


def units_facet(declared: str | None) -> str:
    """The ``units=`` facet for a declared unit: the resolved unit, else the null unit."""
    unit = resolve_unit(declared)
    return unit.facet() if unit else NULL_UNIT_FACET


def numeric_facets(declared: str | None, *, precision: int = 1) -> str:
    """Full numeric point facets in the order pybog and Workbench emit them."""
    return f"{units_facet(declared)}|precision=i:{precision}|min=d:-inf|max=d:+inf"
