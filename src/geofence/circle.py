"""Circular fences: a centre point and a radius in metres on the sphere."""

from __future__ import annotations

import math

from . import geodesy
from .bbox import BoundingBox
from .coords import EARTH_RADIUS_M, Coordinate, CoordinateLike, as_coordinate
from .errors import InvalidGeometryError, ValidationError
from .polygon import Location, Polygon

#: Points whose distance differs from the radius by at most this many metres
#: count as on the circle.
BOUNDARY_TOLERANCE_M = 1e-6


class Circle:
    """All points within ``radius_m`` (great-circle distance) of ``center``."""

    __slots__ = ("_center", "_radius_m")

    def __init__(self, center: CoordinateLike, radius_m: float) -> None:
        self._center = as_coordinate(center)
        if isinstance(radius_m, bool) or not isinstance(radius_m, (int, float)):
            raise InvalidGeometryError(f"circle radius must be a real number, got {radius_m!r}")
        if not math.isfinite(radius_m) or radius_m <= 0:
            raise InvalidGeometryError(f"circle radius must be positive and finite, got {radius_m!r}")
        if radius_m >= math.pi * EARTH_RADIUS_M:
            raise InvalidGeometryError(
                f"circle radius {radius_m!r} m covers the whole sphere"
            )
        self._radius_m = float(radius_m)

    @property
    def center(self) -> Coordinate:
        return self._center

    @property
    def radius_m(self) -> float:
        return self._radius_m

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Circle)
            and self._center == other._center
            and self._radius_m == other._radius_m
        )

    def __hash__(self) -> int:
        return hash((self._center, self._radius_m))

    def __repr__(self) -> str:
        return f"Circle(center={self._center.as_tuple()!r}, radius_m={self._radius_m!r})"

    @property
    def bbox(self) -> BoundingBox:
        # Padded by the boundary tolerance so that every point contains()
        # accepts also falls inside the box, despite rounding.
        c = self._center
        return BoundingBox(c.lat, c.lon, c.lat, c.lon).expand(
            self._radius_m + BOUNDARY_TOLERANCE_M
        )

    def locate(self, point: CoordinateLike) -> Location:
        d = geodesy.haversine_distance(self._center, point)
        if abs(d - self._radius_m) <= BOUNDARY_TOLERANCE_M:
            return Location.BOUNDARY
        return Location.INSIDE if d < self._radius_m else Location.OUTSIDE

    def contains(self, point: CoordinateLike, boundary: bool = True) -> bool:
        """True when the point is within the radius.

        Points exactly on the circle count as inside unless ``boundary=False``.
        """
        location = self.locate(point)
        if location is Location.BOUNDARY:
            return boundary
        return location is Location.INSIDE

    def boundary_distance(self, point: CoordinateLike) -> float:
        """Distance in metres from a point to the circle itself."""
        return abs(geodesy.haversine_distance(self._center, point) - self._radius_m)

    def area(self) -> float:
        """Area of the spherical cap in square metres."""
        return 2.0 * math.pi * EARTH_RADIUS_M**2 * (1.0 - math.cos(self._radius_m / EARTH_RADIUS_M))

    def perimeter(self) -> float:
        """Circumference in metres, measured on the sphere."""
        return 2.0 * math.pi * EARTH_RADIUS_M * math.sin(self._radius_m / EARTH_RADIUS_M)

    def centroid(self) -> Coordinate:
        return self._center

    def to_polygon(self, segments: int = 64) -> Polygon:
        """Approximate the circle by a counter-clockwise regular polygon.

        The vertices lie on the circle, so the polygon is slightly smaller
        than the circle itself.
        """
        if isinstance(segments, bool) or not isinstance(segments, int) or segments < 3:
            raise ValidationError(f"segments must be an integer of at least 3, got {segments!r}")
        # Bearings decrease so that the vertices run counter-clockwise.
        vertices = [
            geodesy.destination(self._center, 360.0 - 360.0 * i / segments, self._radius_m)
            for i in range(segments)
        ]
        return Polygon(vertices)
