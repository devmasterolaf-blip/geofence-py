"""End-to-end checks that run several modules together."""

import json
import math
import random

import pytest

import geofence
from geofence import geodesy, geohash, geojson, polyline, wkt
from geofence.cli import EXIT_OK, main
from geofence.coords import normalize_lon
from geofence.polygon import Location
from geofence.track import parse_track


def kinds(events):
    return [(e.type.value, e.fence_id) for e in events]


class TestAntimeridianFence:
    """A fence around the 180th meridian, defined in WKT, used everywhere."""

    @pytest.fixture
    def fence(self):
        shape = wkt.loads("POLYGON ((179 -18, -179 -18, -179 -16, 179 -16, 179 -18))")
        return geofence.Fence("fiji", shape)

    def test_bounding_box_crosses_and_is_narrow(self, fence):
        assert fence.bbox.crosses_antimeridian
        assert fence.bbox.width_deg == pytest.approx(2.0)

    def test_index_finds_it_from_both_sides(self, fence):
        index = geofence.FenceIndex([fence])
        for point in [(-17, 179.5), (-17, -179.5), (-17, 180), (-17, -180)]:
            assert [f.id for f in index.containing(point)] == ["fiji"], point
        for point in [(-17, 178.9), (-17, -178.9), (-17, 0), (-15.9, 180)]:
            assert index.containing(point) == [], point

    def test_signed_distance_is_continuous_across_the_meridian(self, fence):
        west = fence.signed_distance((-17, 179.999))
        east = fence.signed_distance((-17, -179.999))
        assert west == pytest.approx(east, abs=1e-6)
        assert west < -100_000

    def test_engine_follows_a_boat_across(self, fence):
        engine = geofence.GeofenceEngine([fence], hysteresis_m=5_000)
        track = [(-17, 178.5), (-17, 179.5), (-17, -179.5), (-17, -178.99), (-17, -178.9)]
        seen = [kinds(engine.update("boat", t, point)) for t, point in enumerate(track)]
        assert seen == [[], [("enter", "fiji")], [], [], [("exit", "fiji")]]

    def test_survives_geojson_and_wkt_round_trips(self, fence):
        (again,) = geojson.load_fences(geojson.dumps_fences([fence]))
        assert again.shape == fence.shape
        assert wkt.loads(wkt.dumps(fence.shape)) == fence.shape

    def test_geohash_covering_spans_both_sides(self, fence):
        cells = geohash.covering(fence.bbox, 3)
        assert geohash.encode((-17, 179.9), 3) in cells
        assert geohash.encode((-17, -179.9), 3) in cells
        assert geohash.encode((-17, 0), 3) not in cells


class TestCircleAgainstItsPolygon:
    def test_membership_agrees_away_from_the_rim(self):
        rnd = random.Random(21)
        circle = geofence.Circle((60, 10), 5_000)
        polygon = circle.to_polygon(256)
        for _ in range(1500):
            point = geodesy.destination(circle.center, rnd.uniform(0, 360), rnd.uniform(0, 10_000))
            if abs(geodesy.haversine_distance(circle.center, point) - 5_000) < 5:
                continue
            assert circle.contains(point) == polygon.contains(point)

    def test_polygon_area_approaches_the_cap_area(self):
        circle = geofence.Circle((0, 179.9), 50_000)
        assert circle.to_polygon(256).area() == pytest.approx(circle.area(), rel=2e-3)

    def test_polar_cap_is_found_through_the_index(self):
        cap = geofence.Fence("pole", geofence.Circle((89.9, 0), 50_000))
        index = geofence.FenceIndex([cap])
        for point in [(90, 0), (89.95, 180), (89.95, -90), (89.7, 180)]:
            assert [f.id for f in index.containing(point)] == ["pole"], point
        assert index.containing((89.4, 180)) == []


class TestPointInPolygonAgainstWindingNumber:
    """Cross-check ray casting with an independent winding-number test."""

    @staticmethod
    def winding(point, ring):
        x, y = point
        number = 0
        for i, (x1, y1) in enumerate(ring):
            x2, y2 = ring[(i + 1) % len(ring)]
            cross = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
            if cross == 0 and min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2):
                return None
            if y1 <= y:
                if y2 > y and cross > 0:
                    number += 1
            elif y2 <= y and cross < 0:
                number -= 1
        return number

    @pytest.mark.parametrize("shift", [0, 176, -178])
    def test_integer_grid_polygons(self, shift):
        rnd = random.Random(shift)
        checked = 0
        for _ in range(400):
            corners = set()
            while len(corners) < rnd.randint(3, 7):
                corners.add((rnd.randint(-5, 5), rnd.randint(-5, 5)))
            # Sorting by angle around an off-grid centre gives a simple polygon.
            outline = sorted(corners, key=lambda p: math.atan2(p[1] - 0.01, p[0] - 0.013))
            try:
                ring = geofence.Ring([(y, normalize_lon(x + shift)) for x, y in outline])
            except geofence.InvalidGeometryError:
                continue
            for _ in range(30):
                query = (rnd.randint(-6, 6), rnd.randint(-6, 6))
                number = self.winding(query, outline)
                if number is None:
                    expected = Location.BOUNDARY
                else:
                    expected = Location.INSIDE if number % 2 else Location.OUTSIDE
                got = ring.locate((query[1], normalize_lon(query[0] + shift)))
                assert got is expected, (outline, shift, query)
                checked += 1
        assert checked > 5_000


