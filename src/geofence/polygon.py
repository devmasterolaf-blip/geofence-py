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

from typing import Iterable, Iterator

from . import geodesy
from .bbox import BoundingBox
from .coords import Coordinate, CoordinateLike, as_coordinates, normalize_lon
from .errors import InvalidGeometryError


def _wrap_lon(lon: float) -> float:
    """Wrap into ``[-180, 180]`` while leaving in-range values (incl. 180) alone."""
    return lon if -180.0 <= lon <= 180.0 else normalize_lon(lon)


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
        """Longitudes made continuous by letting each edge run the short way."""

        def step(a: float, b: float) -> float:
            delta = b - a
            if delta > 180.0:
                delta -= 360.0
            elif delta < -180.0:
                delta += 360.0
            return delta

        xs = [coords[0].lon]
        for previous, current in zip(coords, coords[1:]):
            xs.append(xs[-1] + step(previous.lon, current.lon))
        closing = xs[-1] + step(coords[-1].lon, coords[0].lon)
        if abs(closing - xs[0]) > 1e-9:
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
