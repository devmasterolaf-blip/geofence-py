"""Rings, polygons with holes and multipolygons.

Edge model
----------
Edges are straight lines in longitude/latitude space (the same convention as
GeoJSON), not great-circle arcs.  An edge whose end points are more than 180
degrees of longitude apart is taken to run the short way, across the
antimeridian, so shapes that straddle longitude 180 work as expected.  Rings
that encircle a pole cannot be represented in this model and are rejected.
"""

from __future__ import annotations

import enum
import math
from typing import Iterable, Iterator, Union

from . import geodesy
from .bbox import BoundingBox
from .coords import (
    EARTH_RADIUS_M,
    Coordinate,
    CoordinateLike,
    as_coordinate,
    as_coordinates,
    normalize_lon,
)
from .errors import InvalidGeometryError

#: Points closer than this many degrees to an edge count as on the boundary.
BOUNDARY_TOLERANCE_DEG = 1e-12


class Location(enum.Enum):
    """Where a point lies relative to a shape."""

    INSIDE = "inside"
    BOUNDARY = "boundary"
    OUTSIDE = "outside"


def _wrap_lon(lon: float) -> float:
    """Wrap into ``[-180, 180]`` while leaving in-range values (incl. 180) alone."""
    return lon if -180.0 <= lon <= 180.0 else normalize_lon(lon)


