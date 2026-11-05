"""Length unit helpers.

All distances inside the package are metres.  These helpers convert at the
edges (CLI arguments, report output) between metres and a small set of named
units.
"""

from __future__ import annotations

import math

from .errors import UnitError, ValidationError

#: Metres per unit, keyed by canonical unit name.
METERS_PER_UNIT: dict[str, float] = {
    "m": 1.0,
    "km": 1000.0,
    "mi": 1609.344,
    "nmi": 1852.0,
    "ft": 0.3048,
}

_ALIASES: dict[str, str] = {
    "meter": "m",
    "meters": "m",
    "metre": "m",
    "metres": "m",
    "kilometer": "km",
    "kilometers": "km",
    "kilometre": "km",
    "kilometres": "km",
    "mile": "mi",
    "miles": "mi",
    "nm": "nmi",
    "nautical_mile": "nmi",
    "nautical_miles": "nmi",
    "foot": "ft",
    "feet": "ft",
}


def canonical_unit(name: str) -> str:
    """Return the canonical short name (``m``, ``km``, ``mi``, ``nmi``, ``ft``).

    Matching ignores case and surrounding whitespace and accepts a few long
    spellings such as ``"kilometres"`` or ``"nautical_miles"``.
    """
    if not isinstance(name, str):
        raise UnitError(f"unit must be a string, got {type(name).__name__}")
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    key = _ALIASES.get(key, key)
    if key not in METERS_PER_UNIT:
        known = ", ".join(sorted(METERS_PER_UNIT))
        raise UnitError(f"unknown length unit {name!r} (known units: {known})")
    return key


def to_meters(value: float, unit: str) -> float:
    """Convert ``value`` expressed in ``unit`` to metres."""
    return _check_number(value) * METERS_PER_UNIT[canonical_unit(unit)]


def from_meters(meters: float, unit: str) -> float:
    """Convert a length in metres to ``unit``."""
    return _check_number(meters) / METERS_PER_UNIT[canonical_unit(unit)]


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert ``value`` from one named unit to another."""
    return from_meters(to_meters(value, from_unit), to_unit)


def format_distance(meters: float, unit: str = "m", precision: int = 3) -> str:
    """Render a metre value in ``unit`` with a fixed number of decimals.

    >>> format_distance(1500, "km")
    '1.500 km'
    """
    if isinstance(precision, bool) or not isinstance(precision, int) or precision < 0:
        raise ValidationError(f"precision must be a non-negative integer, got {precision!r}")
    canonical = canonical_unit(unit)
    return f"{from_meters(meters, canonical):.{precision}f} {canonical}"


def _check_number(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"length must be a real number, got {value!r}")
    if not math.isfinite(value):
        raise ValidationError(f"length must be finite, got {value!r}")
    return float(value)
