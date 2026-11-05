import math

import pytest

from geofence import geodesy
from geofence.coords import EARTH_RADIUS_M, Coordinate
from geofence.errors import InvalidCoordinateError, ValidationError

PARIS = Coordinate(48.8566, 2.3522)
LONDON = Coordinate(51.5074, -0.1278)
NEW_YORK = Coordinate(40.7128, -74.0060)


class TestHaversine:
    def test_zero_for_same_point(self):
        assert geodesy.haversine_distance(PARIS, PARIS) == 0.0

    def test_quarter_circumference(self):
        quarter = math.pi * EARTH_RADIUS_M / 2
        assert geodesy.haversine_distance((0, 0), (0, 90)) == pytest.approx(quarter)
        assert geodesy.haversine_distance((0, 0), (90, 0)) == pytest.approx(quarter)

    def test_antipodal_points_are_half_circumference(self):
        assert geodesy.haversine_distance((10, 20), (-10, -160)) == pytest.approx(
            math.pi * EARTH_RADIUS_M
        )

    def test_known_city_pair(self):
        # Paris - London is about 343.5 km on the mean sphere.
        assert geodesy.haversine_distance(PARIS, LONDON) == pytest.approx(343_556, rel=1e-3)

    def test_is_symmetric(self):
        assert geodesy.haversine_distance(PARIS, NEW_YORK) == pytest.approx(
            geodesy.haversine_distance(NEW_YORK, PARIS)
        )

    def test_short_way_across_antimeridian(self):
        d = geodesy.haversine_distance((0, 179.5), (0, -179.5))
        assert d == pytest.approx(math.radians(1.0) * EARTH_RADIUS_M)

    def test_custom_radius(self):
        assert geodesy.haversine_distance((0, 0), (0, 180), radius=1.0) == pytest.approx(math.pi)

    @pytest.mark.parametrize("radius", [0, -1, math.nan, math.inf, "6371", True])
    def test_bad_radius_rejected(self, radius):
        with pytest.raises(ValidationError):
            geodesy.haversine_distance((0, 0), (1, 1), radius=radius)

    def test_accepts_plain_pairs_and_validates_them(self):
        assert geodesy.haversine_distance((0, 0), [0, 1]) > 0
        with pytest.raises(InvalidCoordinateError):
            geodesy.haversine_distance((0, 0), (91, 0))


class TestBearings:
    @pytest.mark.parametrize(
        "target, expected",
        [((1, 0), 0), ((0, 1), 90), ((-1, 0), 180), ((0, -1), 270)],
    )
    def test_cardinal_directions(self, target, expected):
        assert geodesy.initial_bearing((0, 0), target) == pytest.approx(expected)

    def test_result_is_in_compass_range(self):
        bearing = geodesy.initial_bearing(PARIS, NEW_YORK)
        assert 0 <= bearing < 360
        assert bearing == pytest.approx(291.8, abs=0.1)

    def test_coincident_points_give_zero(self):
        assert geodesy.initial_bearing(PARIS, PARIS) == 0.0

    def test_final_bearing_differs_on_long_routes(self):
        initial = geodesy.initial_bearing(PARIS, NEW_YORK)
        final = geodesy.final_bearing(PARIS, NEW_YORK)
        assert final == pytest.approx(233.7, abs=0.2)
        assert abs(initial - final) > 30

    def test_final_bearing_along_meridian_equals_initial(self):
        assert geodesy.final_bearing((0, 10), (20, 10)) == pytest.approx(0.0)
        assert geodesy.final_bearing((20, 10), (0, 10)) == pytest.approx(180.0)


class TestDestination:
    def test_due_north_one_degree(self):
        one_degree = math.radians(1.0) * EARTH_RADIUS_M
        dest = geodesy.destination((0, 0), 0, one_degree)
        assert dest.lat == pytest.approx(1.0)
        assert dest.lon == pytest.approx(0.0)

    def test_round_trip_with_distance_and_bearing(self):
        d = geodesy.haversine_distance(PARIS, NEW_YORK)
        bearing = geodesy.initial_bearing(PARIS, NEW_YORK)
        dest = geodesy.destination(PARIS, bearing, d)
        assert dest.lat == pytest.approx(NEW_YORK.lat, abs=1e-6)
        assert dest.lon == pytest.approx(NEW_YORK.lon, abs=1e-6)

    def test_wraps_longitude_over_antimeridian(self):
        dest = geodesy.destination((0, 179.5), 90, math.radians(1.0) * EARTH_RADIUS_M)
        assert dest.lon == pytest.approx(-179.5)

    def test_zero_distance_returns_start(self):
        dest = geodesy.destination(PARIS, 123, 0)
        assert dest.lat == pytest.approx(PARIS.lat)
        assert dest.lon == pytest.approx(PARIS.lon)

    def test_negative_distance_goes_backwards(self):
        forward = geodesy.destination((0, 0), 270, 1000)
        backward = geodesy.destination((0, 0), 90, -1000)
        assert backward.lon == pytest.approx(forward.lon)

    def test_passing_over_the_pole(self):
        dest = geodesy.destination((89, 0), 0, math.radians(2.0) * EARTH_RADIUS_M)
        assert dest.lat == pytest.approx(89.0)
        assert abs(dest.lon) == pytest.approx(180.0)

    @pytest.mark.parametrize("bearing, distance", [(math.nan, 1), (0, math.inf), ("n", 1)])
    def test_bad_arguments_rejected(self, bearing, distance):
        with pytest.raises(ValidationError):
            geodesy.destination((0, 0), bearing, distance)


