"""Computational geometry and geofencing for latitude/longitude data.

The most commonly used names are re-exported here; everything else lives in
the submodules (``geofence.geodesy``, ``geofence.polyline``,
``geofence.geohash``, ``geofence.wkt``, ``geofence.geojson``, ...).

Coordinates are always ``(latitude, longitude)`` in degrees inside the
library.  GeoJSON and WKT use ``(longitude, latitude)``; the readers and
writers convert at the boundary.
"""

from . import geodesy, geohash, geojson, polyline, track, units, validity, wkt
from .bbox import BoundingBox
from .circle import Circle
from .coords import EARTH_RADIUS_M, Coordinate
from .engine import Event, EventType, GeofenceEngine, Position
from .errors import (
    ConvergenceError,
    DuplicateFenceError,
    EngineError,
    GeofenceError,
    GeohashError,
    GeoJsonParseError,
    InvalidCoordinateError,
    InvalidGeometryError,
    OutOfOrderError,
    ParseError,
    TrackParseError,
    UnitError,
    UnknownFenceError,
    ValidationError,
    WktParseError,
)
from .fence import Fence
from .geodesy import (
    cross_track_distance,
    destination,
    distance,
    haversine_distance,
    initial_bearing,
    midpoint,
    vincenty_distance,
)
from .index import FenceIndex, GridIndex
from .polygon import Location, MultiPolygon, Polygon, Ring
from .polyline import LineString

__version__ = "0.1.0"

__all__ = [
    "BoundingBox",
    "Circle",
    "ConvergenceError",
    "Coordinate",
    "DuplicateFenceError",
    "EARTH_RADIUS_M",
    "EngineError",
    "Event",
    "EventType",
    "Fence",
    "FenceIndex",
    "GeoJsonParseError",
    "GeofenceEngine",
    "GeofenceError",
    "GeohashError",
    "GridIndex",
    "InvalidCoordinateError",
    "InvalidGeometryError",
    "LineString",
    "Location",
    "MultiPolygon",
    "OutOfOrderError",
    "ParseError",
    "Polygon",
    "Position",
    "Ring",
    "TrackParseError",
    "UnitError",
    "UnknownFenceError",
    "ValidationError",
    "WktParseError",
    "__version__",
    "cross_track_distance",
    "destination",
    "distance",
    "geodesy",
    "geohash",
    "geojson",
    "haversine_distance",
    "initial_bearing",
    "midpoint",
    "polyline",
    "track",
    "units",
    "validity",
    "vincenty_distance",
    "wkt",
]
