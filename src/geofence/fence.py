"""A fence: an identified shape that positions can be tested against."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping, Union

from .bbox import BoundingBox
from .circle import Circle
from .coords import CoordinateLike, as_coordinate
from .errors import InvalidGeometryError, ValidationError
from .polygon import Location, MultiPolygon, Polygon, Ring

FenceShape = Union[Polygon, MultiPolygon, Circle]


class Fence:
    """A shape with an id, an optional display name and free-form properties.

    ``shape`` may be a :class:`Polygon`, :class:`MultiPolygon` or
    :class:`Circle`; a bare :class:`Ring` is promoted to a polygon.  The
    bounding box is computed once, since fences are immutable.
    """

    __slots__ = ("_id", "_shape", "_name", "_properties", "_bbox")

    def __init__(
        self,
        fence_id: str,
        shape: Union[FenceShape, Ring],
        name: str | None = None,
        properties: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(fence_id, str) or not fence_id.strip():
            raise ValidationError(f"fence id must be a non-empty string, got {fence_id!r}")
        if isinstance(shape, Ring):
            shape = Polygon(shape)
        if not isinstance(shape, (Polygon, MultiPolygon, Circle)):
            raise InvalidGeometryError(
                f"fence shape must be a Polygon, MultiPolygon or Circle, got {type(shape).__name__}"
            )
        if name is not None and not isinstance(name, str):
            raise ValidationError(f"fence name must be a string, got {name!r}")
        self._id = fence_id
        self._shape = shape
        self._name = name if name else fence_id
        self._properties = MappingProxyType(dict(properties or {}))
        self._bbox = shape.bbox

    @property
    def id(self) -> str:
        return self._id

    @property
    def shape(self) -> FenceShape:
        return self._shape

    @property
    def name(self) -> str:
        """Display name; falls back to the id when none was given."""
        return self._name

    @property
    def properties(self) -> Mapping[str, Any]:
        """Read-only view of the extra properties."""
        return self._properties

    @property
    def bbox(self) -> BoundingBox:
        return self._bbox

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Fence) and self._id == other._id and self._shape == other._shape

    def __hash__(self) -> int:
        return hash((self._id, self._shape))

    def __repr__(self) -> str:
        return f"Fence({self._id!r}, {type(self._shape).__name__})"

    def locate(self, point: CoordinateLike) -> Location:
        c = as_coordinate(point)
        if not self._bbox.contains(c):
            return Location.OUTSIDE
        return self._shape.locate(c)

    def contains(self, point: CoordinateLike, boundary: bool = True) -> bool:
        """True when the point is inside the fence (boundary included by default)."""
        location = self.locate(point)
        if location is Location.BOUNDARY:
            return boundary
        return location is Location.INSIDE

    def signed_distance(self, point: CoordinateLike) -> float:
        """Metres to the fence boundary: negative inside, positive outside, 0 on it."""
        c = as_coordinate(point)
        location = self.locate(c)
        if location is Location.BOUNDARY:
            return 0.0
        d = self._shape.boundary_distance(c)
        return -d if location is Location.INSIDE else d

    def distance_to(self, point: CoordinateLike) -> float:
        """Metres from the point to the fence; ``0.0`` when the point is inside."""
        return max(0.0, self.signed_distance(point))