class TestMidpointAndInterpolate:
    def test_midpoint_on_equator(self):
        assert geodesy.midpoint((0, 0), (0, 90)).as_tuple() == pytest.approx((0, 45))

    def test_midpoint_is_equidistant(self):
        mid = geodesy.midpoint(PARIS, NEW_YORK)
        assert geodesy.haversine_distance(PARIS, mid) == pytest.approx(
            geodesy.haversine_distance(mid, NEW_YORK)
        )

    def test_midpoint_across_antimeridian(self):
        mid = geodesy.midpoint((0, 170), (0, -170))
        assert mid.same_place(Coordinate(0, 180), tolerance_deg=1e-9)

    def test_interpolate_endpoints_and_middle(self):
        assert geodesy.interpolate(PARIS, LONDON, 0).as_tuple() == pytest.approx(PARIS.as_tuple())
        assert geodesy.interpolate(PARIS, LONDON, 1).as_tuple() == pytest.approx(LONDON.as_tuple())
        half = geodesy.interpolate(PARIS, LONDON, 0.5)
        assert half.as_tuple() == pytest.approx(geodesy.midpoint(PARIS, LONDON).as_tuple())

    def test_interpolate_quarter_distance(self):
        total = geodesy.haversine_distance(PARIS, NEW_YORK)
        quarter = geodesy.interpolate(PARIS, NEW_YORK, 0.25)
        assert geodesy.haversine_distance(PARIS, quarter) == pytest.approx(total / 4)

    def test_interpolate_same_point(self):
        assert geodesy.interpolate(PARIS, PARIS, 0.3) == PARIS

    def test_interpolate_rejects_bad_fraction_and_antipodes(self):
        with pytest.raises(ValidationError):
            geodesy.interpolate(PARIS, LONDON, 1.5)
        with pytest.raises(ValidationError, match="antipodal"):
            geodesy.interpolate((0, 0), (0, 180), 0.5)


class TestTrackDistances:
    ONE_DEG = math.radians(1.0) * EARTH_RADIUS_M

    def test_cross_track_sign(self):
        # Path runs east along the equator; south is to the right.
        right = geodesy.cross_track_distance((-1, 5), (0, 0), (0, 10))
        left = geodesy.cross_track_distance((1, 5), (0, 0), (0, 10))
        assert right == pytest.approx(self.ONE_DEG)
        assert left == pytest.approx(-self.ONE_DEG)

    def test_cross_track_zero_on_path(self):
        assert geodesy.cross_track_distance((0, 3), (0, 0), (0, 10)) == pytest.approx(0, abs=1e-6)

    def test_cross_track_with_degenerate_path(self):
        d = geodesy.cross_track_distance((1, 0), (0, 0), (0, 0))
        assert d == pytest.approx(self.ONE_DEG)

    def test_along_track(self):
        assert geodesy.along_track_distance((1, 5), (0, 0), (0, 10)) == pytest.approx(
            5 * self.ONE_DEG, rel=1e-3
        )
        assert geodesy.along_track_distance((1, -2), (0, 0), (0, 10)) < 0
        assert geodesy.along_track_distance((0, 0), (0, 0), (0, 10)) == 0.0

    def test_distance_to_segment_uses_endpoints_outside_the_span(self):
        start, end = (0, 0), (0, 10)
        assert geodesy.distance_to_segment((1, 5), start, end) == pytest.approx(self.ONE_DEG)
        assert geodesy.distance_to_segment((0, -2), start, end) == pytest.approx(2 * self.ONE_DEG)
        assert geodesy.distance_to_segment((0, 13), start, end) == pytest.approx(3 * self.ONE_DEG)
        before = geodesy.distance_to_segment((1, -1), start, end)
        assert before == pytest.approx(geodesy.haversine_distance((1, -1), start))

    def test_distance_to_zero_length_segment(self):
        assert geodesy.distance_to_segment((1, 0), (0, 0), (0, 0)) == pytest.approx(self.ONE_DEG)
