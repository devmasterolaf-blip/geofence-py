"""Reading and writing a subset of GeoJSON (RFC 7946).

Supported geometry types: ``Point``, ``LineString``, ``Polygon`` and
``MultiPolygon``.  Positions are ``[lon, lat]``; an optional third element
(altitude) is accepted and ignored.  Polygon rings must be closed, as the
specification requires.

Fences are read from ``Feature`` objects: polygons and multipolygons map
directly, and a ``Point`` feature with a numeric ``radius_m`` property becomes
a circular fence.

Every problem raises :class:`~geofence.errors.GeoJsonParseError` whose
``path`` attribute points at the offending value, for example
``$.features[2].geometry.coordinates[0][3]``.
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable, Union

from .circle import Circle
from .coords import Coordinate
from .errors import GeoJsonParseError, GeofenceError, InvalidCoordinateError
from .fence import Fence
from .polygon import MultiPolygon, Polygon, Ring
from .polyline import LineString

Geometry = Union[Coordinate, LineString, Polygon, MultiPolygon]

#: Feature property that turns a Point feature into a circular fence.
RADIUS_PROPERTY = "radius_m"

_UNSUPPORTED_TYPES = ("MultiPoint", "MultiLineString", "GeometryCollection")


def loads(text: str) -> Any:
    """Decode JSON text, reporting syntax errors as :class:`GeoJsonParseError`."""
    if not isinstance(text, str):
        raise GeoJsonParseError(f"GeoJSON input must be a string, got {type(text).__name__}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise GeoJsonParseError(
            f"invalid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})"
        ) from None


def _require_object(obj: Any, path: str) -> dict:
    if not isinstance(obj, dict):
        raise GeoJsonParseError(f"expected an object, got {_kind(obj)}", path)
    return obj


def _require_array(obj: Any, path: str, what: str) -> list:
    if not isinstance(obj, list):
        raise GeoJsonParseError(f"expected {what} (an array), got {_kind(obj)}", path)
    return obj


def _kind(obj: Any) -> str:
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "a boolean"
    if isinstance(obj, (int, float)):
        return "a number"
    if isinstance(obj, str):
        return "a string"
    if isinstance(obj, list):
        return "an array"
    if isinstance(obj, dict):
        return "an object"
    return type(obj).__name__


def _position(obj: Any, path: str) -> Coordinate:
    values = _require_array(obj, path, "a position")
    if not 2 <= len(values) <= 3:
        raise GeoJsonParseError(
            f"a position needs 2 or 3 numbers, got {len(values)} elements", path
        )
    for offset, value in enumerate(values):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise GeoJsonParseError(
                f"position element must be a number, got {_kind(value)}", f"{path}[{offset}]"
            )
    try:
        return Coordinate.from_lonlat(values[0], values[1])
    except InvalidCoordinateError as exc:
        raise GeoJsonParseError(str(exc), path) from None


def _positions(obj: Any, path: str, what: str) -> list[Coordinate]:
    values = _require_array(obj, path, what)
    return [_position(value, f"{path}[{index}]") for index, value in enumerate(values)]


def _polygon(obj: Any, path: str) -> Polygon:
    rings_json = _require_array(obj, path, "polygon coordinates")
    if not rings_json:
        raise GeoJsonParseError("a polygon needs at least one ring", path)
    rings = []
    for index, ring_json in enumerate(rings_json):
        ring_path = f"{path}[{index}]"
        points = _positions(ring_json, ring_path, "a linear ring")
        try:
            rings.append(Ring.from_closed(points))
        except GeofenceError as exc:
            raise GeoJsonParseError(str(exc), ring_path) from None
    return Polygon(rings[0], rings[1:])


def parse_geometry(obj: Any, path: str = "$") -> Geometry:
    """Convert a decoded GeoJSON geometry object into a geometry instance."""
    data = _require_object(obj, path)
    kind = data.get("type")
    if not isinstance(kind, str):
        raise GeoJsonParseError("missing or non-string 'type' member", path)
    if kind in _UNSUPPORTED_TYPES:
        raise GeoJsonParseError(f"geometry type {kind!r} is not supported", f"{path}.type")
    if kind not in ("Point", "LineString", "Polygon", "MultiPolygon"):
        raise GeoJsonParseError(f"unknown geometry type {kind!r}", f"{path}.type")
    if "coordinates" not in data:
        raise GeoJsonParseError("missing 'coordinates' member", path)
    coordinates = data["coordinates"]
    coords_path = f"{path}.coordinates"
    if kind == "Point":
        return _position(coordinates, coords_path)
    if kind == "LineString":
        points = _positions(coordinates, coords_path, "line string coordinates")
        try:
            return LineString(points)
        except GeofenceError as exc:
            raise GeoJsonParseError(str(exc), coords_path) from None
    if kind == "Polygon":
        return _polygon(coordinates, coords_path)
    members = _require_array(coordinates, coords_path, "multipolygon coordinates")
    if not members:
        raise GeoJsonParseError("a multipolygon needs at least one polygon", coords_path)
    return MultiPolygon(
        _polygon(member, f"{coords_path}[{index}]") for index, member in enumerate(members)
    )


def _lonlat(c: Coordinate) -> list[float]:
    return [c.lon, c.lat]


def _polygon_coordinates(polygon: Polygon) -> list[list[list[float]]]:
    return [[_lonlat(c) for c in ring.closed_coords] for ring in polygon.rings]


def geometry_to_dict(geometry: Geometry | Ring) -> dict[str, Any]:
    """Convert a geometry instance into a GeoJSON geometry object.

    A bare :class:`Ring` is written as a polygon without holes.  Rings are
    written as stored; call ``normalized()`` first for right-hand-rule output.
    """
    if isinstance(geometry, Coordinate):
        return {"type": "Point", "coordinates": _lonlat(geometry)}
    if isinstance(geometry, LineString):
        return {"type": "LineString", "coordinates": [_lonlat(c) for c in geometry.coords]}
    if isinstance(geometry, Ring):
        geometry = Polygon(geometry)
    if isinstance(geometry, Polygon):
        return {"type": "Polygon", "coordinates": _polygon_coordinates(geometry)}
    if isinstance(geometry, MultiPolygon):
        return {
            "type": "MultiPolygon",
            "coordinates": [_polygon_coordinates(polygon) for polygon in geometry.polygons],
        }
    raise TypeError(f"cannot write {type(geometry).__name__} as a GeoJSON geometry")


def _feature_id(feature: dict, properties: dict, index: int, path: str) -> str:
    for source, where in ((feature, f"{path}.id"), (properties, f"{path}.properties.id")):
        if source.get("id") is None:
            continue
        raw = source["id"]
        if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
            raise GeoJsonParseError(f"feature id must be a string or number, got {_kind(raw)}", where)
        text = str(raw).strip()
        if not text:
            raise GeoJsonParseError("feature id must not be blank", where)
        return text
    return f"fence-{index + 1}"


def _fence_from_feature(obj: Any, index: int, path: str) -> Fence:
    feature = _require_object(obj, path)
    if feature.get("type") != "Feature":
        raise GeoJsonParseError(
            f"expected a Feature, got type {feature.get('type')!r}", f"{path}.type"
        )
    properties = feature.get("properties")
    if properties is None:
        properties = {}
    properties = _require_object(properties, f"{path}.properties")
    fence_id = _feature_id(feature, properties, index, path)
    if feature.get("geometry") is None:
        raise GeoJsonParseError("a fence feature needs a geometry", f"{path}.geometry")
    geometry = parse_geometry(feature["geometry"], f"{path}.geometry")

    name = properties.get("name")
    if name is not None and not isinstance(name, str):
        raise GeoJsonParseError(
            f"'name' must be a string, got {_kind(name)}", f"{path}.properties.name"
        )
    if isinstance(geometry, Coordinate):
        radius_path = f"{path}.properties.{RADIUS_PROPERTY}"
        if RADIUS_PROPERTY not in properties:
            raise GeoJsonParseError(
                f"a Point fence needs a numeric '{RADIUS_PROPERTY}' property", radius_path
            )
        radius = properties[RADIUS_PROPERTY]
        if isinstance(radius, bool) or not isinstance(radius, (int, float)):
            raise GeoJsonParseError(f"radius must be a number, got {_kind(radius)}", radius_path)
        try:
            shape: Any = Circle(geometry, radius)
        except GeofenceError as exc:
            raise GeoJsonParseError(str(exc), radius_path) from None
    elif isinstance(geometry, (Polygon, MultiPolygon)):
        shape = geometry
    else:
        raise GeoJsonParseError(
            "a LineString cannot be used as a fence", f"{path}.geometry.type"
        )
    return Fence(fence_id, shape, name=name or None, properties=properties)


def parse_fences(obj: Any) -> list[Fence]:
    """Build fences from a decoded ``FeatureCollection`` or single ``Feature``.

    The fence id comes from the feature's ``id`` member, else from an ``id``
    property, else it is ``fence-N`` with N the one-based feature position.
    Ids must be unique within the collection.
    """
    root = _require_object(obj, "$")
    kind = root.get("type")
    if kind == "Feature":
        return [_fence_from_feature(root, 0, "$")]
    if kind != "FeatureCollection":
        raise GeoJsonParseError(
            f"expected a FeatureCollection or Feature, got type {kind!r}", "$.type"
        )
    if "features" not in root:
        raise GeoJsonParseError("missing 'features' member", "$")
    features = _require_array(root["features"], "$.features", "features")
    fences: list[Fence] = []
    seen: set[str] = set()
    for index, feature in enumerate(features):
        path = f"$.features[{index}]"
        fence = _fence_from_feature(feature, index, path)
        if fence.id in seen:
            raise GeoJsonParseError(f"duplicate fence id {fence.id!r}", path)
        seen.add(fence.id)
        fences.append(fence)
    return fences


def load_fences(text: str) -> list[Fence]:
    """Parse GeoJSON text into fences (see :func:`parse_fences`)."""
    return parse_fences(loads(text))


def read_fences(path: Union[str, os.PathLike]) -> list[Fence]:
    """Read fences from a UTF-8 GeoJSON file."""
    with open(path, encoding="utf-8") as handle:
        return load_fences(handle.read())


def fences_to_dict(fences: Iterable[Fence]) -> dict[str, Any]:
    """Build a ``FeatureCollection`` object from fences.

    Circles are written as ``Point`` features with a ``radius_m`` property,
    the form :func:`parse_fences` reads back.
    """
    features = []
    for fence in fences:
        properties = dict(fence.properties)
        if fence.name != fence.id:
            properties["name"] = fence.name
        if isinstance(fence.shape, Circle):
            geometry = geometry_to_dict(fence.shape.center)
            properties[RADIUS_PROPERTY] = fence.shape.radius_m
        else:
            geometry = geometry_to_dict(fence.shape)
        features.append(
            {"type": "Feature", "id": fence.id, "properties": properties, "geometry": geometry}
        )
    return {"type": "FeatureCollection", "features": features}


def dumps_fences(fences: Iterable[Fence], indent: int | None = None) -> str:
    """Serialise fences as GeoJSON text."""
    return json.dumps(fences_to_dict(fences), indent=indent, allow_nan=False)
