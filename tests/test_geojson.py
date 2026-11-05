import json

import pytest

from geofence import geojson
from geofence.circle import Circle
from geofence.coords import Coordinate
from geofence.errors import GeoJsonParseError, ParseError
from geofence.fence import Fence
from geofence.polygon import MultiPolygon, Polygon, Ring
from geofence.polyline import LineString

SQUARE = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
HOLE = [[0.5, 0.5], [0.5, 1.5], [1.5, 1.5], [1.5, 0.5], [0.5, 0.5]]


def feature(geometry, fid=None, **properties):
    out = {"type": "Feature", "properties": properties, "geometry": geometry}
    if fid is not None:
        out["id"] = fid
    return out


def collection(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def polygon_geometry(*rings):
    return {"type": "Polygon", "coordinates": list(rings)}


def error_for(obj):
    with pytest.raises(GeoJsonParseError) as info:
        geojson.parse_fences(obj)
    return info.value


class TestLoads:
    def test_decodes_json(self):
        assert geojson.loads('{"type": "Point"}') == {"type": "Point"}

    def test_syntax_error_reports_line_and_column(self):
        with pytest.raises(GeoJsonParseError, match=r"invalid JSON: .*line 2, column"):
            geojson.loads('{\n"type": }')

    def test_syntax_error_is_a_parse_error_and_value_error(self):
        with pytest.raises(ParseError):
            geojson.loads("")
        with pytest.raises(ValueError):
            geojson.loads("{")

    def test_rejects_non_string_input(self):
        with pytest.raises(GeoJsonParseError, match="must be a string"):
            geojson.loads(b"{}")


class TestParseGeometry:
    def test_point_swaps_to_lat_lon(self):
        point = geojson.parse_geometry({"type": "Point", "coordinates": [13.4, 52.5]})
        assert point == Coordinate(52.5, 13.4)

    def test_altitude_is_ignored(self):
        point = geojson.parse_geometry({"type": "Point", "coordinates": [13.4, 52.5, 34.0]})
        assert point == Coordinate(52.5, 13.4)

    def test_line_string(self):
        line = geojson.parse_geometry({"type": "LineString", "coordinates": [[0, 0], [1, 1], [2, 0]]})
        assert isinstance(line, LineString)
        assert line.coords[1] == Coordinate(1, 1)

    def test_polygon_with_hole(self):
        polygon = geojson.parse_geometry(polygon_geometry(SQUARE, HOLE))
        assert isinstance(polygon, Polygon)
        assert len(polygon.holes) == 1
        assert polygon.contains((0.25, 0.25))
        assert not polygon.contains((1.0, 1.0))

    def test_multipolygon(self):
        far = [[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]
        shape = geojson.parse_geometry({"type": "MultiPolygon", "coordinates": [[SQUARE], [far]]})
        assert isinstance(shape, MultiPolygon)
        assert len(shape.polygons) == 2
        assert shape.contains((10.5, 10.5))

    @pytest.mark.parametrize(
        "obj, path, fragment",
        [
            ([], "$", "expected an object, got an array"),
            ({}, "$", "missing or non-string 'type'"),
            ({"type": 3}, "$", "missing or non-string 'type'"),
            ({"type": "Circle"}, "$.type", "unknown geometry type 'Circle'"),
            ({"type": "MultiPoint", "coordinates": []}, "$.type", "not supported"),
            ({"type": "GeometryCollection", "geometries": []}, "$.type", "not supported"),
            ({"type": "Point"}, "$", "missing 'coordinates'"),
            ({"type": "Point", "coordinates": None}, "$.coordinates", "got null"),
            ({"type": "Point", "coordinates": [1]}, "$.coordinates", "2 or 3 numbers"),
            ({"type": "Point", "coordinates": [1, 2, 3, 4]}, "$.coordinates", "2 or 3 numbers"),
            ({"type": "Point", "coordinates": [1, "2"]}, "$.coordinates[1]", "got a string"),
            ({"type": "Point", "coordinates": [True, 2]}, "$.coordinates[0]", "got a boolean"),
            ({"type": "Point", "coordinates": [0, 91]}, "$.coordinates", "latitude"),
            ({"type": "LineString", "coordinates": [[0, 0]]}, "$.coordinates", "at least 2"),
            (
                {"type": "LineString", "coordinates": [[0, 0], [1, {}]]},
                "$.coordinates[1][1]",
                "got an object",
            ),
            ({"type": "Polygon", "coordinates": []}, "$.coordinates", "at least one ring"),
            ({"type": "Polygon", "coordinates": [SQUARE[:-1]]}, "$.coordinates[0]", "closed"),
            ({"type": "Polygon", "coordinates": [SQUARE, HOLE[:-1]]}, "$.coordinates[1]", "closed"),
            (
                {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 0]]]},
                "$.coordinates[0]",
                "",
            ),
            (
                {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 100], [0, 0]]]},
                "$.coordinates[0][2]",
                "latitude",
            ),
            ({"type": "MultiPolygon", "coordinates": []}, "$.coordinates", "at least one polygon"),
            (
                {"type": "MultiPolygon", "coordinates": [[SQUARE], [SQUARE[:-1]]]},
                "$.coordinates[1][0]",
                "closed",
            ),
        ],
    )
    def test_errors_carry_the_json_path(self, obj, path, fragment):
        with pytest.raises(GeoJsonParseError) as info:
            geojson.parse_geometry(obj)
        assert info.value.path == path
        assert fragment in str(info.value)
        assert str(info.value).startswith(path + ": ")

    def test_custom_root_path_is_used(self):
        with pytest.raises(GeoJsonParseError) as info:
            geojson.parse_geometry({"type": "Point", "coordinates": [0]}, path="$.geometry")
        assert info.value.path == "$.geometry.coordinates"


