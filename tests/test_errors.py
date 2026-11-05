import pytest

from geofence import errors


def test_everything_derives_from_base():
    classes = [
        obj
        for obj in vars(errors).values()
        if isinstance(obj, type) and issubclass(obj, Exception)
    ]
    assert len(classes) >= 12
    for cls in classes:
        assert issubclass(cls, errors.GeofenceError)


@pytest.mark.parametrize(
    "cls",
    [
        errors.InvalidCoordinateError,
        errors.InvalidGeometryError,
        errors.UnitError,
        errors.GeohashError,
        errors.WktParseError,
        errors.GeoJsonParseError,
        errors.TrackParseError,
        errors.OutOfOrderError,
    ],
)
def test_value_like_errors_are_value_errors(cls):
    assert issubclass(cls, ValueError)


def test_convergence_error_keeps_iteration_count():
    err = errors.ConvergenceError("did not converge", iterations=200)
    assert isinstance(err, ArithmeticError)
    assert err.iterations == 200


def test_wkt_error_reports_offset():
    err = errors.WktParseError("expected number", position=7)
    assert err.position == 7
    assert str(err) == "expected number (at offset 7)"
    assert errors.WktParseError("empty input").position is None


def test_geojson_error_reports_path():
    err = errors.GeoJsonParseError("missing 'type'", path="$.features[0]")
    assert err.path == "$.features[0]"
    assert str(err) == "$.features[0]: missing 'type'"


def test_track_error_reports_line():
    assert str(errors.TrackParseError("bad latitude", line=3)) == "line 3: bad latitude"
    assert errors.TrackParseError("no header").line is None


def test_unknown_fence_error_has_readable_message():
    err = errors.UnknownFenceError("no fence with id 'depot'")
    assert isinstance(err, KeyError)
    assert str(err) == "no fence with id 'depot'"