class TestEngineAgainstBruteForce:
    def test_random_walk_over_many_fences(self):
        rnd = random.Random(3)
        fences = []
        for number in range(60):
            lat, lon = rnd.uniform(-1, 1), rnd.uniform(179, 181)
            if number % 2:
                shape = geofence.Circle((lat, normalize_lon(lon)), rnd.uniform(2_000, 30_000))
            else:
                half = rnd.uniform(0.02, 0.3)
                shape = geofence.Polygon(
                    geofence.Ring(
                        [
                            (lat - half, normalize_lon(lon - half)),
                            (lat - half, normalize_lon(lon + half)),
                            (lat + half, normalize_lon(lon + half)),
                            (lat + half, normalize_lon(lon - half)),
                        ]
                    )
                )
            fences.append(geofence.Fence(f"f{number:02d}", shape))
        engine = geofence.GeofenceEngine(fences, cell_size_deg=0.1)

        lat, lon = 0.0, 180.0
        inside = set()
        events = 0
        for step in range(1500):
            lat = max(-1.5, min(1.5, lat + rnd.uniform(-0.05, 0.05)))
            lon += rnd.uniform(-0.05, 0.05)
            point = (lat, normalize_lon(lon))
            for event in engine.update("walker", step, point):
                events += 1
                if event.type is geofence.EventType.ENTER:
                    assert event.fence_id not in inside
                    inside.add(event.fence_id)
                else:
                    assert event.type is geofence.EventType.EXIT
                    inside.remove(event.fence_id)
            assert inside == {f.id for f in fences if f.contains(point)}
            assert set(engine.inside("walker")) == inside
        assert events > 50

    def test_nearest_matches_a_linear_scan(self):
        rnd = random.Random(8)
        fences = [
            geofence.Fence(
                f"c{number}",
                geofence.Circle(
                    (rnd.uniform(-2, 2), normalize_lon(rnd.uniform(177, 183))), rnd.uniform(500, 20_000)
                ),
            )
            for number in range(40)
        ]
        index = geofence.FenceIndex(fences, cell_size_deg=0.2)
        for _ in range(100):
            point = (rnd.uniform(-3, 3), normalize_lon(rnd.uniform(176, 184)))
            expected = sorted(f.distance_to(point) for f in fences)[:3]
            got = [d for _, d in index.nearest(point, k=3)]
            assert got == pytest.approx(expected, abs=1e-6)


class TestHolesAndMultipolygonsInTheEngine:
    def test_walking_into_a_hole_leaves_the_fence(self):
        donut = geofence.Polygon(
            geofence.Ring([(0, 0), (0, 0.1), (0.1, 0.1), (0.1, 0)]),
            [geofence.Ring([(0.04, 0.04), (0.04, 0.06), (0.06, 0.06), (0.06, 0.04)])],
        )
        engine = geofence.GeofenceEngine([geofence.Fence("donut", donut)], hysteresis_m=500)
        assert kinds(engine.update("d", 0, (0.02, 0.02))) == [("enter", "donut")]
        # 111 m into the hole: still within the exit margin.
        assert engine.update("d", 1, (0.041, 0.05)) == []
        # Centre of the hole, about 1.1 km from its edge.
        assert kinds(engine.update("d", 2, (0.05, 0.05))) == [("exit", "donut")]
        assert kinds(engine.update("d", 3, (0.02, 0.02))) == [("enter", "donut")]

    def test_hopping_between_multipolygon_parts_with_a_wide_margin(self):
        parts = geofence.MultiPolygon(
            [
                geofence.Polygon(geofence.Ring([(0, 0), (0, 0.01), (0.01, 0.01), (0.01, 0)])),
                geofence.Polygon(geofence.Ring([(0, 0.02), (0, 0.03), (0.01, 0.03), (0.01, 0.02)])),
            ]
        )
        fence = geofence.Fence("campus", parts)
        strict = geofence.GeofenceEngine([fence])
        relaxed = geofence.GeofenceEngine([fence], hysteresis_m=800)
        walk = [(0.005, 0.005), (0.005, 0.015), (0.005, 0.025)]
        assert [kinds(strict.update("d", t, p)) for t, p in enumerate(walk)] == [
            [("enter", "campus")],
            [("exit", "campus")],
            [("enter", "campus")],
        ]
        assert [kinds(relaxed.update("d", t, p)) for t, p in enumerate(walk)] == [
            [("enter", "campus")],
            [],
            [],
        ]