def _on_segment(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> bool:
    """True when (px, py) lies on the closed segment a-b, within tolerance."""
    tol = BOUNDARY_TOLERANCE_DEG
    cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    if abs(cross) > tol * max(1.0, math.hypot(bx - ax, by - ay)):
        return False
    return (
        min(ax, bx) - tol <= px <= max(ax, bx) + tol
        and min(ay, by) - tol <= py <= max(ay, by) + tol
    )


class Ring:
    """A closed ring of at least three vertices.

    The constructor accepts the vertices with or without the repeated
    closing point and stores them without it.  Use :meth:`from_closed` when
    the input format requires explicit closure and an unclosed ring should
    be reported as an error.
    """

    __slots__ = ("_coords", "_xs", "_ys")

    def __init__(self, points: Iterable[CoordinateLike]) -> None:
        coords = as_coordinates(points)
        if len(coords) > 1 and coords[0] == coords[-1]:
            coords.pop()
        if len(coords) < 3:
            raise InvalidGeometryError(
                f"a ring needs at least 3 distinct vertices, got {len(coords)}"
            )
        self._coords: tuple[Coordinate, ...] = tuple(coords)
        self._xs: tuple[float, ...] = self._unwrap_longitudes(self._coords)
        self._ys: tuple[float, ...] = tuple(c.lat for c in self._coords)

    @classmethod
    def from_closed(cls, points: Iterable[CoordinateLike]) -> "Ring":
        """Build a ring from points whose last point must repeat the first."""
        coords = as_coordinates(points)
        if len(coords) < 4:
            raise InvalidGeometryError(
                f"a closed ring needs at least 4 points (first repeated last), got {len(coords)}"
            )
        if coords[0] != coords[-1]:
            raise InvalidGeometryError(
                f"ring is not closed: first point {coords[0]} differs from last point {coords[-1]}"
            )
        return cls(coords)

    @staticmethod
    def _unwrap_longitudes(coords: tuple[Coordinate, ...]) -> tuple[float, ...]:
        """Longitudes made continuous by letting each edge run the short way.

        Every value is the original longitude plus a whole number of turns,
        so a query longitude shifted by the same number of turns compares
        exactly with the stored vertices.
        """
        turns = 0
        xs = [coords[0].lon]
        n = len(coords)
        for i in range(1, n + 1):
            delta = coords[i % n].lon - coords[i - 1].lon
            if delta > 180.0:
                turns -= 1
            elif delta < -180.0:
                turns += 1
            if i < n:
                xs.append(coords[i].lon + 360.0 * turns)
        if turns != 0:
            raise InvalidGeometryError(
                "ring encircles a pole, which the lon/lat edge model cannot represent"
            )
        return tuple(xs)

    # -- views ------------------------------------------------------------

    @property
    def coords(self) -> tuple[Coordinate, ...]:
        """Vertices without the repeated closing point."""
        return self._coords

    @property
    def closed_coords(self) -> list[Coordinate]:
        """Vertices with the first one repeated at the end."""
        return [*self._coords, self._coords[0]]

    def planar_vertices(self) -> list[tuple[float, float]]:
        """Vertices as ``(x, y)`` with continuous (unwrapped) longitudes as x.

        For a ring that crosses the antimeridian some x values lie outside
        ``[-180, 180]``.
        """
        return list(zip(self._xs, self._ys))

    def __len__(self) -> int:
        return len(self._coords)

    def edges(self) -> Iterator[tuple[Coordinate, Coordinate]]:
        """All edges, including the closing one."""
        n = len(self._coords)
        for i in range(n):
            yield self._coords[i], self._coords[(i + 1) % n]

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Ring) and self._coords == other._coords

    def __hash__(self) -> int:
        return hash(self._coords)

    def __repr__(self) -> str:
        return f"Ring({[c.as_tuple() for c in self._coords]!r})"

    # -- shape ------------------------------------------------------------

    @property
    def crosses_antimeridian(self) -> bool:
        return self.bbox.crosses_antimeridian

    @property
    def bbox(self) -> BoundingBox:
        west, east = min(self._xs), max(self._xs)
        if east - west >= 360.0:
            west, east = -180.0, 180.0
        return BoundingBox(min(self._ys), _wrap_lon(west), max(self._ys), _wrap_lon(east))

    def planar_signed_area(self) -> float:
        """Shoelace area in square degrees; positive when counter-clockwise."""
        xs, ys = self._xs, self._ys
        n = len(xs)
        total = 0.0
        for i in range(n):
            j = (i + 1) % n
            total += xs[i] * ys[j] - xs[j] * ys[i]
        return total / 2.0

    @property
    def is_ccw(self) -> bool:
        """True when the vertices run counter-clockwise on a north-up map."""
        return self.planar_signed_area() > 0.0

    def reversed(self) -> "Ring":
        """The same ring with the opposite vertex order."""
        return Ring((self._coords[0], *reversed(self._coords[1:])))

    def oriented(self, ccw: bool = True) -> "Ring":
        """This ring, or its reverse, so that it has the requested orientation."""
        return self if self.is_ccw == ccw else self.reversed()

    def perimeter(self) -> float:
        """Length of the boundary in metres (great-circle length per edge)."""
        return sum(geodesy.haversine_distance(a, b) for a, b in self.edges())

    def signed_area(self) -> float:
        """Area on the sphere in square metres; positive when counter-clockwise.

        Uses the line-integral formula of Chamberlain and Duquette.  It is
        exact for edges along meridians and parallels and a close
        approximation for the small and medium shapes typical of geofences.
        """
        xs, ys = self._xs, self._ys
        n = len(xs)
        total = 0.0
        for i in range(n):
            j = (i + 1) % n
            total += math.radians(xs[j] - xs[i]) * (
                2.0 + math.sin(math.radians(ys[i])) + math.sin(math.radians(ys[j]))
            )
        return -total * EARTH_RADIUS_M * EARTH_RADIUS_M / 2.0

    def area(self) -> float:
        """Enclosed area on the sphere in square metres (never negative)."""
        return abs(self.signed_area())

    def _planar_centroid(self) -> tuple[float, float, float]:
        """Centroid ``(x, y)`` in unwrapped degrees and the absolute planar area."""
        xs, ys = self._xs, self._ys
        n = len(xs)
        area = self.planar_signed_area()
        if abs(area) < 1e-18:
            return sum(xs) / n, sum(ys) / n, 0.0
        cx = cy = 0.0
        for i in range(n):
            j = (i + 1) % n
            cross = xs[i] * ys[j] - xs[j] * ys[i]
            cx += (xs[i] + xs[j]) * cross
            cy += (ys[i] + ys[j]) * cross
        return cx / (6.0 * area), cy / (6.0 * area), abs(area)

    def centroid(self) -> Coordinate:
        """Centroid of the enclosed area, computed in lon/lat space.

        A ring with no area (all vertices on one line) yields the mean of
        its vertices.
        """
        x, y, _ = self._planar_centroid()
        return Coordinate(y, _wrap_lon(x))

    # -- point location ---------------------------------------------------

    def _locate_planar(self, px: float, py: float) -> Location:
        """Even-odd ray casting in unwrapped lon/lat space."""
        xs, ys = self._xs, self._ys
        n = len(xs)
        inside = False
        for i in range(n):
            j = (i + 1) % n
            ax, ay, bx, by = xs[i], ys[i], xs[j], ys[j]
            if _on_segment(px, py, ax, ay, bx, by):
                return Location.BOUNDARY
            # Half-open rule: an edge counts when it spans the ray's latitude
            # with exactly one end strictly above it, so a vertex on the ray
            # is never counted twice.
            if (ay > py) != (by > py):
                x_cross = ax + (py - ay) * (bx - ax) / (by - ay)
                if x_cross > px:
                    inside = not inside
        return Location.INSIDE if inside else Location.OUTSIDE

    def locate(self, point: CoordinateLike) -> Location:
        """Classify a point as inside, on the boundary of, or outside the ring."""
        c = as_coordinate(point)
        if not min(self._ys) <= c.lat <= max(self._ys):
            return Location.OUTSIDE
        west, east = min(self._xs), max(self._xs)
        result = Location.OUTSIDE
        # The unwrapped ring may sit one turn east or west of the input range.
        for turn in (-360.0, 0.0, 360.0):
            x = c.lon + turn
            if not west <= x <= east:
                continue
            found = self._locate_planar(x, c.lat)
            if found is Location.BOUNDARY:
                return found
            if found is Location.INSIDE:
                result = found
        return result

    def contains(self, point: CoordinateLike, boundary: bool = True) -> bool:
        """True when the point is inside the ring.

        Points on the boundary count as inside unless ``boundary=False``.
        """
        location = self.locate(point)
        if location is Location.BOUNDARY:
            return boundary
        return location is Location.INSIDE

    def boundary_distance(self, point: CoordinateLike) -> float:
        """Distance in metres from a point to the nearest edge of the ring.

        Each edge is measured as a great-circle arc, which matches the lon/lat
        edge model closely for edges up to a few kilometres long.
        """
        c = as_coordinate(point)
        return min(geodesy.distance_to_segment(c, a, b) for a, b in self.edges())


