import pytest

from geofence import geohash
from geofence.bbox import BoundingBox
from geofence.coords import Coordinate
from geofence.errors import GeohashError, InvalidCoordinateError


class TestEncode:
    @pytest.mark.parametrize(
        "point, precision, expected",
        [
            ((57.64911, 10.40744), 11, "u4pruydqqvj"),
            ((42.6, -5.6), 5, "ezs42"),
            ((-25.382708, -49.265506), 8, "6gkzwgjz"),
            ((0, 0), 1, "s"),
            ((-90, -180), 4, "0000"),
            ((90, 180), 4, "zzzz"),
        ],
    )
    def test_known_values(self, point, precision, expected):
        assert geohash.encode(point, precision) == expected

    def test_default_precision_is_nine(self):
        assert len(geohash.encode((48.8566, 2.3522))) == 9

    def test_longer_hash_extends_shorter_one(self):
        point = (35.6762, 139.6503)
        full = geohash.encode(point, 12)
        for precision in range(1, 12):
            assert geohash.encode(point, precision) == full[:precision]

    @pytest.mark.parametrize("precision", [0, 13, -1, 2.5, "5", True, None])
    def test_bad_precision(self, precision):
        with pytest.raises(GeohashError):
            geohash.encode((0, 0), precision)

    def test_bad_coordinate(self):
        with pytest.raises(InvalidCoordinateError):
            geohash.encode((100, 0), 5)


class TestDecode:
    def test_centre_of_known_cell(self):
        centre = geohash.decode("ezs42")
        assert centre.lat == pytest.approx(42.605, abs=1e-3)
        assert centre.lon == pytest.approx(-5.603, abs=1e-3)

    def test_bounds_contain_the_encoded_point(self):
        point = Coordinate(-33.8688, 151.2093)
        for precision in (1, 4, 7, 12):
            assert geohash.bounds(geohash.encode(point, precision)).contains(point)

    def test_round_trip_of_centre(self):
        for text in ["s", "u4pruydqqvj", "0000", "zzzz", "6gkzwgjz", "9q8yyk8ytpxr"]:
            assert geohash.encode(geohash.decode(text), len(text)) == text

    def test_upper_case_accepted(self):
        assert geohash.decode("EZS42") == geohash.decode("ezs42")

    def test_bounds_shrink_with_precision(self):
        coarse, fine = geohash.bounds("ezs4"), geohash.bounds("ezs42")
        assert coarse.contains_box(fine)
        assert fine.width_deg < coarse.width_deg

    @pytest.mark.parametrize("bad", ["", "abc", "ezs4i", "ez s4", "0" * 13, None, 12])
    def test_invalid_hash(self, bad):
        with pytest.raises(GeohashError):
            geohash.decode(bad)

    def test_error_names_the_bad_character(self):
        with pytest.raises(GeohashError, match="'L' at position 2"):
            geohash.bounds("ezLs")

    def test_cell_size(self):
        assert geohash.cell_size(1) == (45.0, 45.0)
        height, width = geohash.cell_size(5)
        assert height == pytest.approx(180 / 2**12)
        assert width == pytest.approx(360 / 2**13)


class TestNeighbors:
    def test_known_neighbours(self):
        assert geohash.neighbor("ezs42", "n") == "ezs48"
        assert geohash.neighbor("ezs42", "e") == "ezs43"
        assert geohash.neighbor("ezs42", "s") == "ezs40"
        assert geohash.neighbor("ezs42", "w") == "ezefr"

    def test_all_eight_are_adjacent_and_distinct(self):
        around = geohash.neighbors("u4pruy")
        assert set(around) == set(geohash.DIRECTIONS)
        assert len(set(around.values())) == 8
        centre_box = geohash.bounds("u4pruy")
        for cell in around.values():
            assert len(cell) == 6
            assert geohash.bounds(cell).intersects(centre_box)

    def test_opposite_directions_cancel(self):
        for a, b in [("n", "s"), ("e", "w"), ("ne", "sw"), ("nw", "se")]:
            assert geohash.neighbor(geohash.neighbor("9q8yyk", a), b) == "9q8yyk"

    def test_wraps_over_the_antimeridian(self):
        east_edge = geohash.encode((10, 179.999), 5)
        west_edge = geohash.encode((10, -179.999), 5)
        assert geohash.neighbor(east_edge, "e") == west_edge
        assert geohash.neighbor(west_edge, "w") == east_edge

    def test_no_neighbour_beyond_the_poles(self):
        top = geohash.encode((89.999, 10), 4)
        assert geohash.neighbor(top, "n") is None
        assert set(geohash.neighbors(top)) == {"e", "se", "s", "sw", "w"}
        bottom = geohash.encode((-89.999, 10), 4)
        assert geohash.neighbor(bottom, "se") is None

    def test_unknown_direction(self):
        with pytest.raises(GeohashError, match="unknown direction"):
            geohash.neighbor("ezs42", "up")


class TestCovering:
    def test_single_cell(self):
        cell = geohash.bounds("ezs42")
        inner = BoundingBox(
            cell.south + 0.001, cell.west + 0.001, cell.north - 0.001, cell.east - 0.001
        )
        assert geohash.covering(inner, 5) == ["ezs42"]

    def test_every_cell_touches_the_box_and_every_point_is_covered(self):
        box = BoundingBox(48.80, 2.25, 48.90, 2.42)
        cells = geohash.covering(box, 5)
        assert cells == sorted(set(cells))
        for cell in cells:
            assert geohash.bounds(cell).intersects(box)
        for point in [box.center, *box.corners, (48.85, 2.3)]:
            assert geohash.encode(point, 5) in cells

    def test_count_matches_grid_arithmetic(self):
        height, width = geohash.cell_size(4)
        box = BoundingBox(0.01, 0.01, 0.01 + 2 * height, 0.01 + 3 * width)
        assert len(geohash.covering(box, 4)) == 3 * 4

    def test_box_across_antimeridian(self):
        box = BoundingBox(-0.5, 179.5, 0.5, -179.5)
        cells = geohash.covering(box, 3)
        assert geohash.encode((0, 179.9), 3) in cells
        assert geohash.encode((0, -179.9), 3) in cells
        assert geohash.encode((0, 0), 3) not in cells
        assert len(cells) == 4

    def test_world_at_precision_one(self):
        assert geohash.covering(BoundingBox.world(), 1) == sorted(geohash.BASE32)

    def test_limit(self):
        box = BoundingBox(0, 0, 1, 1)
        with pytest.raises(GeohashError, match="max_cells"):
            geohash.covering(box, 6)
        assert len(geohash.covering(box, 6, max_cells=50_000)) > 4096
        with pytest.raises(GeohashError):
            geohash.covering(box, 3, max_cells=0)

    def test_rejects_non_box(self):
        with pytest.raises(GeohashError):
            geohash.covering((0, 0, 1, 1), 5)
