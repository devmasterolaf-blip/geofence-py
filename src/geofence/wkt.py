"""Reading and writing a subset of Well-Known Text (WKT).

Supported geometry types: ``POINT``, ``LINESTRING``, ``POLYGON`` and
``MULTIPOLYGON``, two-dimensional and non-empty.  WKT writes coordinates as
``x y``, which is ``lon lat``.

Parse failures raise :class:`~geofence.errors.WktParseError` with the
character offset at which the problem was found.
"""

from __future__ import annotations

import re
from typing import Union

from .coords import Coordinate
from .errors import InvalidCoordinateError, InvalidGeometryError, WktParseError
from .polygon import MultiPolygon, Polygon, Ring
from .polyline import LineString

WktGeometry = Union[Coordinate, LineString, Polygon, MultiPolygon]

_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_WORD = re.compile(r"[A-Za-z]+")
_SUPPORTED = ("POINT", "LINESTRING", "POLYGON", "MULTIPOLYGON")
_KNOWN_UNSUPPORTED = (
    "MULTIPOINT",
    "MULTILINESTRING",
    "GEOMETRYCOLLECTION",
    "CIRCULARSTRING",
    "COMPOUNDCURVE",
    "CURVEPOLYGON",
    "TRIANGLE",
    "TIN",
    "POLYHEDRALSURFACE",
)


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def skip_space(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def at_end(self) -> bool:
        self.skip_space()
        return self.pos >= len(self.text)

    def describe_here(self) -> str:
        if self.pos >= len(self.text):
            return "end of input"
        return repr(self.text[self.pos])

    def word(self) -> str | None:
        self.skip_space()
        match = _WORD.match(self.text, self.pos)
        if match is None:
            return None
        self.pos = match.end()
        return match.group().upper()

    def expect(self, char: str) -> None:
        self.skip_space()
        if self.pos >= len(self.text) or self.text[self.pos] != char:
            raise WktParseError(f"expected {char!r} but found {self.describe_here()}", self.pos)
        self.pos += 1

    def accept(self, char: str) -> bool:
        self.skip_space()
        if self.pos < len(self.text) and self.text[self.pos] == char:
            self.pos += 1
            return True
        return False

    def number(self) -> float:
        self.skip_space()
        match = _NUMBER.match(self.text, self.pos)
        if match is None:
            raise WktParseError(f"expected a number but found {self.describe_here()}", self.pos)
        self.pos = match.end()
        return float(match.group())

    # -- grammar ----------------------------------------------------------

    def position(self) -> Coordinate:
        self.skip_space()
        start = self.pos
        lon = self.number()
        lat = self.number()
        self.skip_space()
        if _NUMBER.match(self.text, self.pos):
            raise WktParseError("only two-dimensional coordinates are supported", self.pos)
        try:
            return Coordinate(lat, lon)
        except InvalidCoordinateError as exc:
            raise WktParseError(str(exc), start) from None

    def position_list(self) -> list[Coordinate]:
        self.expect("(")
        points = [self.position()]
        while self.accept(","):
            points.append(self.position())
        self.expect(")")
        return points

    def ring(self) -> Ring:
        self.skip_space()
        start = self.pos
        points = self.position_list()
        try:
            return Ring.from_closed(points)
        except InvalidGeometryError as exc:
            raise WktParseError(str(exc), start) from None

    def polygon(self) -> Polygon:
        self.expect("(")
        rings = [self.ring()]
        while self.accept(","):
            rings.append(self.ring())
        self.expect(")")
        return Polygon(rings[0], rings[1:])

    def geometry(self) -> WktGeometry:
        self.skip_space()
        start = self.pos
        kind = self.word()
        if kind is None:
            raise WktParseError(
                f"expected a geometry type but found {self.describe_here()}", start
            )
        if kind in _KNOWN_UNSUPPORTED:
            raise WktParseError(f"geometry type {kind} is not supported", start)
        if kind not in _SUPPORTED:
            raise WktParseError(f"unknown geometry type {kind!r}", start)
        self.skip_space()
        modifier_at = self.pos
        modifier = self.word()
        if modifier == "EMPTY":
            raise WktParseError(f"empty {kind} geometries are not supported", modifier_at)
        if modifier in ("Z", "M", "ZM"):
            raise WktParseError(
                f"{kind} {modifier}: only two-dimensional geometries are supported", modifier_at
            )
        if modifier is not None:
            raise WktParseError(f"unexpected {modifier!r} after {kind}", modifier_at)

        if kind == "POINT":
            self.expect("(")
            point = self.position()
            self.expect(")")
            return point
        if kind == "LINESTRING":
            self.skip_space()
            line_at = self.pos
            points = self.position_list()
            try:
                return LineString(points)
            except InvalidGeometryError as exc:
                raise WktParseError(str(exc), line_at) from None
        if kind == "POLYGON":
            return self.polygon()
        self.expect("(")
        polygons = [self.polygon()]
        while self.accept(","):
            polygons.append(self.polygon())
        self.expect(")")
        return MultiPolygon(polygons)


def loads(text: str) -> WktGeometry:
    """Parse WKT text into a geometry object.

    ``POINT`` gives a :class:`Coordinate`, ``LINESTRING`` a
    :class:`LineString`, ``POLYGON`` a :class:`Polygon` and ``MULTIPOLYGON``
    a :class:`MultiPolygon`.  Keywords are case-insensitive.
    """
    if not isinstance(text, str):
        raise WktParseError(f"WKT input must be a string, got {type(text).__name__}")
    parser = _Parser(text)
    if parser.at_end():
        raise WktParseError("empty WKT input", 0)
    geometry = parser.geometry()
    if not parser.at_end():
        raise WktParseError(
            f"unexpected {parser.describe_here()} after the end of the geometry", parser.pos
        )
    return geometry


def _number(value: float, precision: int) -> str:
    text = f"{value:.{precision}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _position(c: Coordinate, precision: int) -> str:
    return f"{_number(c.lon, precision)} {_number(c.lat, precision)}"


def _ring_text(ring: Ring, precision: int) -> str:
    return "(" + ", ".join(_position(c, precision) for c in ring.closed_coords) + ")"


def _polygon_text(polygon: Polygon, precision: int) -> str:
    return "(" + ", ".join(_ring_text(ring, precision) for ring in polygon.rings) + ")"


def dumps(geometry: WktGeometry | Ring, precision: int = 6) -> str:
    """Serialise a geometry as WKT with up to ``precision`` decimals.

    Trailing zeros are dropped.  A bare :class:`Ring` is written as a
    polygon without holes.
    """
    if isinstance(precision, bool) or not isinstance(precision, int) or not 0 <= precision <= 15:
        raise ValueError(f"precision must be an integer between 0 and 15, got {precision!r}")
    if isinstance(geometry, Coordinate):
        return f"POINT ({_position(geometry, precision)})"
    if isinstance(geometry, LineString):
        return "LINESTRING (" + ", ".join(_position(c, precision) for c in geometry.coords) + ")"
    if isinstance(geometry, Ring):
        geometry = Polygon(geometry)
    if isinstance(geometry, Polygon):
        return "POLYGON " + _polygon_text(geometry, precision)
    if isinstance(geometry, MultiPolygon):
        return (
            "MULTIPOLYGON ("
            + ", ".join(_polygon_text(polygon, precision) for polygon in geometry.polygons)
            + ")"
        )
    raise TypeError(f"cannot write {type(geometry).__name__} as WKT")
