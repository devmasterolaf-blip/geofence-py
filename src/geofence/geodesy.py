"""Great-circle and ellipsoidal calculations.

Angles going in and out are degrees, distances are metres.  Bearings are
compass bearings: ``0`` is north, ``90`` east, always in ``[0, 360)``.

The spherical functions use the mean Earth radius and are accurate to about
0.3 % of the distance.
"""

from __future__ import annotations

import math

from .coords import (
    EARTH_RADIUS_M,
    Coordinate,
    CoordinateLike,
    as_coordinate,
    normalize_lon,
)
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


def _check_finite(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{name} must be a real number, got {value!r}")
    if not math.isfinite(value):
        raise ValidationError(f"{name} must be finite, got {value!r}")
    return float(value)


def _from_radians(lat: float, lon: float) -> Coordinate:
    lat_deg = max(-90.0, min(90.0, math.degrees(lat)))
    return Coordinate(lat_deg, normalize_lon(math.degrees(lon)))


def destination(
    start: CoordinateLike,
    bearing_deg: float,
    distance_m: float,
    radius: float = EARTH_RADIUS_M,
) -> Coordinate:
    """Point reached by travelling ``distance_m`` from ``start`` on a bearing.

    A negative distance travels in the opposite direction.
    """
    lat1, lon1 = _radians(start)
    theta = math.radians(_check_finite("bearing", bearing_deg))
    delta = _check_finite("distance", distance_m) / _check_radius(radius)
    sin_lat2 = math.sin(lat1) * math.cos(delta) + math.cos(lat1) * math.sin(delta) * math.cos(theta)
    sin_lat2 = max(-1.0, min(1.0, sin_lat2))
    lat2 = math.asin(sin_lat2)
    y = math.sin(theta) * math.sin(delta) * math.cos(lat1)
    x = math.cos(delta) - math.sin(lat1) * sin_lat2
    return _from_radians(lat2, lon1 + math.atan2(y, x))


def midpoint(a: CoordinateLike, b: CoordinateLike) -> Coordinate:
    """Half-way point along the great circle between ``a`` and ``b``."""
    lat1, lon1 = _radians(a)
    lat2, lon2 = _radians(b)
    dlon = lon2 - lon1
    bx = math.cos(lat2) * math.cos(dlon)
    by = math.cos(lat2) * math.sin(dlon)
    lat = math.atan2(
        math.sin(lat1) + math.sin(lat2),
        math.sqrt((math.cos(lat1) + bx) ** 2 + by * by),
    )
    lon = lon1 + math.atan2(by, math.cos(lat1) + bx)
    return _from_radians(lat, lon)


def interpolate(a: CoordinateLike, b: CoordinateLike, fraction: float) -> Coordinate:
    """Point at ``fraction`` of the way from ``a`` (0.0) to ``b`` (1.0).

    Raises :class:`ValidationError` for antipodal points, where infinitely
    many great circles join the two ends.
    """
    fraction = _check_finite("fraction", fraction)
    if not 0.0 <= fraction <= 1.0:
        raise ValidationError(f"fraction must be within [0, 1], got {fraction!r}")
    start, end = as_coordinate(a), as_coordinate(b)
    delta = angular_distance(start, end)
    if delta < 1e-15:
        return start
    sin_delta = math.sin(delta)
    if sin_delta < 1e-12:
        raise ValidationError("cannot interpolate between antipodal points")
    lat1, lon1 = _radians(start)
    lat2, lon2 = _radians(end)
    wa = math.sin((1.0 - fraction) * delta) / sin_delta
    wb = math.sin(fraction * delta) / sin_delta
    x = wa * math.cos(lat1) * math.cos(lon1) + wb * math.cos(lat2) * math.cos(lon2)
    y = wa * math.cos(lat1) * math.sin(lon1) + wb * math.cos(lat2) * math.sin(lon2)
    z = wa * math.sin(lat1) + wb * math.sin(lat2)
    return _from_radians(math.atan2(z, math.hypot(x, y)), math.atan2(y, x))


def cross_track_distance(
    point: CoordinateLike,
    start: CoordinateLike,
    end: CoordinateLike,
    radius: float = EARTH_RADIUS_M,
) -> float:
    """Signed distance from ``point`` to the great circle through ``start`` and ``end``.

    Positive values lie to the right of the direction of travel, negative
    values to the left.  When ``start`` and ``end`` coincide there is no
    path; the plain distance to ``start`` is returned.
    """
    radius = _check_radius(radius)
    delta13 = angular_distance(start, point)
    if angular_distance(start, end) < 1e-15:
        return radius * delta13
    theta13 = math.radians(initial_bearing(start, point))
    theta12 = math.radians(initial_bearing(start, end))
    sin_xt = math.sin(delta13) * math.sin(theta13 - theta12)
    return radius * math.asin(max(-1.0, min(1.0, sin_xt)))


def along_track_distance(
    point: CoordinateLike,
    start: CoordinateLike,
    end: CoordinateLike,
    radius: float = EARTH_RADIUS_M,
) -> float:
    """Distance from ``start`` to the foot of ``point`` on the path to ``end``.

    Negative when the foot lies behind ``start``.
    """
    radius = _check_radius(radius)
    delta13 = angular_distance(start, point)
    if delta13 < 1e-15 or angular_distance(start, end) < 1e-15:
        return 0.0
    theta13 = math.radians(initial_bearing(start, point))
    theta12 = math.radians(initial_bearing(start, end))
    delta_xt = math.asin(max(-1.0, min(1.0, math.sin(delta13) * math.sin(theta13 - theta12))))
    cos_xt = math.cos(delta_xt)
    if cos_xt < 1e-15:
        return 0.0
    along = math.acos(max(-1.0, min(1.0, math.cos(delta13) / cos_xt)))
    if math.cos(theta13 - theta12) < 0:
        along = -along
    return radius * along


def distance_to_segment(
    point: CoordinateLike,
    start: CoordinateLike,
    end: CoordinateLike,
    radius: float = EARTH_RADIUS_M,
) -> float:
    """Shortest distance from ``point`` to the great-circle arc ``start``-``end``."""
    radius = _check_radius(radius)
    segment = radius * angular_distance(start, end)
    along = along_track_distance(point, start, end, radius)
    if along <= 0.0:
        return radius * angular_distance(point, start)
    if along >= segment:
        return radius * angular_distance(point, end)
    return abs(cross_track_distance(point, start, end, radius))
