# geofence-py

A small computational-geometry and geofencing library for latitude/longitude
data, written in pure Python with no runtime dependencies, plus a `geofence`
command line tool.

It covers the pieces you usually need to answer "where is this device relative
to my zones?":

- validated coordinates and bounding boxes, including boxes that cross the
  antimeridian
- great-circle distance (haversine), ellipsoidal distance (Vincenty inverse on
  WGS-84), bearings, destination point, midpoint, interpolation, cross-track
  and along-track distance
- polylines: length, point at a distance, Douglas-Peucker simplification
- polygons with holes and multipolygons: point-in-polygon with an explicit
  boundary result, area, perimeter, centroid, orientation, validity checks
- circular fences
- geohash encoding, decoding, neighbours and bounding-box covering
- a grid spatial index with "which fences contain this point" and
  k-nearest-fence queries
- a geofence engine that turns per-device position streams into
  enter / exit / dwell events, with an exit margin and sample confirmation to
  stop flapping at a boundary
- readers and writers for WKT and a GeoJSON subset, and a CSV track reader,
  all with typed errors that say where the problem is
- length unit helpers (m, km, mi, nmi, ft)

This is a young project (version 0.1.0). See [Limitations](#limitations) for
what it does not do.

## Install

Python 3.10 or newer is declared in `pyproject.toml`; development and testing
so far have been on Python 3.13 only.

```sh
git clone <repository-url> geofence-py
cd geofence-py
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
```

This installs the `geofence` package and the `geofence` command into the
virtual environment. The package itself needs nothing but the standard
library; the `test` extra adds pytest.

## Conventions

- Inside the library a point is always `(latitude, longitude)` in degrees.
  Functions accept a `Coordinate` or a plain `(lat, lon)` tuple.
- GeoJSON and WKT store `longitude latitude`; the readers and writers convert.
- Distances are metres, bearings are degrees clockwise from north, timestamps
  are seconds (normally Unix time).
- The spherical formulas use the mean Earth radius 6 371 008.8 m.
- Polygon edges are straight lines in longitude/latitude space (the GeoJSON
  model), not great-circle arcs. A ring that crosses the antimeridian is
  handled by unwrapping its longitudes; a ring that encircles a pole is
  rejected.

## Library usage

### Distances and bearings

```python
from geofence import BoundingBox, Coordinate, geodesy, units

berlin, paris = Coordinate(52.52, 13.405), Coordinate(48.8566, 2.3522)

geodesy.haversine_distance(berlin, paris)   # 877465 m on the sphere
geodesy.vincenty_distance(berlin, paris)    # 879699 m on the WGS-84 ellipsoid
geodesy.distance(berlin, paris)             # Vincenty, haversine if it fails to converge
geodesy.initial_bearing(berlin, paris)      # 246.7 degrees
geodesy.destination(berlin, 90, 10_000)     # Coordinate 10 km due east
geodesy.midpoint(berlin, paris)
geodesy.cross_track_distance((50.0, 8.0), berlin, paris)  # -91775 m: left of the path
units.convert(26.2, "mi", "km")             # 42.1648128

box = BoundingBox.from_points([(-17, 179.5), (-18, -179.2)])
box.crosses_antimeridian                    # True
box.contains((-17.5, 180))                  # True
```

`vincenty_distance` raises `ConvergenceError` for nearly antipodal points;
`distance(..., method="auto")` then falls back to the spherical result.

### Polygons

```python
from geofence import Location, Polygon, Ring, validity

square = Ring([(0, 0), (0, 4), (4, 4), (4, 0)])
hole = Ring([(1, 1), (1, 3), (3, 3), (3, 1)])
polygon = Polygon(square, [hole])

polygon.locate((0.5, 0.5))                  # Location.INSIDE
polygon.locate((2, 2))                      # Location.OUTSIDE (in the hole)
polygon.locate((0, 2))                      # Location.BOUNDARY
polygon.contains((0, 2))                    # True: the boundary counts by default
polygon.contains((0, 2), boundary=False)    # False
polygon.area()                              # square metres on the sphere
polygon.centroid()                          # Coordinate(2.0, 2.0)

bow_tie = Ring([(0, 0), (2, 2), (0, 2), (2, 0)])
[issue.code for issue in validity.issues(bow_tie)]   # ['self-intersection']
```

Boundary rules: `locate` returns `BOUNDARY` for a point on an edge or vertex
of any ring (within 1e-12 degrees); the boundary of a hole belongs to the
polygon. Everything else is decided by even-odd ray casting.

### Lines

```python
from geofence import LineString

line = LineString([(0, 0), (0.0001, 0.5), (0, 1), (1, 1)])
line.length()                               # 222390 m
line.simplify(100).coords                   # drops the point 11 m off the straight line
```

### Geohash

```python
from geofence import BoundingBox, geohash

geohash.encode((57.64911, 10.40744), precision=11)   # 'u4pruydqqvj'
geohash.decode("u4pruydqqvj")                        # centre of the cell
geohash.bounds("u4pru")                              # BoundingBox of the cell
geohash.neighbors("u4pru")["n"]                      # 'u4r2h'
geohash.covering(BoundingBox(48.0, 11.0, 48.05, 11.1), precision=5)
# ['u0xc4', 'u0xc5', 'u0xc6', 'u0xc7', 'u0xch', 'u0xck']
```

### Fences, index and engine

```python
from geofence import Circle, Fence, FenceIndex, GeofenceEngine, geodesy

depot = Fence("depot", Circle((48.0, 11.0), 100))

index = FenceIndex([depot])
index.containing((48.0, 11.0))              # [depot]
index.nearest((48.1, 11.0), k=1)            # [(depot, metres to its boundary)]

engine = GeofenceEngine([depot], hysteresis_m=25, dwell_s=60)
for t, metres_east in [(0, 300), (10, 50), (40, 110), (75, 90), (90, 200)]:
    point = geodesy.destination((48.0, 11.0), 90, metres_east)
    for event in engine.update("truck-1", t, point):
        print(t, event.type.value, event.fence_id, event.duration_s)
# 10 enter depot 0.0
# 75 dwell depot 65.0
# 90 exit depot 80.0
```

How the engine decides:

- A device **enters** a fence when a sample is inside it or on its boundary.
- It **exits** when a sample is more than `hysteresis_m` metres outside. In
  the example the sample at t=40 is 10 m outside the 100 m circle, inside the
  25 m margin, so nothing happens.
- With `confirmations=N` a transition is only reported after N consecutive
  samples agree; the event carries the time of the confirming sample.
- With `dwell_s` set, one **dwell** event per visit is emitted by the first
  update at least that long after the enter event.
- Updates for one device must not go back in time (`OutOfOrderError`);
  different devices are independent.

### WKT, GeoJSON and CSV tracks

```python
from geofence import GeoJsonParseError, WktParseError, geojson, wkt

shape = wkt.loads("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 1 3, 3 3, 3 1, 1 1))")
wkt.dumps(shape)   # 'POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 1 3, 3 3, 3 1, 1 1))'

try:
    wkt.loads("POLYGON ((0 0, 4 0, 4 4, 0 4))")
except WktParseError as exc:
    exc.position                            # 9: character offset of the bad ring

try:
    geojson.parse_geometry({"type": "Point", "coordinates": [200, 0]})
except GeoJsonParseError as exc:
    exc.path                                # '$.coordinates'

fences = geojson.read_fences("examples/fences.geojson", strict=True)
text = geojson.dumps_fences(fences, indent=2)
```

Supported formats:

| Format  | Read and written | Rejected with a typed error |
|---------|------------------|-----------------------------|
| WKT     | `POINT`, `LINESTRING`, `POLYGON`, `MULTIPOLYGON` | `EMPTY`, Z/M coordinates, other geometry types, `SRID=` prefixes |
| GeoJSON | `Point`, `LineString`, `Polygon`, `MultiPolygon`; `Feature` and `FeatureCollection` as fences | `MultiPoint`, `MultiLineString`, `GeometryCollection` |

A fence file is a `FeatureCollection` (or a single `Feature`). Polygon and
MultiPolygon features become polygon fences; a `Point` feature with a numeric
`radius_m` property becomes a circular fence. The fence id is the feature
`id`, else the `id` property, else `fence-N`. `strict=True` additionally
rejects invalid polygons (self-intersections, holes outside the exterior, ...).

A track file is CSV with a header row. Required columns: `timestamp` (or
`time`, `ts`), `lat` (`latitude`), `lon` (`lng`, `longitude`); optional:
`device` (`device_id`, `id`). Timestamps are numbers of seconds or ISO-8601
date-times; without an offset they are read as UTC.

### Errors

Every exception raised on purpose for bad input derives from
`geofence.GeofenceError`:

```
GeofenceError
    ValidationError (also ValueError)
        InvalidCoordinateError
        InvalidGeometryError
        UnitError
        GeohashError
    ConvergenceError (also ArithmeticError)
    ParseError (also ValueError)
        WktParseError        .position  character offset
        GeoJsonParseError    .path      JSON path such as $.features[2].geometry
        TrackParseError      .line      one-based line number
    EngineError
        DuplicateFenceError (also ValueError)
        UnknownFenceError (also KeyError)
        OutOfOrderError (also ValueError)
```

## Command line

```sh
$ geofence distance 52.52,13.405 48.1351,11.582 --unit km --bearing
504.689 km
initial bearing 195.571 deg

$ geofence contains examples/fences.geojson 48.005,11.005
depot	Main depot

$ geofence simplify examples/route.wkt --tolerance 20000
LINESTRING (13.405 52.52, 12.9 52.39, 11.9 50.9, 11.582 48.1351)

$ geofence geohash encode 57.64911,10.40744 --precision 11
u4pruydqqvj

$ geofence events examples/fences.geojson examples/track.csv --dwell 180 --hysteresis 20
2026-03-01T08:01:00Z	truck-1	enter	depot
2026-03-01T08:02:00Z	truck-2	enter	gate
2026-03-01T08:05:00Z	truck-1	dwell	depot	240s
2026-03-01T08:07:00Z	truck-1	exit	depot	360s
2026-03-01T08:07:00Z	truck-1	enter	gate
2026-03-01T08:08:00Z	truck-2	exit	gate	360s
2026-03-01T08:09:00Z	truck-1	exit	gate	120s
```

`simplify` and `events` also print a one-line summary to standard error.
The same commands work as `python -m geofence ...`.

| Command | What it does |
|---------|--------------|
| `distance LAT,LON LAT,LON` | Distance between two points. `--method auto\|haversine\|vincenty`, `--unit m\|km\|mi\|nmi\|ft`, `--precision N`, `--bearing`. |
| `contains FENCES.geojson LAT,LON` | Prints `id<TAB>name` for each fence containing the point. `--exclude-boundary`, `--strict`. |
| `simplify INPUT --tolerance METRES` | Douglas-Peucker on a WKT `LINESTRING` or GeoJSON `LineString` read from a file or `-` (standard input). `--format wkt\|geojson`, `--precision N`. |
| `geohash encode\|decode\|neighbors\|cover` | Geohash helpers; `cover` takes `SOUTH,WEST,NORTH,EAST`, `--precision` and `--max-cells`. |
| `events FENCES.geojson TRACK.csv` | Replays the track and prints events. `--hysteresis METRES`, `--dwell SECONDS`, `--confirm N`, `--sort`, `--format text\|json`, `--strict`. |

Coordinates that start with a minus sign (`-33.9,18.4`) can be passed as they
are; no `--` separator is needed.

Exit status:

| Code | Meaning |
|------|---------|
| 0 | success |
| 1 | `contains` found no fence for the point |
| 2 | bad command line (unknown option, malformed coordinate, ...) |
| 3 | an input file or value was read but is not valid |
| 4 | an input file could not be read |

## Project layout

```
src/geofence/
    coords.py     Coordinate, longitude normalisation
    bbox.py       BoundingBox (antimeridian-aware)
    units.py      length unit conversion and formatting
    geodesy.py    haversine, Vincenty inverse, bearings, destination, track distances
    polyline.py   length, point at distance, Douglas-Peucker, LineString
    polygon.py    Ring, Polygon, MultiPolygon, Location
    validity.py   ring and polygon validity checks
    circle.py     Circle (spherical cap)
    geohash.py    encode, decode, neighbours, covering
    fence.py      Fence: an identified shape with signed boundary distance
    index.py      GridIndex and FenceIndex
    engine.py     GeofenceEngine, Event, Position
    wkt.py        WKT reader and writer
    geojson.py    GeoJSON reader and writer, fence collections
    track.py      CSV track reader, timestamp parsing
    cli.py        the geofence command
    errors.py     exception hierarchy
tests/            pytest suite, one file per module plus integration tests
examples/         sample fence, track and route files and a quickstart script
```

## Running the tests

```sh
.venv/bin/python -m pytest
```

The suite needs only pytest and runs in a few seconds. `tests/test_examples.py`
runs the files in `examples/` through the library and the CLI, so the sample
data stays in step with the code.

## Limitations

- The Earth model for polygons is spherical with straight lon/lat edges.
  `area()` is exact on the sphere for edges along meridians and parallels but
  only approximate for diagonal edges, and the error grows with edge length:
  for a right triangle at 40 degrees latitude it is about 0.25 % with
  1-degree legs and about 3 % with 10-degree legs.
- Rings that encircle a pole are not supported, so `Circle.to_polygon` fails
  for a circle that contains a pole. Circles themselves work at the poles.
- Vincenty is implemented for the inverse problem only and does not converge
  for nearly antipodal points.
- Validity checks do not look for overlap between the members of a
  multipolygon.
- The spatial index is a fixed-size grid held in memory; there is no R-tree
  and no persistence. Engine state is in memory only.
- WKT and GeoJSON support is the subset listed above.
- No coordinate reference systems other than WGS-84 longitude/latitude.

## License

MIT, see [LICENSE](LICENSE). Contributions are welcome; see
[CONTRIBUTING.md](CONTRIBUTING.md). Changes are listed in
[CHANGELOG.md](CHANGELOG.md).
