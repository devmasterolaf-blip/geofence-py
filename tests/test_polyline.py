import math

import pytest

from geofence import geodesy, polyline
from geofence.coords import EARTH_RADIUS_M, Coordinate
from geofence.errors import InvalidGeometryError, ValidationError

ONE_DEG = math.radians(1.0) * EARTH_RADIUS_M


class TestLength:
    def test_empty_and_single_point(self):
        assert polyline.length([]) == 0.0
        assert polyline.length([(1, 2)]) == 0.0
        assert polyline.cumulative_distances([]) == []

    def test_sums_segments(self):
        line = [(0, 0), (0, 1), (1, 1)]
        assert polyline.length(line) == pytest.approx(2 * ONE_DEG)
        assert polyline.cumulative_distances(line) == pytest.approx([0, ONE_DEG, 2 * ONE_DEG])

    def test_vincenty_method(self):
        line = [(0, 0), (0, 1)]
        assert polyline.length(line, method="vincenty") == pytest.approx(
            geodesy.vincenty_distance((0, 0), (0, 1))
        )

    def test_unknown_method(self):
        with pytest.raises(ValidationError):
            polyline.length([(0, 0), (0, 1)], method="euclid")


class TestPointAtDistance:
    LINE = [(0, 0), (0, 1), (1, 1)]

    def test_inside_first_and_second_segment(self):
        assert polyline.point_at_distance(self.LINE, ONE_DEG / 2).as_tuple() == pytest.approx((0, 0.5))
        assert polyline.point_at_distance(self.LINE, 1.5 * ONE_DEG).as_tuple() == pytest.approx((0.5, 1))

    def test_start_and_past_the_end(self):
        assert polyline.point_at_distance(self.LINE, 0).as_tuple() == pytest.approx((0, 0))
        assert polyline.point_at_distance(self.LINE, 10 * ONE_DEG) == Coordinate(1, 1)

    def test_skips_zero_length_segments(self):
        line = [(0, 0), (0, 0), (0, 1)]
        assert polyline.point_at_distance(line, ONE_DEG / 4).as_tuple() == pytest.approx((0, 0.25))

    def test_rejects_bad_input(self):
        with pytest.raises(InvalidGeometryError):
            polyline.point_at_distance([], 1)
        with pytest.raises(ValidationError):
            polyline.point_at_distance(self.LINE, -1)


class TestSimplify:
    def test_short_inputs_returned_unchanged(self):
        assert polyline.simplify([], 10) == []
        assert polyline.simplify([(1, 2)], 10) == [Coordinate(1, 2)]
        assert polyline.simplify([(1, 2), (3, 4)], 10) == [Coordinate(1, 2), Coordinate(3, 4)]

    def test_removes_points_within_tolerance(self):
        line = [(0, 0), (0.0001, 1), (0, 2), (1, 2)]
        # (0.0001, 1) is about 11 m off the straight line.
        assert polyline.simplify(line, 50) == [Coordinate(0, 0), Coordinate(0, 2), Coordinate(1, 2)]
        assert len(polyline.simplify(line, 5)) == 4

    def test_keeps_endpoints_and_order(self):
        line = [(0, i * 0.01 + (0.002 if i % 2 else 0)) for i in range(50)]
        result = polyline.simplify(line, 1000)
        assert result[0] == Coordinate(*line[0])
        assert result[-1] == Coordinate(*line[-1])
        positions = [line.index(c.as_tuple()) for c in result]
        assert positions == sorted(positions)

    def test_zero_tolerance_drops_only_collinear_points(self):
        line = [(0, 0), (0, 1), (0, 2), (1, 2)]
        assert polyline.simplify(line, 0) == [Coordinate(0, 0), Coordinate(0, 2), Coordinate(1, 2)]

    def test_huge_tolerance_leaves_two_points(self):
        line = [(0, 0), (5, 5), (-5, 10), (0, 15)]
        assert polyline.simplify(line, 1e9) == [Coordinate(0, 0), Coordinate(0, 15)]

    def test_result_stays_within_tolerance_of_original(self):
        line = [(math.sin(i / 5) * 0.01, i * 0.002) for i in range(200)]
        tolerance = 100.0
        simple = polyline.simplify(line, tolerance)
        assert 2 < len(simple) < len(line)
        for point in line:
            nearest = min(
                geodesy.distance_to_segment(point, a, b) for a, b in zip(simple, simple[1:])
            )
            assert nearest <= tolerance + 1e-6

    def test_closed_loop_keeps_its_shape(self):
        ring = [(0, 0), (0, 1), (1, 1), (1, 0), (0, 0)]
        assert len(polyline.simplify(ring, 100)) == 5

    def test_long_line_does_not_hit_recursion_limit(self):
        line = [(0.0001 * (i % 2), i * 0.0001) for i in range(5000)]
        assert len(polyline.simplify(line, 1)) == 5000

    @pytest.mark.parametrize("tolerance", [-1, math.nan, math.inf, "5", None])
    def test_bad_tolerance_rejected(self, tolerance):
        with pytest.raises(ValidationError):
            polyline.simplify([(0, 0), (1, 1), (2, 2)], tolerance)
