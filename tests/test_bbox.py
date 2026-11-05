import math

import pytest

from geofence.bbox import BoundingBox
from geofence.coords import Coordinate
from geofence.errors import InvalidGeometryError, ValidationError


def test_plain_box_properties():
    box = BoundingBox(10, 20, 30, 60)
    assert not box.crosses_antimeridian
    assert box.width_deg == 40
    assert box.height_deg == 20
    assert box.center == Coordinate(20, 40)
    assert [c.as_tuple() for c in box.corners] == [(10, 20), (10, 60), (30, 60), (30, 20)]


def test_crossing_box_properties():
    box = BoundingBox(-10, 170, 10, -170)
    assert box.crosses_antimeridian
    assert box.width_deg == 20
    assert box.center.same_place(Coordinate(0, 180))


def test_world_box_is_full_width_and_zero_width_box_is_a_meridian():
    assert BoundingBox.world().width_deg == 360
    assert BoundingBox(0, 5, 10, 5).width_deg == 0
    assert BoundingBox(0, 5, 10, 5).contains((3, 5))


def test_south_above_north_rejected():
    with pytest.raises(InvalidGeometryError, match="south"):
        BoundingBox(10, 0, 5, 1)


@pytest.mark.parametrize("args", [(-91, 0, 0, 1), (0, -181, 1, 0), (0, 0, math.nan, 1), (0, 0, 1, "2")])
def test_invalid_corner_values_rejected(args):
    with pytest.raises(InvalidGeometryError):
        BoundingBox(*args)


class TestContains:
    def test_edges_are_inside(self):
        box = BoundingBox(0, 0, 10, 10)
        for point in [(0, 0), (10, 10), (5, 0), (0, 5), (5, 5)]:
            assert box.contains(point)
        for point in [(-0.001, 5), (5, 10.001), (11, 5)]:
            assert not box.contains(point)

    def test_crossing_box(self):
        box = BoundingBox(-10, 170, 10, -170)
        assert box.contains((0, 175))
        assert box.contains((0, -175))
        assert box.contains((0, 180))
        assert box.contains((0, -180))
        assert not box.contains((0, 0))
        assert not box.contains((0, 169.9))
        assert not box.contains((0, -169.9))

    def test_world_contains_everything(self):
        world = BoundingBox.world()
        for point in [(90, 0), (-90, 180), (0, -180), (12, 34)]:
            assert world.contains(point)

    def test_contains_box(self):
        outer = BoundingBox(-10, 170, 10, -160)
        assert outer.contains_box(BoundingBox(-5, 175, 5, -175))
        assert outer.contains_box(BoundingBox(-5, -179, 5, -165))
        assert not outer.contains_box(BoundingBox(-5, 160, 5, 175))
        assert not outer.contains_box(BoundingBox(-20, 175, 5, -175))
        assert BoundingBox.world().contains_box(outer)


class TestIntersects:
    def test_overlap_touch_and_disjoint(self):
        a = BoundingBox(0, 0, 10, 10)
        assert a.intersects(BoundingBox(5, 5, 15, 15))
        assert a.intersects(BoundingBox(10, 10, 20, 20))  # shared corner
        assert not a.intersects(BoundingBox(11, 0, 20, 10))
        assert not a.intersects(BoundingBox(0, 10.5, 10, 20))

    def test_is_symmetric_across_the_antimeridian(self):
        crossing = BoundingBox(-10, 170, 10, -170)
        east_side = BoundingBox(-5, -175, 5, -160)
        west_side = BoundingBox(-5, 160, 5, 172)
        far = BoundingBox(-5, 0, 5, 20)
        for other, expected in [(east_side, True), (west_side, True), (far, False)]:
            assert crossing.intersects(other) is expected
            assert other.intersects(crossing) is expected

    def test_containment_counts_as_intersection(self):
        assert BoundingBox(0, 0, 10, 10).intersects(BoundingBox(4, 4, 5, 5))
        assert BoundingBox(4, 4, 5, 5).intersects(BoundingBox(0, 0, 10, 10))


