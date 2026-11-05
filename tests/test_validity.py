import pytest

from geofence import validity
from geofence.errors import InvalidGeometryError
from geofence.polygon import MultiPolygon, Polygon, Ring
from geofence.validity import segment_relation

SQUARE = [(0, 0), (0, 10), (10, 10), (10, 0)]
HOLE = [(4, 4), (4, 6), (6, 6), (6, 4)]


def codes(found):
    return [issue.code for issue in found]


class TestSegmentRelation:
    def test_proper_crossing(self):
        assert segment_relation((0, 0), (2, 2), (0, 2), (2, 0)) == "cross"

    def test_disjoint(self):
        assert segment_relation((0, 0), (1, 1), (2, 2), (3, 3)) is None
        assert segment_relation((0, 0), (1, 0), (0, 1), (1, 1)) is None

    def test_shared_endpoint_and_t_junction_touch(self):
        assert segment_relation((0, 0), (1, 1), (1, 1), (2, 0)) == "touch"
        assert segment_relation((0, 0), (2, 0), (1, 0), (1, 5)) == "touch"

    def test_collinear_overlap_touches(self):
        assert segment_relation((0, 0), (2, 0), (1, 0), (3, 0)) == "touch"


class TestRingIssues:
    def test_simple_shapes_are_valid(self):
        assert validity.ring_issues(Ring(SQUARE)) == []
        assert validity.is_valid(Ring([(0, 0), (0, 1), (1, 0)]))
        assert validity.is_valid(Ring([(0, 0), (5, 2), (0, 4), (10, 2)]))  # concave

    def test_bow_tie_self_intersects(self):
        bow_tie = Ring([(0, 0), (10, 10), (0, 10), (10, 0)])
        found = validity.ring_issues(bow_tie)
        assert codes(found) == ["self-intersection"]
        assert "edges 0 and 2" in found[0].message

    def test_ring_touching_itself_at_a_vertex(self):
        pinched = Ring([(0, 0), (0, 4), (2, 2), (4, 4), (4, 0), (2, 2)])
        assert "self-intersection" in codes(validity.ring_issues(pinched))

    def test_spike_is_reported(self):
        spike = Ring([(0, 0), (0, 10), (0, 5), (10, 5)])
        assert "self-intersection" in codes(validity.ring_issues(spike))

    def test_duplicate_vertex_is_reported_once_and_not_as_intersection(self):
        ring = Ring([(0, 0), (0, 10), (0, 10), (10, 10), (10, 0)])
        found = validity.ring_issues(ring)
        assert codes(found) == ["duplicate-vertex"]
        assert "vertex 2" in found[0].message

    def test_collinear_ring_has_no_area(self):
        found = validity.ring_issues(Ring([(0, 0), (0, 1), (0, 2)]))
        assert codes(found) == ["zero-area"]

    def test_symmetric_bow_tie_is_not_mistaken_for_zero_area(self):
        bow_tie = Ring([(0, 0), (10, 10), (0, 10), (10, 0)])
        assert bow_tie.planar_signed_area() == 0
        assert "zero-area" not in codes(validity.ring_issues(bow_tie))

    def test_too_few_distinct_vertices(self):
        found = validity.ring_issues(Ring([(0, 0), (0, 0), (1, 1)]))
        assert "too-few-distinct-vertices" in codes(found)

    def test_valid_ring_across_antimeridian(self):
        assert validity.is_valid(Ring([(-5, 175), (-5, -175), (5, -175), (5, 175)]))

    def test_issue_string(self):
        issue = validity.ring_issues(Ring([(0, 0), (10, 10), (0, 10), (10, 0)]))[0]
        assert str(issue) == "self-intersection: ring: edges 0 and 2 intersect"


class TestPolygonIssues:
    def test_valid_polygon_with_hole(self):
        assert validity.polygon_issues(Polygon(SQUARE, [HOLE])) == []

    def test_hole_outside(self):
        poly = Polygon(SQUARE, [[(20, 20), (20, 21), (21, 21), (21, 20)]])
        assert codes(validity.issues(poly)) == ["hole-outside-exterior"]

    def test_hole_sticking_out(self):
        poly = Polygon(SQUARE, [[(8, 8), (8, 12), (9, 12), (9, 8)]])
        found = validity.issues(poly)
        assert codes(found) == ["hole-outside-exterior"]
        assert "hole 1" in found[0].message

    def test_hole_crossing_exterior_with_all_vertices_inside(self):
        # Concave exterior: the notch cuts through the hole between its vertices.
        notched = [(0, 0), (0, 10), (10, 10), (10, 6), (5, 5), (10, 4), (10, 0)]
        poly = Polygon(notched, [[(6, 1), (6, 9), (7, 9), (7, 1)]])
        assert codes(validity.issues(poly)) == ["hole-crosses-exterior"]

    def test_overlapping_holes(self):
        poly = Polygon(SQUARE, [HOLE, [(5, 5), (5, 7), (7, 7), (7, 5)]])
        found = validity.issues(poly)
        assert codes(found) == ["holes-overlap"]
        assert "holes 1 and 2" in found[0].message

    def test_crossing_holes_without_contained_vertices(self):
        plus_a = [(4, 1), (4, 9), (6, 9), (6, 1)]
        plus_b = [(1, 4), (1, 6), (9, 6), (9, 4)]
        assert codes(validity.issues(Polygon(SQUARE, [plus_a, plus_b]))) == ["holes-overlap"]

    def test_ring_problems_are_labelled(self):
        poly = Polygon(SQUARE, [[(4, 4), (6, 6), (4, 6), (6, 4)]])
        found = validity.issues(poly)
        assert codes(found) == ["self-intersection"]
        assert found[0].message.startswith("polygon hole 1:")

    def test_hole_across_antimeridian(self):
        shell = [(-5, 170), (-5, -170), (5, -170), (5, 170)]
        hole = [(-1, -179), (-1, -178), (1, -178), (1, -179)]
        assert validity.is_valid(Polygon(shell, [hole]))


class TestDispatchAndValidate:
    def test_multipolygon_labels_members(self):
        multi = MultiPolygon([SQUARE, [(20, 20), (30, 30), (20, 30), (30, 20)]])
        found = validity.issues(multi)
        assert codes(found) == ["self-intersection"]
        assert found[0].message.startswith("polygon 2 exterior")

    def test_validate_raises_with_all_messages(self):
        validity.validate(Polygon(SQUARE, [HOLE]))
        with pytest.raises(InvalidGeometryError, match="self-intersection"):
            validity.validate(Ring([(0, 0), (10, 10), (0, 10), (10, 0)]))

    def test_unknown_type(self):
        with pytest.raises(TypeError):
            validity.issues("POLYGON")


class TestCheckRingPoints:
    def test_closed_valid_ring(self):
        assert validity.check_ring_points(SQUARE + [SQUARE[0]]) == []

    def test_unclosed_ring_is_reported(self):
        assert codes(validity.check_ring_points(SQUARE)) == ["unclosed-ring"]
        assert validity.check_ring_points(SQUARE, require_closed=False) == []

    def test_too_few_points(self):
        found = validity.check_ring_points([(0, 0), (1, 1)])
        assert codes(found) == ["unclosed-ring", "unusable-ring"]

    def test_closed_bow_tie_reports_only_the_intersection(self):
        bow_tie = [(0, 0), (10, 10), (0, 10), (10, 0), (0, 0)]
        assert codes(validity.check_ring_points(bow_tie)) == ["self-intersection"]
