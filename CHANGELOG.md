# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

Nothing yet.

## 0.1.0 - 2026-11-05

First version. Nothing has been published to a package index; install from a
checkout.

### Added

- `Coordinate` and `BoundingBox` with validation, longitude normalisation and
  support for boxes that cross the antimeridian (contains, contains_box,
  intersects, union, expand, split).
- `geodesy`: haversine distance, Vincenty inverse on WGS-84 with a
  `ConvergenceError` and an `auto` method that falls back to haversine,
  initial and final bearing, destination point, midpoint, interpolation,
  cross-track, along-track and point-to-segment distance.
- `polyline`: length, cumulative distances, point at a distance,
  Douglas-Peucker simplification, and the `LineString` type.
- `polygon`: `Ring`, `Polygon` with holes and `MultiPolygon`, with
  point-in-polygon returning `INSIDE`, `BOUNDARY` or `OUTSIDE`, area,
  perimeter, centroid, orientation and normalisation.
- `validity`: checks for unclosed rings, duplicate vertices, too few distinct
  vertices, zero area, self-intersection, holes outside or crossing the
  exterior and overlapping holes.
- `Circle` fences with conversion to a polygon.
- `geohash`: encode, decode, cell bounds, neighbours and covering of a
  bounding box with a cell limit.
- `Fence`, `GridIndex` and `FenceIndex` with containing, intersecting and
  k-nearest queries.
- `GeofenceEngine` producing enter, exit and dwell events per device, with an
  exit hysteresis margin, consecutive-sample confirmation and out-of-order
  detection.
- WKT reader and writer (`POINT`, `LINESTRING`, `POLYGON`, `MULTIPOLYGON`)
  reporting the character offset of a parse error.
- GeoJSON reader and writer for the same geometry types and for fence
  collections, reporting the JSON path of a parse error; optional strict
  loading that rejects invalid polygons.
- CSV track reader with flexible column names, numeric and ISO-8601
  timestamps and line-numbered errors.
- Length unit helpers for m, km, mi, nmi and ft.
- `geofence` command with `distance`, `contains`, `simplify`, `geohash` and
  `events` subcommands and documented exit codes.
- Example data and a quickstart script under `examples/`.

### Fixed

- Huge integer coordinates and circle radii are reported as typed validation
  errors instead of leaking `OverflowError`.
- `BoundingBox.contains_box` no longer returns false for a box that shares an
  edge with the container because of floating-point rounding.

### Known limitations

See the "Limitations" section of the README.