def _align_turn(x: float, reference: float) -> float:
    """Shift ``x`` by whole turns so that it lies within 180 degrees of ``reference``."""
    return x - 360.0 * round((x - reference) / 360.0)


def _combine_centroids(parts: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    """Weighted mean of ``(x, y, weight)`` parts; weights may be negative."""
    reference = parts[0][0]
    total = sum(weight for _, _, weight in parts)
    if abs(total) < 1e-18:
        return parts[0][0], parts[0][1], 0.0
    x = sum(_align_turn(px, reference) * weight for px, _, weight in parts) / total
    y = sum(py * weight for _, py, weight in parts) / total
    return x, y, total


RingLike = Union[Ring, Iterable[CoordinateLike]]


def _as_ring(value: RingLike) -> Ring:
    return value if isinstance(value, Ring) else Ring(value)


class Polygon:
    """An exterior ring with zero or more holes.

    A point inside a hole is outside the polygon; a point on the edge of a
    hole is on the polygon's boundary.  Construction does not check that the
    holes lie inside the exterior; see the validity helpers for that.
    """

    __slots__ = ("_exterior", "_holes")

    def __init__(self, exterior: RingLike, holes: Iterable[RingLike] = ()) -> None:
        self._exterior = _as_ring(exterior)
        self._holes = tuple(_as_ring(hole) for hole in holes)

    @property
    def exterior(self) -> Ring:
        return self._exterior

    @property
    def holes(self) -> tuple[Ring, ...]:
        return self._holes

    @property
    def rings(self) -> tuple[Ring, ...]:
        """Exterior first, then the holes."""
        return (self._exterior, *self._holes)

    @property
    def bbox(self) -> BoundingBox:
        return self._exterior.bbox

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Polygon) and self.rings == other.rings

    def __hash__(self) -> int:
        return hash(self.rings)

    def __repr__(self) -> str:
        return f"Polygon(exterior={self._exterior!r}, holes={list(self._holes)!r})"

    def locate(self, point: CoordinateLike) -> Location:
        c = as_coordinate(point)
        outer = self._exterior.locate(c)
        if outer is not Location.INSIDE:
            return outer
        for hole in self._holes:
            inner = hole.locate(c)
            if inner is Location.BOUNDARY:
                return Location.BOUNDARY
            if inner is Location.INSIDE:
                return Location.OUTSIDE
        return Location.INSIDE

    def contains(self, point: CoordinateLike, boundary: bool = True) -> bool:
        """True when the point is inside the polygon and not in a hole.

        Points on the exterior ring or on the edge of a hole count as inside
        unless ``boundary=False``.
        """
        location = self.locate(point)
        if location is Location.BOUNDARY:
            return boundary
        return location is Location.INSIDE

    def boundary_distance(self, point: CoordinateLike) -> float:
        """Distance in metres to the nearest edge of the exterior or of a hole."""
        c = as_coordinate(point)
        return min(ring.boundary_distance(c) for ring in self.rings)

    def area(self) -> float:
        """Area on the sphere in square metres, holes subtracted."""
        return max(0.0, self._exterior.area() - sum(hole.area() for hole in self._holes))

    def perimeter(self) -> float:
        """Total boundary length in metres, including the edges of holes."""
        return sum(ring.perimeter() for ring in self.rings)

    def _planar_centroid(self) -> tuple[float, float, float]:
        parts = [self._exterior._planar_centroid()]
        for hole in self._holes:
            x, y, weight = hole._planar_centroid()
            parts.append((x, y, -weight))
        return _combine_centroids(parts)

    def centroid(self) -> Coordinate:
        """Centroid in lon/lat space, with holes weighted negatively.

        The centroid of a concave polygon, or of one with a hole, may lie
        outside the polygon.
        """
        x, y, _ = self._planar_centroid()
        return Coordinate(y, _wrap_lon(x))

    def normalized(self) -> "Polygon":
        """Copy with a counter-clockwise exterior and clockwise holes."""
        return Polygon(
            self._exterior.oriented(ccw=True),
            [hole.oriented(ccw=False) for hole in self._holes],
        )


