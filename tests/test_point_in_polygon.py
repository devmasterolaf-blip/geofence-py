import pytest

from geofence.polygon import Location, Polygon, Ring

SQUARE = [(0, 0), (0, 10), (10, 10), (10, 0)]
HOLE = [(4, 4), (4, 6), (6, 6), (6, 4)]


class TestRingLocate:
    @pytest.mark.parametrize("point", [(5, 5), (0.001, 0.001), (9.999, 9.999), (1, 9)])
    def test_inside(self, point):
        assert Ring(SQUARE).locate(point) is Location.INSIDE

    @pytest.mark.parametrize("point", [(-1, 5), (11, 5), (5, -1), (5, 11), (20, 20), (5, -175)])
    def test_outside(self, point):
        assert Ring(SQUARE).locate(point) is Location.OUTSIDE

    @pytest.mark.parametrize("point", [(0, 0), (10, 10), (0, 5), (5, 0), (10, 3), (7, 10)])
    def test_vertices_and_edges_are_boundary(self, point):
        assert Ring(SQUARE).locate(point) is Location.BOUNDARY

    def test_orientation_does_not_matter(self):
        ring = Ring(SQUARE).reversed()
        assert ring.locate((5, 5)) is Location.INSIDE
        assert ring.locate((15, 5)) is Location.OUTSIDE

    def test_boundary_flag(self):
        ring = Ring(SQUARE)
        assert ring.contains((0, 5))
        assert not ring.contains((0, 5), boundary=False)
        assert ring.contains((5, 5), boundary=False)
        assert not ring.contains((50, 5))

    def test_ray_through_a_vertex_is_counted_once(self):
        # Diamond: the eastward ray from the centre row passes through a vertex.
        diamond = Ring([(0, 5), (5, 10), (10, 5), (5, 0)])
        assert diamond.locate((5, 5)) is Location.INSIDE
        assert diamond.locate((5, -1)) is Location.OUTSIDE
        assert diamond.locate((5, 11)) is Location.OUTSIDE
        assert diamond.locate((0, 4)) is Location.OUTSIDE  # level with the bottom vertex
        assert diamond.locate((10, 6)) is Location.OUTSIDE  # level with the top vertex

    def test_ray_along_a_horizontal_edge(self):
        # Concave "U": points level with the inner horizontal edge.
        u_shape = Ring([(0, 0), (0, 9), (9, 9), (9, 6), (3, 6), (3, 3), (9, 3), (9, 0)])
        assert u_shape.locate((3, 1)) is Location.INSIDE
        assert u_shape.locate((3, 4.5)) is Location.BOUNDARY
        assert u_shape.locate((5, 4.5)) is Location.OUTSIDE
        assert u_shape.locate((5, 1.5)) is Location.INSIDE
        assert u_shape.locate((9, 4.5)) is Location.OUTSIDE
        assert u_shape.locate((9, 1)) is Location.BOUNDARY

    def test_concave_ring(self):
        arrow = Ring([(0, 0), (5, 2), (0, 4), (10, 2)])
        assert arrow.locate((6, 2)) is Location.INSIDE
        assert arrow.locate((2, 2)) is Location.OUTSIDE
        assert arrow.locate((5, 2)) is Location.BOUNDARY

    def test_point_just_off_the_edge_is_not_boundary(self):
        ring = Ring(SQUARE)
        assert ring.locate((5, 10 + 1e-9)) is Location.OUTSIDE
        assert ring.locate((5, 10 - 1e-9)) is Location.INSIDE


class TestAntimeridianRing:
    RING = Ring([(-5, 175), (-5, -175), (5, -175), (5, 175)])

    @pytest.mark.parametrize("point", [(0, 178), (0, -178), (0, 180), (0, -180), (4.9, 175.1)])
    def test_inside_on_both_sides(self, point):
        assert self.RING.locate(point) is Location.INSIDE

    @pytest.mark.parametrize("point", [(0, 0), (0, 170), (0, -170), (6, 180), (0, 90)])
    def test_outside(self, point):
        assert self.RING.locate(point) is Location.OUTSIDE

    @pytest.mark.parametrize("point", [(0, 175), (0, -175), (5, 180), (-5, -179.3), (5, -175)])
    def test_boundary(self, point):
        assert self.RING.locate(point) is Location.BOUNDARY

    def test_vertices_with_awkward_decimals_are_boundary(self):
        ring = Ring([(-1.1, 179.3), (-1.1, -179.9), (2.7, -179.9), (2.7, 179.3)])
        for vertex in ring.coords:
            assert ring.locate(vertex) is Location.BOUNDARY

    def test_ring_starting_east_of_the_antimeridian(self):
        ring = Ring([(-5, -175), (5, -175), (5, 175), (-5, 175)])
        assert ring.locate((0, 179)) is Location.INSIDE
        assert ring.locate((0, -179)) is Location.INSIDE
        assert ring.locate((0, 0)) is Location.OUTSIDE


class TestPolygonWithHoles:
    POLY = Polygon(SQUARE, holes=[HOLE])

    def test_structure(self):
        assert self.POLY.exterior == Ring(SQUARE)
        assert self.POLY.holes == (Ring(HOLE),)
        assert self.POLY.rings == (Ring(SQUARE), Ring(HOLE))
        assert self.POLY.bbox == Ring(SQUARE).bbox
        assert self.POLY == Polygon(Ring(SQUARE), [Ring(HOLE)])
        assert self.POLY != Polygon(SQUARE)
        assert len({self.POLY, Polygon(SQUARE, [HOLE])}) == 1

    def test_point_in_hole_is_outside(self):
        assert self.POLY.locate((5, 5)) is Location.OUTSIDE
        assert not self.POLY.contains((5, 5))

    def test_point_between_hole_and_exterior_is_inside(self):
        assert self.POLY.locate((2, 2)) is Location.INSIDE
        assert self.POLY.contains((2, 2), boundary=False)

    def test_hole_edge_is_boundary(self):
        assert self.POLY.locate((4, 5)) is Location.BOUNDARY
        assert self.POLY.contains((4, 5))
        assert not self.POLY.contains((4, 5), boundary=False)

    def test_exterior_edge_is_boundary_and_outside_stays_outside(self):
        assert self.POLY.locate((0, 5)) is Location.BOUNDARY
        assert self.POLY.locate((-3, 5)) is Location.OUTSIDE

    def test_multiple_holes(self):
        poly = Polygon(SQUARE, holes=[[(1, 1), (1, 2), (2, 2), (2, 1)], [(7, 7), (7, 8), (8, 8), (8, 7)]])
        assert not poly.contains((1.5, 1.5))
        assert not poly.contains((7.5, 7.5))
        assert poly.contains((5, 5))
