import math

import pytest

from geofence.bbox import BoundingBox
from geofence.coords import EARTH_RADIUS_M, Coordinate
from geofence.errors import InvalidCoordinateError, InvalidGeometryError
from geofence.polygon import Ring

SQUARE = [(0, 0), (0, 10), (10, 10), (10, 0)]  # (lat, lon), counter-clockwise on a map


class TestConstruction:
    def test_open_and_closed_input_are_equivalent(self):
        open_ring = Ring(SQUARE)
        closed_ring = Ring(SQUARE + [SQUARE[0]])
        assert open_ring == closed_ring
        assert hash(open_ring) == hash(closed_ring)
        assert len(open_ring) == 4
        assert len(open_ring.closed_coords) == 5
        assert open_ring.closed_coords[0] == open_ring.closed_coords[-1]

    def test_needs_three_vertices(self):
        with pytest.raises(InvalidGeometryError, match="at least 3"):
            Ring([(0, 0), (1, 1)])
        with pytest.raises(InvalidGeometryError):
            Ring([(0, 0), (1, 1), (0, 0)])  # closing point does not count

    def test_from_closed_requires_closure(self):
        assert Ring.from_closed(SQUARE + [SQUARE[0]]) == Ring(SQUARE)
        with pytest.raises(InvalidGeometryError, match="not closed"):
            Ring.from_closed(SQUARE)
        with pytest.raises(InvalidGeometryError, match="at least 4"):
            Ring.from_closed([(0, 0), (1, 1), (0, 0)])

    def test_invalid_vertices_rejected(self):
        with pytest.raises(InvalidCoordinateError):
            Ring([(0, 0), (0, 200), (10, 10)])

    def test_edges_include_closing_edge(self):
        edges = list(Ring(SQUARE).edges())
        assert len(edges) == 4
        assert edges[-1] == (Coordinate(10, 0), Coordinate(0, 0))

    def test_repr_round_trips_vertices(self):
        assert repr(Ring(SQUARE)) == "Ring([(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0)])"


class TestOrientation:
    def test_ccw_detection(self):
        ring = Ring(SQUARE)
        assert ring.is_ccw
        assert ring.planar_signed_area() == pytest.approx(100.0)
        assert not ring.reversed().is_ccw
        assert ring.reversed().planar_signed_area() == pytest.approx(-100.0)

    def test_reversed_keeps_first_vertex(self):
        ring = Ring(SQUARE)
        assert ring.reversed().coords[0] == ring.coords[0]
        assert ring.reversed().reversed() == ring

    def test_oriented(self):
        ring = Ring(SQUARE)
        assert ring.oriented(ccw=True) is ring
        clockwise = ring.oriented(ccw=False)
        assert not clockwise.is_ccw
        assert clockwise.oriented(ccw=False) is clockwise


class TestExtent:
    def test_bbox(self):
        assert Ring(SQUARE).bbox == BoundingBox(0, 0, 10, 10)

    def test_ring_over_antimeridian_gets_narrow_crossing_bbox(self):
        ring = Ring([(-5, 175), (-5, -175), (5, -175), (5, 175)])
        assert ring.crosses_antimeridian
        assert ring.bbox == BoundingBox(-5, 175, 5, -175)
        assert ring.planar_signed_area() == pytest.approx(100.0)

    def test_ring_touching_180_is_not_crossing(self):
        ring = Ring([(0, 170), (0, 180), (10, 180), (10, 170)])
        assert not ring.crosses_antimeridian
        assert ring.bbox == BoundingBox(0, 170, 10, 180)

    def test_ring_around_a_pole_is_rejected(self):
        with pytest.raises(InvalidGeometryError, match="pole"):
            Ring([(80, 0), (80, 120), (80, -120)])

    def test_perimeter(self):
        one_degree = math.radians(1.0) * EARTH_RADIUS_M
        ring = Ring([(0, 0), (0, 1), (1, 1), (1, 0)])
        # The top edge is a hair shorter than a degree of the equator.
        assert ring.perimeter() == pytest.approx(4 * one_degree, rel=1e-4)
        assert ring.perimeter() < 4 * one_degree
