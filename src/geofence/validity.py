"""Structural validity checks for rings, polygons and multipolygons.

The geometry classes accept anything that can be evaluated; these helpers
report the problems that make results unreliable (self-intersections, holes
outside their shell and so on) without raising, so a caller can decide what
to do with imperfect input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Union

from .coords import CoordinateLike, as_coordinates
from .errors import InvalidGeometryError
from .polygon import Location, MultiPolygon, Polygon, Ring

Point = tuple[float, float]
Shape = Union[Ring, Polygon, MultiPolygon]


@dataclass(frozen=True, slots=True)
class ValidityIssue:
    """One problem found in a shape.

    ``code`` is a stable machine-readable identifier; ``message`` explains
    the problem and where it is.
    """

    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def _orient(a: Point, b: Point, c: Point) -> int:
    """Sign of the turn a -> b -> c: 1 left, -1 right, 0 collinear."""
    cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (cross > 0) - (cross < 0)


def _within_box(a: Point, b: Point, p: Point) -> bool:
    return min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])


def segment_relation(a: Point, b: Point, c: Point, d: Point) -> str | None:
    """How segments ``a-b`` and ``c-d`` meet in the plane.

    Returns ``"cross"`` when they pass through each other at a single interior
    point, ``"touch"`` when they share an end point or overlap along a line,
    and ``None`` when they are disjoint.
    """
    d1, d2 = _orient(c, d, a), _orient(c, d, b)
    d3, d4 = _orient(a, b, c), _orient(a, b, d)
    if d1 * d2 < 0 and d3 * d4 < 0:
        return "cross"
    if (
        (d1 == 0 and _within_box(c, d, a))
        or (d2 == 0 and _within_box(c, d, b))
        or (d3 == 0 and _within_box(a, b, c))
        or (d4 == 0 and _within_box(a, b, d))
    ):
        return "touch"
    return None


def _is_spike(a: Point, b: Point, c: Point) -> bool:
    """True when the path a -> b -> c doubles back on itself at ``b``."""
    if _orient(a, b, c) != 0:
        return False
    return (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) < 0


def ring_issues(ring: Ring, label: str = "ring") -> list[ValidityIssue]:
    """Problems of a single ring: repeated vertices, no area, self-intersection."""
    issues: list[ValidityIssue] = []
    raw = ring.planar_vertices()
    vertices: list[Point] = []
    for index, vertex in enumerate(raw):
        if vertices and vertex == vertices[-1]:
            issues.append(
                ValidityIssue("duplicate-vertex", f"{label}: vertex {index} repeats the previous vertex")
            )
            continue
        vertices.append(vertex)
    if len(vertices) > 1 and vertices[0] == vertices[-1]:
        vertices.pop()
    if len(vertices) < 3:
        issues.append(
            ValidityIssue(
                "too-few-distinct-vertices",
                f"{label}: only {len(vertices)} distinct vertices, need at least 3",
            )
        )
        return issues
    # A signed area of zero is not enough: the two lobes of a bow tie cancel.
    if all(_orient(vertices[0], vertices[1], v) == 0 for v in vertices[2:]):
        issues.append(
            ValidityIssue("zero-area", f"{label}: all vertices lie on one line, so it encloses no area")
        )
        return issues

    n = len(vertices)
    for i in range(n):
        a, b = vertices[i], vertices[(i + 1) % n]
        if _is_spike(a, b, vertices[(i + 2) % n]):
            issues.append(
                ValidityIssue("self-intersection", f"{label}: edges {i} and {(i + 1) % n} double back on each other")
            )
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue  # first and last edge share the starting vertex
            if segment_relation(a, b, vertices[j], vertices[(j + 1) % n]) is not None:
                issues.append(
                    ValidityIssue("self-intersection", f"{label}: edges {i} and {j} intersect")
                )
    return issues


def _aligned_vertices(ring: Ring, reference_x: float) -> list[Point]:
    """Planar vertices shifted by whole turns to sit next to ``reference_x``."""
    vertices = ring.planar_vertices()
    shift = 360.0 * round((reference_x - vertices[0][0]) / 360.0)
    return [(x + shift, y) for x, y in vertices]


def _rings_cross(first: Ring, second: Ring) -> bool:
    a = first.planar_vertices()
    b = _aligned_vertices(second, a[0][0])
    for i in range(len(a)):
        for j in range(len(b)):
            if segment_relation(a[i], a[(i + 1) % len(a)], b[j], b[(j + 1) % len(b)]) == "cross":
                return True
    return False


def polygon_issues(polygon: Polygon, label: str = "polygon") -> list[ValidityIssue]:
    """Problems of a polygon: ring problems plus misplaced or overlapping holes."""
    issues = ring_issues(polygon.exterior, f"{label} exterior")
    for number, hole in enumerate(polygon.holes, start=1):
        issues.extend(ring_issues(hole, f"{label} hole {number}"))
    for number, hole in enumerate(polygon.holes, start=1):
        if any(polygon.exterior.locate(v) is Location.OUTSIDE for v in hole.coords):
            issues.append(
                ValidityIssue("hole-outside-exterior", f"{label} hole {number}: lies partly outside the exterior ring")
            )
        elif _rings_cross(polygon.exterior, hole):
            issues.append(
                ValidityIssue("hole-crosses-exterior", f"{label} hole {number}: crosses the exterior ring")
            )
    holes = polygon.holes
    for i in range(len(holes)):
        for j in range(i + 1, len(holes)):
            overlap = (
                any(holes[j].locate(v) is Location.INSIDE for v in holes[i].coords)
                or any(holes[i].locate(v) is Location.INSIDE for v in holes[j].coords)
                or _rings_cross(holes[i], holes[j])
            )
            if overlap:
                issues.append(
                    ValidityIssue("holes-overlap", f"{label}: holes {i + 1} and {j + 1} overlap")
                )
    return issues


def issues(shape: Shape) -> list[ValidityIssue]:
    """All validity problems of a ring, polygon or multipolygon.

    For a multipolygon each member is checked on its own; overlap between
    members is not examined.
    """
    if isinstance(shape, Ring):
        return ring_issues(shape)
    if isinstance(shape, Polygon):
        return polygon_issues(shape)
    if isinstance(shape, MultiPolygon):
        found: list[ValidityIssue] = []
        for number, polygon in enumerate(shape.polygons, start=1):
            found.extend(polygon_issues(polygon, f"polygon {number}"))
        return found
    raise TypeError(f"cannot check validity of {type(shape).__name__}")


def is_valid(shape: Shape) -> bool:
    """True when :func:`issues` finds nothing."""
    return not issues(shape)


def validate(shape: Shape) -> None:
    """Raise :class:`InvalidGeometryError` listing every problem, if any."""
    found = issues(shape)
    if found:
        raise InvalidGeometryError("; ".join(str(issue) for issue in found))


def check_ring_points(
    points: Iterable[CoordinateLike], require_closed: bool = True
) -> list[ValidityIssue]:
    """Check raw ring input, before it has been turned into a :class:`Ring`.

    Reports an unclosed ring (when ``require_closed`` is set) and too few
    points as issues instead of raising, then adds the usual ring checks if a
    ring can be built at all.
    """
    coords = as_coordinates(points)
    found: list[ValidityIssue] = []
    closed = len(coords) > 1 and coords[0] == coords[-1]
    if require_closed and not closed:
        found.append(
            ValidityIssue("unclosed-ring", "ring: the last point does not repeat the first point")
        )
    try:
        ring = Ring(coords)
    except InvalidGeometryError as exc:
        found.append(ValidityIssue("unusable-ring", f"ring: {exc}"))
        return found
    found.extend(ring_issues(ring))
    return found
