"""Validated coordinate and bounding-box types.

The package uses latitude/longitude in decimal degrees on the WGS-84 datum.
``Coordinate`` is always constructed as ``(lat, lon)``; formats that use the
opposite order (GeoJSON, WKT) convert at their own boundary through
:meth:`Coordinate.from_lonlat` and :meth:`Coordinate.as_lonlat`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Union

from .errors import InvalidCoordinateError

#: Mean Earth radius in metres (IUGG), used by all spherical formulas.
EARTH_RADIUS_M = 6371008.8

CoordinateLike = Union["Coordinate", tuple[float, float], list[float]]


def normalize_lon(lon: float) -> float:
    """Wrap a longitude in degrees into the half-open range ``[-180, 180)``."""
    wrapped = math.fmod(lon + 180.0, 360.0)
    if wrapped < 0:
        wrapped += 360.0
    return wrapped - 180.0


def _check_degrees(name: str, value: object, limit: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidCoordinateError(f"{name} must be a real number, got {value!r}")
    if not math.isfinite(value):
        raise InvalidCoordinateError(f"{name} must be finite, got {value!r}")
    if not -limit <= value <= limit:
        raise InvalidCoordinateError(
            f"{name} {value!r} is outside the range [{-limit:g}, {limit:g}]"
        )
    return float(value)


@dataclass(frozen=True, slots=True)
class Coordinate:
    """A point on the Earth in decimal degrees.

    ``lat`` must lie in ``[-90, 90]`` and ``lon`` in ``[-180, 180]``.  Both
    ends of the longitude range are accepted; ``-180`` and ``180`` describe
    the same meridian.  Use :meth:`wrapped` to build a coordinate from a
    longitude outside that range.
    """

    lat: float
    lon: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "lat", _check_degrees("latitude", self.lat, 90.0))
        object.__setattr__(self, "lon", _check_degrees("longitude", self.lon, 180.0))

    @classmethod
    def from_lonlat(cls, lon: float, lat: float) -> "Coordinate":
        """Build from ``(lon, lat)`` order as used by GeoJSON and WKT."""
        return cls(lat, lon)

    @classmethod
    def wrapped(cls, lat: float, lon: float) -> "Coordinate":
        """Build a coordinate, wrapping any finite longitude into range.

        The latitude is still validated strictly: there is no meaningful way
        to wrap a latitude without also changing the longitude.
        """
        if isinstance(lon, bool) or not isinstance(lon, (int, float)) or not math.isfinite(lon):
            raise InvalidCoordinateError(f"longitude must be a finite real number, got {lon!r}")
        return cls(lat, normalize_lon(lon))

    @classmethod
    def parse(cls, text: str) -> "Coordinate":
        """Parse ``"lat,lon"`` (optional spaces around the comma)."""
        if not isinstance(text, str):
            raise InvalidCoordinateError(f"expected 'lat,lon' text, got {text!r}")
        parts = text.split(",")
        if len(parts) != 2:
            raise InvalidCoordinateError(f"expected 'lat,lon', got {text!r}")
        try:
            lat, lon = float(parts[0]), float(parts[1])
        except ValueError:
            raise InvalidCoordinateError(f"expected 'lat,lon' with numeric parts, got {text!r}") from None
        return cls(lat, lon)

    def as_tuple(self) -> tuple[float, float]:
        """Return ``(lat, lon)``."""
        return (self.lat, self.lon)

    def as_lonlat(self) -> tuple[float, float]:
        """Return ``(lon, lat)``."""
        return (self.lon, self.lat)

    def same_place(self, other: "Coordinate", tolerance_deg: float = 0.0) -> bool:
        """True when both coordinates denote the same point.

        Unlike ``==`` this treats longitudes ``-180`` and ``180`` as equal and
        ignores the longitude altogether at the poles.
        """
        if abs(self.lat - other.lat) > tolerance_deg:
            return False
        if abs(self.lat) == 90.0:
            return True
        delta = abs(normalize_lon(self.lon - other.lon))
        return delta <= tolerance_deg

    def __str__(self) -> str:
        return f"{self.lat:.6f},{self.lon:.6f}"


def as_coordinate(value: CoordinateLike) -> Coordinate:
    """Coerce a ``Coordinate`` or a ``(lat, lon)`` pair to a ``Coordinate``."""
    if isinstance(value, Coordinate):
        return value
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return Coordinate(value[0], value[1])
    raise InvalidCoordinateError(
        f"expected a Coordinate or a (lat, lon) pair, got {value!r}"
    )


def as_coordinates(values: Iterable[CoordinateLike]) -> list[Coordinate]:
    """Coerce an iterable of coordinate-like values to a list."""
    return [as_coordinate(value) for value in values]