PolygonLike = Union[Polygon, Ring, Iterable[CoordinateLike]]


def _as_polygon(value: PolygonLike) -> Polygon:
    return value if isinstance(value, Polygon) else Polygon(value)


class MultiPolygon:
    """A collection of one or more polygons treated as a single shape."""

    __slots__ = ("_polygons",)

    def __init__(self, polygons: Iterable[PolygonLike]) -> None:
        self._polygons = tuple(_as_polygon(polygon) for polygon in polygons)
        if not self._polygons:
            raise InvalidGeometryError("a multipolygon needs at least one polygon")

    @property
    def polygons(self) -> tuple[Polygon, ...]:
        return self._polygons

    def __len__(self) -> int:
        return len(self._polygons)

    def __iter__(self) -> Iterator[Polygon]:
        return iter(self._polygons)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, MultiPolygon) and self._polygons == other._polygons

    def __hash__(self) -> int:
        return hash(self._polygons)

    def __repr__(self) -> str:
        return f"MultiPolygon({list(self._polygons)!r})"

    @property
    def bbox(self) -> BoundingBox:
        box = self._polygons[0].bbox
        for polygon in self._polygons[1:]:
            box = box.union(polygon.bbox)
        return box

    def locate(self, point: CoordinateLike) -> Location:
        c = as_coordinate(point)
        result = Location.OUTSIDE
        for polygon in self._polygons:
            found = polygon.locate(c)
            if found is Location.INSIDE:
                return found
            if found is Location.BOUNDARY:
                result = found
        return result

    def contains(self, point: CoordinateLike, boundary: bool = True) -> bool:
        """True when any member polygon contains the point."""
        location = self.locate(point)
        if location is Location.BOUNDARY:
            return boundary
        return location is Location.INSIDE

    def boundary_distance(self, point: CoordinateLike) -> float:
        """Distance in metres to the nearest edge of any member polygon."""
        c = as_coordinate(point)
        return min(polygon.boundary_distance(c) for polygon in self._polygons)

    def area(self) -> float:
        """Sum of the member areas in square metres (overlaps count twice)."""
        return sum(polygon.area() for polygon in self._polygons)

    def perimeter(self) -> float:
        return sum(polygon.perimeter() for polygon in self._polygons)

    def centroid(self) -> Coordinate:
        """Area-weighted centroid of the members in lon/lat space."""
        x, y, _ = _combine_centroids([polygon._planar_centroid() for polygon in self._polygons])
        return Coordinate(y, _wrap_lon(x))

    def normalized(self) -> "MultiPolygon":
        return MultiPolygon(polygon.normalized() for polygon in self._polygons)