class TestGeometryToDict:
    def test_point(self):
        assert geojson.geometry_to_dict(Coordinate(52.5, 13.4)) == {
            "type": "Point",
            "coordinates": [13.4, 52.5],
        }

    def test_line_string(self):
        line = LineString([(0, 0), (1, 2)])
        assert geojson.geometry_to_dict(line) == {
            "type": "LineString",
            "coordinates": [[0, 0], [2, 1]],
        }

    def test_polygon_rings_are_closed(self):
        out = geojson.geometry_to_dict(geojson.parse_geometry(polygon_geometry(SQUARE, HOLE)))
        assert out == {"type": "Polygon", "coordinates": [SQUARE, HOLE]}

    def test_ring_is_written_as_polygon(self):
        out = geojson.geometry_to_dict(Ring([(0, 0), (0, 2), (2, 2)]))
        assert out["type"] == "Polygon"
        assert out["coordinates"] == [[[0, 0], [2, 0], [2, 2], [0, 0]]]

    def test_multipolygon_round_trip(self):
        far = [[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]
        obj = {"type": "MultiPolygon", "coordinates": [[SQUARE, HOLE], [far]]}
        assert geojson.geometry_to_dict(geojson.parse_geometry(obj)) == obj

    def test_antimeridian_ring_keeps_original_longitudes(self):
        ring = [[179, 0], [-179, 0], [-179, 1], [179, 1], [179, 0]]
        obj = polygon_geometry(ring)
        assert geojson.geometry_to_dict(geojson.parse_geometry(obj)) == obj

    def test_unsupported_object_raises_type_error(self):
        with pytest.raises(TypeError, match="Circle"):
            geojson.geometry_to_dict(Circle((0, 0), 10))


class TestParseFences:
    def test_feature_collection(self):
        fences = geojson.parse_fences(
            collection(
                feature(polygon_geometry(SQUARE), fid="depot", name="Main depot", zone="a"),
                feature({"type": "Point", "coordinates": [10, 20]}, fid="gate", radius_m=150),
            )
        )
        assert [f.id for f in fences] == ["depot", "gate"]
        assert fences[0].name == "Main depot"
        assert fences[0].properties["zone"] == "a"
        assert isinstance(fences[0].shape, Polygon)
        assert isinstance(fences[1].shape, Circle)
        assert fences[1].shape.center == Coordinate(20, 10)
        assert fences[1].shape.radius_m == 150
        assert fences[1].name == "gate"

    def test_single_feature(self):
        fences = geojson.parse_fences(feature(polygon_geometry(SQUARE), fid="only"))
        assert [f.id for f in fences] == ["only"]

    def test_id_falls_back_to_property_then_position(self):
        fences = geojson.parse_fences(
            collection(
                feature(polygon_geometry(SQUARE), id="from-property"),
                feature(polygon_geometry(SQUARE)),
                feature(polygon_geometry(SQUARE), fid=17),
            )
        )
        assert [f.id for f in fences] == ["from-property", "fence-2", "17"]

    def test_null_properties_are_allowed(self):
        obj = {"type": "Feature", "id": "a", "properties": None, "geometry": polygon_geometry(SQUARE)}
        (fence,) = geojson.parse_fences(obj)
        assert dict(fence.properties) == {}

    def test_empty_collection_gives_no_fences(self):
        assert geojson.parse_fences(collection()) == []

    @pytest.mark.parametrize(
        "obj, path, fragment",
        [
            ([], "$", "expected an object"),
            ({"type": "Polygon", "coordinates": [SQUARE]}, "$.type", "FeatureCollection or Feature"),
            ({"type": "FeatureCollection"}, "$", "missing 'features'"),
            ({"type": "FeatureCollection", "features": {}}, "$.features", "got an object"),
            (collection("nope"), "$.features[0]", "expected an object, got a string"),
            (collection(polygon_geometry(SQUARE)), "$.features[0].type", "expected a Feature"),
            (
                collection({"type": "Feature", "properties": {}, "geometry": None}),
                "$.features[0].geometry",
                "needs a geometry",
            ),
            (
                collection({"type": "Feature", "properties": [], "geometry": polygon_geometry(SQUARE)}),
                "$.features[0].properties",
                "expected an object",
            ),
            (
                collection(feature(polygon_geometry(SQUARE), fid=["x"])),
                "$.features[0].id",
                "string or number",
            ),
            (
                collection(feature(polygon_geometry(SQUARE), fid="  ")),
                "$.features[0].id",
                "must not be blank",
            ),
            (
                collection(feature(polygon_geometry(SQUARE), id=True)),
                "$.features[0].properties.id",
                "string or number",
            ),
            (
                collection(feature(polygon_geometry(SQUARE), name=5)),
                "$.features[0].properties.name",
                "'name' must be a string",
            ),
            (
                collection(feature({"type": "Point", "coordinates": [0, 0]})),
                "$.features[0].properties.radius_m",
                "needs a numeric 'radius_m'",
            ),
            (
                collection(feature({"type": "Point", "coordinates": [0, 0]}, radius_m="10")),
                "$.features[0].properties.radius_m",
                "radius must be a number",
            ),
            (
                collection(feature({"type": "Point", "coordinates": [0, 0]}, radius_m=-5)),
                "$.features[0].properties.radius_m",
                "radius",
            ),
            (
                collection(feature({"type": "LineString", "coordinates": [[0, 0], [1, 1]]})),
                "$.features[0].geometry.type",
                "cannot be used as a fence",
            ),
            (
                collection(
                    feature(polygon_geometry(SQUARE), fid="a"),
                    feature(polygon_geometry([[0, 0], [1, 0], [1, 95], [0, 0]]), fid="b"),
                ),
                "$.features[1].geometry.coordinates[0][2]",
                "latitude",
            ),
            (
                collection(
                    feature(polygon_geometry(SQUARE), fid="a"),
                    feature(polygon_geometry(SQUARE), fid="a"),
                ),
                "$.features[1]",
                "duplicate fence id 'a'",
            ),
        ],
    )
    def test_errors_carry_the_json_path(self, obj, path, fragment):
        error = error_for(obj)
        assert error.path == path
        assert fragment in str(error)

    def test_generated_id_can_collide_with_an_explicit_one(self):
        error = error_for(
            collection(
                feature(polygon_geometry(SQUARE), fid="fence-2"),
                feature(polygon_geometry(SQUARE)),
            )
        )
        assert "duplicate fence id 'fence-2'" in str(error)


class TestFenceSerialisation:
    def fences(self):
        return [
            Fence("depot", Polygon(Ring([(0, 0), (0, 2), (2, 2), (2, 0)])), name="Main depot",
                  properties={"zone": "a"}),
            Fence("gate", Circle((20, 10), 150.0)),
        ]

    def test_feature_collection_layout(self):
        out = geojson.fences_to_dict(self.fences())
        assert out["type"] == "FeatureCollection"
        depot, gate = out["features"]
        assert depot["id"] == "depot"
        assert depot["properties"] == {"zone": "a", "name": "Main depot"}
        assert depot["geometry"]["type"] == "Polygon"
        assert gate["geometry"] == {"type": "Point", "coordinates": [10, 20]}
        assert gate["properties"] == {"radius_m": 150.0}

    def test_text_round_trip(self):
        text = geojson.dumps_fences(self.fences(), indent=2)
        again = geojson.load_fences(text)
        assert [f.id for f in again] == ["depot", "gate"]
        assert again[0].name == "Main depot"
        assert again[0].properties["zone"] == "a"
        assert again[0].shape.exterior.coords == self.fences()[0].shape.exterior.coords
        assert again[1].shape.radius_m == 150.0
        assert geojson.dumps_fences(again, indent=2) == text

    def test_compact_output_is_valid_json(self):
        text = geojson.dumps_fences(self.fences())
        assert "\n" not in text
        assert json.loads(text)["features"][1]["id"] == "gate"

    def test_read_fences_from_file(self, tmp_path):
        path = tmp_path / "fences.geojson"
        path.write_text(geojson.dumps_fences(self.fences()), encoding="utf-8")
        assert [f.id for f in geojson.read_fences(path)] == ["depot", "gate"]

    def test_read_fences_reports_bad_content(self, tmp_path):
        path = tmp_path / "broken.geojson"
        path.write_text('{"type": "FeatureCollection", "features": [1]}', encoding="utf-8")
        with pytest.raises(GeoJsonParseError) as info:
            geojson.read_fences(path)
        assert info.value.path == "$.features[0]"