class TestSimplifyKeepsTheLineClose:
    @pytest.mark.parametrize("tolerance", [5, 30, 100])
    def test_no_dropped_point_is_farther_than_the_tolerance(self, tolerance):
        rnd = random.Random(tolerance)
        points = [
            (48 + 0.001 * i + rnd.uniform(-0.0005, 0.0005), 11 + 0.002 * i + rnd.uniform(-0.0005, 0.0005))
            for i in range(200)
        ]
        kept = polyline.simplify(points, tolerance)
        assert kept[0] == geofence.Coordinate(*points[0])
        assert kept[-1] == geofence.Coordinate(*points[-1])
        assert len(kept) < len(points)
        for point in points:
            nearest = min(
                geodesy.distance_to_segment(point, kept[i], kept[i + 1]) for i in range(len(kept) - 1)
            )
            assert nearest <= tolerance + 1e-6

    def test_simplified_line_is_never_longer(self):
        line = geofence.LineString([(0, 0), (0.001, 0.5), (0, 1), (0.5, 1.001), (1, 1)])
        assert line.simplify(500).length() <= line.length()


class TestFilesThroughTheCli:
    def test_fences_written_by_the_library_drive_the_events_command(self, tmp_path, capsys):
        depot = geofence.Fence("depot", geofence.Circle((48.005, 11.0), 200), name="Depot")
        yard = geofence.Fence(
            "yard", wkt.loads("POLYGON ((11.01 48, 11.02 48, 11.02 48.01, 11.01 48.01, 11.01 48))")
        )
        fences_path = tmp_path / "fences.geojson"
        fences_path.write_text(geojson.dumps_fences([depot, yard], indent=2), encoding="utf-8")

        rows = ["device,timestamp,lat,lon"]
        for step in range(13):
            point = geodesy.destination((48.005, 11.0), 90.0, step * 150.0)
            rows.append(f"van,{step * 30},{point.lat:.7f},{point.lon:.7f}")
        track_path = tmp_path / "track.csv"
        track_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

        code = main(["events", str(fences_path), str(track_path), "--format", "json"])
        captured = capsys.readouterr()
        assert code == EXIT_OK
        from_cli = [json.loads(line) for line in captured.out.splitlines()]

        engine = geofence.GeofenceEngine([depot, yard])
        expected = [e.to_dict() for e in engine.process(parse_track(rows))]
        assert from_cli == expected
        assert [(e["type"], e["fence"]) for e in from_cli] == [
            ("enter", "depot"),
            ("exit", "depot"),
            ("enter", "yard"),
            ("exit", "yard"),
        ]

    def test_contains_agrees_with_the_library_for_wkt_defined_fences(self, tmp_path, capsys):
        shape = wkt.loads(
            "MULTIPOLYGON (((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 1 3, 3 3, 3 1, 1 1)), ((10 10, 11 10, 11 11, 10 10)))"
        )
        path = tmp_path / "f.geojson"
        path.write_text(geojson.dumps_fences([geofence.Fence("zones", shape)]), encoding="utf-8")
        for text, point in [("0.5,0.5", (0.5, 0.5)), ("2,2", (2, 2)), ("10.2,10.8", (10.2, 10.8)), ("1,2", (1, 2))]:
            code = main(["contains", str(path), text])
            capsys.readouterr()
            assert (code == EXIT_OK) == shape.contains(point), text


class TestDistanceMethodsAgree:
    def test_ellipsoid_and_sphere_stay_within_flattening(self):
        rnd = random.Random(13)
        for _ in range(300):
            a = (rnd.uniform(-80, 80), rnd.uniform(-180, 180))
            b = (rnd.uniform(-80, 80), rnd.uniform(-180, 180))
            sphere = geodesy.haversine_distance(a, b)
            if sphere > 19_000_000:
                continue
            ellipsoid = geodesy.vincenty_distance(a, b)
            assert abs(sphere - ellipsoid) / ellipsoid < 0.006

    def test_polyline_length_by_either_method(self):
        route = [(52.52, 13.405), (50.1109, 8.6821), (48.1351, 11.582), (47.3769, 8.5417)]
        sphere = polyline.length(route)
        ellipsoid = polyline.length(route, method="vincenty")
        assert sphere == pytest.approx(ellipsoid, rel=0.003)
        assert 900_000 < ellipsoid < 1_000_000
