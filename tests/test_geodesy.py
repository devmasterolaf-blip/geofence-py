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
