# Contributing

Thanks for looking at geofence-py. Bug reports, test cases and patches are all
welcome.

## Setting up

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/python -m pytest
```

The package has no runtime dependencies and should stay that way: anything
under `src/geofence/` may import only the standard library. pytest is the only
development dependency.

## Ground rules for the code

- **Coordinate order.** Inside the library a point is `(lat, lon)` in degrees.
  Only `wkt.py` and `geojson.py` deal with `lon lat` order, at the point where
  text is read or written. Please do not let the other order leak further in.
- **Units.** Distances are metres, bearings degrees clockwise from north,
  timestamps seconds. Put the unit in the parameter name (`radius_m`,
  `tolerance_m`, `dwell_s`).
- **Errors.** Bad input raises a subclass of `GeofenceError` from
  `errors.py` with a message that names the offending value. Parse errors
  carry a location (`position`, `path` or `line`); keep that location accurate
  when you touch a parser, the tests check it. Programming mistakes such as a
  wrong argument type may raise `TypeError`.
- **Immutability.** `Coordinate`, `BoundingBox`, `Ring`, `Polygon`,
  `MultiPolygon`, `LineString`, `Circle` and `Fence` are treated as immutable
  value objects: operations such as `Ring.reversed()` or
  `LineString.simplify()` return new objects instead of changing the receiver.
- **Antimeridian and poles.** Any change to bounding boxes, rings, the index
  or the geohash code needs a test with data on both sides of longitude 180
  and, where it makes sense, at a pole.
- **Boundary semantics.** `locate` distinguishes `INSIDE`, `BOUNDARY` and
  `OUTSIDE`; `contains` takes a `boundary` flag. New shape types must follow
  the same contract and provide `bbox`, `locate`, `contains` and
  `boundary_distance` so that `Fence`, `FenceIndex` and the engine can use
  them.
- **CLI.** Results go to standard output, diagnostics and summaries to
  standard error. Keep the exit codes documented in the README stable.

## Tests

- Every module has a matching `tests/test_<module>.py`; cross-module flows
  live in `tests/test_integration.py`, and `tests/test_examples.py` runs the
  files under `examples/`.
- A bug fix comes with a test that fails without the fix.
- Tests must be deterministic. Randomised checks use a fixed seed.
- Compare floating-point results with `pytest.approx` and an explicit
  tolerance that reflects the accuracy you expect, not the accuracy you got.
- Tests that write files use the `tmp_path` fixture.

## Commits and pull requests

- One logical change per commit, with a message in the form
  `type(scope): summary` (`feat`, `fix`, `test`, `docs`, `refactor`, `chore`).
- Run the full test suite before sending a pull request.
- If behaviour visible to users changes, update `README.md` and add a line
  under "Unreleased" in `CHANGELOG.md`.

## Reporting bugs

Please include the input that triggers the problem (coordinates, WKT or a
small GeoJSON/CSV file), what you expected, what happened instead, and your
Python version. For geometry problems the smallest ring that still shows the
behaviour helps a lot.
