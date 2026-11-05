"""Polylines: length, position along the line, simplification and a LineString type."""

from __future__ import annotations

import math
from typing import Iterable

from . import geodesy
from .bbox import BoundingBox
from .coords import Coordinate, CoordinateLike, as_coordinates
from .errors import InvalidGeometryError, ValidationError


def _segment_distance(method: str):
    if method == "haversine":
        return geodesy.haversine_distance
    if method in ("vincenty", "auto"):
        return lambda a, b: geodesy.distance(a, b, method)
    raise ValidationError(
        f"unknown distance method {method!r} "
        f"(expected one of: {', '.join(geodesy.DISTANCE_METHODS)})"
    )


def cumulative_distances(
    points: Iterable[CoordinateLike], method: str = "haversine"
) -> list[float]:
    """Running distance in metres at every vertex, starting with ``0.0``.

    An empty input gives an empty list.
    """
    coords = as_coordinates(points)
    measure = _segment_distance(method)
    totals: list[float] = []
    running = 0.0
    for index, coord in enumerate(coords):
        if index:
            running += measure(coords[index - 1], coord)
        totals.append(running)
    return totals


def length(points: Iterable[CoordinateLike], method: str = "haversine") -> float:
    """Total length of the polyline in metres (``0.0`` for fewer than two points)."""
    totals = cumulative_distances(points, method)
    return totals[-1] if totals else 0.0


def point_at_distance(points: Iterable[CoordinateLike], distance_m: float) -> Coordinate:
    """Point reached after travelling ``distance_m`` along the polyline.

    Distances are measured on the sphere.  Values beyond the end of the line
    return the last vertex; negative values are rejected.
    """
    coords = as_coordinates(points)
    if not coords:
        raise InvalidGeometryError("polyline has no points")
    if isinstance(distance_m, bool) or not isinstance(distance_m, (int, float)):
        raise ValidationError(f"distance must be a real number, got {distance_m!r}")
    if not math.isfinite(distance_m) or distance_m < 0:
        raise ValidationError(f"distance must be finite and non-negative, got {distance_m!r}")
    remaining = float(distance_m)
    for start, end in zip(coords, coords[1:]):
        segment = geodesy.haversine_distance(start, end)
        if remaining <= segment and segment > 0.0:
            return geodesy.interpolate(start, end, remaining / segment)
        remaining -= segment
    return coords[-1]


def simplify(points: Iterable[CoordinateLike], tolerance_m: float) -> list[Coordinate]:
    """Douglas-Peucker simplification with a tolerance in metres.

    Vertices closer than ``tolerance_m`` to the simplified line are dropped.
    The first and last points are always kept, and the result is a subset of
    the input in the original order.  A tolerance of ``0`` only removes
    vertices that lie exactly on the line between their neighbours.
    """
    coords = as_coordinates(points)
    if isinstance(tolerance_m, bool) or not isinstance(tolerance_m, (int, float)):
        raise ValidationError(f"tolerance must be a real number, got {tolerance_m!r}")
    if not math.isfinite(tolerance_m) or tolerance_m < 0:
        raise ValidationError(f"tolerance must be finite and non-negative, got {tolerance_m!r}")
    if len(coords) <= 2:
        return coords

    keep = [False] * len(coords)
    keep[0] = keep[-1] = True
    # Explicit stack instead of recursion so long tracks cannot overflow it.
    stack = [(0, len(coords) - 1)]
    while stack:
        first, last = stack.pop()
        if last - first < 2:
            continue
        worst_distance = -1.0
        worst_index = first
        for index in range(first + 1, last):
            d = geodesy.distance_to_segment(coords[index], coords[first], coords[last])
            if d > worst_distance:
                worst_distance = d
                worst_index = index
        if worst_distance > tolerance_m:
            keep[worst_index] = True
            stack.append((first, worst_index))
            stack.append((worst_index, last))
    return [coord for coord, kept in zip(coords, keep) if kept]


class LineString:
    """An ordered path of at least two points.

    A thin immutable wrapper around the module-level functions, used as the
    in-memory form of WKT ``LINESTRING`` and GeoJSON ``LineString``.
    """

    __slots__ = ("_coords",)

    def __init__(self, points: Iterable[CoordinateLike]) -> None:
        coords = as_coordinates(points)
        if len(coords) < 2:
            raise InvalidGeometryError(
                f"a line string needs at least 2 points, got {len(coords)}"
            )
        self._coords: tuple[Coordinate, ...] = tuple(coords)

    @property
    def coords(self) -> tuple[Coordinate, ...]:
        return self._coords

    def __len__(self) -> int:
        return len(self._coords)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LineString) and self._coords == other._coords

    def __hash__(self) -> int:
        return hash(self._coords)

    def __repr__(self) -> str:
        return f"LineString({[c.as_tuple() for c in self._coords]!r})"

    @property
    def bbox(self) -> BoundingBox:
        return BoundingBox.from_points(self._coords)

    def length(self, method: str = "haversine") -> float:
        """Length in metres."""
        return length(self._coords, method)

    def point_at_distance(self, distance_m: float) -> Coordinate:
        return point_at_distance(self._coords, distance_m)

    def simplify(self, tolerance_m: float) -> "LineString":
        """Douglas-Peucker simplified copy (always keeps both end points)."""
        return LineString(simplify(self._coords, tolerance_m))