class TestFromPoints:
    def test_simple_cluster(self):
        box = BoundingBox.from_points([(1, 2), (3, -4), (-5, 6)])
        assert (box.south, box.west, box.north, box.east) == (-5, -4, 3, 6)

    def test_single_point(self):
        box = BoundingBox.from_points([Coordinate(7, 8)])
        assert (box.south, box.west, box.north, box.east) == (7, 8, 7, 8)

    def test_cluster_over_antimeridian_gives_narrow_crossing_box(self):
        box = BoundingBox.from_points([(0, 179), (1, -179), (2, 178)])
        assert box.crosses_antimeridian
        assert (box.west, box.east) == (178, -179)
        assert box.width_deg == 3

    def test_tie_prefers_non_crossing(self):
        box = BoundingBox.from_points([(0, -90), (0, 90)])
        assert (box.west, box.east) == (-90, 90)

    def test_empty_rejected(self):
        with pytest.raises(InvalidGeometryError):
            BoundingBox.from_points([])


class TestUnion:
    def test_disjoint_boxes(self):
        u = BoundingBox(0, 0, 10, 10).union(BoundingBox(20, 20, 30, 30))
        assert (u.south, u.west, u.north, u.east) == (0, 0, 30, 30)

    def test_picks_the_narrow_way_round(self):
        u = BoundingBox(0, 170, 10, 175).union(BoundingBox(0, -175, 10, -170))
        assert (u.west, u.east) == (170, -170)
        assert u.width_deg == 20
        v = BoundingBox(0, -175, 10, -170).union(BoundingBox(0, 170, 10, 175))
        assert (v.west, v.east) == (170, -170)

    def test_nested_box_returns_outer_extent(self):
        outer = BoundingBox(0, 0, 10, 10)
        assert outer.union(BoundingBox(2, 2, 3, 3)) == outer
        assert BoundingBox(2, 2, 3, 3).union(outer) == outer

    def test_boxes_that_wrap_the_globe_together(self):
        u = BoundingBox(0, -170, 10, 30).union(BoundingBox(0, 20, 10, -160))
        assert (u.west, u.east) == (-180, 180)


class TestExpand:
    def test_grows_each_side(self):
        box = BoundingBox(0, 0, 0, 0).expand(111_195)
        assert box.north == pytest.approx(1.0, abs=1e-3)
        assert box.south == pytest.approx(-1.0, abs=1e-3)
        assert box.east == pytest.approx(1.0, abs=1e-3)
        assert box.west == pytest.approx(-1.0, abs=1e-3)

    def test_longitude_growth_widens_with_latitude(self):
        box = BoundingBox(60, 10, 60, 10).expand(10_000)
        assert (box.east - box.west) > 2 * (box.north - box.south) * 0.99

    def test_expanding_over_antimeridian_produces_crossing_box(self):
        box = BoundingBox(0, 179.9, 1, 179.95).expand(50_000)
        assert box.crosses_antimeridian
        assert box.contains((0.5, -179.8))

    def test_reaching_a_pole_covers_all_longitudes(self):
        box = BoundingBox(89.5, 0, 89.9, 10).expand(50_000)
        assert box.north == 90
        assert box.width_deg == 360

    def test_zero_keeps_box_and_negative_is_rejected(self):
        box = BoundingBox(1, 2, 3, 4)
        assert box.expand(0) == box
        with pytest.raises(ValidationError):
            box.expand(-1)
        with pytest.raises(ValidationError):
            box.expand(math.inf)


def test_split_at_antimeridian():
    plain = BoundingBox(0, 0, 1, 1)
    assert plain.split() == [plain]
    parts = BoundingBox(-10, 170, 10, -170).split()
    assert parts == [BoundingBox(-10, 170, 10, 180), BoundingBox(-10, -180, 10, -170)]
