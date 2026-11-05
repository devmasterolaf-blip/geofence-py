import math

import pytest

from geofence.coords import Coordinate, as_coordinate, as_coordinates, normalize_lon
from geofence.errors import InvalidCoordinateError


class TestNormalizeLon:
    @pytest.mark.parametrize(
        "lon, expected",
        [
            (0, 0),
            (179.5, 179.5),
            (180, -180),
            (-180, -180),
            (190, -170),
            (-190, 170),
            (360, 0),
            (540, -180),
            (-725, -5),
        ],
    )
    def test_wraps_into_half_open_range(self, lon, expected):
        assert normalize_lon(lon) == pytest.approx(expected)


class TestCoordinate:
    def test_fields_and_tuple_views(self):
        c = Coordinate(48.8566, 2.3522)
        assert c.as_tuple() == (48.8566, 2.3522)
        assert c.as_lonlat() == (2.3522, 48.8566)
        assert Coordinate.from_lonlat(2.3522, 48.8566) == c

    def test_integers_are_stored_as_floats(self):
        c = Coordinate(10, 20)
        assert isinstance(c.lat, float) and isinstance(c.lon, float)

    def test_range_limits_are_inclusive(self):
        Coordinate(90, 180)
        Coordinate(-90, -180)

    @pytest.mark.parametrize("lat, lon", [(90.0001, 0), (-91, 0), (0, 180.5), (0, -181)])
    def test_out_of_range_rejected(self, lat, lon):
        with pytest.raises(InvalidCoordinateError):
            Coordinate(lat, lon)

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, "1.0", None, True])
    def test_non_finite_and_non_numeric_rejected(self, bad):
        with pytest.raises(InvalidCoordinateError):
            Coordinate(bad, 0)
        with pytest.raises(InvalidCoordinateError):
            Coordinate(0, bad)

    def test_error_message_names_the_field(self):
        with pytest.raises(InvalidCoordinateError, match="latitude"):
            Coordinate(123, 0)
        with pytest.raises(InvalidCoordinateError, match="longitude"):
            Coordinate(0, 500)

    def test_is_hashable_and_immutable(self):
        c = Coordinate(1, 2)
        assert {c: "x"}[Coordinate(1, 2)] == "x"
        with pytest.raises(AttributeError):
            c.lat = 5

    def test_wrapped_normalises_longitude_only(self):
        assert Coordinate.wrapped(10, 190) == Coordinate(10, -170)
        assert Coordinate.wrapped(10, -540) == Coordinate(10, -180)
        with pytest.raises(InvalidCoordinateError):
            Coordinate.wrapped(95, 0)
        with pytest.raises(InvalidCoordinateError):
            Coordinate.wrapped(0, math.inf)

    def test_parse(self):
        assert Coordinate.parse("48.85, 2.35") == Coordinate(48.85, 2.35)
        assert Coordinate.parse("-33.9,-70.6") == Coordinate(-33.9, -70.6)

    @pytest.mark.parametrize("text", ["", "1", "1,2,3", "a,b", "1;2", "95,0"])
    def test_parse_rejects_bad_text(self, text):
        with pytest.raises(InvalidCoordinateError):
            Coordinate.parse(text)

    def test_same_place_handles_antimeridian_and_poles(self):
        assert Coordinate(10, 180).same_place(Coordinate(10, -180))
        assert Coordinate(10, 180) != Coordinate(10, -180)
        assert Coordinate(90, 12).same_place(Coordinate(90, -140))
        assert not Coordinate(10, 20).same_place(Coordinate(10, 20.001))
        assert Coordinate(10, 20).same_place(Coordinate(10, 20.001), tolerance_deg=0.01)

    def test_str_uses_six_decimals(self):
        assert str(Coordinate(1.5, -2.25)) == "1.500000,-2.250000"


class TestCoercion:
    def test_accepts_pairs_and_coordinates(self):
        c = Coordinate(1, 2)
        assert as_coordinate(c) is c
        assert as_coordinate((1, 2)) == c
        assert as_coordinate([1, 2]) == c
        assert as_coordinates([(1, 2), c]) == [c, c]

    @pytest.mark.parametrize("bad", [(1, 2, 3), "1,2", 5, None])
    def test_rejects_other_shapes(self, bad):
        with pytest.raises(InvalidCoordinateError):
            as_coordinate(bad)


class TestHugeIntegers:
    """Integers too large for a float must fail like any other out-of-range value."""

    @pytest.mark.parametrize("lat, lon", [(10**400, 0), (0, 10**400), (-(10**400), 0), (0, -(10**400))])
    def test_out_of_range_error_instead_of_overflow(self, lat, lon):
        with pytest.raises(InvalidCoordinateError, match="outside the range"):
            Coordinate(lat, lon)

    def test_from_lonlat(self):
        with pytest.raises(InvalidCoordinateError, match="longitude"):
            Coordinate.from_lonlat(10**400, 0)
