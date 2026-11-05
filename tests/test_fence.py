import math

import pytest

from geofence import geodesy
from geofence.circle import Circle
from geofence.coords import EARTH_RADIUS_M
from geofence.errors import InvalidGeometryError, ValidationError
from geofence.fence import Fence
from geofence.polygon import Location, MultiPolygon, Polygon, Ring

SQUARE = [(0, 0), (0, 2), (2, 2), (2, 0)]
ONE_DEG = math.radians(1.0) * EARTH_RADIUS_M


def test_basic_attributes():
    fence = Fence("depot", Polygon(SQUARE), name="Main depot", properties={"zone": 3})
    assert fence.id == "depot"
    assert fence.name == "Main depot"
    assert fence.properties["zone"] == 3
    assert fence.bbox == Polygon(SQUARE).bbox
    assert repr(fence) == "Fence('depot', Polygon)"


def test_name_defaults_to_id_and_properties_are_read_only():
    source = {"a": 1}
    fence = Fence("f1", Polygon(SQUARE), properties=source)
    assert fence.name == "f1"
    source["a"] = 2
    assert fence.properties["a"] == 1
    with pytest.raises(TypeError):
        fence.properties["a"] = 5


def test_ring_is_promoted_to_polygon():
    assert Fence("r", Ring(SQUARE)).shape == Polygon(SQUARE)


@pytest.mark.parametrize("bad_id", ["", "   ", None, 7])
def test_bad_id(bad_id):
    with pytest.raises(ValidationError):
        Fence(bad_id, Polygon(SQUARE))


def test_bad_shape_and_name():
    with pytest.raises(InvalidGeometryError):
        Fence("x", SQUARE)
    with pytest.raises(ValidationError):
        Fence("x", Polygon(SQUARE), name=5)


def test_equality_uses_id_and_shape():
    assert Fence("a", Polygon(SQUARE)) == Fence("a", Polygon(SQUARE), name="other")
    assert Fence("a", Polygon(SQUARE)) != Fence("b", Polygon(SQUARE))
    assert len({Fence("a", Polygon(SQUARE)), Fence("a", Polygon(SQUARE))}) == 1


def test_contains_and_locate_for_each_shape_kind():
    poly = Fence("p", Polygon(SQUARE))
    multi = Fence("m", MultiPolygon([SQUARE, [(5, 5), (5, 6), (6, 6), (6, 5)]]))
    circle = Fence("c", Circle((1, 1), 50_000))
    for fence in (poly, multi, circle):
        assert fence.contains((1, 1))
        assert not fence.contains((40, 40))
        assert fence.locate((40, 40)) is Location.OUTSIDE
    assert multi.contains((5.5, 5.5))
    assert poly.locate((0, 1)) is Location.BOUNDARY
    assert not poly.contains((0, 1), boundary=False)


def test_signed_distance():
    fence = Fence("p", Polygon(SQUARE))
    assert fence.signed_distance((1, 1)) == pytest.approx(-ONE_DEG, rel=1e-3)
    assert fence.signed_distance((1, 3)) == pytest.approx(ONE_DEG, rel=1e-3)
    assert fence.signed_distance((0, 1)) == 0.0
    assert fence.distance_to((1, 1)) == 0.0
    assert fence.distance_to((1, 3)) == pytest.approx(ONE_DEG, rel=1e-3)


def test_signed_distance_for_circle():
    centre = (10, 10)
    fence = Fence("c", Circle(centre, 1000))
    assert fence.signed_distance(centre) == pytest.approx(-1000)
    outside = geodesy.destination(centre, 90, 1750)
    assert fence.signed_distance(outside) == pytest.approx(750, abs=1e-3)
