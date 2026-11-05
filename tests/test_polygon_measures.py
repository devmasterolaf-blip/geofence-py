import math

import pytest

from geofence.bbox import BoundingBox
from geofence.coords import EARTH_RADIUS_M, Coordinate
from geofence.errors import InvalidGeometryError
from geofence.polygon import Location, MultiPolygon, Polygon, Ring

SQUARE = [(0, 0), (0, 10), (10, 10), (10, 0)]
HOLE = [(4, 4), (4, 6), (6, 6), (6, 4)]


def lat_lon_rectangle_area(south, west, north, east):
    """Exact area of a rectangle bounded by parallels and meridians."""
    return (
        EARTH_RADIUS_M**2
        * math.radians(east - west)
        * (math.sin(math.radians(north)) - math.sin(math.radians(south)))
    )


class TestArea:
    def test_lat_lon_rectangle_is_exact(self):
        assert Ring(SQUARE).area() == pytest.approx(lat_lon_rectangle_area(0, 0, 10, 10))

    def test_signed_area_follows_orientation(self):
        ring = Ring(SQUARE)
        assert ring.signed_area() > 0
        assert ring.reversed().signed_area() == pytest.approx(-ring.signed_area())
        assert ring.reversed().area() == pytest.approx(ring.area())

    def test_small_square_matches_flat_approximation(self):
        side_deg = 0.001
        ring = Ring([(0, 0), (0, side_deg), (side_deg, side_deg), (side_deg, 0)])
        side_m = math.radians(side_deg) * EARTH_RADIUS_M
        assert ring.area() == pytest.approx(side_m**2, rel=1e-6)

    def test_high_latitude_cells_are_smaller(self):
        low = Ring([(0, 0), (0, 1), (1, 1), (1, 0)]).area()
        high = Ring([(60, 0), (60, 1), (61, 1), (61, 0)]).area()
        assert high == pytest.approx(lat_lon_rectangle_area(60, 0, 61, 1))
        assert high < 0.51 * low

    def test_area_across_antimeridian(self):
        crossing = Ring([(-5, 175), (-5, -175), (5, -175), (5, 175)])
        assert crossing.area() == pytest.approx(lat_lon_rectangle_area(-5, 175, 5, 185))

    def test_polygon_subtracts_holes(self):
        poly = Polygon(SQUARE, [HOLE])
        expected = lat_lon_rectangle_area(0, 0, 10, 10) - lat_lon_rectangle_area(4, 4, 6, 6)
        assert poly.area() == pytest.approx(expected)

    def test_hole_orientation_does_not_change_area(self):
        a = Polygon(SQUARE, [HOLE]).area()
        b = Polygon(SQUARE, [list(reversed(HOLE))]).area()
        assert a == pytest.approx(b)

    def test_perimeter_includes_holes(self):
        poly = Polygon(SQUARE, [HOLE])
        assert poly.perimeter() == pytest.approx(Ring(SQUARE).perimeter() + Ring(HOLE).perimeter())


class TestCentroid:
    def test_square(self):
        assert Ring(SQUARE).centroid().as_tuple() == pytest.approx((5, 5))
        assert Ring(SQUARE).reversed().centroid().as_tuple() == pytest.approx((5, 5))

    def test_triangle(self):
        assert Ring([(0, 0), (0, 6), (6, 0)]).centroid().as_tuple() == pytest.approx((2, 2))

    def test_l_shape_is_area_weighted(self):
        ring = Ring([(0, 0), (0, 2), (1, 2), (1, 1), (2, 1), (2, 0)])
        lat, lon = ring.centroid().as_tuple()
        assert (lat, lon) == pytest.approx((5 / 6, 5 / 6))

    def test_degenerate_ring_uses_vertex_mean(self):
        assert Ring([(0, 0), (0, 1), (0, 2)]).centroid().as_tuple() == pytest.approx((0, 1))

    def test_across_antimeridian(self):
        ring = Ring([(-5, 175), (-5, -175), (5, -175), (5, 175)])
        assert ring.centroid().same_place(Coordinate(0, 180), tolerance_deg=1e-9)
        shifted = Ring([(-5, 178), (-5, -172), (5, -172), (5, 178)])
        assert shifted.centroid().as_tuple() == pytest.approx((0, -177))

    def test_hole_pulls_centroid_away(self):
        poly = Polygon(SQUARE, [[(1, 1), (1, 3), (3, 3), (3, 1)]])
        lat, lon = poly.centroid().as_tuple()
        assert lat > 5 and lon > 5
        # (100 * 5 - 4 * 2) / 96
        assert lat == pytest.approx(492 / 96)

    def test_centred_hole_keeps_centroid(self):
        assert Polygon(SQUARE, [HOLE]).centroid().as_tuple() == pytest.approx((5, 5))


