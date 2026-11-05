import math

import pytest

from geofence import geodesy
from geofence.circle import Circle
from geofence.coords import EARTH_RADIUS_M, Coordinate
from geofence.errors import InvalidCoordinateError, InvalidGeometryError, ValidationError
from geofence.polygon import Location, MultiPolygon, Polygon, Ring

CENTER = Coordinate(48.8566, 2.3522)


class TestCircle:
    def test_basic_properties(self):
        circle = Circle(CENTER, 500)
        assert circle.center == CENTER
        assert circle.radius_m == 500.0
        assert circle.centroid() == CENTER
        assert circle == Circle((48.8566, 2.3522), 500.0)
        assert hash(circle) == hash(Circle(CENTER, 500))
        assert circle != Circle(CENTER, 501)
        assert repr(circle) == "Circle(center=(48.8566, 2.3522), radius_m=500.0)"

    @pytest.mark.parametrize("radius", [0, -5, math.nan, math.inf, "100", None, True, 3e7])
    def test_bad_radius(self, radius):
        with pytest.raises(InvalidGeometryError):
            Circle(CENTER, radius)

    def test_bad_center(self):
        with pytest.raises(InvalidCoordinateError):
            Circle((91, 0), 10)

    def test_locate(self):
        circle = Circle(CENTER, 1000)
        assert circle.locate(CENTER) is Location.INSIDE
        assert circle.locate(geodesy.destination(CENTER, 45, 999)) is Location.INSIDE
        assert circle.locate(geodesy.destination(CENTER, 45, 1001)) is Location.OUTSIDE
        on_edge = geodesy.destination(CENTER, 200, 1000)
        assert circle.locate(on_edge) is Location.BOUNDARY
        assert circle.contains(on_edge)
        assert not circle.contains(on_edge, boundary=False)

    def test_boundary_distance(self):
        circle = Circle(CENTER, 1000)
        assert circle.boundary_distance(CENTER) == pytest.approx(1000)
        assert circle.boundary_distance(geodesy.destination(CENTER, 10, 1500)) == pytest.approx(500, abs=1e-3)
        assert circle.boundary_distance(geodesy.destination(CENTER, 10, 400)) == pytest.approx(600, abs=1e-3)

    def test_bbox_contains_the_circle(self):
        circle = Circle(CENTER, 2000)
        box = circle.bbox
        for bearing in range(0, 360, 15):
            assert box.contains(geodesy.destination(CENTER, bearing, 2000))
        assert not box.contains(geodesy.destination(CENTER, 0, 2100))

    def test_bbox_over_antimeridian(self):
        box = Circle((0, 179.99), 5000).bbox
        assert box.crosses_antimeridian
        assert box.contains((0, -179.98))

    def test_area_and_perimeter_for_small_circle(self):
        circle = Circle(CENTER, 100)
        assert circle.area() == pytest.approx(math.pi * 100**2, rel=1e-6)
        assert circle.perimeter() == pytest.approx(2 * math.pi * 100, rel=1e-6)

    def test_hemisphere_area(self):
        quarter = math.pi * EARTH_RADIUS_M / 2
        assert Circle((0, 0), quarter).area() == pytest.approx(2 * math.pi * EARTH_RADIUS_M**2)

    def test_to_polygon(self):
        circle = Circle(CENTER, 1000)
        poly = circle.to_polygon(segments=72)
        assert len(poly.exterior) == 72
        assert poly.exterior.is_ccw
        assert poly.area() == pytest.approx(circle.area(), rel=5e-3)
        assert poly.area() < circle.area()
        assert poly.contains(CENTER)
        assert poly.centroid().as_tuple() == pytest.approx(CENTER.as_tuple(), abs=1e-6)
        with pytest.raises(ValidationError):
            circle.to_polygon(segments=2)

    def test_to_polygon_over_antimeridian(self):
        poly = Circle((0, 180), 10_000).to_polygon(16)
        assert poly.exterior.crosses_antimeridian
        assert poly.contains((0, 179.95)) and poly.contains((0, -179.95))


class TestPolygonBoundaryDistance:
    ONE_DEG = math.radians(1.0) * EARTH_RADIUS_M
    SQUARE = [(0, 0), (0, 2), (2, 2), (2, 0)]

    def test_ring_from_inside_and_outside(self):
        ring = Ring(self.SQUARE)
        assert ring.boundary_distance((1, 1)) == pytest.approx(self.ONE_DEG, rel=1e-3)
        assert ring.boundary_distance((1, 3)) == pytest.approx(self.ONE_DEG, rel=1e-3)
        assert ring.boundary_distance((0, 1)) == pytest.approx(0, abs=1e-6)
        assert ring.boundary_distance((-1, -1)) == pytest.approx(
            geodesy.haversine_distance((-1, -1), (0, 0))
        )

    def test_polygon_considers_holes(self):
        poly = Polygon([(0, 0), (0, 10), (10, 10), (10, 0)], [[(4, 4), (4, 6), (6, 6), (6, 4)]])
        assert poly.boundary_distance((5, 5)) == pytest.approx(self.ONE_DEG, rel=1e-2)
        assert poly.boundary_distance((5, 3.5)) == pytest.approx(0.5 * self.ONE_DEG, rel=1e-2)

    def test_multipolygon_takes_nearest_member(self):
        multi = MultiPolygon([self.SQUARE, [(0, 10), (0, 12), (2, 12), (2, 10)]])
        assert multi.boundary_distance((1, 9)) == pytest.approx(self.ONE_DEG, rel=1e-3)
        assert multi.boundary_distance((1, 3.5)) == pytest.approx(1.5 * self.ONE_DEG, rel=1e-3)
