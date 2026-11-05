"""Great-circle and ellipsoidal calculations.

Angles going in and out are degrees, distances are metres.  Bearings are
compass bearings: ``0`` is north, ``90`` east, always in ``[0, 360)``.

The spherical functions use the mean Earth radius and are accurate to about
0.3 % of the distance.
"""

from __future__ import annotations

import math

from .coords import EARTH_RADIUS_M, Coordinate, CoordinateLike, as_coordinate
from .errors import ValidationError


def _radians(point: CoordinateLike) -> tuple[float, float]:
    c = as_coordinate(point)
    return math.radians(c.lat), math.radians(c.lon)


def _check_radius(radius: float) -> float:
    if isinstance(radius, bool) or not isinstance(radius, (int, float)):
        raise ValidationError(f"radius must be a real number, got {radius!r}")
    if not math.isfinite(radius) or radius <= 0:
        raise ValidationError(f"radius must be positive and finite, got {radius!r}")
    return float(radius)


def angular_distance(a: CoordinateLike, b: CoordinateLike) -> float:
    """Central angle between two points in radians (haversine formula)."""
    lat1, lon1 = _radians(a)
    lat2, lon2 = _radians(b)
    sin_dlat = math.sin((lat2 - lat1) / 2.0)
    sin_dlon = math.sin((lon2 - lon1) / 2.0)
    h = sin_dlat * sin_dlat + math.cos(lat1) * math.cos(lat2) * sin_dlon * sin_dlon
    return 2.0 * math.asin(min(1.0, math.sqrt(h)))


def haversine_distance(
    a: CoordinateLike, b: CoordinateLike, radius: float = EARTH_RADIUS_M
) -> float:
    """Great-circle distance in metres on a sphere of the given radius."""
    return _check_radius(radius) * angular_distance(a, b)


def initial_bearing(a: CoordinateLike, b: CoordinateLike) -> float:
    """Bearing to follow when leaving ``a`` towards ``b`` on a great circle.

    For coincident points the bearing is undefined and ``0.0`` is returned.
    """
    lat1, lon1 = _radians(a)
    lat2, lon2 = _radians(b)
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    if abs(x) < 1e-15 and abs(y) < 1e-15:
        return 0.0
    return math.degrees(math.atan2(y, x)) % 360.0


def final_bearing(a: CoordinateLike, b: CoordinateLike) -> float:
    """Bearing on arrival at ``b`` when travelling from ``a``."""
    return (initial_bearing(b, a) + 180.0) % 360.0
