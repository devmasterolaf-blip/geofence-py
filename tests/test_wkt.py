import pytest

from geofence import wkt
from geofence.circle import Circle
from geofence.coords import Coordinate
from geofence.errors import ParseError, WktParseError
from geofence.polygon import MultiPolygon, Polygon, Ring
from geofence.polyline import LineString

SQUARE = [(0, 0), (0, 10), (10, 10), (10, 0)]
HOLE = [(4, 4), (4, 6), (6, 6), (6, 4)]


class TestLoads:
    def test_point_uses_lon_lat_order(self):
        assert wkt.loads("POINT (2.3522 48.8566)") == Coordinate(48.8566, 2.3522)

    def test_linestring(self):
        assert wkt.loads("LINESTRING (0 0, 1 0, 1 1)") == LineString([(0, 0), (0, 1), (1, 1)])

    def test_polygon_with_hole(self):
        text = "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0), (4 4, 6 4, 6 6, 4 6, 4 4))"
        assert wkt.loads(text) == Polygon(SQUARE, [HOLE])

    def test_multipolygon(self):
        text = "MULTIPOLYGON (((0 0, 10 0, 10 10, 0 10, 0 0)), ((20 20, 21 20, 21 21, 20 20)))"
        geometry = wkt.loads(text)
        assert isinstance(geometry, MultiPolygon)
        assert len(geometry) == 2
        assert geometry.polygons[0] == Polygon(SQUARE)

    def test_case_and_whitespace_are_flexible(self):
        assert wkt.loads("  point(1 2)  ") == Coordinate(2, 1)
        assert wkt.loads("Polygon((0 0,10 0,10 10,0 10,0 0))") == Polygon(SQUARE)
        assert wkt.loads("POINT\n(\t1\n2 )") == Coordinate(2, 1)

    def test_number_formats(self):
        assert wkt.loads("POINT (-1.5e1 +.5)") == Coordinate(0.5, -15.0)
        assert wkt.loads("POINT (5. 1E1)") == Coordinate(10.0, 5.0)


class TestLoadsErrors:
    @pytest.mark.parametrize(
        "text, message, position",
        [
            ("", "empty WKT input", 0),
            ("   ", "empty WKT input", 0),
            ("(1 2)", "expected a geometry type", 0),
            ("CIRCLE (1 2)", "unknown geometry type 'CIRCLE'", 0),
            ("MULTIPOINT (1 2)", "MULTIPOINT is not supported", 0),
            ("POINT 1 2", "expected '('", 6),
            ("POINT (1)", "expected a number but found ')'", 8),
            ("POINT (1 x)", "expected a number but found 'x'", 9),
            ("POINT (1 2", "expected ')' but found end of input", 10),
            ("POINT (1 2) extra", "unexpected 'e' after the end", 12),
            ("POINT (1 2 3)", "two-dimensional", 11),
            ("POINT Z (1 2 3)", "two-dimensional", 6),
            ("POINT EMPTY", "empty POINT", 6),
            ("POINT (200 0)", "longitude", 7),
            ("POINT (0 95)", "latitude", 7),
            ("LINESTRING (1 2)", "at least 2 points", 11),
            ("LINESTRING (1 2, 3 4", "expected ')'", 20),
            ("POLYGON ((0 0, 1 0, 1 1, 0 1))", "not closed", 9),
            ("POLYGON ((0 0, 1 0, 0 0))", "at least 4 points", 9),
            ("POLYGON (0 0, 1 0, 1 1, 0 0)", "expected '('", 9),
            ("POLYGON ((0 0, 1 0, 1 1, 0 0), (5 5, 6 5, 6 6, 5 6))", "not closed", 31),
            ("MULTIPOLYGON ((0 0, 1 0, 1 1, 0 0))", "expected '('", 15),
            ("POLYGON ((0 0, 1 0, 1 1, 0 0)) POINT (1 1)", "unexpected 'P'", 31),
        ],
    )
    def test_message_and_offset(self, text, message, position):
        with pytest.raises(WktParseError) as info:
            wkt.loads(text)
        assert message in str(info.value)
        assert info.value.position == position

    def test_error_is_a_parse_error_and_value_error(self):
        with pytest.raises(ParseError):
            wkt.loads("nope")
        with pytest.raises(ValueError):
            wkt.loads("nope")

    def test_non_string_input(self):
        with pytest.raises(WktParseError, match="must be a string"):
            wkt.loads(b"POINT (1 2)")


class TestDumps:
    def test_point(self):
        assert wkt.dumps(Coordinate(48.8566, 2.3522)) == "POINT (2.3522 48.8566)"

    def test_linestring(self):
        assert wkt.dumps(LineString([(0, 0), (0.5, 1)])) == "LINESTRING (0 0, 1 0.5)"

    def test_polygon_is_written_closed(self):
        assert wkt.dumps(Polygon(SQUARE, [HOLE])) == (
            "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0), (4 4, 6 4, 6 6, 4 6, 4 4))"
        )

    def test_ring_is_written_as_polygon(self):
        assert wkt.dumps(Ring(SQUARE)) == "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))"

    def test_multipolygon(self):
        multi = MultiPolygon([SQUARE, [(20, 20), (20, 21), (21, 21)]])
        assert wkt.dumps(multi) == (
            "MULTIPOLYGON (((0 0, 10 0, 10 10, 0 10, 0 0)), ((20 20, 21 20, 21 21, 20 20)))"
        )

    def test_precision_and_negative_zero(self):
        point = Coordinate(1.23456789, -0.00000001)
        assert wkt.dumps(point) == "POINT (0 1.234568)"
        assert wkt.dumps(point, precision=2) == "POINT (0 1.23)"
        assert wkt.dumps(point, precision=0) == "POINT (0 1)"
        assert wkt.dumps(Coordinate(10, 100), precision=0) == "POINT (100 10)"

    def test_bad_precision_and_type(self):
        with pytest.raises(ValueError):
            wkt.dumps(Coordinate(0, 0), precision=-1)
        with pytest.raises(TypeError):
            wkt.dumps(Circle((0, 0), 10))

    @pytest.mark.parametrize(
        "geometry",
        [
            Coordinate(-33.8688, 151.2093),
            LineString([(0, 0), (1.5, 2.25), (-3, 4)]),
            Polygon(SQUARE, [HOLE]),
            MultiPolygon([Polygon(SQUARE, [HOLE]), [(20, 20), (20, 21), (21, 21)]]),
            Polygon([(-5, 175), (-5, -175), (5, -175), (5, 175)]),
        ],
    )
    def test_round_trip(self, geometry):
        assert wkt.loads(wkt.dumps(geometry)) == geometry