def test_normalized_orients_exterior_ccw_and_holes_cw():
    poly = Polygon(list(reversed(SQUARE)), [HOLE])
    assert not poly.exterior.is_ccw and poly.holes[0].is_ccw
    fixed = poly.normalized()
    assert fixed.exterior.is_ccw
    assert not fixed.holes[0].is_ccw
    assert fixed.area() == pytest.approx(poly.area())
    assert fixed.normalized() == fixed


class TestMultiPolygon:
    FAR = [(20, 20), (20, 30), (30, 30), (30, 20)]
    MULTI = MultiPolygon([Polygon(SQUARE, [HOLE]), FAR])

    def test_structure(self):
        assert len(self.MULTI) == 2
        assert list(self.MULTI)[1] == Polygon(self.FAR)
        assert self.MULTI == MultiPolygon([Polygon(SQUARE, [HOLE]), Polygon(self.FAR)])
        assert hash(self.MULTI) == hash(MultiPolygon([Polygon(SQUARE, [HOLE]), Polygon(self.FAR)]))

    def test_needs_a_member(self):
        with pytest.raises(InvalidGeometryError):
            MultiPolygon([])

    def test_contains_any_member(self):
        assert self.MULTI.contains((2, 2))
        assert self.MULTI.contains((25, 25))
        assert not self.MULTI.contains((5, 5))  # hole of the first member
        assert not self.MULTI.contains((15, 15))
        assert self.MULTI.locate((20, 25)) is Location.BOUNDARY
        assert not self.MULTI.contains((20, 25), boundary=False)

    def test_inside_one_member_wins_over_boundary_of_another(self):
        overlapping = MultiPolygon([SQUARE, [(5, 5), (5, 15), (15, 15), (15, 5)]])
        assert overlapping.locate((5, 7)) is Location.INSIDE

    def test_area_and_perimeter_are_sums(self):
        assert self.MULTI.area() == pytest.approx(
            Polygon(SQUARE, [HOLE]).area() + Polygon(self.FAR).area()
        )
        assert self.MULTI.perimeter() == pytest.approx(
            Polygon(SQUARE, [HOLE]).perimeter() + Polygon(self.FAR).perimeter()
        )

    def test_bbox_is_union(self):
        assert self.MULTI.bbox == BoundingBox(0, 0, 30, 30)

    def test_bbox_of_members_on_both_sides_of_antimeridian(self):
        multi = MultiPolygon(
            [[(0, 170), (0, 175), (5, 175), (5, 170)], [(0, -175), (0, -170), (5, -170), (5, -175)]]
        )
        assert multi.bbox == BoundingBox(0, 170, 5, -170)

    def test_centroid_is_weighted_by_area(self):
        multi = MultiPolygon([[(0, 0), (0, 2), (2, 2), (2, 0)], [(0, 10), (0, 11), (1, 11), (1, 10)]])
        lat, lon = multi.centroid().as_tuple()
        assert lon == pytest.approx((4 * 1 + 1 * 10.5) / 5)
        assert lat == pytest.approx((4 * 1 + 1 * 0.5) / 5)
