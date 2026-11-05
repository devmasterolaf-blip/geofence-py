"""Geohash encoding, decoding, neighbours and bounding-box covering.

A geohash of precision ``p`` carries ``5 * p`` bits, alternating between
longitude and latitude starting with longitude.  Internally a cell is the
pair of integer indices those bits spell out, which makes neighbour and
covering arithmetic exact.
"""

from __future__ import annotations

from .bbox import BoundingBox
from .coords import Coordinate, CoordinateLike, as_coordinate
from .errors import GeohashError

BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
MAX_PRECISION = 12

_DECODE = {char: value for value, char in enumerate(BASE32)}

#: Direction name -> (latitude step, longitude step) in cells.
DIRECTIONS: dict[str, tuple[int, int]] = {
    "n": (1, 0),
    "ne": (1, 1),
    "e": (0, 1),
    "se": (-1, 1),
    "s": (-1, 0),
    "sw": (-1, -1),
    "w": (0, -1),
    "nw": (1, -1),
}


def _check_precision(precision: int) -> int:
    if isinstance(precision, bool) or not isinstance(precision, int):
        raise GeohashError(f"precision must be an integer, got {precision!r}")
    if not 1 <= precision <= MAX_PRECISION:
        raise GeohashError(f"precision must be between 1 and {MAX_PRECISION}, got {precision}")
    return precision


def _bit_counts(precision: int) -> tuple[int, int]:
    """Number of (latitude, longitude) bits at a precision."""
    total = 5 * precision
    return total // 2, total - total // 2


def _bisect(value: float, low: float, high: float, bits: int) -> int:
    """Index of the cell holding ``value`` after ``bits`` halvings of [low, high]."""
    index = 0
    for _ in range(bits):
        mid = (low + high) / 2.0
        index <<= 1
        if value >= mid:
            index |= 1
            low = mid
        else:
            high = mid
    return index


def _from_cell(lat_index: int, lon_index: int, precision: int) -> str:
    lat_bits, lon_bits = _bit_counts(precision)
    chars = []
    value = 0
    for position in range(5 * precision):
        if position % 2 == 0:
            lon_bits -= 1
            bit = (lon_index >> lon_bits) & 1
        else:
            lat_bits -= 1
            bit = (lat_index >> lat_bits) & 1
        value = (value << 1) | bit
        if position % 5 == 4:
            chars.append(BASE32[value])
            value = 0
    return "".join(chars)


def _to_cell(geohash: str) -> tuple[int, int, int]:
    """Return ``(lat_index, lon_index, precision)`` for a geohash string."""
    if not isinstance(geohash, str):
        raise GeohashError(f"geohash must be a string, got {type(geohash).__name__}")
    text = geohash.lower()
    if not text:
        raise GeohashError("geohash must not be empty")
    if len(text) > MAX_PRECISION:
        raise GeohashError(
            f"geohash {geohash!r} is longer than the supported {MAX_PRECISION} characters"
        )
    lat_index = lon_index = 0
    position = 0
    for offset, char in enumerate(text):
        if char not in _DECODE:
            raise GeohashError(
                f"invalid geohash character {geohash[offset]!r} at position {offset} in {geohash!r}"
            )
        value = _DECODE[char]
        for shift in range(4, -1, -1):
            bit = (value >> shift) & 1
            if position % 2 == 0:
                lon_index = (lon_index << 1) | bit
            else:
                lat_index = (lat_index << 1) | bit
            position += 1
    return lat_index, lon_index, len(text)


def _cell_bounds(lat_index: int, lon_index: int, precision: int) -> BoundingBox:
    lat_bits, lon_bits = _bit_counts(precision)
    lat_step = 180.0 / (1 << lat_bits)
    lon_step = 360.0 / (1 << lon_bits)
    south = -90.0 + lat_index * lat_step
    west = -180.0 + lon_index * lon_step
    return BoundingBox(south, west, min(90.0, south + lat_step), min(180.0, west + lon_step))


