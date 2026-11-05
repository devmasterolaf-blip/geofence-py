"""Latitude/longitude bounding boxes, including boxes that cross the antimeridian.

A box is stored as ``(south, west, north, east)``.  Its longitude range runs
*eastwards* from ``west`` to ``east``; when ``west > east`` the box crosses
the antimeridian (for example ``west=170, east=-170`` is 20 degrees wide).
The special pair ``west=-180, east=180`` covers every longitude.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from .coords import (
    EARTH_RADIUS_M,
    Coordinate,
    CoordinateLike,
    as_coordinate,
    normalize_lon,
)
from .errors import InvalidCoordinateError, InvalidGeometryError, ValidationError


def _lon_width(west: float, east: float) -> float:
    """Eastward extent in degrees from ``west`` to ``east`` (0..360)."""
    if west == -180.0 and east == 180.0:
        return 360.0
    return (east - west) % 360.0


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """An axis-aligned box in degrees; edges are part of the box."""

    south: float
    west: float
    north: float
    east: float

    def __post_init__(self) -> None:
        # Reuse Coordinate's validation for the two corners.
        try:
            sw = Coordinate(self.south, self.west)
            ne = Coordinate(self.north, self.east)
        except InvalidCoordinateError as exc:
            raise InvalidGeometryError(f"invalid bounding box corner: {exc}") from None
        if sw.lat > ne.lat:
            raise InvalidGeometryError(
                f"bounding box south ({sw.lat!r}) is greater than north ({ne.lat!r})"
            )
        object.__setattr__(self, "south", sw.lat)
        object.__setattr__(self, "west", sw.lon)
        object.__setattr__(self, "north", ne.lat)
        object.__setattr__(self, "east", ne.lon)

    # -- construction -----------------------------------------------------

    @classmethod
    def world(cls) -> "BoundingBox":
        """The box covering the whole globe."""
        return cls(-90.0, -180.0, 90.0, 180.0)

    @classmethod
    def from_points(cls, points: Iterable[CoordinateLike]) -> "BoundingBox":
        """Smallest box containing all points.

        The longitude range is the narrowest one that holds every point, so
        a cluster of points on both sides of the antimeridian yields a narrow
        crossing box rather than one that spans almost the whole globe.  When
        a crossing and a non-crossing box are equally narrow the non-crossing
        one is returned.
        """
        coords = [as_coordinate(point) for point in points]
        if not coords:
            raise InvalidGeometryError("cannot build a bounding box from zero points")
        south = min(c.lat for c in coords)
        north = max(c.lat for c in coords)
        lons = sorted({c.lon for c in coords})
        # The box is the complement of the widest empty gap between
        # neighbouring longitudes; start with the gap over the antimeridian.
        best_gap = lons[0] + 360.0 - lons[-1]
        west, east = lons[0], lons[-1]
        for previous, current in zip(lons, lons[1:]):
            gap = current - previous
            if gap > best_gap:
                best_gap = gap
                west, east = current, previous
        return cls(south, west, north, east)

    # -- basic properties -------------------------------------------------

    @property
    def crosses_antimeridian(self) -> bool:
        return self.west > self.east

    @property
    def width_deg(self) -> float:
        """Longitude extent in degrees, measured eastwards (0..360)."""
        return _lon_width(self.west, self.east)

    @property
    def height_deg(self) -> float:
        return self.north - self.south

    @property
    def center(self) -> Coordinate:
        lat = (self.south + self.north) / 2.0
        lon = normalize_lon(self.west + self.width_deg / 2.0)
        return Coordinate(lat, lon)

    @property
    def corners(self) -> tuple[Coordinate, Coordinate, Coordinate, Coordinate]:
        """Corners in the order SW, SE, NE, NW."""
        return (
            Coordinate(self.south, self.west),
            Coordinate(self.south, self.east),
            Coordinate(self.north, self.east),
            Coordinate(self.north, self.west),
        )

    # -- predicates -------------------------------------------------------

    def contains_lon(self, lon: float) -> bool:
        return (lon - self.west) % 360.0 <= self.width_deg

    def contains(self, point: CoordinateLike) -> bool:
        """True when the point lies inside the box or on its edge."""
        c = as_coordinate(point)
        return self.south <= c.lat <= self.north and self.contains_lon(c.lon)

    def contains_box(self, other: "BoundingBox") -> bool:
        """True when ``other`` lies completely inside this box."""
        if other.south < self.south or other.north > self.north:
            return False
        if self.width_deg >= 360.0:
            return True
        offset = (other.west - self.west) % 360.0
        return offset + other.width_deg <= self.width_deg

    def intersects(self, other: "BoundingBox") -> bool:
        """True when the boxes share at least one point (touching counts)."""
        if other.south > self.north or other.north < self.south:
            return False
        return (
            (other.west - self.west) % 360.0 <= self.width_deg
            or (self.west - other.west) % 360.0 <= other.width_deg
        )

    # -- derived boxes ----------------------------------------------------

    def union(self, other: "BoundingBox") -> "BoundingBox":
        """Smallest box containing both boxes."""
        south = min(self.south, other.south)
        north = max(self.north, other.north)
        # Candidate 1 keeps our west edge, candidate 2 keeps the other's.
        start = (other.west - self.west) % 360.0
        width1 = max(self.width_deg, start + other.width_deg)
        east1 = self.east if self.width_deg >= start + other.width_deg else other.east
        back = (self.west - other.west) % 360.0
        width2 = max(other.width_deg, back + self.width_deg)
        east2 = other.east if other.width_deg >= back + self.width_deg else self.east
        if min(width1, width2) >= 360.0:
            return BoundingBox(south, -180.0, north, 180.0)
        if width1 <= width2:
            return BoundingBox(south, self.west, north, east1)
        return BoundingBox(south, other.west, north, east2)

    def expand(self, meters: float) -> "BoundingBox":
        """Grow the box by ``meters`` on every side.

        Near a pole, or when the grown box would wrap around the globe, the
        longitude range becomes the full circle.
        """
        if isinstance(meters, bool) or not isinstance(meters, (int, float)) or not math.isfinite(meters):
            raise ValidationError(f"expansion distance must be a finite number, got {meters!r}")
        if meters < 0:
            raise ValidationError(f"expansion distance must not be negative, got {meters!r}")
        dlat = math.degrees(meters / EARTH_RADIUS_M)
        south = max(-90.0, self.south - dlat)
        north = min(90.0, self.north + dlat)
        widest_lat = max(abs(south), abs(north))
        if widest_lat >= 90.0:
            return BoundingBox(south, -180.0, north, 180.0)
        dlon = math.degrees(meters / (EARTH_RADIUS_M * math.cos(math.radians(widest_lat))))
        if self.width_deg + 2.0 * dlon >= 360.0:
            return BoundingBox(south, -180.0, north, 180.0)
        return BoundingBox(
            south, normalize_lon(self.west - dlon), north, normalize_lon(self.east + dlon)
        )

    def split(self) -> list["BoundingBox"]:
        """Split at the antimeridian into one or two non-crossing boxes."""
        if not self.crosses_antimeridian:
            return [self]
        return [
            BoundingBox(self.south, self.west, self.north, 180.0),
            BoundingBox(self.south, -180.0, self.north, self.east),
        ]

    def __str__(self) -> str:
        return f"[{self.south:g},{self.west:g} .. {self.north:g},{self.east:g}]"