def encode(point: CoordinateLike, precision: int = 9) -> str:
    """Geohash of a point with ``precision`` characters (1 to 12)."""
    c = as_coordinate(point)
    lat_bits, lon_bits = _bit_counts(_check_precision(precision))
    lat_index = _bisect(c.lat, -90.0, 90.0, lat_bits)
    lon_index = _bisect(c.lon, -180.0, 180.0, lon_bits)
    return _from_cell(lat_index, lon_index, precision)


def bounds(geohash: str) -> BoundingBox:
    """Bounding box of the cell a geohash names."""
    return _cell_bounds(*_to_cell(geohash))


def decode(geohash: str) -> Coordinate:
    """Centre point of the cell a geohash names."""
    return bounds(geohash).center


def cell_size(precision: int) -> tuple[float, float]:
    """``(height, width)`` of a cell in degrees at the given precision."""
    lat_bits, lon_bits = _bit_counts(_check_precision(precision))
    return 180.0 / (1 << lat_bits), 360.0 / (1 << lon_bits)


def neighbor(geohash: str, direction: str) -> str | None:
    """Adjacent cell in a compass direction (``n``, ``ne``, ``e`` ...).

    Longitude wraps around the antimeridian.  There is nothing north of the
    northernmost row or south of the southernmost one; ``None`` is returned
    there.
    """
    if direction not in DIRECTIONS:
        raise GeohashError(
            f"unknown direction {direction!r} (expected one of: {', '.join(DIRECTIONS)})"
        )
    lat_index, lon_index, precision = _to_cell(geohash)
    lat_bits, lon_bits = _bit_counts(precision)
    dlat, dlon = DIRECTIONS[direction]
    lat_index += dlat
    if not 0 <= lat_index < (1 << lat_bits):
        return None
    lon_index = (lon_index + dlon) % (1 << lon_bits)
    return _from_cell(lat_index, lon_index, precision)


def neighbors(geohash: str) -> dict[str, str]:
    """The up to eight cells around a geohash, keyed by direction."""
    found = {}
    for direction in DIRECTIONS:
        cell = neighbor(geohash, direction)
        if cell is not None:
            found[direction] = cell
    return found


def covering(box: BoundingBox, precision: int, max_cells: int = 4096) -> list[str]:
    """Sorted geohashes of every cell at ``precision`` that touches ``box``.

    Boxes crossing the antimeridian are covered on both sides.  A
    :class:`GeohashError` is raised instead of building a list of more than
    ``max_cells`` cells; pick a coarser precision or raise the limit.
    """
    if not isinstance(box, BoundingBox):
        raise GeohashError(f"expected a BoundingBox, got {type(box).__name__}")
    lat_bits, lon_bits = _bit_counts(_check_precision(precision))
    if isinstance(max_cells, bool) or not isinstance(max_cells, int) or max_cells < 1:
        raise GeohashError(f"max_cells must be a positive integer, got {max_cells!r}")
    spans = []
    total = 0
    for part in box.split():
        lat_lo = _bisect(part.south, -90.0, 90.0, lat_bits)
        lat_hi = _bisect(part.north, -90.0, 90.0, lat_bits)
        lon_lo = _bisect(part.west, -180.0, 180.0, lon_bits)
        lon_hi = _bisect(part.east, -180.0, 180.0, lon_bits)
        spans.append((lat_lo, lat_hi, lon_lo, lon_hi))
        total += (lat_hi - lat_lo + 1) * (lon_hi - lon_lo + 1)
    if total > max_cells:
        raise GeohashError(
            f"covering needs {total} cells at precision {precision}, more than max_cells={max_cells}"
        )
    cells = set()
    for lat_lo, lat_hi, lon_lo, lon_hi in spans:
        for lat_index in range(lat_lo, lat_hi + 1):
            for lon_index in range(lon_lo, lon_hi + 1):
                cells.add(_from_cell(lat_index, lon_index, precision))
    return sorted(cells)
